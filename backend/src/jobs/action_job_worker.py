"""
Action Job Worker for Story 8.5.

Background worker that processes queued action jobs:
- Picks up QUEUED jobs from action_jobs table
- Executes actions via platform executors
- Records execution logs for audit
- Handles partial success and rollback generation

Run as a cron job or background worker:
    python -m src.jobs.action_job_worker

Configuration:
- ACTION_JOB_BATCH_SIZE: Number of tenants to process per batch (default: 50)
- ACTION_JOB_MAX_CONCURRENT: Max concurrent actions per job (default: 5)

SECURITY:
- All operations are tenant-scoped
- Entitlement checks before each job
- Full audit trail via action_execution_logs

EXTERNAL PLATFORM IS SOURCE OF TRUTH:
- State captured before/after execution
- Platform response determines success/failure
- No blind retries - failures require explicit re-trigger

Story 8.5 - Action Execution (Scoped & Reversible)
"""

import os
import sys
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.session import get_db_session_sync
from src.models.ai_action import AIAction, ActionStatus
from src.models.action_job import ActionJob, ActionJobStatus
from src.services.action_job_runner import ActionJobRunner
from src.services.action_job_dispatcher import ActionJobDispatcher, dispatch_action_jobs
from src.services.billing_entitlements import BillingEntitlementsService, BillingFeature
from src.jobs.job_entitlements import (
    JobEntitlementChecker,
    JobType,
    JobEntitlementResult,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
ACTION_JOB_BATCH_SIZE = int(os.getenv("ACTION_JOB_BATCH_SIZE", "50"))


class ActionJobWorker:
    """
    Background worker for processing action jobs.

    Processes queued jobs for all tenants, executing actions
    against external platforms with full audit logging.
    """

    def __init__(self, db_session: Session):
        """
        Initialize action job worker.

        Args:
            db_session: Database session
        """
        self.db = db_session
        self.run_id = str(uuid.uuid4())
        self.stats = {
            "jobs_processed": 0,
            "jobs_succeeded": 0,
            "jobs_failed": 0,
            "jobs_partial": 0,
            "actions_executed": 0,
            "actions_succeeded": 0,
            "actions_failed": 0,
            "tenants_processed": 0,
            "jobs_dispatched": 0,
            "errors": 0,
        }

    def _get_queued_jobs(self, limit: int = 100) -> List[ActionJob]:
        """Get queued jobs across all tenants."""
        return (
            self.db.query(ActionJob)
            .filter(ActionJob.status == ActionJobStatus.QUEUED)
            .order_by(ActionJob.created_at.asc())
            .limit(limit)
            .all()
        )

    def _check_entitlement(self, tenant_id: str) -> JobEntitlementResult:
        """Check if tenant is entitled to AI actions."""
        checker = JobEntitlementChecker(self.db)
        return checker.check_job_entitlement(tenant_id, JobType.AI_ACTION)

    async def process_job(self, job: ActionJob) -> bool:
        """
        Process a single action job.

        Args:
            job: ActionJob to process

        Returns:
            True if job completed successfully, False otherwise
        """
        tenant_id = job.tenant_id
        job_id = job.job_id

        logger.info(
            "Processing action job",
            extra={
                "run_id": self.run_id,
                "tenant_id": tenant_id,
                "job_id": job_id,
                "action_count": len(job.action_ids) if job.action_ids else 0,
            },
        )

        try:
            # Check entitlement
            entitlement = self._check_entitlement(tenant_id)
            if not entitlement.is_allowed:
                logger.warning(
                    "Job skipped due to entitlement",
                    extra={
                        "tenant_id": tenant_id,
                        "job_id": job_id,
                        "reason": entitlement.reason,
                    },
                )
                # Mark job as failed due to entitlement
                job.status = ActionJobStatus.FAILED
                job.error_message = f"Entitlement check failed: {entitlement.reason}"
                job.completed_at = datetime.now(timezone.utc)
                self.db.flush()
                self.stats["jobs_failed"] += 1
                return False

            # Create job runner and process
            runner = ActionJobRunner(self.db, tenant_id)
            await runner.process_job(job)

            # Update stats based on job status
            self.stats["jobs_processed"] += 1
            self.stats["actions_executed"] += (job.succeeded_count or 0) + (job.failed_count or 0)
            self.stats["actions_succeeded"] += job.succeeded_count or 0
            self.stats["actions_failed"] += job.failed_count or 0

            if job.status == ActionJobStatus.SUCCEEDED:
                self.stats["jobs_succeeded"] += 1
                return True
            elif job.status == ActionJobStatus.PARTIAL_SUCCESS:
                self.stats["jobs_partial"] += 1
                return True  # Partial success is still a "success" for the worker
            else:
                self.stats["jobs_failed"] += 1
                return False

        except Exception as e:
            logger.error(
                "Error processing action job",
                extra={
                    "run_id": self.run_id,
                    "tenant_id": tenant_id,
                    "job_id": job_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            self.stats["errors"] += 1
            self.stats["jobs_failed"] += 1

            # Mark job as failed
            job.status = ActionJobStatus.FAILED
            job.error_message = f"Worker error: {str(e)}"
            job.completed_at = datetime.now(timezone.utc)
            self.db.flush()

            return False

    async def dispatch_new_jobs(self) -> int:
        """
        Dispatch new jobs for approved actions.

        Returns number of jobs created.
        """
        try:
            jobs_created = dispatch_action_jobs(self.db, limit=ACTION_JOB_BATCH_SIZE)
            self.stats["jobs_dispatched"] += jobs_created

            logger.info(
                "Jobs dispatched",
                extra={
                    "run_id": self.run_id,
                    "jobs_created": jobs_created,
                },
            )

            return jobs_created

        except Exception as e:
            logger.error(
                "Error dispatching jobs",
                extra={
                    "run_id": self.run_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            self.stats["errors"] += 1
            return 0

    async def run(self) -> Dict:
        """
        Run the action job worker.

        Processes all queued jobs and dispatches new ones.

        Returns run statistics.
        """
        start_time = datetime.now(timezone.utc)
        logger.info(
            "Starting action job worker",
            extra={"run_id": self.run_id},
        )

        try:
            # First, dispatch new jobs for approved actions
            await self.dispatch_new_jobs()

            # Get all queued jobs
            jobs = self._get_queued_jobs(limit=ACTION_JOB_BATCH_SIZE)
            logger.info(
                f"Found {len(jobs)} queued jobs to process",
                extra={"run_id": self.run_id},
            )

            # Track unique tenants
            tenants_seen = set()

            # Process jobs
            for job in jobs:
                tenants_seen.add(job.tenant_id)
                await self.process_job(job)

                # Commit after each job
                self.db.commit()

            self.stats["tenants_processed"] = len(tenants_seen)

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(
                "Action job worker failed",
                extra={
                    "run_id": self.run_id,
                    "error": str(e),
                },
                exc_info=True,
            )

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        self.stats["duration_seconds"] = duration
        self.stats["run_id"] = self.run_id

        logger.info(
            "Action job worker completed",
            extra={
                "run_id": self.run_id,
                "duration_seconds": duration,
                **self.stats,
            },
        )

        return self.stats


async def main():
    """Main entry point for action job worker."""
    logger.info("Action Job Worker starting")

    try:
        for session in get_db_session_sync():
            worker = ActionJobWorker(session)
            stats = await worker.run()
            logger.info("Action Job Worker stats", extra=stats)
    except Exception as e:
        logger.error("Action Job Worker failed", extra={"error": str(e)}, exc_info=True)
        sys.exit(1)

    logger.info("Action Job Worker finished")


if __name__ == "__main__":
    asyncio.run(main())
