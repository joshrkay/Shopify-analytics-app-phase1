"""
Ingestion job model for orchestration.

Defines the IngestionJob model that tracks Airbyte sync jobs with:
- Tenant isolation via TenantScopedMixin
- Status tracking (queued|running|failed|dead_letter|success)
- Retry tracking with max 5 attempts
- Correlation IDs for observability

SECURITY: tenant_id is ONLY extracted from JWT, never from client input.
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    String,
    Integer,
    Enum,
    DateTime,
    Text,
    Index,
    JSON,
    Boolean,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin

# Use JSONB for PostgreSQL, JSON for other databases (testing)
JSONType = JSON().with_variant(JSONB(), "postgresql")


class JobStatus(str, enum.Enum):
    """Ingestion job status enumeration."""
    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    SUCCESS = "success"


class IngestionJob(Base, TimestampMixin, TenantScopedMixin):
    """
    Tracks ingestion job execution for Airbyte Cloud syncs.

    CRITICAL: Only ONE active job per tenant + connector combination.
    This is enforced via partial unique index and application-level checks.

    Attributes:
        job_id: Primary key (UUID)
        tenant_id: Tenant identifier from JWT org_id (NEVER from client input)
        connector_id: Internal connector/connection ID
        external_account_id: External platform account ID (e.g., Shopify shop ID)
        status: Current job status (queued|running|failed|dead_letter|success)
        retry_count: Number of retry attempts (max 5)
        run_id: Airbyte job run ID (set when sync starts)
        correlation_id: Request correlation ID for tracing
        error_message: Last error message (for failed/dead_letter jobs)
        error_code: Error classification (auth_error|rate_limit|server_error|etc)
        started_at: When the job started running
        completed_at: When the job finished (success or final failure)
        metadata: Additional job metadata (sync type, etc)
    """

    __tablename__ = "ingestion_jobs"

    job_id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)"
    )

    # Connection identifiers
    connector_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Internal connector/connection ID"
    )
    external_account_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="External platform account ID (e.g., Shopify shop ID)"
    )

    # Status tracking
    status = Column(
        Enum(JobStatus),
        default=JobStatus.QUEUED,
        nullable=False,
        index=True,
        comment="Job status: queued, running, failed, dead_letter, success"
    )

    # Retry tracking
    retry_count = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Number of retry attempts (max 5)"
    )

    # Airbyte integration
    run_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Airbyte job run ID"
    )

    # Observability
    correlation_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Request correlation ID for distributed tracing"
    )

    # Error tracking
    error_message = Column(
        Text,
        nullable=True,
        comment="Last error message for failed jobs"
    )
    error_code = Column(
        String(50),
        nullable=True,
        index=True,
        comment="Error classification (auth_error, rate_limit, server_error)"
    )

    # Timestamps for lifecycle
    started_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the job started running"
    )
    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the job finished"
    )
    next_retry_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Scheduled time for next retry attempt"
    )

    # Additional metadata
    metadata = Column(
        JSONType,
        nullable=True,
        default=dict,
        comment="Additional job metadata (sync type, records count, etc)"
    )

    # Table constraints and indexes
    __table_args__ = (
        # Composite index for tenant-scoped status queries
        Index("ix_ingestion_jobs_tenant_status", "tenant_id", "status"),
        # Composite index for tenant + connector queries
        Index("ix_ingestion_jobs_tenant_connector", "tenant_id", "connector_id"),
        # Partial unique index: only ONE queued/running job per tenant+connector
        Index(
            "ix_ingestion_jobs_active_unique",
            "tenant_id",
            "connector_id",
            unique=True,
            postgresql_where=(status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
        ),
        # Index for finding jobs to retry
        Index(
            "ix_ingestion_jobs_retry_pending",
            "status",
            "next_retry_at",
            postgresql_where=(status == JobStatus.FAILED)
        ),
        # Index for dead letter queue queries
        Index(
            "ix_ingestion_jobs_dlq",
            "tenant_id",
            "created_at",
            postgresql_where=(status == JobStatus.DEAD_LETTER)
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<IngestionJob("
            f"job_id={self.job_id}, "
            f"tenant_id={self.tenant_id}, "
            f"connector_id={self.connector_id}, "
            f"status={self.status.value if self.status else None}"
            f")>"
        )

    @property
    def is_active(self) -> bool:
        """Check if job is currently active (queued or running)."""
        return self.status in (JobStatus.QUEUED, JobStatus.RUNNING)

    @property
    def is_terminal(self) -> bool:
        """Check if job is in a terminal state."""
        return self.status in (JobStatus.SUCCESS, JobStatus.DEAD_LETTER)

    @property
    def can_retry(self) -> bool:
        """Check if job can be retried (failed and under max retries)."""
        return self.status == JobStatus.FAILED and self.retry_count < 5

    def mark_running(self, run_id: str) -> None:
        """Mark job as running with Airbyte run ID."""
        self.status = JobStatus.RUNNING
        self.run_id = run_id
        self.started_at = datetime.now(timezone.utc)

    def mark_success(self, metadata: dict | None = None) -> None:
        """Mark job as successful."""
        self.status = JobStatus.SUCCESS
        self.completed_at = datetime.now(timezone.utc)
        if metadata:
            self.metadata = {**(self.metadata or {}), **metadata}

    def mark_failed(
        self,
        error_message: str,
        error_code: str | None = None,
        next_retry_at: datetime | None = None,
    ) -> None:
        """
        Mark job as failed with error details.

        Args:
            error_message: Human-readable error description
            error_code: Error classification for retry decisions
            next_retry_at: When to attempt retry (None = no auto-retry)
        """
        self.status = JobStatus.FAILED
        self.error_message = error_message
        self.error_code = error_code
        self.next_retry_at = next_retry_at
        self.retry_count += 1

    def mark_dead_letter(self, error_message: str) -> None:
        """Move job to dead letter queue after exhausting retries."""
        self.status = JobStatus.DEAD_LETTER
        self.error_message = error_message
        self.completed_at = datetime.now(timezone.utc)
        self.next_retry_at = None
