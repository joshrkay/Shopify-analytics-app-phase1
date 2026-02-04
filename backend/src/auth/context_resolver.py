"""
Authentication context resolver for mapping Clerk identity to internal records.

This module provides:
- Mapping clerk_user_id to internal User records
- Building AuthContext with roles, permissions, and tenant access
- Lazy sync for users who haven't been synced via webhook

Data flow:
1. JWT verified by clerk_verifier → claims extracted
2. context_resolver maps clerk_user_id → internal User
3. AuthContext built with user's roles and tenant access
4. AuthContext attached to request for use by route handlers

SECURITY:
- clerk_user_id comes ONLY from verified JWT (never from client input)
- tenant_id is determined from user's roles (never from client input)
- Permissions are computed from roles in the permissions matrix
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Set, FrozenSet

from sqlalchemy.orm import Session

from src.auth.jwt import ExtractedClaims, extract_claims
from src.models.user import User
from src.models.tenant import Tenant
from src.models.user_tenant_roles import UserTenantRole
from src.services.clerk_sync_service import ClerkSyncService
from src.constants.permissions import (
    Permission,
    Role,
    get_permissions_for_roles,
    has_multi_tenant_access,
    get_role_category,
    RoleCategory,
)

logger = logging.getLogger(__name__)


@dataclass
class TenantAccess:
    """
    Represents a user's access to a specific tenant.

    Contains:
    - tenant_id: Internal tenant ID
    - tenant_name: Display name
    - roles: Set of role names for this tenant
    - permissions: Computed permissions from roles
    - billing_tier: Tenant's billing tier
    """

    tenant_id: str
    tenant_name: str
    roles: FrozenSet[str]
    permissions: FrozenSet[Permission]
    billing_tier: str
    clerk_org_id: Optional[str] = None
    is_active: bool = True

    def has_permission(self, permission: Permission) -> bool:
        """Check if user has a specific permission for this tenant."""
        return permission in self.permissions

    def has_role(self, role: str) -> bool:
        """Check if user has a specific role for this tenant."""
        return role.lower() in {r.lower() for r in self.roles}


@dataclass
class AuthContext:
    """
    Authentication and authorization context for a request.

    Contains:
    - user: Internal User record (or None for unauthenticated)
    - clerk_user_id: Clerk user ID from JWT
    - session_id: Session ID from JWT
    - tenant_access: Dict of tenant_id -> TenantAccess
    - current_tenant_id: Currently selected tenant (from JWT org_id or default)
    - is_authenticated: Whether request is authenticated

    Usage in route handlers:
        @router.get("/data")
        async def get_data(auth: AuthContext = Depends(get_auth_context)):
            if not auth.is_authenticated:
                raise HTTPException(401, "Authentication required")

            if not auth.has_permission(Permission.ANALYTICS_VIEW):
                raise HTTPException(403, "Permission denied")

            tenant_id = auth.current_tenant_id
            ...
    """

    # Identity
    user: Optional[User]
    clerk_user_id: str
    session_id: Optional[str]

    # Tenant access
    tenant_access: Dict[str, TenantAccess] = field(default_factory=dict)
    current_tenant_id: Optional[str] = None

    # Organization context from JWT
    org_id: Optional[str] = None
    org_role: Optional[str] = None
    org_slug: Optional[str] = None

    # Metadata
    authenticated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_authenticated(self) -> bool:
        """Check if context represents an authenticated user."""
        return self.clerk_user_id is not None and self.user is not None

    @property
    def user_id(self) -> Optional[str]:
        """Get internal user ID."""
        return self.user.id if self.user else None

    @property
    def allowed_tenant_ids(self) -> List[str]:
        """Get list of tenant IDs user has access to."""
        return [
            ta.tenant_id for ta in self.tenant_access.values() if ta.is_active
        ]

    @property
    def current_tenant_access(self) -> Optional[TenantAccess]:
        """Get TenantAccess for current tenant."""
        if self.current_tenant_id:
            return self.tenant_access.get(self.current_tenant_id)
        return None

    @property
    def current_roles(self) -> FrozenSet[str]:
        """Get roles for current tenant."""
        ta = self.current_tenant_access
        return ta.roles if ta else frozenset()

    @property
    def current_permissions(self) -> FrozenSet[Permission]:
        """Get permissions for current tenant."""
        ta = self.current_tenant_access
        return ta.permissions if ta else frozenset()

    @property
    def has_multi_tenant_access(self) -> bool:
        """Check if user has multi-tenant access (agency roles)."""
        return len(self.allowed_tenant_ids) > 1

    def has_permission(self, permission: Permission) -> bool:
        """Check if user has permission for current tenant."""
        return permission in self.current_permissions

    def has_permission_for_tenant(
        self, permission: Permission, tenant_id: str
    ) -> bool:
        """Check if user has permission for a specific tenant."""
        ta = self.tenant_access.get(tenant_id)
        return ta is not None and permission in ta.permissions

    def has_access_to_tenant(self, tenant_id: str) -> bool:
        """Check if user has any access to a tenant."""
        ta = self.tenant_access.get(tenant_id)
        return ta is not None and ta.is_active

    def get_roles_for_tenant(self, tenant_id: str) -> FrozenSet[str]:
        """Get user's roles for a specific tenant."""
        ta = self.tenant_access.get(tenant_id)
        return ta.roles if ta else frozenset()

    def switch_tenant(self, tenant_id: str) -> bool:
        """
        Switch current tenant context.

        Args:
            tenant_id: Tenant ID to switch to

        Returns:
            True if switch successful, False if no access
        """
        if not self.has_access_to_tenant(tenant_id):
            return False
        self.current_tenant_id = tenant_id
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "user_id": self.user_id,
            "clerk_user_id": self.clerk_user_id,
            "session_id": self.session_id,
            "current_tenant_id": self.current_tenant_id,
            "allowed_tenant_ids": self.allowed_tenant_ids,
            "org_id": self.org_id,
            "org_role": self.org_role,
            "is_authenticated": self.is_authenticated,
            "has_multi_tenant_access": self.has_multi_tenant_access,
        }


