"""
Usage tracking models for API call metering.

UsageRecord: High-volume table for individual API calls
UsageAggregate: Rolled-up usage for efficient querying
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, DateTime, Enum,
    ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship

from src.models.base import Base, TimestampMixin, TenantScopedMixin, generate_uuid


class UsageRecord(Base, TenantScopedMixin):
    """
    Individual API call tracking.

    HIGH VOLUME TABLE - written on every billable API request.
    Aggregated hourly into UsageAggregate, then deleted after retention period.

    NOTE: Does not include TimestampMixin to reduce storage (uses recorded_at).
    """

    __tablename__ = "usage_records"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )

    # Foreign key to store
    store_id = Column(
        String(36),
        ForeignKey("shopify_stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Request details
    endpoint = Column(
        String(255),
        nullable=False,
        comment="API endpoint path"
    )
    method = Column(
        String(10),
        nullable=False,
        comment="HTTP method (GET, POST, etc.)"
    )
    user_id = Column(
        String(255),
        nullable=True,
        comment="User who made the request (from JWT)"
    )

    # Metering
    usage_type = Column(
        String(50),
        default="api_call",
        comment="Type of usage (api_call, ai_tokens, storage_mb)"
    )
    quantity = Column(
        Integer,
        default=1,
        comment="Units consumed (usually 1 for API calls)"
    )

    # Timing
    recorded_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        comment="When the usage occurred"
    )

    # Response info (optional, for debugging)
    response_status = Column(
        Integer,
        nullable=True,
        comment="HTTP response status code"
    )
    response_time_ms = Column(
        Integer,
        nullable=True,
        comment="Response time in milliseconds"
    )

    # Relationship
    store = relationship("ShopifyStore", back_populates="usage_records")

    # Indexes for efficient querying and cleanup
    # Note: recorded_at index is created via index=True on the column
    __table_args__ = (
        Index("ix_usage_records_tenant_store_time", "tenant_id", "store_id", "recorded_at"),
        Index("ix_usage_records_store_time", "store_id", "recorded_at"),
    )

    def __repr__(self) -> str:
        return f"<UsageRecord(store_id={self.store_id}, endpoint={self.endpoint}, recorded_at={self.recorded_at})>"


class UsageAggregate(Base, TimestampMixin, TenantScopedMixin):
    """
    Hourly/daily aggregated usage for efficient querying.

    Populated by background job from UsageRecord.
    Used for usage reports and limit enforcement.
    """

    __tablename__ = "usage_aggregates"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )

    # Foreign key to store
    store_id = Column(
        String(36),
        ForeignKey("shopify_stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Aggregation period
    period_start = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Start of aggregation period"
    )
    period_end = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="End of aggregation period"
    )
    period_type = Column(
        Enum("hourly", "daily", "monthly", name="period_type"),
        default="hourly",
        comment="Aggregation granularity"
    )

    # Usage type
    usage_type = Column(
        String(50),
        default="api_call",
        comment="Type of usage being aggregated"
    )

    # Aggregated metrics
    total_quantity = Column(
        Integer,
        default=0,
        comment="Total units consumed in period"
    )
    unique_endpoints = Column(
        Integer,
        default=0,
        comment="Number of unique endpoints called"
    )
    unique_users = Column(
        Integer,
        default=0,
        comment="Number of unique users"
    )
    success_count = Column(
        Integer,
        default=0,
        comment="Number of successful requests (2xx)"
    )
    error_count = Column(
        Integer,
        default=0,
        comment="Number of error requests (4xx, 5xx)"
    )
    avg_response_time_ms = Column(
        Integer,
        nullable=True,
        comment="Average response time in milliseconds"
    )

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint(
            "store_id", "period_start", "period_type", "usage_type",
            name="uq_usage_aggregate"
        ),
        Index("ix_usage_agg_store_period", "store_id", "period_start"),
        Index("ix_usage_agg_tenant_period", "tenant_id", "period_start"),
    )

    def __repr__(self) -> str:
        return f"<UsageAggregate(store_id={self.store_id}, period={self.period_type}, total={self.total_quantity})>"


class UsageType:
    """Standard usage types for metering."""
    API_CALL = "api_call"
    AI_TOKENS = "ai_tokens"
    STORAGE_MB = "storage_mb"
    EXPORT_COUNT = "export_count"
    REPORT_GENERATION = "report_generation"
