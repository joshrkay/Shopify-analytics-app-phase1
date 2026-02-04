"""
Canonical permissions matrix for AI Growth Analytics.

IMPORTANT: This is the single source of truth for all permissions.
All permission checks MUST reference these constants.
UI permission gating is UX only - server-side enforcement is security.

Roles are defined in Clerk and mapped here.

Role Hierarchy:
- Merchant roles: MERCHANT_ADMIN > MERCHANT_VIEWER (single tenant access)
- Agency roles: AGENCY_ADMIN > AGENCY_VIEWER (multi-tenant access)
- Platform roles: ADMIN > OWNER > EDITOR > VIEWER (legacy, backward compatible)

Agency users have access to multiple tenant_ids via JWT allowed_tenants[] claim.
All queries are filtered via RLS: tenant_id IN ({{ current_user.allowed_tenants }})
"""

from enum import Enum
from typing import FrozenSet


class Role(str, Enum):
    """
    User roles from Clerk.

    Keep in sync with Clerk organization role configuration.

    Role Categories:
    - Merchant roles: Single-tenant access for store owners/staff
    - Agency roles: Multi-tenant access for agencies managing multiple stores
    - Platform roles: Legacy roles maintained for backward compatibility
    """
    # Platform roles (legacy, backward compatible)
    ADMIN = "admin"
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"

    # Merchant roles (single tenant)
    MERCHANT_ADMIN = "merchant_admin"
    MERCHANT_VIEWER = "merchant_viewer"

    # Agency roles (multi-tenant)
    AGENCY_ADMIN = "agency_admin"
    AGENCY_VIEWER = "agency_viewer"

    # Super admin (platform-level)
    SUPER_ADMIN = "super_admin"


class RoleCategory(str, Enum):
    """
    Role categories for determining tenant access scope.
    """
    MERCHANT = "merchant"  # Single tenant_id access
    AGENCY = "agency"      # Multiple tenant_ids via allowed_tenants[]
    PLATFORM = "platform"  # Legacy platform roles


# Map roles to their categories
ROLE_CATEGORIES = {
    Role.MERCHANT_ADMIN: RoleCategory.MERCHANT,
    Role.MERCHANT_VIEWER: RoleCategory.MERCHANT,
    Role.AGENCY_ADMIN: RoleCategory.AGENCY,
    Role.AGENCY_VIEWER: RoleCategory.AGENCY,
    Role.ADMIN: RoleCategory.PLATFORM,
    Role.OWNER: RoleCategory.PLATFORM,
    Role.EDITOR: RoleCategory.PLATFORM,
    Role.VIEWER: RoleCategory.PLATFORM,
    Role.SUPER_ADMIN: RoleCategory.PLATFORM,
}


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

    # Agency-specific permissions
    AGENCY_STORES_VIEW = "agency:stores:view"       # View assigned client stores
    AGENCY_STORES_SWITCH = "agency:stores:switch"   # Switch between client stores
    AGENCY_REPORTS_VIEW = "agency:reports:view"     # View cross-store reports

    # Multi-tenant access permission
    MULTI_TENANT_ACCESS = "multi_tenant:access"     # Access multiple tenant_ids

    # Action Proposal permissions (Story 8.4)
    ACTION_PROPOSALS_VIEW = "action_proposals:view"       # View proposals
    ACTION_PROPOSALS_APPROVE = "action_proposals:approve" # Approve/reject proposals
    ACTION_PROPOSALS_AUDIT = "action_proposals:audit"     # View audit trail

    # Action Execution permissions (Story 8.5)
    ACTIONS_VIEW = "actions:view"           # View actions and their status
    ACTIONS_EXECUTE = "actions:execute"     # Trigger action execution
    ACTIONS_ROLLBACK = "actions:rollback"   # Rollback executed actions
    ACTIONS_AUDIT = "actions:audit"         # View action execution logs


