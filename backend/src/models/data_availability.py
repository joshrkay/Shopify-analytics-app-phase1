"""
Data availability state model for per-tenant, per-source freshness tracking.

Implements a computed state machine with three states:
- FRESH: Data within SLA threshold
- STALE: SLA exceeded but within grace window (error threshold)
- UNAVAILABLE: Beyond grace window or ingestion failed

State is derived from sync timestamps and SLA thresholds defined in
config/data_freshness_sla.yml — never set manually.

SECURITY: All rows are tenant-scoped via tenant_id from JWT.
"""

import uuid
from enum import Enum

from sqlalchemy import Column, String, Integer, DateTime, Text, Index

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin, generate_uuid


class AvailabilityState(str, Enum):
    """Data availability states."""
    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class AvailabilityReason(str, Enum):
    """Reason codes for availability state transitions."""
    SYNC_OK = "sync_ok"                             # Sync within SLA
    SLA_EXCEEDED = "sla_exceeded"                    # Warn threshold breached
    GRACE_WINDOW_EXCEEDED = "grace_window_exceeded"  # Error threshold breached
    SYNC_FAILED = "sync_failed"                      # Last sync failed
    NEVER_SYNCED = "never_synced"                    # No sync recorded


class DataAvailability(Base, TenantScopedMixin, TimestampMixin):
    """
    Persists the latest computed availability state per tenant + source.

    One row per (tenant_id, source_type) pair. Updated by
    DataAvailabilityService.evaluate(); never written directly.

    SECURITY: tenant_id is from JWT only.
    """
    __tablename__ = "data_availability"

    id = Column(
        String(255),
        primary_key=True,
        default=generate_uuid,
        comment="Primary key (UUID)"
    )
    source_type = Column(
        String(100),
        nullable=False,
        comment="SLA config source key (e.g. shopify_orders, facebook_ads)"
    )
    state = Column(
        String(20),
        nullable=False,
        comment="Current availability state: fresh, stale, unavailable"
    )
    reason = Column(
        String(50),
        nullable=False,
        comment="Reason code for current state"
    )

    # Thresholds captured at evaluation time (for auditability)
    warn_threshold_minutes = Column(
        Integer,
        nullable=False,
        comment="SLA warn threshold (minutes) used for this evaluation"
    )
    error_threshold_minutes = Column(
        Integer,
        nullable=False,
        comment="SLA error threshold (minutes) used for this evaluation"
    )

    # Sync metadata
    last_sync_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of most recent successful sync"
    )
    last_sync_status = Column(
        String(50),
        nullable=True,
        comment="Status of most recent sync attempt"
    )
    minutes_since_sync = Column(
        Integer,
        nullable=True,
        comment="Minutes elapsed since last successful sync"
    )

    # State transition tracking
    state_changed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Timestamp when state last transitioned"
    )
    previous_state = Column(
        String(20),
        nullable=True,
        comment="State before the most recent transition"
    )

    # Evaluation metadata
    evaluated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Timestamp of the evaluation that produced this state"
    )
    billing_tier = Column(
        String(50),
        nullable=False,
        default="free",
        comment="Billing tier used for SLA lookup"
    )

    __table_args__ = (
        Index(
            "ix_data_availability_tenant_source",
            "tenant_id", "source_type",
            unique=True,
        ),
        Index("ix_data_availability_state", "state"),
        Index("ix_data_availability_tenant_state", "tenant_id", "state"),
    )

    def __repr__(self) -> str:
        return (
            f"<DataAvailability("
            f"tenant_id={self.tenant_id}, "
            f"source_type={self.source_type}, "
            f"state={self.state}"
            f")>"
        )
