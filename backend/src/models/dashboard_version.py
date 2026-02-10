"""
Dashboard Version model - Immutable snapshots of dashboard state.

Each version captures the full dashboard configuration and all report
configs at a point in time. Used for version history and restore.

Version cap: 50 per dashboard (configurable via MAX_DASHBOARD_VERSIONS env var).

Phase: Custom Reports & Dashboard Builder
"""

import os
import uuid

from sqlalchemy import (
    Column, String, Integer, Text,
    ForeignKey, Index, UniqueConstraint, JSON,
)
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin


# Configurable version cap per dashboard
MAX_DASHBOARD_VERSIONS = int(os.getenv("MAX_DASHBOARD_VERSIONS", "50"))


class DashboardVersion(Base, TimestampMixin):
    """
    Immutable snapshot of a CustomDashboard at a point in time.

    Created automatically on every dashboard mutation (report add/update/remove,
    layout change, metadata update, publish, restore).

    snapshot_json contains the full dashboard + reports state:
    {
        "dashboard": { "name": ..., "description": ..., "layout_json": ..., "filters_json": ... },
        "reports": [
            { "id": ..., "name": ..., "chart_type": ..., "config_json": ..., "position_json": ... },
            ...
        ]
    }

    NOT tenant-scoped because it's always accessed through its parent dashboard
    which IS tenant-scoped. The dashboard_id FK enforces the relationship.
    """

    __tablename__ = "dashboard_versions"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)",
    )

    dashboard_id = Column(
        String(36),
        ForeignKey("custom_dashboards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent dashboard. CASCADE delete when dashboard is removed.",
    )

    version_number = Column(
        Integer,
        nullable=False,
        comment="Auto-incrementing version number within the dashboard",
    )

    snapshot_json = Column(
        JSON,
        nullable=False,
        comment="Full dashboard + reports state snapshot",
    )

    change_summary = Column(
        String(500),
        nullable=False,
        comment="Human-readable description of what changed",
    )

    created_by = Column(
        String(255),
        nullable=False,
        comment="User ID who made the change (from JWT)",
    )

    # Relationships
    dashboard = relationship(
        "CustomDashboard",
        back_populates="versions",
    )

    # Indexes and constraints
    __table_args__ = (
        # Each version number is unique per dashboard
        UniqueConstraint(
            "dashboard_id", "version_number",
            name="uk_dashboard_versions_dashboard_version",
        ),
        # Query versions for a dashboard in order
        Index(
            "idx_dashboard_versions_dashboard_number",
            "dashboard_id", "version_number",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<DashboardVersion(id={self.id}, dashboard_id={self.dashboard_id}, "
            f"version_number={self.version_number})>"
        )
