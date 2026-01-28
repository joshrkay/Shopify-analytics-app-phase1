"""
Action job dispatcher for Story 8.5.

Creates ActionJob records to process approved actions.
Enforces: one active job per tenant, entitlement checks.

Unlike insight/recommendation jobs which are cron-triggered,
action jobs are created when actions are approved and ready
for execution.

SECURITY: tenant_id from JWT only, never from client input.

Story 8.5 - Action Execution (Scoped & Reversible)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.models.ai_action import AIAction, ActionStatus
from src.models.action_job import ActionJob, ActionJobStatus
from src.services.billing_entitlements import BillingEntitlementsService, BillingFeature


logger = logging.getLogger(__name__)


class ActionJobDispatcher:
    """
    Dispatcher for action execution jobs.

    Creates jobs to process approved actions. Enforces single
    active job per tenant to prevent concurrent execution issues.

    Unlike insight jobs, action jobs are created on-demand when
    actions are approved, not on a fixed schedule.
    """

    def __init__(self, db_session: Session, tenant_id: str):
        """
        Initialize dispatcher.

        Args:
            db_session: Database session
            tenant_id: Tenant identifier (from JWT only)
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id

    # =========================================================================
    # Entitlement Checks
    # =========================================================================

    def _check_entitlement(self) -> bool:
        """Check if tenant is entitled to AI actions."""
        service = BillingEntitlementsService(self.db, self.tenant_id)
        result = service.check_feature_entitlement(BillingFeature.AI_ACTIONS)
        return result.is_entitled

    def _has_active_job(self) -> bool:
        """Check if tenant already has an active job."""
        active_job = (
            self.db.query(ActionJob)
            .filter(
                ActionJob.tenant_id == self.tenant_id,
                ActionJob.status.in_([
                    ActionJobStatus.QUEUED,
                    ActionJobStatus.RUNNING,
                ]),
            )
            .first()
        )
        return active_job is not None

    def _get_approved_actions(self, limit: int = 10) -> list[AIAction]:
        """Get approved actions ready for execution."""
        return (
            self.db.query(AIAction)
            .filter(
                AIAction.tenant_id == self.tenant_id,
                AIAction.status == ActionStatus.APPROVED,
            )
            .order_by(AIAction.created_at.asc())
            .limit(limit)
            .all()
        )

    # =========================================================================
    # Job Creation
    # =========================================================================

    def should_create_job(self) -> tuple[bool, str]:
        """
        Check if a job should be created.

        Returns:
            Tuple of (should_create, reason)
        """
        if not self._check_entitlement():
            return False, "Not entitled to AI actions"

        if self._has_active_job():
            return False, "Active job already exists"

        actions = self._get_approved_actions(limit=1)
        if not actions:
            return False, "No approved actions to process"

        return True, "Ready to create job"

    def create_job(self, max_actions: int = 10) -> Optional[ActionJob]:
        """
        Create a job for approved actions.

        Args:
            max_actions: Maximum number of actions to include in job

        Returns:
            Created ActionJob or None if cannot create
        """
        should_create, reason = self.should_create_job()

        if not should_create:
            logger.info(
                "Not creating action job",
                extra={
                    "tenant_id": self.tenant_id,
                    "reason": reason,
                }
            )
            return None

        # Get approved actions
        actions = self._get_approved_actions(limit=max_actions)

        if not actions:
            return None

        # Create job with action IDs
        action_ids = [action.id for action in actions]

        job = ActionJob(
            tenant_id=self.tenant_id,
            status=ActionJobStatus.QUEUED,
            action_ids=action_ids,
        )

        self.db.add(job)
        self.db.flush()

        # Update actions to QUEUED status and set job_id
        for action in actions:
            action.status = ActionStatus.QUEUED
            action.job_id = job.job_id

        self.db.flush()

        logger.info(
            "Action job created",
            extra={
                "tenant_id": self.tenant_id,
                "job_id": job.job_id,
                "action_count": len(action_ids),
            }
        )

        return job

    def create_job_for_action(self, action_id: str) -> Optional[ActionJob]:
        """
        Create a job for a specific action.

        Args:
            action_id: ID of the action to execute

        Returns:
            Created ActionJob or None if cannot create
        """
        if not self._check_entitlement():
            logger.warning(
                "Not entitled to create action job",
                extra={"tenant_id": self.tenant_id}
            )
            return None

        if self._has_active_job():
            logger.info(
                "Active job exists, cannot create new job",
                extra={"tenant_id": self.tenant_id}
            )
            return None

        # Get the specific action
        action = (
            self.db.query(AIAction)
            .filter(
                AIAction.id == action_id,
                AIAction.tenant_id == self.tenant_id,
                AIAction.status == ActionStatus.APPROVED,
            )
            .first()
        )

        if not action:
            logger.warning(
                "Action not found or not approved",
                extra={
                    "tenant_id": self.tenant_id,
                    "action_id": action_id,
                }
            )
            return None

        # Create job with single action
        job = ActionJob(
            tenant_id=self.tenant_id,
            status=ActionJobStatus.QUEUED,
            action_ids=[action_id],
        )

        self.db.add(job)
        self.db.flush()

        # Update action
        action.status = ActionStatus.QUEUED
        action.job_id = job.job_id

        self.db.flush()

        logger.info(
            "Action job created for single action",
            extra={
                "tenant_id": self.tenant_id,
                "job_id": job.job_id,
                "action_id": action_id,
            }
        )

        return job

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get_pending_action_count(self) -> int:
        """Get count of approved actions waiting for job."""
        return (
            self.db.query(AIAction)
            .filter(
                AIAction.tenant_id == self.tenant_id,
                AIAction.status == ActionStatus.APPROVED,
            )
            .count()
        )

    def get_active_job(self) -> Optional[ActionJob]:
        """Get currently active job for tenant."""
        return (
            self.db.query(ActionJob)
            .filter(
                ActionJob.tenant_id == self.tenant_id,
                ActionJob.status.in_([
                    ActionJobStatus.QUEUED,
                    ActionJobStatus.RUNNING,
                ]),
            )
            .first()
        )


# =============================================================================
# Dispatch Functions for Cron/Worker
# =============================================================================

def dispatch_action_jobs(db_session: Session, limit: int = 100) -> int:
    """
    Dispatch action jobs for all tenants with approved actions.

    This function is called by cron/worker to create jobs for
    all tenants that have approved actions waiting.

    Args:
        db_session: Database session
        limit: Maximum number of tenants to process

    Returns:
        Number of jobs created
    """
    # Get distinct tenant_ids with approved actions
    tenant_ids = (
        db_session.query(AIAction.tenant_id)
        .filter(AIAction.status == ActionStatus.APPROVED)
        .distinct()
        .limit(limit)
        .all()
    )

    jobs_created = 0

    for (tenant_id,) in tenant_ids:
        try:
            dispatcher = ActionJobDispatcher(db_session, tenant_id)
            job = dispatcher.create_job()

            if job:
                jobs_created += 1

        except Exception as e:
            logger.error(
                "Error creating action job for tenant",
                extra={
                    "tenant_id": tenant_id,
                    "error": str(e),
                },
                exc_info=True,
            )

    db_session.commit()

    logger.info(
        "Action job dispatch completed",
        extra={
            "tenants_checked": len(tenant_ids),
            "jobs_created": jobs_created,
        }
    )

    return jobs_created
