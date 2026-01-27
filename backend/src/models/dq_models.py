"""
Data Quality models for sync health monitoring.

Provides SQLAlchemy models for:
- DQCheck: Check definitions and thresholds
- DQResult: Per-run check execution results
- DQIncident: Severe failures and dashboard blocks
- SyncRun: Sync execution tracking with metrics
- BackfillJob: Merchant-triggered backfill requests

SECURITY: All tables are tenant-scoped via tenant_id from JWT.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, List, Any

from sqlalchemy import (
    Column, String, Integer, Boolean, Text, DateTime,
    ForeignKey, Numeric, BigInteger, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin, generate_uuid


class DQCheckType(str, Enum):
    """Types of data quality checks."""
    FRESHNESS = "freshness"
    ROW_COUNT_DROP = "row_count_drop"
    ZERO_SPEND = "zero_spend"
    ZERO_ORDERS = "zero_orders"
    MISSING_DAYS = "missing_days"
    NEGATIVE_VALUES = "negative_values"
    DUPLICATE_PRIMARY_KEY = "duplicate_primary_key"


class DQSeverity(str, Enum):
    """Data quality issue severity levels."""
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class DQResultStatus(str, Enum):
    """Result status for a DQ check execution."""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class DQIncidentStatus(str, Enum):
    """Status of a DQ incident."""
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    AUTO_RESOLVED = "auto_resolved"


class SyncRunStatus(str, Enum):
    """Status of a sync run."""
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConnectorSourceType(str, Enum):
    """Connector source types with freshness SLAs."""
    # 2-hour SLA
    SHOPIFY_ORDERS = "shopify_orders"
    SHOPIFY_REFUNDS = "shopify_refunds"
    RECHARGE = "recharge"

    # 24-hour SLA
    META_ADS = "meta_ads"
    GOOGLE_ADS = "google_ads"
    TIKTOK_ADS = "tiktok_ads"
    PINTEREST_ADS = "pinterest_ads"
    SNAP_ADS = "snap_ads"
    AMAZON_ADS = "amazon_ads"
    KLAVIYO = "klaviyo"
    POSTSCRIPT = "postscript"
    ATTENTIVE = "attentive"
    GA4 = "ga4"


class BackfillJobStatus(str, Enum):
    """Status of a backfill job."""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Freshness thresholds per source type (in minutes)
FRESHNESS_THRESHOLDS = {
    # 2-hour SLA sources
    ConnectorSourceType.SHOPIFY_ORDERS: {"warning": 120, "high": 240, "critical": 480},
    ConnectorSourceType.SHOPIFY_REFUNDS: {"warning": 120, "high": 240, "critical": 480},
    ConnectorSourceType.RECHARGE: {"warning": 120, "high": 240, "critical": 480},

    # 24-hour SLA sources
    ConnectorSourceType.META_ADS: {"warning": 1440, "high": 2880, "critical": 5760},
    ConnectorSourceType.GOOGLE_ADS: {"warning": 1440, "high": 2880, "critical": 5760},
    ConnectorSourceType.TIKTOK_ADS: {"warning": 1440, "high": 2880, "critical": 5760},
    ConnectorSourceType.PINTEREST_ADS: {"warning": 1440, "high": 2880, "critical": 5760},
    ConnectorSourceType.SNAP_ADS: {"warning": 1440, "high": 2880, "critical": 5760},
    ConnectorSourceType.AMAZON_ADS: {"warning": 1440, "high": 2880, "critical": 5760},
    ConnectorSourceType.KLAVIYO: {"warning": 1440, "high": 2880, "critical": 5760},
    ConnectorSourceType.POSTSCRIPT: {"warning": 1440, "high": 2880, "critical": 5760},
    ConnectorSourceType.ATTENTIVE: {"warning": 1440, "high": 2880, "critical": 5760},
    ConnectorSourceType.GA4: {"warning": 1440, "high": 2880, "critical": 5760},
}


def get_freshness_threshold(source_type: ConnectorSourceType, severity: DQSeverity) -> int:
    """Get freshness threshold in minutes for a source type and severity."""
    thresholds = FRESHNESS_THRESHOLDS.get(source_type, {"warning": 1440, "high": 2880, "critical": 5760})
    return thresholds.get(severity.value, 1440)


def is_critical_source(source_type: ConnectorSourceType) -> bool:
    """Check if a source type is critical (Shopify, Recharge)."""
    return source_type in [
        ConnectorSourceType.SHOPIFY_ORDERS,
        ConnectorSourceType.SHOPIFY_REFUNDS,
        ConnectorSourceType.RECHARGE,
    ]


class DQCheck(Base, TimestampMixin):
    """
    Data quality check definition.

    Stores check configurations and thresholds.
    """
    __tablename__ = "dq_checks"

    id = Column(String(255), primary_key=True, default=generate_uuid)
    check_name = Column(String(255), nullable=False)
    check_type = Column(String(50), nullable=False)
    source_type = Column(String(50), nullable=True)

    # Thresholds (in minutes for freshness)
    warning_threshold = Column(Integer, nullable=True)
    high_threshold = Column(Integer, nullable=True)
    critical_threshold = Column(Integer, nullable=True)

    # For anomaly checks
    anomaly_threshold_percent = Column(Numeric(5, 2), nullable=True)

    # Behavior
    is_enabled = Column(Boolean, nullable=False, default=True)
    is_blocking = Column(Boolean, nullable=False, default=False)

    # Messages
    description = Column(Text, nullable=True)
    merchant_message = Column(Text, nullable=True)
    support_message = Column(Text, nullable=True)
    recommended_actions = Column(JSONB, nullable=False, default=list)

    # Relationships
    results = relationship("DQResult", back_populates="check")
    incidents = relationship("DQIncident", back_populates="check")


class DQResult(Base, TenantScopedMixin):
    """
    Data quality check execution result.

    Stores per-run results for each check.
    SECURITY: tenant_id is from JWT only.
    """
    __tablename__ = "dq_results"

    id = Column(String(255), primary_key=True, default=generate_uuid)
    check_id = Column(String(255), ForeignKey("dq_checks.id"), nullable=False)
    connector_id = Column(String(255), nullable=False)
    run_id = Column(String(255), nullable=False)
    correlation_id = Column(String(255), nullable=True)

    # Result
    status = Column(String(20), nullable=False)
    severity = Column(String(20), nullable=True)

    # Observed values
    observed_value = Column(Numeric(20, 4), nullable=True)
    expected_value = Column(Numeric(20, 4), nullable=True)
    threshold_value = Column(Numeric(20, 4), nullable=True)
    minutes_since_sync = Column(Integer, nullable=True)

    # Messages
    message = Column(Text, nullable=True)
    merchant_message = Column(Text, nullable=True)
    support_details = Column(Text, nullable=True)

    # Context
    context_metadata = Column(JSONB, nullable=False, default=dict)

    # Timestamps
    executed_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    check = relationship("DQCheck", back_populates="results")

    __table_args__ = (
        Index("ix_dq_results_tenant_connector", "tenant_id", "connector_id"),
        Index("ix_dq_results_run_id", "run_id"),
    )


class DQIncident(Base, TenantScopedMixin, TimestampMixin):
    """
    Data quality incident for severe failures.

    Tracks critical issues that may block dashboards.
    SECURITY: tenant_id is from JWT only.
    """
    __tablename__ = "dq_incidents"

    id = Column(String(255), primary_key=True, default=generate_uuid)
    connector_id = Column(String(255), nullable=False)
    check_id = Column(String(255), ForeignKey("dq_checks.id"), nullable=False)
    result_id = Column(String(255), ForeignKey("dq_results.id"), nullable=True)
    run_id = Column(String(255), nullable=True)
    correlation_id = Column(String(255), nullable=True)

    # Incident details
    severity = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default=DQIncidentStatus.OPEN.value)
    is_blocking = Column(Boolean, nullable=False, default=False)

    # Description
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)

    # Messages
    merchant_message = Column(Text, nullable=True)
    support_details = Column(Text, nullable=True)
    recommended_actions = Column(JSONB, nullable=False, default=list)

    # Resolution tracking
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(String(255), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String(255), nullable=True)
    resolution_notes = Column(Text, nullable=True)

    # When opened
    opened_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # Relationships
    check = relationship("DQCheck", back_populates="incidents")

    __table_args__ = (
        Index("ix_dq_incidents_tenant_connector", "tenant_id", "connector_id"),
        Index("ix_dq_incidents_status", "status"),
    )


class SyncRun(Base, TenantScopedMixin, TimestampMixin):
    """
    Sync run tracking with metrics.

    SECURITY: tenant_id is from JWT only.
    """
    __tablename__ = "sync_runs"

    run_id = Column(String(255), primary_key=True, default=generate_uuid)
    connector_id = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default=SyncRunStatus.RUNNING.value)
    source_type = Column(String(50), nullable=True)

    # Timestamps
    started_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Metrics
    rows_synced = Column(Integer, nullable=True)
    rows_updated = Column(Integer, nullable=True)
    rows_deleted = Column(Integer, nullable=True)
    bytes_synced = Column(BigInteger, nullable=True)
    duration_seconds = Column(Numeric(10, 2), nullable=True)

    # Error tracking
    error_message = Column(Text, nullable=True)
    error_code = Column(String(50), nullable=True)

    # Metadata
    run_metadata = Column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_sync_runs_tenant_connector", "tenant_id", "connector_id"),
        Index("ix_sync_runs_status", "status"),
    )


class BackfillJob(Base, TenantScopedMixin, TimestampMixin):
    """
    Merchant-triggered backfill job.

    SECURITY: tenant_id is from JWT only.
    Max 90 days for merchants.
    """
    __tablename__ = "backfill_jobs"

    id = Column(String(255), primary_key=True, default=generate_uuid)
    connector_id = Column(String(255), nullable=False)

    # Date range
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)

    # Status
    status = Column(String(50), nullable=False, default=BackfillJobStatus.QUEUED.value)

    # Requesting user
    requested_by = Column(String(255), nullable=False)

    # Execution tracking
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Results
    rows_backfilled = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_backfill_jobs_tenant_connector", "tenant_id", "connector_id"),
        Index("ix_backfill_jobs_status", "status"),
    )


# Maximum backfill days for merchants
MAX_MERCHANT_BACKFILL_DAYS = 90
