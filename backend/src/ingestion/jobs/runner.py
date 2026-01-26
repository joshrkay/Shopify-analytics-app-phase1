"""
Job runner for ingestion orchestration.

Executes ingestion jobs:
- Picks up queued jobs
- Calls Airbyte Cloud API to trigger syncs
- Handles retries and DLQ on failures
- Emits audit events for observability

Designed to run as Render managed worker with cron triggers.

SECURITY: All operations are tenant-isolated.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.ingestion.jobs.models import IngestionJob, JobStatus
from src.ingestion.jobs.dispatcher import (
    JobDispatcher,
    get_global_queued_jobs,
    get_global_failed_jobs_for_retry,
)
from src.ingestion.jobs.retry import (
    RetryPolicy,
    ErrorCategory,
    should_retry,
    categorize_error,
    log_retry_decision,
)
from src.ingestion.airbyte.client import IngestionAirbyteClient, SyncJobResult
from src.services.airbyte_service import AirbyteService
from src.jobs.job_entitlements import JobEntitlementChecker, JobType
from src.integrations.airbyte.models import AirbyteJobStatus

logger = logging.getLogger(__name__)

# Default execution timeouts
DEFAULT_SYNC_TIMEOUT_SECONDS = 3600  # 1 hour
DEFAULT_POLL_INTERVAL_SECONDS = 30


class JobRunner:
    """
    Executes ingestion jobs by triggering Airbyte syncs.

    Responsibilities:
    - Execute queued jobs
    - Handle retries with exponential backoff
    - Move jobs to DLQ after max retries
    - Emit audit events for all state transitions

    SECURITY: Enforces tenant isolation and job entitlements.
    """

    def __init__(
        self,
        db_session: Session,
        airbyte_client: Optional[IngestionAirbyteClient] = None,
        retry_policy: RetryPolicy = RetryPolicy(),
        sync_timeout_seconds: float = DEFAULT_SYNC_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ):
        """
        Initialize job runner.

        Args:
            db_session: Database session
            airbyte_client: Optional Airbyte client (creates default if not provided)
            retry_policy: Retry policy configuration
            sync_timeout_seconds: Maximum sync wait time
            poll_interval_seconds: Status check interval
        """
        self.db = db_session
        self._airbyte_client = airbyte_client
        self.retry_policy = retry_policy
        self.sync_timeout = sync_timeout_seconds
        self.poll_interval = poll_interval_seconds

    def _get_airbyte_client(self) -> IngestionAirbyteClient:
        """Get or create Airbyte client."""
        if self._airbyte_client is None:
            self._airbyte_client = IngestionAirbyteClient()
        return self._airbyte_client

    def _get_airbyte_connection_id(
        self,
        tenant_id: str,
        connector_id: str,
    ) -> Optional[str]:
        """
        Get Airbyte connection ID for an internal connector.

        Args:
            tenant_id: Tenant identifier
            connector_id: Internal connector ID

        Returns:
            Airbyte connection UUID or None
        """
        service = AirbyteService(self.db, tenant_id)
        connection = service.get_connection(connector_id)
        return connection.airbyte_connection_id if connection else None

    def _check_entitlement(self, tenant_id: str) -> bool:
        """
        Check if tenant has entitlement to run sync jobs.

        Args:
            tenant_id: Tenant identifier

        Returns:
            True if allowed, False otherwise
        """
        checker = JobEntitlementChecker(self.db)
        result = checker.check_job_entitlement(tenant_id, JobType.SYNC)
        return result.is_allowed

    def _log_job_started(self, job: IngestionJob) -> None:
        """Log job.started audit event."""
        logger.info(
            "job.started",
            extra={
                "job_id": job.job_id,
                "tenant_id": job.tenant_id,
                "connector_id": job.connector_id,
                "external_account_id": job.external_account_id,
                "run_id": job.run_id,
                "correlation_id": job.correlation_id,
            },
        )

    def _log_job_retry(
        self,
        job: IngestionJob,
        error_category: ErrorCategory,
        delay_seconds: float,
    ) -> None:
        """Log job.retry audit event."""
        logger.info(
            "job.retry",
            extra={
                "job_id": job.job_id,
                "tenant_id": job.tenant_id,
                "connector_id": job.connector_id,
                "retry_count": job.retry_count,
                "error_category": error_category.value,
                "delay_seconds": delay_seconds,
                "next_retry_at": job.next_retry_at.isoformat() if job.next_retry_at else None,
                "correlation_id": job.correlation_id,
            },
        )

    def _log_job_failed(self, job: IngestionJob) -> None:
        """Log job.failed audit event."""
        logger.error(
            "job.failed",
            extra={
                "job_id": job.job_id,
                "tenant_id": job.tenant_id,
                "connector_id": job.connector_id,
                "error_message": job.error_message,
                "error_code": job.error_code,
                "retry_count": job.retry_count,
                "correlation_id": job.correlation_id,
            },
        )

    def _log_job_dead_lettered(self, job: IngestionJob) -> None:
        """Log job.dead_lettered audit event."""
        logger.error(
            "job.dead_lettered",
            extra={
                "job_id": job.job_id,
                "tenant_id": job.tenant_id,
                "connector_id": job.connector_id,
                "error_message": job.error_message,
                "error_code": job.error_code,
                "retry_count": job.retry_count,
                "correlation_id": job.correlation_id,
            },
        )

    def _log_job_completed(
        self,
        job: IngestionJob,
        result: SyncJobResult,
    ) -> None:
        """Log job.completed audit event."""
        logger.info(
            "job.completed",
            extra={
                "job_id": job.job_id,
                "tenant_id": job.tenant_id,
                "connector_id": job.connector_id,
                "run_id": job.run_id,
                "records_synced": result.records_synced,
                "bytes_synced": result.bytes_synced,
                "duration_seconds": result.duration_seconds,
                "correlation_id": job.correlation_id,
            },
        )

    async def execute_job(self, job: IngestionJob) -> None:
        """
        Execute a single ingestion job.

        Triggers Airbyte sync and waits for completion.
        Updates job status based on result.

        Args:
            job: IngestionJob to execute
        """
        # Check entitlement
        if not self._check_entitlement(job.tenant_id):
            logger.warning(
                "job.skipped_entitlement",
                extra={
                    "job_id": job.job_id,
                    "tenant_id": job.tenant_id,
                    "connector_id": job.connector_id,
                },
            )
            job.mark_failed(
                error_message="Job skipped - tenant entitlement check failed",
                error_code="entitlement_denied",
            )
            self.db.flush()
            return

        # Get Airbyte connection ID
        airbyte_connection_id = self._get_airbyte_connection_id(
            job.tenant_id,
            job.connector_id,
        )

        if not airbyte_connection_id:
            job.mark_failed(
                error_message=f"Connection {job.connector_id} not found or missing Airbyte ID",
                error_code="connection_not_found",
            )
            self.db.flush()
            self._log_job_failed(job)
            return

        # Trigger sync
        client = self._get_airbyte_client()

        result = await client.trigger_sync(
            airbyte_connection_id=airbyte_connection_id,
            connector_id=job.connector_id,
            external_account_id=job.external_account_id,
        )

        # Handle trigger failure
        if result.error_category is not None:
            self._handle_job_failure(
                job=job,
                error_category=result.error_category,
                error_message=result.error_message or "Sync trigger failed",
                retry_after=result.retry_after,
            )
            return

        # Mark job as running
        if result.run_id:
            job.mark_running(result.run_id)
            self.db.flush()
            self._log_job_started(job)

        # Wait for sync completion
        wait_result = await client.wait_for_sync(
            run_id=result.run_id,
            connection_id=airbyte_connection_id,
            timeout_seconds=self.sync_timeout,
            poll_interval_seconds=self.poll_interval,
        )

        # Handle result
        if wait_result.error_category is not None:
            self._handle_job_failure(
                job=job,
                error_category=wait_result.error_category,
                error_message=wait_result.error_message or "Sync failed",
                retry_after=wait_result.retry_after,
            )
            return

        if wait_result.status == AirbyteJobStatus.SUCCEEDED:
            job.mark_success(metadata={
                "records_synced": wait_result.records_synced,
                "bytes_synced": wait_result.bytes_synced,
                "duration_seconds": wait_result.duration_seconds,
            })
            self.db.flush()
            self._log_job_completed(job, wait_result)
        else:
            # Sync completed but not successful
            self._handle_job_failure(
                job=job,
                error_category=ErrorCategory.SYNC_FAILED,
                error_message=f"Sync completed with status: {wait_result.status.value if wait_result.status else 'unknown'}",
            )

    def _handle_job_failure(
        self,
        job: IngestionJob,
        error_category: ErrorCategory,
        error_message: str,
        retry_after: Optional[int] = None,
    ) -> None:
        """
        Handle job failure with retry logic.

        Args:
            job: Failed job
            error_category: Classified error type
            error_message: Human-readable error
            retry_after: Server-specified retry delay
        """
        decision = should_retry(
            error_category=error_category,
            retry_count=job.retry_count,
            policy=self.retry_policy,
            retry_after=retry_after,
        )

        log_retry_decision(
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            error_category=error_category,
            decision=decision,
        )

        if decision.move_to_dlq:
            job.mark_dead_letter(error_message)
            self.db.flush()
            self._log_job_dead_lettered(job)
        elif decision.should_retry:
            job.mark_failed(
                error_message=error_message,
                error_code=error_category.value,
                next_retry_at=decision.next_retry_at,
            )
            self.db.flush()
            self._log_job_retry(job, error_category, decision.delay_seconds)
        else:
            job.mark_failed(
                error_message=error_message,
                error_code=error_category.value,
            )
            self.db.flush()
            self._log_job_failed(job)

    async def process_queued_jobs(
        self,
        limit: int = 10,
    ) -> int:
        """
        Process batch of queued jobs.

        Picks up and executes queued jobs across all tenants.
        Respects job isolation - only one job per tenant+connector.

        Args:
            limit: Maximum jobs to process in this batch

        Returns:
            Number of jobs processed
        """
        jobs = get_global_queued_jobs(self.db, limit=limit)

        if not jobs:
            logger.debug("No queued jobs to process")
            return 0

        processed = 0
        for job in jobs:
            try:
                # Check isolation - skip if another job started
                if job.status != JobStatus.QUEUED:
                    continue

                await self.execute_job(job)
                processed += 1

            except Exception as e:
                logger.error(
                    "Unexpected error executing job",
                    extra={
                        "job_id": job.job_id,
                        "tenant_id": job.tenant_id,
                        "error": str(e),
                    },
                    exc_info=True,
                )
                # Mark as failed with unknown error
                self._handle_job_failure(
                    job=job,
                    error_category=ErrorCategory.UNKNOWN,
                    error_message=f"Unexpected error: {str(e)[:500]}",
                )

        self.db.commit()
        return processed

    async def process_retry_jobs(
        self,
        limit: int = 10,
    ) -> int:
        """
        Process failed jobs due for retry.

        Picks up jobs in FAILED status with next_retry_at in the past.

        Args:
            limit: Maximum jobs to process

        Returns:
            Number of jobs retried
        """
        jobs = get_global_failed_jobs_for_retry(self.db, limit=limit)

        if not jobs:
            logger.debug("No failed jobs ready for retry")
            return 0

        processed = 0
        for job in jobs:
            try:
                # Re-check isolation before retry
                dispatcher = JobDispatcher(self.db, job.tenant_id)
                active = dispatcher.get_active_job(job.connector_id)

                if active and active.job_id != job.job_id:
                    logger.info(
                        "Retry skipped - active job exists",
                        extra={
                            "job_id": job.job_id,
                            "active_job_id": active.job_id,
                            "tenant_id": job.tenant_id,
                        },
                    )
                    continue

                # Reset to queued for re-execution
                job.status = JobStatus.QUEUED
                job.next_retry_at = None
                self.db.flush()

                await self.execute_job(job)
                processed += 1

            except Exception as e:
                logger.error(
                    "Unexpected error retrying job",
                    extra={
                        "job_id": job.job_id,
                        "tenant_id": job.tenant_id,
                        "error": str(e),
                    },
                    exc_info=True,
                )
                self._handle_job_failure(
                    job=job,
                    error_category=ErrorCategory.UNKNOWN,
                    error_message=f"Retry failed: {str(e)[:500]}",
                )

        self.db.commit()
        return processed


async def run_worker_cycle(
    db_session: Session,
    airbyte_client: Optional[IngestionAirbyteClient] = None,
    job_limit: int = 10,
) -> dict:
    """
    Run one cycle of the ingestion worker.

    Called by cron trigger to process jobs.

    Args:
        db_session: Database session
        airbyte_client: Optional Airbyte client
        job_limit: Maximum jobs per category to process

    Returns:
        Summary of jobs processed
    """
    runner = JobRunner(
        db_session=db_session,
        airbyte_client=airbyte_client,
    )

    queued_processed = await runner.process_queued_jobs(limit=job_limit)
    retry_processed = await runner.process_retry_jobs(limit=job_limit)

    logger.info(
        "Worker cycle completed",
        extra={
            "queued_processed": queued_processed,
            "retry_processed": retry_processed,
        },
    )

    return {
        "queued_processed": queued_processed,
        "retry_processed": retry_processed,
    }
