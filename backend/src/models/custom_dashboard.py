"""
Custom Dashboard model - User-created dashboards.

Tenant-scoped model for storing custom dashboard configurations.
Dashboards contain zero or more CustomReports and support
versioning, sharing, and template-based creation.

Phase: Custom Reports & Dashboard Builder
"""

import uuid
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Integer, Boolean, Text, DateTime,
    ForeignKey, Index, UniqueConstraint, JSON,
)
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin


class DashboardStatus(str, PyEnum):
    """Status values for custom dashboards."""
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class CustomDashboard(Base, TimestampMixin, TenantScopedMixin):
    """
    User-created custom dashboard.

    Contains layout configuration and references to child CustomReport widgets.
    Supports draft/published/archived lifecycle and optional template origin.

    SECURITY: tenant_id from JWT only. All queries must be tenant-scoped.
    """

    __tablename__ = "custom_dashboards"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)",
    )

    name = Column(
        String(255),
        nullable=False,
        comment="User-facing dashboard name",
    )

    description = Column(
        Text,
        nullable=True,
        comment="Optional dashboard description (max ~2000 chars enforced at API layer)",
    )

    status = Column(
        String(20),
        nullable=False,
        default=DashboardStatus.DRAFT.value,
        index=True,
        comment="Lifecycle status: draft, published, archived",
    )

    layout_json = Column(
        JSON,
        nullable=False,
        default=dict,
        comment="Grid layout positions for report widgets. Validated at API layer.",
    )

    filters_json = Column(
        JSON,
        nullable=True,
        comment="Dashboard-level filter configuration (date range, dimensions)",
    )

    template_id = Column(
        String(36),
        ForeignKey("report_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Source template ID if created from template. SET NULL on template delete.",
    )

    is_template_derived = Column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether this dashboard was created from a template",
    )

    version_number = Column(
        Integer,
        nullable=False,
        default=1,
        comment="Current version number, incremented on each mutation",
    )

    created_by = Column(
        String(255),
        nullable=False,
        index=True,
        comment="User ID of the dashboard creator (from JWT)",
    )

    # Relationships
    reports = relationship(
        "CustomReport",
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="CustomReport.sort_order",
    )

    versions = relationship(
        "DashboardVersion",
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="DashboardVersion.version_number.desc()",
    )

    shares = relationship(
        "DashboardShare",
        back_populates="dashboard",
        cascade="all, delete-orphan",
    )

    audit_entries = relationship(
        "DashboardAudit",
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="DashboardAudit.created_at.desc()",
    )

    # Indexes and constraints
    __table_args__ = (
        # Prevent duplicate active dashboard names per tenant
        UniqueConstraint(
            "tenant_id", "name", "status",
            name="uk_custom_dashboards_tenant_name_status",
        ),
        # Common query: list dashboards for a tenant filtered by status
        Index(
            "idx_custom_dashboards_tenant_status",
            "tenant_id", "status",
        ),
        # Common query: list dashboards created by a user
        Index(
            "idx_custom_dashboards_tenant_created_by",
            "tenant_id", "created_by",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CustomDashboard(id={self.id}, name={self.name!r}, "
            f"tenant_id={self.tenant_id}, status={self.status})>"
        )
