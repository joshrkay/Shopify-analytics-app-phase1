"""
Action Proposal Job Runner.

Executes queued action proposal generation jobs.
Processes recommendations and generates proposals.

SECURITY:
- Tenant isolation via tenant_id in all queries
- No external API calls during generation

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
)
from src.services.action_proposal_generation_service import (
    ActionProposalGenerationService,
)


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


class ActionProposalJobRunner:
    """
    Runner for action proposal generation jobs.

    Processes QUEUED jobs by:
    1. Marking as RUNNING
    2. Generating proposals from recommendations
    3. Marking as SUCCESS/FAILED
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

    def get_next_job(self) -> ActionProposalJob | None:
        """
        Get the next queued job for this tenant.

        Returns:
            Next queued job or None
        """
        return (
            self.db.query(ActionProposalJob)
            .filter(
                ActionProposalJob.tenant_id == self.tenant_id,
                ActionProposalJob.status == ActionProposalJobStatus.QUEUED,
            )
            .order_by(ActionProposalJob.created_at.asc())
            .first()
        )

    def run_job(self, job: ActionProposalJob) -> None:
        """
        Execute a single job.

        Args:
            job: The job to execute

        Raises:
            ValueError: If job is not in QUEUED status
        """
        if job.status != ActionProposalJobStatus.QUEUED:
            raise ValueError(f"Job is not queued: {job.status.value}")

        logger.info(
            "Starting action proposal job",
            extra={
                "tenant_id": self.tenant_id,
                "job_id": job.job_id,
            },
        )

        # Mark as running
        job.mark_running()
        self.db.flush()

        try:
            # Create generation service
            generation_service = ActionProposalGenerationService(
                db_session=self.db,
                tenant_id=self.tenant_id,
            )

            # Generate proposals
            proposals, recommendations_processed = generation_service.generate_proposals(
                job_id=job.job_id,
            )

            # Mark as success
            job.mark_success(
                proposals_generated=len(proposals),
                recommendations_processed=recommendations_processed,
            )

            logger.info(
                "Action proposal job completed",
                extra={
                    "tenant_id": self.tenant_id,
                    "job_id": job.job_id,
                    "proposals_generated": len(proposals),
                    "recommendations_processed": recommendations_processed,
                },
            )

        except Exception as e:
            # Mark as failed
            error_message = str(e)[:500]
            job.mark_failed(error_message)

            logger.error(
                "Action proposal job failed",
                extra={
                    "tenant_id": self.tenant_id,
                    "job_id": job.job_id,
                    "error": error_message,
                },
                exc_info=True,
            )

        finally:
            self.db.flush()

    def run_next_job(self) -> ActionProposalJob | None:
        """
        Run the next queued job for this tenant.

        Returns:
            The job that was run, or None if no jobs
        """
        job = self.get_next_job()
        if not job:
            return None

        self.run_job(job)
        return job


def run_action_proposal_worker_cycle(db_session: Session) -> dict:
    """
    Run one cycle of the action proposal worker.

    Finds tenants with queued jobs and runs them.

    Args:
        db_session: Database session

    Returns:
        Statistics about the worker cycle
    """
    stats = {
        "jobs_processed": 0,
        "proposals_generated": 0,
        "failures": 0,
    }

    # Find tenants with queued jobs
    query = text("""
        SELECT DISTINCT tenant_id
        FROM action_proposal_jobs
        WHERE status = 'queued'
        ORDER BY created_at ASC
        LIMIT 10
    """)

    result = db_session.execute(query)
    tenant_ids = [row[0] for row in result.fetchall()]

    for tenant_id in tenant_ids:
        try:
            runner = ActionProposalJobRunner(db_session, tenant_id)
            job = runner.run_next_job()

            if job:
                stats["jobs_processed"] += 1
                if job.status == ActionProposalJobStatus.SUCCESS:
                    stats["proposals_generated"] += job.proposals_generated
                elif job.status == ActionProposalJobStatus.FAILED:
                    stats["failures"] += 1

                db_session.commit()

        except Exception as e:
            logger.error(
                "Error in worker cycle",
                extra={
                    "tenant_id": tenant_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            db_session.rollback()
            stats["failures"] += 1

    return stats
