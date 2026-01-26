"""
Canonical permissions matrix for AI Growth Analytics.

IMPORTANT: This is the single source of truth for all permissions.
All permission checks MUST reference these constants.
UI permission gating is UX only - server-side enforcement is security.

Roles are defined in Frontegg and mapped here.
"""

from enum import Enum
from typing import FrozenSet


class Role(str, Enum):
    """
    User roles from Frontegg.

    Keep in sync with Frontegg role configuration.
    """
    ADMIN = "admin"
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class Permission(str, Enum):
    """
    All permissions in the system.

    Naming convention: RESOURCE_ACTION
    """
    # Analytics permissions
    ANALYTICS_VIEW = "analytics:view"
    ANALYTICS_EXPORT = "analytics:export"
    ANALYTICS_EXPLORE = "analytics:explore"  # Superset Explore mode access

    # Store/connector permissions
    STORE_VIEW = "store:view"
    STORE_CREATE = "store:create"
    STORE_UPDATE = "store:update"
    STORE_DELETE = "store:delete"

    # Billing permissions
    BILLING_VIEW = "billing:view"
    BILLING_MANAGE = "billing:manage"

    # User/team management
    TEAM_VIEW = "team:view"
    TEAM_MANAGE = "team:manage"
    TEAM_INVITE = "team:invite"

    # AI features
    AI_INSIGHTS_VIEW = "ai:insights:view"
    AI_ACTIONS_EXECUTE = "ai:actions:execute"  # Write-back actions
    AI_CONFIG_MANAGE = "ai:config:manage"  # API keys, model selection

    # Automation permissions
    AUTOMATION_VIEW = "automation:view"
    AUTOMATION_CREATE = "automation:create"
    AUTOMATION_APPROVE = "automation:approve"
    AUTOMATION_EXECUTE = "automation:execute"

    # Admin permissions (platform-level)
    ADMIN_PLANS_VIEW = "admin:plans:view"
    ADMIN_PLANS_MANAGE = "admin:plans:manage"
    ADMIN_SYSTEM_CONFIG = "admin:system:config"
    ADMIN_AUDIT_VIEW = "admin:audit:view"

    # Settings
    SETTINGS_VIEW = "settings:view"
    SETTINGS_MANAGE = "settings:manage"


# Permission matrix: Role -> Set of Permissions
# This is the canonical source of truth for RBAC
ROLE_PERMISSIONS: dict[Role, FrozenSet[Permission]] = {
    Role.VIEWER: frozenset([
        Permission.ANALYTICS_VIEW,
        Permission.STORE_VIEW,
        Permission.BILLING_VIEW,
        Permission.TEAM_VIEW,
        Permission.AI_INSIGHTS_VIEW,
        Permission.AUTOMATION_VIEW,
        Permission.SETTINGS_VIEW,
    ]),

    Role.EDITOR: frozenset([
        # All viewer permissions
        Permission.ANALYTICS_VIEW,
        Permission.ANALYTICS_EXPORT,
        Permission.ANALYTICS_EXPLORE,  # Superset Explore mode
        Permission.STORE_VIEW,
        Permission.STORE_CREATE,
        Permission.STORE_UPDATE,
        Permission.BILLING_VIEW,
        Permission.TEAM_VIEW,
        Permission.AI_INSIGHTS_VIEW,
        Permission.AI_ACTIONS_EXECUTE,
        Permission.AUTOMATION_VIEW,
        Permission.AUTOMATION_CREATE,
        Permission.SETTINGS_VIEW,
    ]),

    Role.OWNER: frozenset([
        # All editor permissions plus management
        Permission.ANALYTICS_VIEW,
        Permission.ANALYTICS_EXPORT,
        Permission.ANALYTICS_EXPLORE,  # Superset Explore mode
        Permission.STORE_VIEW,
        Permission.STORE_CREATE,
        Permission.STORE_UPDATE,
        Permission.STORE_DELETE,
        Permission.BILLING_VIEW,
        Permission.BILLING_MANAGE,
        Permission.TEAM_VIEW,
        Permission.TEAM_MANAGE,
        Permission.TEAM_INVITE,
        Permission.AI_INSIGHTS_VIEW,
        Permission.AI_ACTIONS_EXECUTE,
        Permission.AI_CONFIG_MANAGE,
        Permission.AUTOMATION_VIEW,
        Permission.AUTOMATION_CREATE,
        Permission.AUTOMATION_APPROVE,
        Permission.AUTOMATION_EXECUTE,
        Permission.SETTINGS_VIEW,
        Permission.SETTINGS_MANAGE,
    ]),

    Role.ADMIN: frozenset([
        # All permissions including admin
        Permission.ANALYTICS_VIEW,
        Permission.ANALYTICS_EXPORT,
        Permission.ANALYTICS_EXPLORE,  # Superset Explore mode
        Permission.STORE_VIEW,
        Permission.STORE_CREATE,
        Permission.STORE_UPDATE,
        Permission.STORE_DELETE,
        Permission.BILLING_VIEW,
        Permission.BILLING_MANAGE,
        Permission.TEAM_VIEW,
        Permission.TEAM_MANAGE,
        Permission.TEAM_INVITE,
        Permission.AI_INSIGHTS_VIEW,
        Permission.AI_ACTIONS_EXECUTE,
        Permission.AI_CONFIG_MANAGE,
        Permission.AUTOMATION_VIEW,
        Permission.AUTOMATION_CREATE,
        Permission.AUTOMATION_APPROVE,
        Permission.AUTOMATION_EXECUTE,
        Permission.ADMIN_PLANS_VIEW,
        Permission.ADMIN_PLANS_MANAGE,
        Permission.ADMIN_SYSTEM_CONFIG,
        Permission.ADMIN_AUDIT_VIEW,
        Permission.SETTINGS_VIEW,
        Permission.SETTINGS_MANAGE,
    ]),
}


def get_permissions_for_role(role: Role) -> FrozenSet[Permission]:
    """Get all permissions for a given role."""
    return ROLE_PERMISSIONS.get(role, frozenset())


def get_permissions_for_roles(roles: list[str]) -> set[Permission]:
    """
    Get union of all permissions for a list of role names.

    Handles invalid role names gracefully (ignores them).
    """
    permissions: set[Permission] = set()
    for role_name in roles:
        try:
            role = Role(role_name.lower())
            permissions.update(ROLE_PERMISSIONS.get(role, frozenset()))
        except ValueError:
            # Invalid role name, skip
            continue
    return permissions


def role_has_permission(role: Role, permission: Permission) -> bool:
    """Check if a role has a specific permission."""
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def roles_have_permission(roles: list[str], permission: Permission) -> bool:
    """Check if any of the given roles has the specified permission."""
    for role_name in roles:
        try:
            role = Role(role_name.lower())
            if permission in ROLE_PERMISSIONS.get(role, frozenset()):
                return True
        except ValueError:
            continue
    return False
