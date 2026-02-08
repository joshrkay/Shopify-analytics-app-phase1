"""
UserRoleAssignment model for data-driven, tenant-scoped RBAC.

Links users to data-driven Role instances per tenant. This enables:
- Users having different custom roles across different tenants
- Runtime permission evaluation from DB (not hardcoded enums)
- Audit trail for who granted the assignment and when

Coexists with the legacy UserTenantRole junction table during migration.
The RBAC service resolves permissions from BOTH sources (union).

Story 5.5.1 - Data Model: Custom Roles Per Tenant
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin

if TYPE_CHECKING:
    from src.models.user import User
    from src.models.tenant import Tenant
    from src.models.role import Role


class UserRoleAssignment(Base, TimestampMixin):
    """
    Maps a user to a data-driven Role for a specific tenant.

    - user_id: the user receiving the role
    - role_id: FK to the data-driven Role row
    - tenant_id: denormalized for query performance (Role.tenant_id can be NULL for global roles)
    - source: how the assignment was created (admin_grant, agency_approval, migration)

    SECURITY:
    - CASCADE delete on user_id/role_id/tenant_id
    - Unique constraint prevents duplicate (user, role, tenant) combos
    """

    __tablename__ = "user_role_assignments"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Internal UUID primary key",
    )

    user_id = Column(
        String(255),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User ID (FK to users.id)",
    )

    role_id = Column(
        String(255),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Role ID (FK to roles.id)",
    )

    tenant_id = Column(
        String(255),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID (FK to tenants.id) — denormalized for query performance",
    )

    assigned_by = Column(
        String(255),
        nullable=True,
        comment="clerk_user_id of user who granted this assignment",
    )

    assigned_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When the assignment was created",
    )

    source = Column(
        String(50),
        nullable=True,
        default="admin_grant",
        comment="How this assignment was created: admin_grant, agency_approval, migration",
    )

    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Whether this assignment is active (soft-delete)",
    )

    # Relationships
    user = relationship("User", lazy="joined")
    role = relationship("Role", back_populates="assignments", lazy="joined")
    tenant = relationship("Tenant", lazy="joined")

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "tenant_id", name="uq_user_role_assignment"),
        Index("ix_user_role_assignments_tenant_user", "tenant_id", "user_id"),
        Index("ix_user_role_assignments_tenant_active", "tenant_id", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserRoleAssignment(id={self.id}, user_id={self.user_id}, "
            f"role_id={self.role_id}, tenant_id={self.tenant_id}, is_active={self.is_active})>"
        )

    @classmethod
    def create_from_approval(
        cls,
        user_id: str,
        role_id: str,
        tenant_id: str,
        assigned_by: str,
    ) -> "UserRoleAssignment":
        """Factory for agency approval workflow."""
        return cls(
            user_id=user_id,
            role_id=role_id,
            tenant_id=tenant_id,
            assigned_by=assigned_by,
            source="agency_approval",
            assigned_at=datetime.now(timezone.utc),
        )

    @classmethod
    def create_from_admin(
        cls,
        user_id: str,
        role_id: str,
        tenant_id: str,
        assigned_by: str,
    ) -> "UserRoleAssignment":
        """Factory for admin grants."""
        return cls(
            user_id=user_id,
            role_id=role_id,
            tenant_id=tenant_id,
            assigned_by=assigned_by,
            source="admin_grant",
            assigned_at=datetime.now(timezone.utc),
        )

    def deactivate(self) -> None:
        """Soft-delete this assignment."""
        self.is_active = False

    def reactivate(self, reactivated_by: Optional[str] = None) -> None:
        """Reactivate a previously deactivated assignment."""
        self.is_active = True
        if reactivated_by:
            self.assigned_by = reactivated_by
