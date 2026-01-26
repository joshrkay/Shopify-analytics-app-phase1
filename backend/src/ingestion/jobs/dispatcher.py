"""
Job dispatcher for ingestion orchestration.

Handles:
- Cron-triggered scheduled job creation
- Job queueing with isolation (one active job per tenant+connector)
- Job entitlement checks
- Manual requeue from dead letter queue (support-only)

SECURITY: All operations are tenant-scoped via tenant_id from JWT.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.ingestion.jobs.models import IngestionJob, JobStatus
from src.platform.audit import AuditAction

logger = logging.getLogger(__name__)


class JobIsolationError(Exception):
    """Raised when job isolation constraints are violated."""

    def __init__(self, message: str, existing_job_id: str):
        super().__init__(message)
        self.existing_job_id = existing_job_id


class JobNotFoundError(Exception):
    """Raised when a job is not found."""
    pass


class JobDispatcher:
    """
    Dispatcher for ingestion jobs.

    Responsibilities:
    - Create and queue jobs with isolation enforcement
    - Check for existing active jobs before dispatching
    - Manage job lifecycle transitions
    - Support manual requeue from DLQ (support-only operation)

    SECURITY: All operations are tenant-scoped. tenant_id comes from JWT.
    """

    def __init__(self, db_session: Session, tenant_id: str):
        """
        Initialize job dispatcher.

        Args:
            db_session: Database session
            tenant_id: Tenant ID from JWT (org_id)

        Raises:
            ValueError: If tenant_id is empty or None
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id

    def get_active_job(
        self,
        connector_id: str,
    ) -> Optional[IngestionJob]:
        """
        Get active job for a connector.

        Active = queued or running status.

        Args:
            connector_id: Internal connector ID

        Returns:
            Active IngestionJob if exists, None otherwise
        """
        return (
            self.db.query(IngestionJob)
            .filter(
                IngestionJob.tenant_id == self.tenant_id,
                IngestionJob.connector_id == connector_id,
                IngestionJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            )
            .first()
        )

    def has_active_job(self, connector_id: str) -> bool:
        """
        Check if an active job exists for a connector.

        Args:
            connector_id: Internal connector ID

        Returns:
            True if active job exists
        """
        return self.get_active_job(connector_id) is not None

    def dispatch(
        self,
        connector_id: str,
        external_account_id: str,
        correlation_id: Optional[str] = None,
        job_metadata: Optional[dict] = None,
    ) -> IngestionJob:
        """
        Dispatch a new ingestion job.

        Creates a job in QUEUED status, enforcing isolation constraint
        (only one active job per tenant+connector).

        Args:
            connector_id: Internal connector/connection ID
            external_account_id: External platform account ID
            correlation_id: Request correlation ID for tracing
            job_metadata: Additional job metadata

        Returns:
            Created IngestionJob in QUEUED status

        Raises:
            JobIsolationError: If active job already exists for this connector
        """
        # Check for existing active job
        active_job = self.get_active_job(connector_id)
        if active_job:
            logger.warning(
                "Job dispatch blocked - active job exists",
                extra={
                    "tenant_id": self.tenant_id,
                    "connector_id": connector_id,
                    "existing_job_id": active_job.job_id,
                    "existing_status": active_job.status.value,
                },
            )
            raise JobIsolationError(
                f"Active job already exists for connector {connector_id}",
                existing_job_id=active_job.job_id,
            )

        # Create new job
        job = IngestionJob(
            job_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            connector_id=connector_id,
            external_account_id=external_account_id,
            status=JobStatus.QUEUED,
            retry_count=0,
            correlation_id=correlation_id,
            job_metadata=job_metadata or {},
        )

        try:
            self.db.add(job)
            self.db.flush()

            logger.info(
                "job.queued",
                extra={
                    "job_id": job.job_id,
                    "tenant_id": self.tenant_id,
                    "connector_id": connector_id,
                    "external_account_id": external_account_id,
                    "correlation_id": correlation_id,
                },
            )

            return job

        except IntegrityError:
            # Partial unique index violation - race condition
            self.db.rollback()
            active_job = self.get_active_job(connector_id)
            existing_id = active_job.job_id if active_job else "unknown"

            logger.warning(
                "Job dispatch race condition - concurrent job created",
                extra={
                    "tenant_id": self.tenant_id,
                    "connector_id": connector_id,
                    "existing_job_id": existing_id,
                },
            )
            raise JobIsolationError(
                f"Concurrent active job detected for connector {connector_id}",
                existing_job_id=existing_id,
            )

    def get_job(self, job_id: str) -> Optional[IngestionJob]:
        """
        Get a job by ID within tenant scope.

        Args:
            job_id: Job UUID

        Returns:
            IngestionJob if found, None otherwise
        """
        return (
            self.db.query(IngestionJob)
            .filter(
                IngestionJob.tenant_id == self.tenant_id,
                IngestionJob.job_id == job_id,
            )
            .first()
        )

    def get_queued_jobs(
        self,
        connector_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[IngestionJob]:
        """
        Get queued jobs ready for execution.

        Args:
            connector_id: Optional filter by connector
            limit: Maximum jobs to return

        Returns:
            List of queued IngestionJobs ordered by creation time
        """
        query = (
            self.db.query(IngestionJob)
            .filter(
                IngestionJob.tenant_id == self.tenant_id,
                IngestionJob.status == JobStatus.QUEUED,
            )
        )

        if connector_id:
            query = query.filter(IngestionJob.connector_id == connector_id)

        return (
            query
            .order_by(IngestionJob.created_at.asc())
            .limit(limit)
            .all()
        )

    def get_failed_jobs_for_retry(
        self,
        limit: int = 100,
    ) -> list[IngestionJob]:
        """
        Get failed jobs that are due for retry.

        Jobs with next_retry_at in the past and status=FAILED.

        Args:
            limit: Maximum jobs to return

        Returns:
            List of failed IngestionJobs ready for retry
        """
        now = datetime.now(timezone.utc)

        return (
            self.db.query(IngestionJob)
            .filter(
                IngestionJob.tenant_id == self.tenant_id,
                IngestionJob.status == JobStatus.FAILED,
                IngestionJob.next_retry_at <= now,
                IngestionJob.retry_count < 5,  # Max retries
            )
            .order_by(IngestionJob.next_retry_at.asc())
            .limit(limit)
            .all()
        )

    def get_dead_letter_jobs(
        self,
        limit: int = 100,
    ) -> list[IngestionJob]:
        """
        Get jobs in dead letter queue.

        Args:
            limit: Maximum jobs to return

        Returns:
            List of dead-lettered IngestionJobs
        """
        return (
            self.db.query(IngestionJob)
            .filter(
                IngestionJob.tenant_id == self.tenant_id,
                IngestionJob.status == JobStatus.DEAD_LETTER,
            )
            .order_by(IngestionJob.completed_at.desc())
            .limit(limit)
            .all()
        )

    def requeue_from_dlq(
        self,
        job_id: str,
        correlation_id: Optional[str] = None,
    ) -> IngestionJob:
        """
        Requeue a job from dead letter queue.

        SUPPORT-ONLY: This operation should be restricted to support staff.
        Creates a new job with reset retry count.

        Args:
            job_id: Job UUID of dead-lettered job
            correlation_id: New correlation ID for tracing

        Returns:
            New IngestionJob in QUEUED status

        Raises:
            JobNotFoundError: If job not found
            JobIsolationError: If active job exists
            ValueError: If job is not in dead letter status
        """
        original_job = self.get_job(job_id)

        if not original_job:
            raise JobNotFoundError(f"Job {job_id} not found")

        if original_job.status != JobStatus.DEAD_LETTER:
            raise ValueError(
                f"Job {job_id} is not in dead letter queue (status: {original_job.status.value})"
            )

        logger.info(
            "job.dlq_requeue",
            extra={
                "original_job_id": job_id,
                "tenant_id": self.tenant_id,
                "connector_id": original_job.connector_id,
                "correlation_id": correlation_id,
            },
        )

        # Create new job (dispatch handles isolation check)
        return self.dispatch(
            connector_id=original_job.connector_id,
            external_account_id=original_job.external_account_id,
            correlation_id=correlation_id or original_job.correlation_id,
            job_metadata={
                **(original_job.job_metadata or {}),
                "requeued_from": job_id,
                "original_error": original_job.error_message,
            },
        )

    def cancel_job(self, job_id: str) -> IngestionJob:
        """
        Cancel a queued job.

        Only queued jobs can be cancelled. Running jobs must complete or fail.

        Args:
            job_id: Job UUID

        Returns:
            Cancelled IngestionJob

        Raises:
            JobNotFoundError: If job not found
            ValueError: If job is not in queued status
        """
        job = self.get_job(job_id)

        if not job:
            raise JobNotFoundError(f"Job {job_id} not found")

        if job.status != JobStatus.QUEUED:
            raise ValueError(
                f"Cannot cancel job {job_id} in status {job.status.value}"
            )

        job.status = JobStatus.FAILED
        job.error_message = "Cancelled by user"
        job.error_code = "cancelled"
        job.completed_at = datetime.now(timezone.utc)

        self.db.flush()

        logger.info(
            "job.cancelled",
            extra={
                "job_id": job_id,
                "tenant_id": self.tenant_id,
                "connector_id": job.connector_id,
            },
        )

        return job


def get_global_queued_jobs(
    db_session: Session,
    limit: int = 100,
) -> list[IngestionJob]:
    """
    Get queued jobs across all tenants for cron processing.

    Used by the worker to pick up jobs. Returns oldest jobs first.

    Args:
        db_session: Database session
        limit: Maximum jobs to return

    Returns:
        List of queued IngestionJobs across all tenants
    """
    return (
        db_session.query(IngestionJob)
        .filter(IngestionJob.status == JobStatus.QUEUED)
        .order_by(IngestionJob.created_at.asc())
        .limit(limit)
        .all()
    )


def get_global_failed_jobs_for_retry(
    db_session: Session,
    limit: int = 100,
) -> list[IngestionJob]:
    """
    Get failed jobs due for retry across all tenants.

    Used by the worker to process retry queue.

    Args:
        db_session: Database session
        limit: Maximum jobs to return

    Returns:
        List of failed IngestionJobs ready for retry
    """
    now = datetime.now(timezone.utc)

    return (
        db_session.query(IngestionJob)
        .filter(
            IngestionJob.status == JobStatus.FAILED,
            IngestionJob.next_retry_at <= now,
            IngestionJob.retry_count < 5,
        )
        .order_by(IngestionJob.next_retry_at.asc())
        .limit(limit)
        .all()
    )