# Permission matrix: Role -> Set of Permissions
# This is the canonical source of truth for RBAC
ROLE_PERMISSIONS: dict[Role, FrozenSet[Permission]] = {
    # --- Legacy Platform Roles (backward compatible) ---
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
        # Action Proposal permissions (Story 8.4)
        Permission.ACTION_PROPOSALS_VIEW,
        Permission.ACTION_PROPOSALS_APPROVE,
        Permission.ACTION_PROPOSALS_AUDIT,
        # Action Execution permissions (Story 8.5)
        Permission.ACTIONS_VIEW,
        Permission.ACTIONS_EXECUTE,
        Permission.ACTIONS_ROLLBACK,
        Permission.ACTIONS_AUDIT,
    ]),

    Role.ADMIN: frozenset([
        # All permissions including admin and agency
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
        # Agency permissions (admin has full access)
        Permission.AGENCY_STORES_VIEW,
        Permission.AGENCY_STORES_SWITCH,
        Permission.AGENCY_REPORTS_VIEW,
        Permission.MULTI_TENANT_ACCESS,
        # Action Proposal permissions (Story 8.4)
        Permission.ACTION_PROPOSALS_VIEW,
        Permission.ACTION_PROPOSALS_APPROVE,
        Permission.ACTION_PROPOSALS_AUDIT,
        # Action Execution permissions (Story 8.5)
        Permission.ACTIONS_VIEW,
        Permission.ACTIONS_EXECUTE,
        Permission.ACTIONS_ROLLBACK,
        Permission.ACTIONS_AUDIT,
    ]),

    # --- Merchant Roles (single tenant access) ---
    Role.MERCHANT_ADMIN: frozenset([
        # Full access to own store
        Permission.ANALYTICS_VIEW,
        Permission.ANALYTICS_EXPLORE,  # Superset Explore mode
        Permission.STORE_VIEW,
        Permission.STORE_UPDATE,
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
        # Action Proposal permissions (Story 8.4)
        Permission.ACTION_PROPOSALS_VIEW,
        Permission.ACTION_PROPOSALS_APPROVE,
        Permission.ACTION_PROPOSALS_AUDIT,
        # Action Execution permissions (Story 8.5)
        Permission.ACTIONS_VIEW,
        Permission.ACTIONS_EXECUTE,
        Permission.ACTIONS_ROLLBACK,
        Permission.ACTIONS_AUDIT,
    ]),

    Role.MERCHANT_VIEWER: frozenset([
        # Read-only dashboards only
        Permission.ANALYTICS_VIEW,
        Permission.STORE_VIEW,
        Permission.BILLING_VIEW,
        Permission.TEAM_VIEW,
        Permission.AI_INSIGHTS_VIEW,
        Permission.AUTOMATION_VIEW,
        Permission.SETTINGS_VIEW,
        # Action Proposal permissions (view only, no approval)
        Permission.ACTION_PROPOSALS_VIEW,
        # Action Execution permissions (view only, no execute/rollback)
        Permission.ACTIONS_VIEW,
    ]),

    # --- Agency Roles (multi-tenant access via allowed_tenants[]) ---
    Role.AGENCY_ADMIN: frozenset([
        # View multiple stores with editing capabilities
        Permission.ANALYTICS_VIEW,
        Permission.ANALYTICS_EXPLORE,  # Superset Explore mode
        Permission.STORE_VIEW,
        Permission.TEAM_VIEW,
        Permission.AI_INSIGHTS_VIEW,
        Permission.AUTOMATION_VIEW,
        Permission.SETTINGS_VIEW,
        # Agency-specific permissions
        Permission.AGENCY_STORES_VIEW,
        Permission.AGENCY_STORES_SWITCH,
        Permission.AGENCY_REPORTS_VIEW,
        Permission.MULTI_TENANT_ACCESS,
        # Action Proposal permissions (Story 8.4)
        Permission.ACTION_PROPOSALS_VIEW,
        Permission.ACTION_PROPOSALS_APPROVE,
        Permission.ACTION_PROPOSALS_AUDIT,
        # Action Execution permissions (Story 8.5)
        Permission.ACTIONS_VIEW,
        Permission.ACTIONS_EXECUTE,
        Permission.ACTIONS_ROLLBACK,
        Permission.ACTIONS_AUDIT,
    ]),

    Role.AGENCY_VIEWER: frozenset([
        # Limited dashboards across assigned stores
        Permission.ANALYTICS_VIEW,
        Permission.STORE_VIEW,
        Permission.AI_INSIGHTS_VIEW,
        Permission.SETTINGS_VIEW,
        # Agency-specific permissions (limited)
        Permission.AGENCY_STORES_VIEW,
        Permission.AGENCY_STORES_SWITCH,
        Permission.MULTI_TENANT_ACCESS,
        # Action Proposal permissions (view only, no approval)
        Permission.ACTION_PROPOSALS_VIEW,
        # Action Execution permissions (view only, no execute/rollback)
        Permission.ACTIONS_VIEW,
    ]),

    # --- Super Admin (platform-level, all access) ---
    Role.SUPER_ADMIN: frozenset([
        # All permissions including multi-tenant
        Permission.ANALYTICS_VIEW,
        Permission.ANALYTICS_EXPORT,
        Permission.ANALYTICS_EXPLORE,
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
        Permission.AGENCY_STORES_VIEW,
        Permission.AGENCY_STORES_SWITCH,
        Permission.AGENCY_REPORTS_VIEW,
        Permission.MULTI_TENANT_ACCESS,
        # Action Proposal permissions (Story 8.4)
        Permission.ACTION_PROPOSALS_VIEW,
        Permission.ACTION_PROPOSALS_APPROVE,
        Permission.ACTION_PROPOSALS_AUDIT,
        # Action Execution permissions (Story 8.5)
        Permission.ACTIONS_VIEW,
        Permission.ACTIONS_EXECUTE,
        Permission.ACTIONS_ROLLBACK,
        Permission.ACTIONS_AUDIT,
    ]),
}


