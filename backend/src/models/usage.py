"""
UsageRecord and UsageAggregate models - Usage tracking and aggregation.

UsageRecord: Individual API calls (high volume, append-only)
UsageAggregate: Aggregated usage counters per tenant per feature
"""

import uuid
import enum
from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, UniqueConstraint, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB

from src.repositories.base_repo import Base
from src.models.base import TimestampMixin, TenantScopedMixin


class UsageEventType(str, enum.Enum):
    """Usage event type enumeration."""
    INCREMENT = "increment"
    SET = "set"
    RESET = "reset"


class PeriodType(str, enum.Enum):
    """Billing period type enumeration."""
    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"


class MeterType(str, enum.Enum):
    """Usage meter type enumeration."""
    COUNTER = "counter"  # Increments
    GAUGE = "gauge"  # Current value
    CUMULATIVE = "cumulative"  # Never resets


class UsageRecord(Base, TenantScopedMixin):
    """
    Individual API call record (high volume, append-only).
    
    SECURITY: This is append-only. No UPDATE or DELETE operations allowed.
    Used for audit trail and reconciliation.
    """
    
    __tablename__ = "usage_events"
    
    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)"
    )
    
    store_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Foreign key to shopify_stores.id (optional)"
    )
    
    endpoint = Column(
        String(255),
        nullable=True,
        index=True,
        comment="API endpoint that was called"
    )
    
    method = Column(
        String(10),
        nullable=True,
        comment="HTTP method (GET, POST, etc.)"
    )
    
    feature_key = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Feature identifier (e.g., 'ai_insights')"
    )
    
    meter_id = Column(
        String(255),
        ForeignKey("usage_meters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Optional foreign key to usage_meters.id"
    )
    
    event_type = Column(
        String(50),
        nullable=False,
        comment="Event type: increment, set, reset"
    )
    
    value = Column(
        Numeric(20, 2),
        nullable=False,
        comment="Event value"
    )
    
    previous_value = Column(
        Numeric(20, 2),
        nullable=True,
        comment="Value before this event"
    )
    
    period_type = Column(
        String(50),
        nullable=False,
        comment="Billing period type: monthly, yearly, lifetime"
    )
    
    period_start = Column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Start of billing period"
    )
    
    extra_metadata = Column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Additional event context (user_id, request_id, etc.)"
    )
    
    recorded_at = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="When the API call was recorded"
    )
    
    # Note: No updated_at - this is append-only
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Timestamp when record was created (append-only)"
    )
    
    # Indexes
    __table_args__ = (
        Index(
            "idx_usage_events_tenant_feature_created",
            "tenant_id",
            "feature_key",
            "created_at",
            postgresql_ops={"created_at": "DESC"}
        ),
        Index(
            "idx_usage_events_period",
            "tenant_id",
            "period_type",
            "period_start",
            postgresql_where=text("period_start IS NOT NULL")
        ),
    )
    
    def __repr__(self) -> str:
        return f"<UsageRecord(id={self.id}, tenant_id={self.tenant_id}, feature_key={self.feature_key}, value={self.value})>"


class UsageAggregate(Base, TimestampMixin, TenantScopedMixin):
    """
    Aggregated usage counter per tenant per feature.
    
    Updated from UsageRecord events.
    Used for fast entitlement checks.
    """
    
    __tablename__ = "usage_meters"
    
    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)"
    )
    
    feature_key = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Feature identifier (e.g., 'ai_insights', 'openrouter_tokens')"
    )
    
    meter_type = Column(
        String(50),
        nullable=False,
        comment="Meter type: counter (increments), gauge (current value), cumulative (never resets)"
    )
    
    period_type = Column(
        String(50),
        nullable=False,
        comment="Period type: monthly, yearly, lifetime"
    )
    
    current_value = Column(
        Numeric(20, 2),
        nullable=False,
        default=0,
        comment="Current usage value"
    )
    
    limit_value = Column(
        Numeric(20, 2),
        nullable=True,
        comment="Usage limit (NULL means unlimited)"
    )
    
    reset_at = Column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="When meter resets (for monthly/yearly)"
    )
    
    extra_metadata = Column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Additional meter configuration"
    )
    
    # Constraints
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "feature_key",
            "period_type",
            name="uk_usage_meters_tenant_feature_period"
        ),
        Index(
            "idx_usage_meters_tenant_feature",
            "tenant_id",
            "feature_key"
        ),
        Index(
            "idx_usage_meters_reset_at",
            "reset_at",
            postgresql_where=text("reset_at IS NOT NULL")
        ),
    )
    
    def __repr__(self) -> str:
        return f"<UsageAggregate(id={self.id}, tenant_id={self.tenant_id}, feature_key={self.feature_key}, current_value={self.current_value})>"
