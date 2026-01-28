"""
Recommendation Job model for tracking recommendation generation.

Tracks the execution of recommendation generation jobs that analyze
AI insights and produce tactical recommendations.

SECURITY:
- Tenant isolation via TenantScopedMixin (tenant_id from JWT only)
- Only one active job per tenant at a time (enforced by DB constraint)

Story 8.3 - AI Recommendations (No Actions)
"""

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, String, Integer, Enum, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import JSON

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin


# Use JSONB for PostgreSQL, JSON for other databases (testing)
JSONType = JSON().with_variant(JSONB(), "postgresql")


class RecommendationJobStatus(str, enum.Enum):
    """Status of a recommendation generation job."""
    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    SUCCESS = "success"
    SKIPPED = "skipped"


class RecommendationJobCadence(str, enum.Enum):
    """Cadence for recommendation generation."""
    DAILY = "daily"
    HOURLY = "hourly"  # Enterprise only


class RecommendationJob(Base, TimestampMixin, TenantScopedMixin):
    """
    Tracks recommendation generation job execution.

    Jobs are created by the dispatcher based on:
    - New insights that need recommendations
    - Scheduled cadence (daily or hourly for enterprise)

    Only ONE active (queued/running) job per tenant is allowed,
    enforced by a partial unique index in the database.

    SECURITY: tenant_id from TenantScopedMixin ensures isolation.
    tenant_id is ONLY extracted from JWT, never from client input.
    """

    __tablename__ = "recommendation_jobs"

    job_id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Unique job identifier (UUID)"
    )

    # Cadence
    cadence = Column(
        Enum(RecommendationJobCadence),
        nullable=False,
        default=RecommendationJobCadence.DAILY,
        comment="Job cadence: daily (standard) or hourly (enterprise)"
    )

    # Status tracking
    status = Column(
        Enum(RecommendationJobStatus),
        nullable=False,
        default=RecommendationJobStatus.QUEUED,
        index=True,
        comment="Current job status"
    )

    # Results
    recommendations_generated = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of recommendations created"
    )

    insights_processed = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of insights analyzed"
    )

    # Timing
    started_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When job started execution"
    )

    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When job completed (success or failure)"
    )

    # Error tracking
    error_message = Column(
        Text,
        nullable=True,
        comment="Error message if job failed"
    )

    # Job metadata (insights analyzed, skip reasons, etc.)
    job_metadata = Column(
        JSONType,
        nullable=False,
        default=dict,
        comment="Additional job metadata"
    )

    def __repr__(self) -> str:
        return (
            f"<RecommendationJob("
            f"job_id={self.job_id}, "
            f"tenant_id={self.tenant_id}, "
            f"status={self.status.value if self.status else None}"
            f")>"
        )

    @property
    def is_active(self) -> bool:
        """Check if job is currently active (queued or running)."""
        return self.status in (
            RecommendationJobStatus.QUEUED,
            RecommendationJobStatus.RUNNING,
        )

    @property
    def is_terminal(self) -> bool:
        """Check if job has reached a terminal state."""
        return self.status in (
            RecommendationJobStatus.SUCCESS,
            RecommendationJobStatus.FAILED,
            RecommendationJobStatus.SKIPPED,
        )

    def mark_running(self) -> None:
        """Mark job as running."""
        self.status = RecommendationJobStatus.RUNNING
        self.started_at = datetime.now(timezone.utc)

    def mark_success(
        self,
        recommendations_generated: int,
        insights_processed: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Mark job as successfully completed."""
        self.status = RecommendationJobStatus.SUCCESS
        self.recommendations_generated = recommendations_generated
        self.insights_processed = insights_processed
        self.completed_at = datetime.now(timezone.utc)
        if metadata:
            self.job_metadata = {**(self.job_metadata or {}), **metadata}

    def mark_failed(self, error_message: str) -> None:
        """Mark job as failed."""
        self.status = RecommendationJobStatus.FAILED
        self.error_message = error_message
        self.completed_at = datetime.now(timezone.utc)

    def mark_skipped(self, reason: str) -> None:
        """Mark job as skipped (e.g., no new insights to process)."""
        self.status = RecommendationJobStatus.SKIPPED
        self.completed_at = datetime.now(timezone.utc)
        self.job_metadata = {
            **(self.job_metadata or {}),
            "skip_reason": reason,
        }