class AuthContextResolver:
    """
    Resolves authentication context from JWT claims.

    Responsibilities:
    - Map clerk_user_id to internal User record
    - Load user's tenant access and roles
    - Build AuthContext for request handling
    - Handle lazy sync for users not yet in database
    """

    def __init__(self, session: Session):
        """
        Initialize resolver with database session.

        Args:
            session: SQLAlchemy session for database operations
        """
        self.session = session
        self.sync_service = ClerkSyncService(session)

    def resolve(
        self,
        claims: ExtractedClaims,
        lazy_sync: bool = True,
    ) -> AuthContext:
        """
        Resolve AuthContext from JWT claims.

        Args:
            claims: Extracted claims from verified JWT
            lazy_sync: Whether to create user if not exists (default True)

        Returns:
            AuthContext with user's identity and access

        Process:
        1. Look up user by clerk_user_id
        2. If not found and lazy_sync, create minimal user record
        3. Load user's tenant roles
        4. Determine current tenant from JWT org_id or default
        5. Build and return AuthContext
        """
        # 1. Look up user by clerk_user_id
        user = self._get_or_create_user(
            clerk_user_id=claims.clerk_user_id,
            lazy_sync=lazy_sync,
        )

        # 2. Load tenant access
        tenant_access = self._load_tenant_access(user) if user else {}

        # 3. Determine current tenant
        current_tenant_id = self._resolve_current_tenant(
            claims=claims,
            tenant_access=tenant_access,
        )

        # 4. Build AuthContext
        context = AuthContext(
            user=user,
            clerk_user_id=claims.clerk_user_id,
            session_id=claims.session_id,
            tenant_access=tenant_access,
            current_tenant_id=current_tenant_id,
            org_id=claims.org_id,
            org_role=claims.org_role,
            org_slug=claims.org_slug,
        )

        logger.debug(
            "Resolved auth context",
            extra={
                "clerk_user_id": claims.clerk_user_id,
                "user_id": user.id if user else None,
                "current_tenant_id": current_tenant_id,
                "tenant_count": len(tenant_access),
            },
        )

        return context

    def _get_or_create_user(
        self,
        clerk_user_id: str,
        lazy_sync: bool,
    ) -> Optional[User]:
        """
        Get user by clerk_user_id, optionally creating if not exists.

        Args:
            clerk_user_id: Clerk user ID from JWT
            lazy_sync: Whether to create minimal user if not exists

        Returns:
            User record or None if not found and lazy_sync is False
        """
        # Look up existing user
        user = self.sync_service.get_user_by_clerk_id(clerk_user_id)

        if user:
            return user

        if not lazy_sync:
            logger.warning(
                "User not found and lazy_sync disabled",
                extra={"clerk_user_id": clerk_user_id},
            )
            return None

        # Create minimal user record (will be enriched by webhook later)
        logger.info(
            "Creating user via lazy sync",
            extra={"clerk_user_id": clerk_user_id},
        )

        user = self.sync_service.get_or_create_user(
            clerk_user_id=clerk_user_id,
        )
        self.session.flush()

        return user

    def _load_tenant_access(self, user: User) -> Dict[str, TenantAccess]:
        """
        Load user's tenant access from database.

        Args:
            user: User record

        Returns:
            Dict mapping tenant_id to TenantAccess
        """
        if not user:
            return {}

        tenant_access: Dict[str, TenantAccess] = {}

        # Get all active tenant roles for user
        roles = (
            self.session.query(UserTenantRole)
            .filter(
                UserTenantRole.user_id == user.id,
                UserTenantRole.is_active == True,
            )
            .all()
        )

        # Group roles by tenant
        tenant_roles: Dict[str, List[str]] = {}
        for role in roles:
            if role.tenant_id not in tenant_roles:
                tenant_roles[role.tenant_id] = []
            tenant_roles[role.tenant_id].append(role.role)

        # Build TenantAccess for each tenant
        for tenant_id, role_names in tenant_roles.items():
            # Load tenant details
            tenant = (
                self.session.query(Tenant)
                .filter(Tenant.id == tenant_id)
                .first()
            )

            if not tenant or not tenant.is_active:
                continue

            # Compute permissions from roles
            permissions = get_permissions_for_roles(role_names)

            tenant_access[tenant_id] = TenantAccess(
                tenant_id=tenant_id,
                tenant_name=tenant.name,
                roles=frozenset(role_names),
                permissions=frozenset(permissions),
                billing_tier=tenant.billing_tier,
                clerk_org_id=tenant.clerk_org_id,
                is_active=True,
            )

        return tenant_access

    def _resolve_current_tenant(
        self,
        claims: ExtractedClaims,
        tenant_access: Dict[str, TenantAccess],
    ) -> Optional[str]:
        """
        Determine the current tenant from JWT and access.

        Priority:
        1. org_id from JWT (if user has access)
        2. Single tenant (if user has exactly one)
        3. None (user must select)

        Args:
            claims: JWT claims
            tenant_access: User's tenant access map

        Returns:
            Current tenant_id or None
        """
        # 1. Check org_id from JWT
        if claims.org_id:
            # Find tenant by clerk_org_id
            for ta in tenant_access.values():
                if ta.clerk_org_id == claims.org_id:
                    return ta.tenant_id

            logger.warning(
                "JWT org_id doesn't match any accessible tenant",
                extra={
                    "org_id": claims.org_id,
                    "accessible_tenants": list(tenant_access.keys()),
                },
            )

        # 2. Default to single tenant
        active_tenants = [ta for ta in tenant_access.values() if ta.is_active]
        if len(active_tenants) == 1:
            return active_tenants[0].tenant_id

        # 3. No default - user must select
        return None


def resolve_auth_context(
    jwt_claims: Dict[str, Any],
    session: Session,
    lazy_sync: bool = True,
) -> AuthContext:
    """
    Convenience function to resolve auth context from JWT claims.

    Args:
        jwt_claims: Raw claims dict from JWT verification
        session: Database session
        lazy_sync: Whether to create user if not exists

    Returns:
        AuthContext for the request
    """
    claims = extract_claims(jwt_claims)
    resolver = AuthContextResolver(session)
    return resolver.resolve(claims, lazy_sync=lazy_sync)


# Anonymous context for unauthenticated requests
ANONYMOUS_CONTEXT = AuthContext(
    user=None,
    clerk_user_id="",
    session_id=None,
    tenant_access={},
    current_tenant_id=None,
)
