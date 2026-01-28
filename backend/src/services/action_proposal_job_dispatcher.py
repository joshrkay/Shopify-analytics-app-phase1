"""
Action Proposal Job Dispatcher.

Creates action proposal generation jobs based on:
- Accepted recommendations that need proposal generation
- Scheduled cadence (daily or hourly for enterprise)

SECURITY:
- Tenant isolation via tenant_id in all queries
- Entitlement check before dispatching

Story 8.4 - Action Proposals (Approval Required)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session
from sqlalchemy import text

from src.models.action_proposal_job import (
    ActionProposalJob,
    ActionProposalJobStatus,
    ActionProposalJobCadence,
)


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


class ActionProposalJobDispatcher:
    """
    Dispatcher for action proposal generation jobs.

    Creates jobs when:
    - There are accepted recommendations without proposals
    - Scheduled cadence triggers
    """

    def __init__(
        self,
        db_session: Session,
        tenant_id: str,
    ):
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id

    def should_dispatch(self) -> bool:
        """
        Check if a new job should be dispatched.

        Returns True if:
        - No active job exists for this tenant
        - There are accepted recommendations without proposals

        Returns:
            True if a job should be dispatched
        """
        # Check for active job
        active_job = (
            self.db.query(ActionProposalJob)
            .filter(
                ActionProposalJob.tenant_id == self.tenant_id,
                ActionProposalJob.status.in_([
                    ActionProposalJobStatus.QUEUED,
                    ActionProposalJobStatus.RUNNING,
                ]),
            )
            .first()
        )

        if active_job:
            logger.debug(
                "Active job exists, skipping dispatch",
                extra={
                    "tenant_id": self.tenant_id,
                    "job_id": active_job.job_id,
                },
            )
            return False

        # Check for accepted recommendations without proposals
        count = self._count_recommendations_needing_proposals()
        return count > 0

    def _count_recommendations_needing_proposals(self) -> int:
        """Count accepted recommendations that don't have proposals yet."""
        query = text("""
            SELECT COUNT(*)
            FROM ai_recommendations r
            WHERE r.tenant_id = :tenant_id
              AND r.is_accepted = 1
              AND r.is_dismissed = 0
              AND r.generated_at > NOW() - INTERVAL '30 days'
              AND NOT EXISTS (
                  SELECT 1 FROM action_proposals p
                  WHERE p.source_recommendation_id = r.id
                    AND p.tenant_id = :tenant_id
              )
        """)

        result = self.db.execute(query, {"tenant_id": self.tenant_id})
        return result.scalar() or 0

    def dispatch_if_needed(
        self,
        cadence: ActionProposalJobCadence = ActionProposalJobCadence.DAILY,
    ) -> ActionProposalJob | None:
        """
        Dispatch a new job if conditions are met.

        Args:
            cadence: Job cadence (daily or hourly)

        Returns:
            Created job or None if dispatch not needed
        """
        if not self.should_dispatch():
            return None

        job = ActionProposalJob(
            tenant_id=self.tenant_id,
            cadence=cadence,
            status=ActionProposalJobStatus.QUEUED,
            proposals_generated=0,
            recommendations_processed=0,
            job_metadata={
                "dispatch_reason": "recommendations_available",
                "recommendations_count": self._count_recommendations_needing_proposals(),
            },
        )

        self.db.add(job)
        self.db.flush()

        logger.info(
            "Action proposal job dispatched",
            extra={
                "tenant_id": self.tenant_id,
                "job_id": job.job_id,
                "cadence": cadence.value,
            },
        )

        return job

    def dispatch_for_tenant(
        self,
        cadence: ActionProposalJobCadence = ActionProposalJobCadence.DAILY,
        force: bool = False,
    ) -> ActionProposalJob | None:
        """
        Dispatch a job for this tenant.

        Args:
            cadence: Job cadence
            force: If True, dispatch even if no recommendations available

        Returns:
            Created job or None
        """
        if force:
            # Check only for active job
            active_job = (
                self.db.query(ActionProposalJob)
                .filter(
                    ActionProposalJob.tenant_id == self.tenant_id,
                    ActionProposalJob.status.in_([
                        ActionProposalJobStatus.QUEUED,
                        ActionProposalJobStatus.RUNNING,
                    ]),
                )
                .first()
            )

            if active_job:
                return None

            job = ActionProposalJob(
                tenant_id=self.tenant_id,
                cadence=cadence,
                status=ActionProposalJobStatus.QUEUED,
                proposals_generated=0,
                recommendations_processed=0,
                job_metadata={
                    "dispatch_reason": "forced",
                },
            )

            self.db.add(job)
            self.db.flush()

            logger.info(
                "Action proposal job force dispatched",
                extra={
                    "tenant_id": self.tenant_id,
                    "job_id": job.job_id,
                },
            )

            return job

        return self.dispatch_if_needed(cadence)


def get_tenants_needing_proposal_jobs(db_session: Session) -> list[str]:
    """
    Get list of tenant IDs that need proposal job dispatch.

    This is used by the scheduler to find tenants with pending work.

    Args:
        db_session: Database session

    Returns:
        List of tenant IDs
    """
    query = text("""
        SELECT DISTINCT r.tenant_id
        FROM ai_recommendations r
        WHERE r.is_accepted = 1
          AND r.is_dismissed = 0
          AND r.generated_at > NOW() - INTERVAL '30 days'
          AND NOT EXISTS (
              SELECT 1 FROM action_proposals p
              WHERE p.source_recommendation_id = r.id
                AND p.tenant_id = r.tenant_id
          )
          AND NOT EXISTS (
              SELECT 1 FROM action_proposal_jobs j
              WHERE j.tenant_id = r.tenant_id
                AND j.status IN ('queued', 'running')
          )
        LIMIT 100
    """)

    result = db_session.execute(query)
    return [row[0] for row in result.fetchall()]
