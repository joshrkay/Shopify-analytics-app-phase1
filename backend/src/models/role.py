"""
Data-driven Role model for tenant-scoped RBAC.

Roles are defined per tenant with custom names and permission sets.
A user can have different roles across different tenants.

Global roles (like super_admin) have tenant_id = NULL.
Tenant-scoped roles have a non-null tenant_id.

Role templates seed new tenants with baseline roles:
- Merchant Admin, Merchant Viewer
- Agency Admin, Agency Viewer
- Analyst
- Super Admin (global only)

Story 5.5.1 - Data Model: Custom Roles Per Tenant
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin

if TYPE_CHECKING:
    from src.models.tenant import Tenant


class Role(Base, TimestampMixin):
    """
    Data-driven role definition, scoped per tenant.

    - tenant_id IS NULL => global role (e.g. super_admin)
    - tenant_id IS NOT NULL => tenant-scoped custom role

    Permissions are stored as an explicit list of permission strings
    in the related RolePermission rows for readability and testability.
    """

    __tablename__ = "roles"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Internal UUID primary key",
    )

    tenant_id = Column(
        String(255),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Owning tenant ID. NULL for global roles (e.g. super_admin).",
    )

    name = Column(
        String(100),
        nullable=False,
        comment="Human-readable role name (e.g. 'Merchant Admin')",
    )

    slug = Column(
        String(100),
        nullable=False,
        comment="Machine-friendly role identifier (e.g. 'merchant_admin')",
    )

    description = Column(
        Text,
        nullable=True,
        comment="Optional description of the role's purpose",
    )

    is_system = Column(
        Boolean,
        nullable=False,
        default=False,
        comment="True for roles seeded from templates; prevents deletion",
    )

    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Soft-delete flag",
    )

    # Relationships
    tenant = relationship("Tenant", lazy="joined")

    permissions = relationship(
        "RolePermission",
        back_populates="role",
        lazy="joined",
        cascade="all, delete-orphan",
    )

    assignments = relationship(
        "UserRoleAssignment",
        back_populates="role",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # A role slug must be unique within a tenant (or globally for NULL tenant)
        UniqueConstraint("tenant_id", "slug", name="uq_roles_tenant_slug"),
        Index("ix_roles_tenant_active", "tenant_id", "is_active"),
    )

    def __repr__(self) -> str:
        scope = f"tenant={self.tenant_id}" if self.tenant_id else "global"
        return f"<Role(id={self.id}, slug={self.slug}, {scope})>"

    @property
    def permission_strings(self) -> list[str]:
        """Return the list of permission strings for this role."""
        return [rp.permission for rp in self.permissions if rp.is_active]

    def has_permission(self, permission: str) -> bool:
        """Check if this role grants a specific permission."""
        return permission in self.permission_strings


class RolePermission(Base, TimestampMixin):
    """
    Explicit permission grant for a role.

    Permissions are stored as strings (e.g. 'analytics:view') for
    readability and testability. This avoids bitset complexity while
    remaining easily queryable.
    """

    __tablename__ = "role_permissions"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Internal UUID primary key",
    )

    role_id = Column(
        String(255),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK to roles.id",
    )

    permission = Column(
        String(100),
        nullable=False,
        comment="Permission string, e.g. 'analytics:view'",
    )

    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        comment="Soft-delete flag",
    )

    # Relationships
    role = relationship("Role", back_populates="permissions")

    __table_args__ = (
        UniqueConstraint("role_id", "permission", name="uq_role_permission"),
        Index("ix_role_permissions_role_active", "role_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<RolePermission(role_id={self.role_id}, permission={self.permission})>"


# ---------------------------------------------------------------------------
# Role templates for seeding new tenants
# ---------------------------------------------------------------------------

# Canonical permission strings used across templates.
# These match the Permission enum values in constants/permissions.py.
ROLE_TEMPLATES: dict[str, dict] = {
    "merchant_admin": {
        "name": "Merchant Admin",
        "slug": "merchant_admin",
        "description": "Full access to own store",
        "is_system": True,
        "permissions": [
            "analytics:view",
            "analytics:export",
            "analytics:explore",
            "store:view",
            "store:update",
            "billing:view",
            "billing:manage",
            "team:view",
            "team:manage",
            "team:invite",
            "ai:insights:view",
            "ai:actions:execute",
            "ai:config:manage",
            "automation:view",
            "automation:create",
            "automation:approve",
            "automation:execute",
            "settings:view",
            "settings:manage",
            "action_proposals:view",
            "action_proposals:approve",
            "action_proposals:audit",
            "actions:view",
            "actions:execute",
            "actions:rollback",
            "actions:audit",
        ],
    },
    "merchant_viewer": {
        "name": "Merchant Viewer",
        "slug": "merchant_viewer",
        "description": "Read-only dashboards for own store",
        "is_system": True,
        "permissions": [
            "analytics:view",
            "store:view",
            "billing:view",
            "team:view",
            "ai:insights:view",
            "automation:view",
            "settings:view",
            "action_proposals:view",
            "actions:view",
        ],
    },
    "agency_admin": {
        "name": "Agency Admin",
        "slug": "agency_admin",
        "description": "Multi-tenant admin for agencies managing client stores",
        "is_system": True,
        "permissions": [
            "analytics:view",
            "analytics:explore",
            "store:view",
            "team:view",
            "ai:insights:view",
            "automation:view",
            "settings:view",
            "agency:stores:view",
            "agency:stores:switch",
            "agency:reports:view",
            "multi_tenant:access",
            "action_proposals:view",
            "action_proposals:approve",
            "action_proposals:audit",
            "actions:view",
            "actions:execute",
            "actions:rollback",
            "actions:audit",
        ],
    },
    "agency_viewer": {
        "name": "Agency Viewer",
        "slug": "agency_viewer",
        "description": "Read-only agency access to assigned stores",
        "is_system": True,
        "permissions": [
            "analytics:view",
            "store:view",
            "ai:insights:view",
            "settings:view",
            "agency:stores:view",
            "agency:stores:switch",
            "multi_tenant:access",
            "action_proposals:view",
            "actions:view",
        ],
    },
    "analyst": {
        "name": "Analyst",
        "slug": "analyst",
        "description": "Analytics-focused role with explore and export access",
        "is_system": True,
        "permissions": [
            "analytics:view",
            "analytics:export",
            "analytics:explore",
            "store:view",
            "ai:insights:view",
            "automation:view",
            "settings:view",
            "action_proposals:view",
            "actions:view",
        ],
    },
    "super_admin": {
        "name": "Super Admin",
        "slug": "super_admin",
        "description": "Platform-level access to all tenants and features",
        "is_system": True,
        "permissions": [
            "analytics:view",
            "analytics:export",
            "analytics:explore",
            "store:view",
            "store:create",
            "store:update",
            "store:delete",
            "billing:view",
            "billing:manage",
            "team:view",
            "team:manage",
            "team:invite",
            "ai:insights:view",
            "ai:actions:execute",
            "ai:config:manage",
            "automation:view",
            "automation:create",
            "automation:approve",
            "automation:execute",
            "admin:plans:view",
            "admin:plans:manage",
            "admin:system:config",
            "admin:audit:view",
            "settings:view",
            "settings:manage",
            "agency:stores:view",
            "agency:stores:switch",
            "agency:reports:view",
            "multi_tenant:access",
            "action_proposals:view",
            "action_proposals:approve",
            "action_proposals:audit",
            "actions:view",
            "actions:execute",
            "actions:rollback",
            "actions:audit",
        ],
    },
}


def seed_roles_for_tenant(
    db_session,
    tenant_id: str,
    *,
    templates: list[str] | None = None,
) -> list["Role"]:
    """
    Seed baseline roles for a tenant from templates.

    Args:
        db_session: SQLAlchemy session
        tenant_id: The tenant to seed roles for
        templates: Optional list of template slugs to seed.
                   Defaults to all non-super_admin templates.

    Returns:
        List of created Role instances.
    """
    if templates is None:
        # Default: all templates except super_admin (which is global)
        templates = [k for k in ROLE_TEMPLATES if k != "super_admin"]

    created_roles: list[Role] = []

    for slug in templates:
        template = ROLE_TEMPLATES.get(slug)
        if not template:
            continue

        role = Role(
            tenant_id=tenant_id,
            name=template["name"],
            slug=template["slug"],
            description=template["description"],
            is_system=template["is_system"],
        )
        db_session.add(role)
        db_session.flush()  # Get the role.id

        for perm_str in template["permissions"]:
            rp = RolePermission(
                role_id=role.id,
                permission=perm_str,
            )
            db_session.add(rp)

        created_roles.append(role)

    return created_roles


def seed_global_super_admin_role(db_session) -> "Role":
    """
    Seed the global super_admin role (tenant_id=NULL).

    Idempotent: skips if already exists.

    Returns:
        The super_admin Role instance.
    """
    from sqlalchemy import and_

    existing = (
        db_session.query(Role)
        .filter(and_(Role.tenant_id.is_(None), Role.slug == "super_admin"))
        .first()
    )
    if existing:
        return existing

    template = ROLE_TEMPLATES["super_admin"]
    role = Role(
        tenant_id=None,
        name=template["name"],
        slug=template["slug"],
        description=template["description"],
        is_system=True,
    )
    db_session.add(role)
    db_session.flush()

    for perm_str in template["permissions"]:
        rp = RolePermission(role_id=role.id, permission=perm_str)
        db_session.add(rp)

    return role
