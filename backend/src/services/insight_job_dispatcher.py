"""
Insight job dispatcher for scheduling insight generation.

Creates InsightJob records based on tenant entitlements and cadence.
Enforces: one active job per tenant, entitlement checks, rate limits.

SECURITY: tenant_id from JWT only, never from client input.

Story 8.1 - AI Insight Generation (Read-Only Analytics)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.models.ai_insight import AIInsight
from src.models.insight_job import InsightJob, InsightJobStatus, InsightJobCadence
from src.models.subscription import Subscription, SubscriptionStatus
from src.services.billing_entitlements import BillingEntitlementsService, BillingFeature


logger = logging.getLogger(__name__)


class InsightJobDispatcher:
    """
    Dispatcher for insight generation jobs.

    Checks entitlements and creates jobs at appropriate cadence.
    Enforces single active job per tenant.
    """

    def __init__(self, db_session: Session, tenant_id: str):
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id

    def _check_entitlement(self) -> bool:
        """Check if tenant is entitled to AI insights."""
        service = BillingEntitlementsService(self.db, self.tenant_id)
        result = service.check_feature_entitlement(BillingFeature.AI_INSIGHTS)
        return result.is_entitled

    def _get_billing_tier(self) -> str:
        """Get tenant's billing tier."""
        service = BillingEntitlementsService(self.db, self.tenant_id)
        return service.get_billing_tier()

    def _has_active_job(self) -> bool:
        """Check if tenant already has an active job."""
        active_job = (
            self.db.query(InsightJob)
            .filter(
                InsightJob.tenant_id == self.tenant_id,
                InsightJob.status.in_(
                    [InsightJobStatus.QUEUED, InsightJobStatus.RUNNING]
                ),
            )
            .first()
        )
        return active_job is not None

    def _is_cadence_allowed(self, cadence: InsightJobCadence) -> bool:
        """Check if cadence is allowed for tenant's tier."""
        if cadence == InsightJobCadence.HOURLY:
            tier = self._get_billing_tier()
            return tier == "enterprise"
        return True  # Daily is allowed for all entitled tiers

    def _get_monthly_insight_count(self) -> int:
        """Count insights generated this month for tenant."""
        start_of_month = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        return (
            self.db.query(AIInsight)
            .filter(
                AIInsight.tenant_id == self.tenant_id,
                AIInsight.generated_at >= start_of_month,
            )
            .count()
        )

    def _check_monthly_limit(self) -> tuple[bool, str]:
        """
        Check if tenant has reached monthly insight limit.

        Returns:
            Tuple of (within_limit, reason)
        """
        service = BillingEntitlementsService(self.db, self.tenant_id)
        limit = service.get_feature_limit("ai_insights_per_month")

        # 0 means not entitled (handled by entitlement check)
        # -1 means unlimited
        if limit == -1:
            return True, "OK"

        if limit == 0:
            return False, "Not entitled to AI insights"

        current_count = self._get_monthly_insight_count()
        if current_count >= limit:
            return False, f"Monthly limit reached ({current_count}/{limit})"

        return True, "OK"

    def should_create_job(self, cadence: InsightJobCadence) -> tuple[bool, str]:
        """
        Check if a job should be created for this tenant at given cadence.

        Args:
            cadence: Requested job cadence

        Returns:
            Tuple of (should_create, reason)
        """
        # Check entitlements
        if not self._check_entitlement():
            return False, "Tenant not entitled to AI insights"

        # Check cadence permission
        if not self._is_cadence_allowed(cadence):
            return False, "Hourly cadence requires enterprise tier"

        # Check monthly limit
        within_limit, limit_reason = self._check_monthly_limit()
        if not within_limit:
            return False, limit_reason

        # Check for existing active job
        if self._has_active_job():
            return False, "Active insight job already exists"

        return True, "OK"

    def dispatch(self, cadence: InsightJobCadence) -> Optional[InsightJob]:
        """
        Create a new insight generation job.

        Args:
            cadence: Job cadence (daily or hourly)

        Returns:
            Created InsightJob or None if not allowed
        """
        should_create, reason = self.should_create_job(cadence)

        if not should_create:
            logger.debug(
                "Insight job not created",
                extra={
                    "tenant_id": self.tenant_id,
                    "cadence": cadence.value,
                    "reason": reason,
                },
            )
            return None

        job = InsightJob(
            tenant_id=self.tenant_id,
            cadence=cadence,
            status=InsightJobStatus.QUEUED,
            insights_generated=0,
            job_metadata={},
        )

        self.db.add(job)
        self.db.flush()

        logger.info(
            "insight_job.dispatched",
            extra={
                "job_id": job.job_id,
                "tenant_id": self.tenant_id,
                "cadence": cadence.value,
            },
        )

        return job


def dispatch_daily_insight_jobs(db_session: Session) -> list[InsightJob]:
    """
    Dispatch daily insight jobs for all eligible tenants.

    Called by cron trigger (daily at configured time).

    Args:
        db_session: Database session

    Returns:
        List of created InsightJob objects
    """
    # Get all tenants with active subscriptions
    subscriptions = (
        db_session.query(Subscription)
        .filter(Subscription.status == SubscriptionStatus.ACTIVE.value)
        .all()
    )

    jobs_created = []
    for sub in subscriptions:
        try:
            dispatcher = InsightJobDispatcher(db_session, sub.tenant_id)
            job = dispatcher.dispatch(InsightJobCadence.DAILY)
            if job:
                jobs_created.append(job)
        except Exception as e:
            logger.error(
                "Failed to dispatch insight job",
                extra={
                    "tenant_id": sub.tenant_id,
                    "error": str(e),
                },
                exc_info=True,
            )

    db_session.commit()

    logger.info(
        "Daily insight jobs dispatched",
        extra={"jobs_created": len(jobs_created)},
    )

    return jobs_created


def dispatch_hourly_insight_jobs(db_session: Session) -> list[InsightJob]:
    """
    Dispatch hourly insight jobs for enterprise tenants.

    Called by cron trigger (hourly).

    Args:
        db_session: Database session

    Returns:
        List of created InsightJob objects
    """
    # Get all tenants with active subscriptions
    subscriptions = (
        db_session.query(Subscription)
        .filter(Subscription.status == SubscriptionStatus.ACTIVE.value)
        .all()
    )

    jobs_created = []
    for sub in subscriptions:
        try:
            dispatcher = InsightJobDispatcher(db_session, sub.tenant_id)
            # Hourly dispatch - will be rejected for non-enterprise
            job = dispatcher.dispatch(InsightJobCadence.HOURLY)
            if job:
                jobs_created.append(job)
        except Exception as e:
            logger.error(
                "Failed to dispatch hourly insight job",
                extra={
                    "tenant_id": sub.tenant_id,
                    "error": str(e),
                },
                exc_info=True,
            )

    db_session.commit()

    logger.info(
        "Hourly insight jobs dispatched",
        extra={"jobs_created": len(jobs_created)},
    )

    return jobs_created
