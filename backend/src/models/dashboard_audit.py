"""
Dashboard Audit model - Append-only audit trail for custom dashboards.

Records all significant actions on a dashboard for compliance and
debugging. Entries are immutable once created.

Phase: Custom Reports & Dashboard Builder
"""

import uuid
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, ForeignKey, Index, JSON,
)
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin


class DashboardAuditAction(str, PyEnum):
    """Audit action types for custom dashboards."""
    CREATED = "created"
    UPDATED = "updated"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    RESTORED = "restored"
    DUPLICATED = "duplicated"
    SHARED = "shared"
    UNSHARED = "unshared"
    SHARE_UPDATED = "share_updated"
    REPORT_ADDED = "report_added"
    REPORT_UPDATED = "report_updated"
    REPORT_REMOVED = "report_removed"
    REPORTS_REORDERED = "reports_reordered"


class DashboardAudit(Base, TimestampMixin, TenantScopedMixin):
    """
    Append-only audit entry for a CustomDashboard.

    Captures who did what and when, with optional structured details.
    Entries are never updated or deleted (compliance requirement).

    SECURITY: tenant_id from JWT only.
    """

    __tablename__ = "dashboard_audit"

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
        comment="Dashboard this audit entry belongs to",
    )

    action = Column(
        String(50),
        nullable=False,
        comment="Action type: created, updated, published, shared, etc.",
    )

    actor_id = Column(
        String(255),
        nullable=False,
        comment="User ID who performed the action (from JWT)",
    )

    details_json = Column(
        JSON,
        nullable=True,
        comment="Action-specific metadata (e.g., share target, report name, version restored)",
    )

    # Relationships
    dashboard = relationship(
        "CustomDashboard",
        back_populates="audit_entries",
    )

    # Indexes
    __table_args__ = (
        # Query audit trail for a dashboard chronologically
        Index(
            "idx_dashboard_audit_dashboard_created",
            "dashboard_id", "created_at",
        ),
        # Tenant scoping for cross-dashboard audit queries
        Index(
            "idx_dashboard_audit_tenant",
            "tenant_id",
        ),
        # Filter by action type
        Index(
            "idx_dashboard_audit_action",
            "action",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<DashboardAudit(id={self.id}, dashboard_id={self.dashboard_id}, "
            f"action={self.action}, actor_id={self.actor_id})>"
        )