# Roles that can approve/reject action proposals (Story 8.4)
# These roles have Permission.ACTION_PROPOSALS_APPROVE
APPROVER_ROLES: FrozenSet[Role] = frozenset([
    Role.MERCHANT_ADMIN,
    Role.AGENCY_ADMIN,
    Role.ADMIN,
    Role.OWNER,
    Role.SUPER_ADMIN,
])

# Roles that can only view proposals but NOT approve/reject
PROPOSAL_VIEWER_ONLY_ROLES: FrozenSet[Role] = frozenset([
    Role.MERCHANT_VIEWER,
    Role.AGENCY_VIEWER,
    Role.VIEWER,
    Role.EDITOR,
])


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


def get_role_category(role: Role) -> RoleCategory:
    """Get the category for a given role."""
    return ROLE_CATEGORIES.get(role, RoleCategory.PLATFORM)


def is_agency_role(role_name: str) -> bool:
    """Check if a role name is an agency role (multi-tenant access)."""
    try:
        role = Role(role_name.lower())
        return ROLE_CATEGORIES.get(role) == RoleCategory.AGENCY
    except ValueError:
        return False


def is_merchant_role(role_name: str) -> bool:
    """Check if a role name is a merchant role (single tenant access)."""
    try:
        role = Role(role_name.lower())
        return ROLE_CATEGORIES.get(role) == RoleCategory.MERCHANT
    except ValueError:
        return False


def has_multi_tenant_access(roles: list[str]) -> bool:
    """
    Check if any of the given roles has multi-tenant access.

    Agency roles and super_admin have multi-tenant access via allowed_tenants[].
    """
    for role_name in roles:
        try:
            role = Role(role_name.lower())
            if Permission.MULTI_TENANT_ACCESS in ROLE_PERMISSIONS.get(role, frozenset()):
                return True
        except ValueError:
            continue
    return False


def get_primary_role_category(roles: list[str]) -> RoleCategory:
    """
    Determine the primary role category for a list of roles.

    Priority: AGENCY > MERCHANT > PLATFORM (to ensure multi-tenant access is respected)
    """
    has_agency = False
    has_merchant = False

    for role_name in roles:
        try:
            role = Role(role_name.lower())
            category = ROLE_CATEGORIES.get(role, RoleCategory.PLATFORM)
            if category == RoleCategory.AGENCY:
                has_agency = True
            elif category == RoleCategory.MERCHANT:
                has_merchant = True
        except ValueError:
            continue

    if has_agency:
        return RoleCategory.AGENCY
    if has_merchant:
        return RoleCategory.MERCHANT
    return RoleCategory.PLATFORM


# Billing tier to allowed roles mapping
# Agency access requires paid tier (Growth or Enterprise)
BILLING_TIER_ALLOWED_ROLES = {
    'free': frozenset([
        Role.MERCHANT_ADMIN,
        Role.MERCHANT_VIEWER,
        # Legacy roles
        Role.VIEWER,
        Role.EDITOR,
    ]),
    'growth': frozenset([
        Role.MERCHANT_ADMIN,
        Role.MERCHANT_VIEWER,
        Role.AGENCY_VIEWER,  # Limited agency access
        # Legacy roles
        Role.VIEWER,
        Role.EDITOR,
        Role.OWNER,
    ]),
    'enterprise': frozenset([
        Role.MERCHANT_ADMIN,
        Role.MERCHANT_VIEWER,
        Role.AGENCY_ADMIN,
        Role.AGENCY_VIEWER,
        # Legacy roles
        Role.VIEWER,
        Role.EDITOR,
        Role.OWNER,
        Role.ADMIN,
    ]),
}


