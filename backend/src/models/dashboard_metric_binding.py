"""
Dashboard metric binding model for Story 2.3.

Tracks which dashboard uses which metric version, supporting:
- Explicit version pinning per dashboard per metric
- Governed repoint with audit trail
- Blast radius tracking (which tenants are affected)
- Tenant-level overrides (pin a specific tenant to a version)

SECURITY:
- Tenant-scoped via TenantScopedMixin for tenant-level pins
- System-level bindings (no tenant_id) for global defaults
- Only Super Admin / Analytics Admin can modify
- All mutations emit audit events
"""

from sqlalchemy import (
    Column, String, Text, DateTime, Index, func,
    UniqueConstraint,
)

from src.db_base import Base
from src.models.base import TimestampMixin, generate_uuid


class DashboardMetricBinding(Base, TimestampMixin):
    """
    Binds a dashboard to a specific metric version.

    There are two levels of bindings:
    1. Global defaults (tenant_id is NULL): Defined in consumers.yaml,
       applies to all tenants unless overridden.
    2. Tenant-level pins (tenant_id is set): Overrides the global default
       for a specific tenant. Used when a tenant needs to stay on an older
       version during migration.

    Attributes:
        id: Unique binding identifier (UUID)
        dashboard_id: Dashboard identifier (e.g., 'merchant_overview')
        metric_name: Metric name (e.g., 'roas')
        metric_version: Version string ('current', 'v1', 'v2') or concrete version
        pinned_by: User who created/modified this binding (email or user_id)
        pinned_at: When the binding was last modified
        reason: Required justification for the binding
        tenant_id: NULL for global defaults, set for tenant-level pins
    """
    __tablename__ = "dashboard_metric_bindings"

    id = Column(String(255), primary_key=True, default=generate_uuid)

    dashboard_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Dashboard identifier (e.g., 'merchant_overview')"
    )

    metric_name = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Metric name (e.g., 'roas', 'revenue')"
    )

    metric_version = Column(
        String(50),
        nullable=False,
        comment="Version string: 'current' or specific version like 'v1', 'v2'"
    )

    pinned_by = Column(
        String(255),
        nullable=True,
        comment="User who set this binding (email or user_id)"
    )

    pinned_at = Column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
        comment="When the binding was last modified"
    )

    reason = Column(
        Text,
        nullable=True,
        comment="Justification for this binding (required by governance)"
    )

    tenant_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="NULL for global default, set for tenant-level pin override"
    )

    previous_version = Column(
        String(50),
        nullable=True,
        comment="Previous metric version before this repoint (for rollback)"
    )

    __table_args__ = (
        # Each dashboard+metric+tenant combination has exactly one binding
        UniqueConstraint(
            "dashboard_id", "metric_name", "tenant_id",
            name="uq_dashboard_metric_tenant_binding"
        ),
        Index(
            "ix_binding_dashboard_metric",
            "dashboard_id", "metric_name"
        ),
        Index(
            "ix_binding_tenant_dashboard",
            "tenant_id", "dashboard_id"
        ),
    )

    def __repr__(self) -> str:
        tenant_str = f", tenant={self.tenant_id}" if self.tenant_id else ""
        return (
            f"<DashboardMetricBinding("
            f"dashboard={self.dashboard_id}, "
            f"metric={self.metric_name}, "
            f"version={self.metric_version}"
            f"{tenant_str})>"
        )
