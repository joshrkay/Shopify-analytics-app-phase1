"""
Dataset metrics model for observability.

Tracks health metrics for each canonical dataset (Story 5.2.8): last_sync_time,
schema_version, row_count, cache_hit_rate, sync_status.

This is a system-level table (no tenant_id) because datasets are shared
across all tenants (data is isolated via RLS, not separate datasets).

Story 5.2.8 — Dataset Observability & Metrics
"""

from enum import Enum

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    Index,
)

from src.db_base import Base
from src.models.base import TimestampMixin, generate_uuid


class DatasetSyncStatus(str, Enum):
    """Status of the most recent dataset sync attempt."""

    OK = "ok"
    FAILED = "failed"
    BLOCKED = "blocked"
    PENDING = "pending"
    STALE = "stale"


class DatasetMetrics(Base, TimestampMixin):
    """
    Current health metrics for a canonical Superset dataset.

    One row per dataset_name. Updated after every sync attempt and
    periodically by the observability service for cache/query metrics.

    This is NOT tenant-scoped — datasets are platform-level resources.
    """

    __tablename__ = "dataset_metrics"

    id = Column(
        String(255),
        primary_key=True,
        default=generate_uuid,
        comment="Primary key (UUID)",
    )
    dataset_name = Column(
        String(255),
        nullable=False,
        unique=True,
        comment="Canonical dataset name (e.g. fact_orders_current)",
    )
    schema_name = Column(
        String(255),
        nullable=False,
        default="analytics",
        comment="Database schema",
    )

    # Sync metrics
    last_sync_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last successful sync",
    )
    last_sync_attempted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last sync attempt (success or failure)",
    )
    sync_status = Column(
        String(20),
        nullable=False,
        default=DatasetSyncStatus.PENDING.value,
        comment="Current sync status: ok, failed, blocked, pending, stale",
    )
    sync_error = Column(
        Text,
        nullable=True,
        comment="Error from last failed sync attempt",
    )
    sync_duration_seconds = Column(
        Float,
        nullable=True,
        comment="Duration of last sync in seconds",
    )

    # Schema metrics
    schema_version = Column(
        String(50),
        nullable=True,
        comment="Current active schema version (e.g. v1)",
    )
    column_count = Column(
        Integer,
        nullable=True,
        comment="Total columns in current version",
    )
    exposed_column_count = Column(
        Integer,
        nullable=True,
        comment="Columns exposed to Superset (superset_expose: true)",
    )

    # Data metrics
    row_count = Column(
        Integer,
        nullable=True,
        comment="Approximate row count from last evaluation",
    )
    row_count_evaluated_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When row_count was last evaluated",
    )

    # Performance metrics (from pg_stat_statements)
    query_count_24h = Column(
        Integer,
        nullable=True,
        comment="Number of queries in last 24 hours",
    )
    avg_query_latency_ms = Column(
        Float,
        nullable=True,
        comment="Average query latency in ms (last 24h)",
    )
    p95_query_latency_ms = Column(
        Float,
        nullable=True,
        comment="95th percentile query latency in ms (last 24h)",
    )

    # Cache metrics
    cache_hit_rate = Column(
        Float,
        nullable=True,
        comment="Cache hit rate (0.0 to 1.0) over last 24h",
    )
    cache_entries = Column(
        Integer,
        nullable=True,
        comment="Number of active cache entries for this dataset",
    )

    __table_args__ = (
        Index("ix_dataset_metrics_status", "sync_status"),
        Index("ix_dataset_metrics_last_sync", "last_sync_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<DatasetMetrics("
            f"dataset_name={self.dataset_name}, "
            f"sync_status={self.sync_status}, "
            f"schema_version={self.schema_version}"
            f")>"
        )
