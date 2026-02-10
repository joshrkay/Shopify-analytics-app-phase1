"""
Custom Report model - Individual charts/widgets within a custom dashboard.

Each report represents a single visualization (chart, KPI, table) placed
on a custom dashboard grid. Reports store their chart configuration,
dataset reference, and grid position.

Phase: Custom Reports & Dashboard Builder
"""

import uuid
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Integer, Text, ForeignKey,
    Index, UniqueConstraint, JSON,
)
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin


class ChartType(str, PyEnum):
    """Supported chart visualization types."""
    LINE = "line"
    BAR = "bar"
    AREA = "area"
    PIE = "pie"
    KPI = "kpi"
    TABLE = "table"


# Minimum grid dimensions per chart type (w, h in grid units)
CHART_MIN_DIMENSIONS = {
    ChartType.LINE: (4, 3),
    ChartType.BAR: (4, 3),
    ChartType.AREA: (4, 3),
    ChartType.PIE: (3, 3),
    ChartType.KPI: (3, 2),
    ChartType.TABLE: (6, 4),
}


class CustomReport(Base, TimestampMixin, TenantScopedMixin):
    """
    Single chart/widget within a CustomDashboard.

    Stores the full chart configuration including metrics, dimensions,
    time range, filters, and display settings. References a Superset
    dataset by name for data queries.

    SECURITY: tenant_id from JWT only. All queries must be tenant-scoped.
    """

    __tablename__ = "custom_reports"

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

    name = Column(
        String(255),
        nullable=False,
        comment="Chart/widget title displayed in the header",
    )

    description = Column(
        Text,
        nullable=True,
        comment="Optional chart description or subtitle",
    )

    chart_type = Column(
        String(50),
        nullable=False,
        comment="Visualization type: line, bar, area, pie, kpi, table",
    )

    dataset_name = Column(
        String(255),
        nullable=False,
        comment="Superset dataset name to query (e.g., 'fact_orders_current')",
    )

    config_json = Column(
        JSON,
        nullable=False,
        comment="Full chart config: metrics, dimensions, time_range, time_grain, filters, display",
    )

    position_json = Column(
        JSON,
        nullable=False,
        comment="Grid position: {x, y, w, h} in 12-column grid units",
    )

    cache_timeout = Column(
        Integer,
        nullable=False,
        default=86400,
        comment="Chart data cache TTL in seconds (default 24h)",
    )

    sort_order = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Display ordering within the dashboard",
    )

    created_by = Column(
        String(255),
        nullable=False,
        comment="User ID who created this report (from JWT)",
    )

    # Relationships
    dashboard = relationship(
        "CustomDashboard",
        back_populates="reports",
    )

    # Indexes and constraints
    __table_args__ = (
        # Prevent duplicate report names within a dashboard
        UniqueConstraint(
            "dashboard_id", "name",
            name="uk_custom_reports_dashboard_name",
        ),
        # Common query: list reports for a dashboard ordered by sort_order
        Index(
            "idx_custom_reports_dashboard_sort",
            "dashboard_id", "sort_order",
        ),
        # Tenant scoping index
        Index(
            "idx_custom_reports_tenant",
            "tenant_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CustomReport(id={self.id}, name={self.name!r}, "
            f"chart_type={self.chart_type}, dashboard_id={self.dashboard_id})>"
        )