def is_role_allowed_for_billing_tier(role_name: str, billing_tier: str) -> bool:
    """
    Check if a role is allowed for a given billing tier.

    Agency roles require paid tiers (Growth or Enterprise).

    Args:
        role_name: The role name to check
        billing_tier: The billing tier ('free', 'growth', 'enterprise')

    Returns:
        True if the role is allowed for the billing tier
    """
    try:
        role = Role(role_name.lower())
    except ValueError:
        return False

    allowed_roles = BILLING_TIER_ALLOWED_ROLES.get(billing_tier.lower(), frozenset())
    return role in allowed_roles


def get_allowed_roles_for_billing_tier(billing_tier: str) -> list[str]:
    """
    Get list of role names allowed for a billing tier.

    Args:
        billing_tier: The billing tier ('free', 'growth', 'enterprise')

    Returns:
        List of allowed role names
    """
    allowed_roles = BILLING_TIER_ALLOWED_ROLES.get(billing_tier.lower(), frozenset())
    return [role.value for role in allowed_roles]


# ============================================================================
# Action Proposal Permission Helpers (Story 8.4)
# ============================================================================


def can_approve_action_proposals(roles: list[str]) -> bool:
    """
    Check if any of the given roles can approve/reject action proposals.

    Args:
        roles: List of role names from JWT

    Returns:
        True if user can approve/reject action proposals
    """
    return roles_have_permission(roles, Permission.ACTION_PROPOSALS_APPROVE)


def can_view_action_proposals(roles: list[str]) -> bool:
    """
    Check if any of the given roles can view action proposals.

    Args:
        roles: List of role names from JWT

    Returns:
        True if user can view action proposals
    """
    return roles_have_permission(roles, Permission.ACTION_PROPOSALS_VIEW)


def can_view_action_proposal_audit(roles: list[str]) -> bool:
    """
    Check if any of the given roles can view action proposal audit trail.

    Args:
        roles: List of role names from JWT

    Returns:
        True if user can view audit trail
    """
    return roles_have_permission(roles, Permission.ACTION_PROPOSALS_AUDIT)


def is_approver_role(role_name: str) -> bool:
    """
    Check if a role name is an approver role.

    Args:
        role_name: The role name to check

    Returns:
        True if the role can approve action proposals
    """
    try:
        role = Role(role_name.lower())
        return role in APPROVER_ROLES
    except ValueError:
        return False


def get_primary_approver_role(roles: list[str]) -> str | None:
    """
    Get the primary approver role from a list of roles.

    Useful for audit logging to capture which role was used for approval.

    Args:
        roles: List of role names from JWT

    Returns:
        The first approver role found, or None if no approver role
    """
    for role_name in roles:
        try:
            role = Role(role_name.lower())
            if role in APPROVER_ROLES:
                return role.value
        except ValueError:
            continue
    return None


# ============================================================================
# Action Execution Permission Helpers (Story 8.5)
# ============================================================================


def can_view_actions(roles: list[str]) -> bool:
    """
    Check if any of the given roles can view actions.

    Args:
        roles: List of role names from JWT

    Returns:
        True if user can view actions
    """
    return roles_have_permission(roles, Permission.ACTIONS_VIEW)


def can_execute_actions(roles: list[str]) -> bool:
    """
    Check if any of the given roles can execute actions.

    Args:
        roles: List of role names from JWT

    Returns:
        True if user can execute actions
    """
    return roles_have_permission(roles, Permission.ACTIONS_EXECUTE)


def can_rollback_actions(roles: list[str]) -> bool:
    """
    Check if any of the given roles can rollback actions.

    Args:
        roles: List of role names from JWT

    Returns:
        True if user can rollback actions
    """
    return roles_have_permission(roles, Permission.ACTIONS_ROLLBACK)


def can_view_action_audit(roles: list[str]) -> bool:
    """
    Check if any of the given roles can view action execution audit logs.

    Args:
        roles: List of role names from JWT

    Returns:
        True if user can view action audit logs
    """
    return roles_have_permission(roles, Permission.ACTIONS_AUDIT)
