"""
Dashboard Share model - Access grants for custom dashboards.

Supports sharing dashboards with specific users or by role,
with configurable permission levels and optional expiry.

Phase: Custom Reports & Dashboard Builder
"""

import uuid
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, DateTime, ForeignKey,
    Index, UniqueConstraint, JSON,
)
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin


class SharePermission(str, PyEnum):
    """Permission levels for dashboard shares."""
    VIEW = "view"       # Can view dashboard and charts
    EDIT = "edit"       # Can view + edit charts and layout
    ADMIN = "admin"     # Can view + edit + manage shares


class DashboardShare(Base, TimestampMixin, TenantScopedMixin):
    """
    Access grant for a CustomDashboard.

    Shares can target a specific user (shared_with_user_id) or a role
    (shared_with_role). At least one must be set.

    Access resolution order (in dashboard_share_service):
    1. Owner (created_by on dashboard) -> full access always
    2. Direct user share -> use share's permission
    3. Role-based share -> use highest permission among matching roles
    4. No match -> denied

    SECURITY:
    - tenant_id from JWT only
    - shared_with_user_id must have tenant access (validated at service layer)
    - Expired shares (expires_at < now) are treated as inactive at query time
    """

    __tablename__ = "dashboard_shares"

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
        comment="Dashboard being shared. CASCADE delete when dashboard removed.",
    )

    shared_with_user_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Specific user ID to share with (mutually exclusive with role-only shares)",
    )

    shared_with_role = Column(
        String(50),
        nullable=True,
        index=True,
        comment="Role to share with: merchant_admin, merchant_viewer, agency_admin, agency_viewer",
    )

    permission = Column(
        String(20),
        nullable=False,
        default=SharePermission.VIEW.value,
        comment="Permission level: view, edit, admin",
    )

    granted_by = Column(
        String(255),
        nullable=False,
        comment="User ID who created the share (from JWT)",
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Optional expiry. NULL = never expires. Checked at query time.",
    )

    # Relationships
    dashboard = relationship(
        "CustomDashboard",
        back_populates="shares",
    )

    # Indexes and constraints
    __table_args__ = (
        # One share per user per dashboard (for user-targeted shares)
        UniqueConstraint(
            "dashboard_id", "shared_with_user_id",
            name="uk_dashboard_shares_dashboard_user",
        ),
        # One share per role per dashboard (for role-targeted shares)
        UniqueConstraint(
            "dashboard_id", "shared_with_role",
            name="uk_dashboard_shares_dashboard_role",
        ),
        # Lookup shares for a dashboard
        Index(
            "idx_dashboard_shares_dashboard",
            "dashboard_id",
        ),
        # Lookup all dashboards shared with a specific user
        Index(
            "idx_dashboard_shares_user",
            "shared_with_user_id",
        ),
        # Tenant scoping
        Index(
            "idx_dashboard_shares_tenant",
            "tenant_id",
        ),
    )

    def __repr__(self) -> str:
        target = self.shared_with_user_id or f"role:{self.shared_with_role}"
        return (
            f"<DashboardShare(id={self.id}, dashboard_id={self.dashboard_id}, "
            f"target={target}, permission={self.permission})>"
        )
