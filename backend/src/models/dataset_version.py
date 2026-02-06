"""
Dataset version model for fail-safe dataset versioning.

Tracks the lifecycle of each canonical dataset version exposed to Superset.
Preserves last-known-good state so that sync failures never leave users
with broken dashboards.

State machine:
    PENDING → ACTIVE → SUPERSEDED
    PENDING → FAILED (sync error or compatibility failure)
    ACTIVE → ROLLED_BACK (operator-initiated revert)

SECURITY: Dataset versions are system-scoped (no tenant_id). They describe
platform-level schema, not per-tenant data.

Story 5.2.7 — Fail-Safe Dataset Versioning
"""

from enum import Enum

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    Index,
    Boolean,
)

from src.db_base import Base
from src.models.base import TimestampMixin, generate_uuid


class DatasetVersionStatus(str, Enum):
    """Lifecycle state of a dataset version."""

    PENDING = "pending"
    ACTIVE = "active"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"


class DatasetVersion(Base, TimestampMixin):
    """
    Immutable record of a dataset version.

    Each row represents one sync attempt. Only one version per dataset_name
    may be ACTIVE at any time. When a new version is activated the previous
    ACTIVE version transitions to SUPERSEDED.

    The column_snapshot stores the JSON column set at sync time so that
    compatibility checks can compare against the last-known-good state
    without querying Superset.
    """

    __tablename__ = "dataset_version"

    id = Column(
        String(255),
        primary_key=True,
        default=generate_uuid,
        comment="Primary key (UUID)",
    )
    dataset_name = Column(
        String(255),
        nullable=False,
        comment="Canonical dataset name (e.g. fact_orders_current)",
    )
    schema_name = Column(
        String(255),
        nullable=False,
        default="analytics",
        comment="Database schema containing the dataset",
    )
    version = Column(
        String(50),
        nullable=False,
        comment="Semantic version tag (e.g. v1, v2)",
    )
    status = Column(
        String(30),
        nullable=False,
        default=DatasetVersionStatus.PENDING.value,
        comment="Lifecycle status: pending, active, failed, superseded, rolled_back",
    )
    column_snapshot = Column(
        Text,
        nullable=False,
        comment="JSON array of column definitions at sync time (last-known-good)",
    )
    column_count = Column(
        Integer,
        nullable=False,
        comment="Total number of columns in this version",
    )
    exposed_column_count = Column(
        Integer,
        nullable=False,
        comment="Number of columns with superset_expose: true",
    )
    is_compatible = Column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether this version passed compatibility checks",
    )
    incompatibility_reason = Column(
        Text,
        nullable=True,
        comment="Description of why compatibility check failed (if applicable)",
    )
    sync_started_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the sync for this version began",
    )
    sync_completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the sync for this version finished (success or failure)",
    )
    activated_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When this version was promoted to ACTIVE",
    )
    deactivated_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When this version was demoted from ACTIVE",
    )
    sync_error = Column(
        Text,
        nullable=True,
        comment="Error message if sync failed",
    )
    dbt_manifest_hash = Column(
        String(64),
        nullable=True,
        comment="SHA-256 of the dbt manifest used for this version (idempotency)",
    )

    __table_args__ = (
        Index("ix_dataset_version_name_status", "dataset_name", "status"),
        Index("ix_dataset_version_name_version", "dataset_name", "version", unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"<DatasetVersion("
            f"dataset_name={self.dataset_name}, "
            f"version={self.version}, "
            f"status={self.status}"
            f")>"
        )
