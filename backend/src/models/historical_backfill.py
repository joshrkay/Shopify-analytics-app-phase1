"""
Historical backfill request model.

Tracks admin-initiated historical data backfill requests.
Separate from BackfillExecution (Story 4.8, dbt-focused) and
BackfillJob (DQ, merchant-triggered).

SECURITY: Only super admins may create these records.
tenant_id is the TARGET tenant provided by admin, not from JWT.

Story 3.4 - Backfill Request API
"""

import uuid
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Date, DateTime, Text, Index, Enum
)

from src.db_base import Base
from src.models.base import TimestampMixin


class HistoricalBackfillStatus(str, PyEnum):
    """Status of a historical backfill request."""
    PENDING = "pending"
    APPROVED = "approved"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


ACTIVE_BACKFILL_STATUSES = [
    HistoricalBackfillStatus.PENDING,
    HistoricalBackfillStatus.APPROVED,
    HistoricalBackfillStatus.RUNNING,
]


class HistoricalBackfillRequest(Base, TimestampMixin):
    """
    Tracks admin-initiated historical backfill requests.

    NOT using TenantScopedMixin because tenant_id is the TARGET tenant
    from the request body, not the caller's tenant from JWT.
    This is a deliberate exception for cross-tenant admin operations.
    """

    __tablename__ = "historical_backfill_requests"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)"
    )

    tenant_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Target tenant ID for the backfill"
    )

    source_system = Column(
        String(50),
        nullable=False,
        comment="Source system: shopify, facebook, google, tiktok, etc."
    )

    start_date = Column(
        Date,
        nullable=False,
        comment="Backfill start date (inclusive)"
    )

    end_date = Column(
        Date,
        nullable=False,
        comment="Backfill end date (inclusive)"
    )

    status = Column(
        Enum(HistoricalBackfillStatus),
        nullable=False,
        default=HistoricalBackfillStatus.PENDING,
        index=True,
        comment="Request status"
    )

    reason = Column(
        Text,
        nullable=False,
        comment="Human-readable reason for the backfill"
    )

    requested_by = Column(
        String(255),
        nullable=False,
        comment="Clerk user ID of the super admin who requested"
    )

    idempotency_key = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="Derived key: hash(tenant_id, source_system, start_date, end_date)"
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

    error_message = Column(
        Text,
        nullable=True,
        comment="Error message if failed"
    )

    __table_args__ = (
        Index(
            "idx_hist_backfill_tenant_source_status",
            "tenant_id",
            "source_system",
            "status",
        ),
        Index(
            "idx_hist_backfill_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<HistoricalBackfillRequest("
            f"id={self.id}, "
            f"tenant_id={self.tenant_id}, "
            f"source_system={self.source_system}, "
            f"status={self.status}"
            f")>"
        )
