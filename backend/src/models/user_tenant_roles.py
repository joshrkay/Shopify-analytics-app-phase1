"""
UserTenantRole model for multi-tenant SaaS platform.

UserTenantRole is the junction table that links users to tenants with
role-based access control. This model enables:
- Users belonging to multiple tenants
- Different roles per tenant
- Tracking who granted access and when
- Audit trail for access changes

Two sources of UserTenantRole records:
1. Clerk webhooks: organizationMembership.created → UserTenantRole
2. Agency grants: POST /api/tenants/{id}/members → UserTenantRole

SECURITY:
- CASCADE delete on user_id: User deletion removes all their tenant access
- CASCADE delete on tenant_id: Tenant deletion removes all user access
- Unique constraint prevents duplicate (user, tenant, role) combinations
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, String, Boolean, DateTime, Index, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin

if TYPE_CHECKING:
    from src.models.user import User
    from src.models.tenant import Tenant


class UserTenantRole(Base, TimestampMixin):
    """
    Junction table linking users to tenants with role assignment.

    Key concepts:
    - A user can have multiple roles in the same tenant
    - A user can be a member of multiple tenants
    - assigned_by tracks who granted the access (audit trail)
    - is_active allows soft-delete without losing history

    Role values come from src.constants.permissions.Role enum:
    - MERCHANT_ADMIN, MERCHANT_VIEWER (single tenant)
    - AGENCY_ADMIN, AGENCY_VIEWER (multi-tenant)
    - ADMIN, OWNER, EDITOR, VIEWER (legacy)

    Sources of records:
    - Clerk webhook: organizationMembership events
    - Agency grant: POST /api/tenants/{id}/members API
    """

    __tablename__ = "user_tenant_roles"

    # Primary Key
    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Internal UUID primary key"
    )

    # Foreign Keys with CASCADE delete
    user_id = Column(
        String(255),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User ID (FK to users.id)"
    )

    tenant_id = Column(
        String(255),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID (FK to tenants.id)"
    )

    # Role Assignment
    role = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Role name from constants/permissions.py Role enum"
    )

    # Assignment tracking (audit trail)
    assigned_by = Column(
        String(255),
        nullable=True,
        comment="clerk_user_id of user who granted this access"
    )

    assigned_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When the access was granted"
    )

    # Source tracking
    source = Column(
        String(50),
        nullable=True,
        default="clerk_webhook",
        comment="How this role was created: clerk_webhook, agency_grant, admin_grant"
    )

    # Status
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Whether this role assignment is active"
    )

    # Relationships
    user = relationship(
        "User",
        back_populates="tenant_roles",
        lazy="joined"
    )

    tenant = relationship(
        "Tenant",
        back_populates="user_roles",
        lazy="joined"
    )

    # Constraints and Indexes (single-column indexes defined via index=True above)
    __table_args__ = (
        # Prevent duplicate (user, tenant, role) combinations
        UniqueConstraint("user_id", "tenant_id", "role", name="uq_user_tenant_role"),
        # Composite indexes for efficient lookups
        Index("ix_user_tenant_roles_tenant_user", "tenant_id", "user_id"),
        Index("ix_user_tenant_roles_tenant_active", "tenant_id", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserTenantRole(id={self.id}, user_id={self.user_id}, "
            f"tenant_id={self.tenant_id}, role={self.role}, is_active={self.is_active})>"
        )

    @property
    def is_admin_role(self) -> bool:
        """Check if this is an admin-level role."""
        admin_roles = {"admin", "owner", "merchant_admin", "agency_admin", "super_admin"}
        return self.role.lower() in admin_roles

    @property
    def is_agency_role(self) -> bool:
        """Check if this is an agency role (multi-tenant access)."""
        agency_roles = {"agency_admin", "agency_viewer"}
        return self.role.lower() in agency_roles

    def deactivate(self, deactivated_by: Optional[str] = None) -> None:
        """
        Soft-delete this role assignment.

        Args:
            deactivated_by: clerk_user_id of user performing the deactivation
        """
        self.is_active = False
        # Optionally track who deactivated (could add a deactivated_by column)

    def reactivate(self, reactivated_by: Optional[str] = None) -> None:
        """
        Reactivate a previously deactivated role assignment.

        Args:
            reactivated_by: clerk_user_id of user performing the reactivation
        """
        self.is_active = True

    @classmethod
    def create_from_clerk(
        cls,
        user_id: str,
        tenant_id: str,
        role: str,
    ) -> "UserTenantRole":
        """
        Factory method for creating role from Clerk webhook.

        Args:
            user_id: Internal user ID
            tenant_id: Internal tenant ID
            role: Role name

        Returns:
            New UserTenantRole instance
        """
        return cls(
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            source="clerk_webhook",
            assigned_at=datetime.now(timezone.utc),
        )

    @classmethod
    def create_from_grant(
        cls,
        user_id: str,
        tenant_id: str,
        role: str,
        granted_by: str,
    ) -> "UserTenantRole":
        """
        Factory method for creating role from agency/admin grant.

        Args:
            user_id: Internal user ID
            tenant_id: Internal tenant ID
            role: Role name
            granted_by: clerk_user_id of granting user

        Returns:
            New UserTenantRole instance
        """
        return cls(
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            assigned_by=granted_by,
            source="agency_grant",
            assigned_at=datetime.now(timezone.utc),
        )
