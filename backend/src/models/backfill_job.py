"""
Backfill job model — tracks individual execution chunks.

A single HistoricalBackfillRequest is split into multiple BackfillJobs,
each covering a 7-day (configurable) date slice. This enables:
- Progress persistence after each chunk
- Safe retry on failure (only the failed chunk)
- Pause / resume at chunk boundaries
- Survival across worker restarts

Story 3.4 - Backfill Execution
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Date, DateTime, Text, Float,
    Index, Enum, JSON,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.db_base import Base
from src.models.base import TimestampMixin

JSONType = JSON().with_variant(JSONB(), "postgresql")


class BackfillJobStatus(str, enum.Enum):
    """Chunk execution status."""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


ACTIVE_JOB_STATUSES = [BackfillJobStatus.QUEUED, BackfillJobStatus.RUNNING]
RETRYABLE_STATUSES = [BackfillJobStatus.FAILED]


class BackfillJob(Base, TimestampMixin):
    """
    Tracks a single execution chunk of a backfill request.

    One HistoricalBackfillRequest → many BackfillJobs (one per date chunk).
    Each chunk is independently retryable and restartable.

    NOT using TenantScopedMixin because tenant_id is the TARGET tenant
    (same rationale as HistoricalBackfillRequest).
    """

    __tablename__ = "historical_backfill_jobs"

    id = Column(
        String(255), primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # Link to parent request
    backfill_request_id = Column(
        String(255), nullable=False, index=True,
        comment="FK to historical_backfill_requests.id",
    )

    # Execution scope
    tenant_id = Column(String(255), nullable=False, index=True)
    source_system = Column(String(50), nullable=False)
    chunk_start_date = Column(Date, nullable=False)
    chunk_end_date = Column(Date, nullable=False)
    chunk_index = Column(Integer, nullable=False, comment="0-based chunk order")

    # Status
    status = Column(
        Enum(BackfillJobStatus), nullable=False,
        default=BackfillJobStatus.QUEUED, index=True,
    )

    # Retry tracking
    attempt = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)

    # Timing
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Results
    rows_affected = Column(Integer, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    job_metadata = Column(JSONType, nullable=True, default=dict)

    __table_args__ = (
        Index("idx_hist_backfill_jobs_request_status",
              "backfill_request_id", "status"),
        Index("idx_hist_backfill_jobs_tenant_status",
              "tenant_id", "status"),
        Index("idx_hist_backfill_jobs_retry",
              "status", "next_retry_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<BackfillJob(id={self.id}, "
            f"chunk={self.chunk_index}, "
            f"status={self.status})>"
        )

    @property
    def is_active(self) -> bool:
        return self.status in (BackfillJobStatus.QUEUED, BackfillJobStatus.RUNNING)

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            BackfillJobStatus.SUCCESS,
            BackfillJobStatus.FAILED,
            BackfillJobStatus.CANCELLED,
        )

    @property
    def can_retry(self) -> bool:
        return (
            self.status == BackfillJobStatus.FAILED
            and self.attempt < self.max_retries
        )

    def mark_running(self) -> None:
        self.status = BackfillJobStatus.RUNNING
        self.started_at = datetime.now(timezone.utc)
        self.attempt += 1

    def mark_success(self, rows_affected: int = 0, duration: float = 0.0) -> None:
        self.status = BackfillJobStatus.SUCCESS
        self.completed_at = datetime.now(timezone.utc)
        self.rows_affected = rows_affected
        self.duration_seconds = duration

    def mark_failed(self, error_message: str) -> None:
        self.status = BackfillJobStatus.FAILED
        self.completed_at = datetime.now(timezone.utc)
        self.error_message = error_message[:1000] if error_message else None

    def mark_cancelled(self) -> None:
        self.status = BackfillJobStatus.CANCELLED
        self.completed_at = datetime.now(timezone.utc)

    def mark_paused(self) -> None:
        self.status = BackfillJobStatus.PAUSED
        self.completed_at = datetime.now(timezone.utc)

    def schedule_retry(self, delay_seconds: float) -> None:
        """Schedule a retry after the given delay."""
        from datetime import timedelta
        self.status = BackfillJobStatus.QUEUED
        self.next_retry_at = datetime.now(timezone.utc) + timedelta(
            seconds=delay_seconds
        )
        self.completed_at = None
        self.started_at = None
