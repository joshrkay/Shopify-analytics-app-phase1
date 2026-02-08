"""
Data-driven RBAC service for runtime permission evaluation.

Resolves permissions from two sources (union):
1. New path: UserRoleAssignment -> Role -> RolePermission (data-driven)
2. Legacy path: UserTenantRole -> ROLE_PERMISSIONS hardcoded matrix

Default deny: returns empty set if no matching permissions found.
Called once per request during TenantContext construction.

Story 5.5.1 - Data Model: Custom Roles Per Tenant
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from src.models.role import Role, RolePermission
from src.models.user_role_assignment import UserRoleAssignment
from src.models.user_tenant_roles import UserTenantRole
from src.constants.permissions import (
    Permission,
    Role as LegacyRole,
    ROLE_PERMISSIONS,
)

logger = logging.getLogger(__name__)


def resolve_permissions_for_user(
    db: Session,
    user_id: str,
    tenant_id: str,
) -> set[str]:
    """
    Resolve all permission strings for a user in a tenant.

    Sources (union of both):
    1. UserRoleAssignment -> Role -> RolePermission (new data-driven path)
    2. UserTenantRole -> ROLE_PERMISSIONS matrix (legacy path)

    Default deny: returns empty set if no matching permissions found.

    Args:
        db: SQLAlchemy session
        user_id: Internal user ID (users.id)
        tenant_id: Tenant ID

    Returns:
        Set of permission strings (e.g. {"analytics:view", "billing:manage"})
    """
    permissions: set[str] = set()

    # --- Source 1: Data-driven roles (UserRoleAssignment -> Role -> RolePermission) ---
    try:
        assignments = (
            db.query(UserRoleAssignment)
            .filter(
                UserRoleAssignment.user_id == user_id,
                UserRoleAssignment.tenant_id == tenant_id,
                UserRoleAssignment.is_active == True,  # noqa: E712
            )
            .all()
        )

        for assignment in assignments:
            role = assignment.role
            if role and role.is_active:
                permissions.update(role.permission_strings)

        # Also check global roles (tenant_id IS NULL) assigned to this user
        global_assignments = (
            db.query(UserRoleAssignment)
            .join(Role, UserRoleAssignment.role_id == Role.id)
            .filter(
                UserRoleAssignment.user_id == user_id,
                UserRoleAssignment.is_active == True,  # noqa: E712
                Role.tenant_id.is_(None),
                Role.is_active == True,  # noqa: E712
            )
            .all()
        )

        for assignment in global_assignments:
            role = assignment.role
            if role:
                permissions.update(role.permission_strings)

    except Exception:
        logger.warning(
            "rbac.resolve_data_driven_permissions_failed",
            extra={"user_id": user_id, "tenant_id": tenant_id},
            exc_info=True,
        )

    # --- Source 2: Legacy roles (UserTenantRole -> ROLE_PERMISSIONS matrix) ---
    try:
        legacy_roles = (
            db.query(UserTenantRole)
            .filter(
                UserTenantRole.user_id == user_id,
                UserTenantRole.tenant_id == tenant_id,
                UserTenantRole.is_active == True,  # noqa: E712
            )
            .all()
        )

        for legacy_role in legacy_roles:
            try:
                role_enum = LegacyRole(legacy_role.role.lower())
                role_perms = ROLE_PERMISSIONS.get(role_enum, frozenset())
                permissions.update(p.value for p in role_perms)
            except ValueError:
                # Unknown role string, skip
                continue

    except Exception:
        logger.warning(
            "rbac.resolve_legacy_permissions_failed",
            extra={"user_id": user_id, "tenant_id": tenant_id},
            exc_info=True,
        )

    return permissions


def user_has_permission(
    db: Session,
    user_id: str,
    tenant_id: str,
    permission: str,
) -> bool:
    """
    Check if user has a specific permission in a tenant.

    Default deny: returns False if permission not found.

    Args:
        db: SQLAlchemy session
        user_id: Internal user ID
        tenant_id: Tenant ID
        permission: Permission string (e.g. "analytics:view")

    Returns:
        True if user has the permission
    """
    resolved = resolve_permissions_for_user(db, user_id, tenant_id)
    return permission in resolved


def user_has_any_permission(
    db: Session,
    user_id: str,
    tenant_id: str,
    permissions: list[str],
) -> bool:
    """
    Check if user has any of the specified permissions in a tenant.

    Default deny: returns False if none found.

    Args:
        db: SQLAlchemy session
        user_id: Internal user ID
        tenant_id: Tenant ID
        permissions: List of permission strings

    Returns:
        True if user has at least one of the permissions
    """
    resolved = resolve_permissions_for_user(db, user_id, tenant_id)
    return bool(resolved.intersection(permissions))


def get_user_roles_for_tenant(
    db: Session,
    user_id: str,
    tenant_id: str,
) -> list[dict]:
    """
    Get all active role assignments for a user in a tenant.

    Returns both data-driven and legacy role information.

    Args:
        db: SQLAlchemy session
        user_id: Internal user ID
        tenant_id: Tenant ID

    Returns:
        List of dicts with role info
    """
    roles = []

    # Data-driven roles
    try:
        assignments = (
            db.query(UserRoleAssignment)
            .filter(
                UserRoleAssignment.user_id == user_id,
                UserRoleAssignment.tenant_id == tenant_id,
                UserRoleAssignment.is_active == True,  # noqa: E712
            )
            .all()
        )

        for assignment in assignments:
            role = assignment.role
            if role and role.is_active:
                roles.append({
                    "id": assignment.id,
                    "role_id": role.id,
                    "role_name": role.name,
                    "role_slug": role.slug,
                    "source": assignment.source or "admin_grant",
                    "type": "data_driven",
                })

    except Exception:
        logger.warning(
            "rbac.get_data_driven_roles_failed",
            extra={"user_id": user_id, "tenant_id": tenant_id},
            exc_info=True,
        )

    # Legacy roles
    try:
        legacy_roles = (
            db.query(UserTenantRole)
            .filter(
                UserTenantRole.user_id == user_id,
                UserTenantRole.tenant_id == tenant_id,
                UserTenantRole.is_active == True,  # noqa: E712
            )
            .all()
        )

        for lr in legacy_roles:
            roles.append({
                "id": lr.id,
                "role_id": None,
                "role_name": lr.role,
                "role_slug": lr.role.lower(),
                "source": lr.source or "clerk_webhook",
                "type": "legacy",
            })

    except Exception:
        logger.warning(
            "rbac.get_legacy_roles_failed",
            extra={"user_id": user_id, "tenant_id": tenant_id},
            exc_info=True,
        )

    return roles
