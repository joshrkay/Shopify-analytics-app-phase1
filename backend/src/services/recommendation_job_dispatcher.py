"""
Recommendation Job Dispatcher.

Creates RecommendationJob records based on:
- New insights that need recommendations
- Scheduled cadence (daily or hourly for enterprise)

SECURITY:
- Tenant isolation in all operations
- Entitlement checking before job creation

Story 8.3 - AI Recommendations (No Actions)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import text

from src.models.recommendation_job import (
    RecommendationJob,
    RecommendationJobStatus,
    RecommendationJobCadence,
)
from src.services.billing_entitlements import (
    BillingEntitlementsService,
    BillingFeature,
)


logger = logging.getLogger(__name__)


class RecommendationJobDispatcher:
    """
    Dispatcher for recommendation generation jobs.

    Creates RecommendationJob records when:
    1. New insights exist that need recommendations
    2. Tenant is entitled to AI recommendations feature
    3. No active job exists for the tenant

    SECURITY: tenant_id from JWT only, never from client input.
    """

    def __init__(self, db_session: Session, tenant_id: str):
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id

    def should_create_job(
        self,
        cadence: RecommendationJobCadence = RecommendationJobCadence.DAILY,
    ) -> tuple[bool, str]:
        """
        Check if a recommendation job should be created.

        Args:
            cadence: Job cadence (daily or hourly)

        Returns:
            Tuple of (should_create, reason)
        """
        # Check entitlement
        entitlement_service = BillingEntitlementsService(self.db, self.tenant_id)

        # Check for AI_RECOMMENDATIONS feature (falls back to AI_INSIGHTS if not defined)
        try:
            result = entitlement_service.check_feature_entitlement(
                BillingFeature.AI_RECOMMENDATIONS
            )
        except (AttributeError, ValueError):
            # AI_RECOMMENDATIONS not defined, try AI_INSIGHTS
            result = entitlement_service.check_feature_entitlement(
                BillingFeature.AI_INSIGHTS
            )

        if not result.is_entitled:
            return False, f"Tenant not entitled to AI recommendations (tier: {result.current_tier})"

        # Check if hourly cadence is allowed (enterprise only)
        if cadence == RecommendationJobCadence.HOURLY:
            if result.current_tier != "enterprise":
                return False, "Hourly recommendation jobs require enterprise tier"

        # Check for active job
        active_job = (
            self.db.query(RecommendationJob)
            .filter(
                RecommendationJob.tenant_id == self.tenant_id,
                RecommendationJob.status.in_([
                    RecommendationJobStatus.QUEUED,
                    RecommendationJobStatus.RUNNING,
                ]),
            )
            .first()
        )

        if active_job:
            return False, f"Active job already exists: {active_job.job_id}"

        # Check if there are unprocessed insights
        has_insights = self._has_unprocessed_insights()
        if not has_insights:
            return False, "No unprocessed insights available"

        return True, "OK"

    def _has_unprocessed_insights(self) -> bool:
        """Check if there are insights without recommendations."""
        query = text("""
            SELECT EXISTS (
                SELECT 1 FROM ai_insights i
                WHERE i.tenant_id = :tenant_id
                  AND i.is_dismissed = 0
                  AND i.generated_at > NOW() - INTERVAL '7 days'
                  AND NOT EXISTS (
                      SELECT 1 FROM ai_recommendations r
                      WHERE r.related_insight_id = i.id
                        AND r.tenant_id = :tenant_id
                  )
            )
        """)

        result = self.db.execute(query, {"tenant_id": self.tenant_id})
        return result.scalar()

    def dispatch(
        self,
        cadence: RecommendationJobCadence = RecommendationJobCadence.DAILY,
    ) -> RecommendationJob | None:
        """
        Create a recommendation job if conditions are met.

        Args:
            cadence: Job cadence (daily or hourly)

        Returns:
            RecommendationJob if created, None otherwise
        """
        should_create, reason = self.should_create_job(cadence)

        if not should_create:
            logger.info(
                "Recommendation job not created",
                extra={
                    "tenant_id": self.tenant_id,
                    "reason": reason,
                    "cadence": cadence.value,
                },
            )
            return None

        job = RecommendationJob(
            tenant_id=self.tenant_id,
            cadence=cadence,
            status=RecommendationJobStatus.QUEUED,
            recommendations_generated=0,
            insights_processed=0,
        )

        self.db.add(job)
        self.db.commit()

        logger.info(
            "Recommendation job created",
            extra={
                "tenant_id": self.tenant_id,
                "job_id": job.job_id,
                "cadence": cadence.value,
            },
        )

        return job


# =============================================================================
# Module-level functions for cron/scheduler integration
# =============================================================================


def dispatch_daily_recommendation_jobs(db_session: Session) -> int:
    """
    Dispatch daily recommendation jobs for all eligible tenants.

    Called by daily cron job. Creates recommendation jobs for tenants
    that have:
    - AI recommendations entitlement
    - Unprocessed insights
    - No active recommendation job

    Args:
        db_session: Database session

    Returns:
        Number of jobs created
    """
    # Get all tenants with AI entitlement
    # This is a simplified version - in production you'd query entitled tenants
    query = text("""
        SELECT DISTINCT tenant_id
        FROM ai_insights
        WHERE generated_at > NOW() - INTERVAL '7 days'
          AND is_dismissed = 0
    """)

    result = db_session.execute(query)
    tenant_ids = [row[0] for row in result.fetchall()]

    jobs_created = 0

    for tenant_id in tenant_ids:
        try:
            dispatcher = RecommendationJobDispatcher(db_session, tenant_id)
            job = dispatcher.dispatch(RecommendationJobCadence.DAILY)
            if job:
                jobs_created += 1
        except Exception as e:
            logger.error(
                "Failed to dispatch recommendation job",
                extra={
                    "tenant_id": tenant_id,
                    "error": str(e),
                },
            )

    logger.info(
        "Daily recommendation job dispatch complete",
        extra={
            "tenants_checked": len(tenant_ids),
            "jobs_created": jobs_created,
        },
    )

    return jobs_created


def dispatch_hourly_recommendation_jobs(db_session: Session) -> int:
    """
    Dispatch hourly recommendation jobs for enterprise tenants.

    Called by hourly cron job. Only creates jobs for enterprise tenants.

    Args:
        db_session: Database session

    Returns:
        Number of jobs created
    """
    # Get enterprise tenants with recent insights
    # In production, this would join with billing/subscription tables
    query = text("""
        SELECT DISTINCT i.tenant_id
        FROM ai_insights i
        WHERE i.generated_at > NOW() - INTERVAL '1 hour'
          AND i.is_dismissed = 0
    """)

    result = db_session.execute(query)
    tenant_ids = [row[0] for row in result.fetchall()]

    jobs_created = 0

    for tenant_id in tenant_ids:
        try:
            dispatcher = RecommendationJobDispatcher(db_session, tenant_id)
            job = dispatcher.dispatch(RecommendationJobCadence.HOURLY)
            if job:
                jobs_created += 1
        except Exception as e:
            logger.error(
                "Failed to dispatch hourly recommendation job",
                extra={
                    "tenant_id": tenant_id,
                    "error": str(e),
                },
            )

    logger.info(
        "Hourly recommendation job dispatch complete",
        extra={
            "tenants_checked": len(tenant_ids),
            "jobs_created": jobs_created,
        },
    )

    return jobs_created
