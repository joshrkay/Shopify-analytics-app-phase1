"""
Backfill execution tracking models.

Tracks dbt backfill operations for audit, monitoring, and history.
All backfills are tenant-scoped for multi-tenant isolation.

Story 4.8 - Backfills & Reprocessing
"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Integer, DateTime, Text, Float, Boolean, Index
)

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin


class BackfillStatus(str, PyEnum):
    """Backfill execution status values."""
    PENDING = "pending"        # Backfill queued, not yet started
    RUNNING = "running"        # Backfill in progress
    COMPLETED = "completed"    # Backfill completed successfully
    FAILED = "failed"          # Backfill failed with error
    CANCELLED = "cancelled"    # Backfill cancelled by user or system


class BackfillExecution(Base, TimestampMixin, TenantScopedMixin):
    """
    Tracks dbt backfill execution history.

    Records each backfill operation for audit, monitoring, and debugging.
    Tenant-scoped to ensure isolation in multi-tenant environment.

    SECURITY: tenant_id is ONLY extracted from JWT (org_id).
    NEVER accept tenant_id from client input.
    """

    __tablename__ = "backfill_executions"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID) - matches backfill_id from service"
    )

    model_selector = Column(
        String(500),
        nullable=False,
        comment="dbt model selector (e.g., 'fact_orders', 'facts', 'fact_orders+')"
    )

    start_date = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Backfill start date"
    )

    end_date = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Backfill end date"
    )

    status = Column(
        Enum(BackfillStatus),
        nullable=False,
        default=BackfillStatus.PENDING,
        index=True,
        comment="Backfill status: pending, running, completed, failed, cancelled"
    )

    is_successful = Column(
        Boolean,
        nullable=True,
        comment="Whether backfill completed successfully"
    )

    rows_affected = Column(
        Integer,
        nullable=True,
        comment="Number of rows affected by backfill (if available)"
    )

    duration_seconds = Column(
        Float,
        nullable=True,
        comment="Execution duration in seconds"
    )

    error_message = Column(
        Text,
        nullable=True,
        comment="Error message if backfill failed (truncated to 1000 chars)"
    )

    dbt_output = Column(
        Text,
        nullable=True,
        comment="dbt command output (truncated to 5000 chars)"
    )

    started_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When backfill execution started"
    )

    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When backfill execution completed"
    )

    triggered_by = Column(
        String(255),
        nullable=True,
        comment="User or system that triggered the backfill"
    )

    # Indexes for common queries
    __table_args__ = (
        Index(
            "idx_backfill_executions_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "idx_backfill_executions_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<BackfillExecution("
            f"id={self.id}, "
            f"tenant_id={self.tenant_id}, "
            f"model_selector={self.model_selector}, "
            f"status={self.status}"
            f")>"
        )
