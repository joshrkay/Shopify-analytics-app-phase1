"""
Tenant Members Service for managing tenant access.

This service handles:
- Listing members of a tenant
- Granting user access to a tenant (agency grants)
- Revoking user access from a tenant
- Updating user roles in a tenant
- Getting all tenants a user has access to

Two sources of tenant membership:
1. Clerk webhooks: organizationMembership events (automatic)
2. Agency grants: POST /api/tenants/{id}/members (manual)

Both result in UserTenantRole records for unified access control.
"""

import logging
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.models.tenant import Tenant, TenantStatus
from src.models.user import User
from src.models.user_tenant_roles import UserTenantRole
from src.services.clerk_sync_service import ClerkSyncService
from src.constants.permissions import Role

logger = logging.getLogger(__name__)


class TenantMembersServiceError(Exception):
    """Base exception for tenant members service errors."""
    pass


class TenantNotFoundError(TenantMembersServiceError):
    """Raised when tenant is not found."""
    pass


class UserNotFoundError(TenantMembersServiceError):
    """Raised when user is not found."""
    pass


class DuplicateRoleError(TenantMembersServiceError):
    """Raised when trying to assign duplicate role."""
    pass


class PermissionDeniedError(TenantMembersServiceError):
    """Raised when user doesn't have permission."""
    pass


class LastAdminError(TenantMembersServiceError):
    """Raised when trying to remove last admin."""
    pass


class TenantMembersService:
    """
    Service for managing tenant membership and access.

    Handles granting, revoking, and updating user access to tenants.
    Used by agency admins to give their team access to client tenants.
    """

    # Roles that can manage team members
    ADMIN_ROLES = {"MERCHANT_ADMIN", "AGENCY_ADMIN", "ADMIN", "OWNER", "SUPER_ADMIN"}

    def __init__(self, session: Session):
        """
        Initialize service with database session.

        Args:
            session: SQLAlchemy session for database operations
        """
        self.session = session
        self.clerk_sync = ClerkSyncService(session)

    def list_members(
        self,
        tenant_id: str,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        List all members of a tenant.

        Args:
            tenant_id: Tenant ID to list members for
            include_inactive: Include deactivated memberships

        Returns:
            List of member details with user info and role

        Raises:
            TenantNotFoundError: If tenant doesn't exist
        """
        tenant = self._get_tenant(tenant_id)

        query = self.session.query(UserTenantRole).filter(
            UserTenantRole.tenant_id == tenant.id
        )

        if not include_inactive:
            query = query.filter(UserTenantRole.is_active == True)

        roles = query.all()

        members = []
        for role in roles:
            user = role.user
            members.append({
                "id": role.id,
                "user_id": user.id,
                "clerk_user_id": user.clerk_user_id,
                "email": user.email,
                "name": user.full_name,
                "avatar_url": user.avatar_url,
                "role": role.role,
                "assigned_by": role.assigned_by,
                "assigned_at": role.assigned_at.isoformat() if role.assigned_at else None,
                "source": role.source,
                "is_active": role.is_active,
            })

        logger.info(
            "Listed tenant members",
            extra={"tenant_id": tenant_id, "count": len(members)}
        )

        return members

    def grant_access(
        self,
        tenant_id: str,
        clerk_user_id: Optional[str] = None,
        email: Optional[str] = None,
        role: str = "MERCHANT_VIEWER",
        granted_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Grant a user access to a tenant.

        Used by agency admins to give team members access to client tenants.
        If user doesn't exist locally, creates via lazy sync.

        Args:
            tenant_id: Tenant to grant access to
            clerk_user_id: Clerk user ID (preferred)
            email: User email (fallback lookup)
            role: Role to assign (from Role enum)
            granted_by: clerk_user_id of user granting access

        Returns:
            Dict with role assignment details

        Raises:
            TenantNotFoundError: If tenant doesn't exist
            UserNotFoundError: If user can't be found or created
            DuplicateRoleError: If role already exists
            ValueError: If neither clerk_user_id nor email provided
        """
        if not clerk_user_id and not email:
            raise ValueError("Either clerk_user_id or email must be provided")

        tenant = self._get_tenant(tenant_id)

        # Get or create user
        user = self._get_or_create_user(clerk_user_id, email)

        # Validate role
        validated_role = self._validate_role(role)

        # Check for existing role
        existing = self.session.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.tenant_id == tenant.id,
            UserTenantRole.role == validated_role,
        ).first()

        if existing:
            if existing.is_active:
                raise DuplicateRoleError(
                    f"User already has role {validated_role} in tenant"
                )
            else:
                # Reactivate existing role
                existing.is_active = True
                existing.assigned_by = granted_by
                self.session.flush()

                logger.info(
                    "Reactivated tenant access",
                    extra={
                        "user_id": user.id,
                        "tenant_id": tenant.id,
                        "role": validated_role,
                    }
                )

                return self._role_to_dict(existing)

        # Create new role assignment
        user_role = UserTenantRole.create_from_grant(
            user_id=user.id,
            tenant_id=tenant.id,
            role=validated_role,
            granted_by=granted_by,
        )
        self.session.add(user_role)
        self.session.flush()

        logger.info(
            "Granted tenant access",
            extra={
                "user_id": user.id,
                "tenant_id": tenant.id,
                "role": validated_role,
                "granted_by": granted_by,
            }
        )

        return self._role_to_dict(user_role)

    def revoke_access(
        self,
        tenant_id: str,
        user_id: str,
        revoked_by: Optional[str] = None,
        grace_period_hours: Optional[int] = None,
    ) -> bool:
        """
        Revoke a user's access to a tenant with grace period.

        Instead of immediately deactivating roles, initiates a grace-period
        revocation. Roles remain active during the grace period; a worker
        job enforces actual deactivation after the grace period ends.

        Args:
            tenant_id: Tenant ID
            user_id: User ID to revoke access from
            revoked_by: clerk_user_id of user revoking access
            grace_period_hours: Override default grace period (env var or 24h)

        Returns:
            True if revocation was initiated

        Raises:
            TenantNotFoundError: If tenant doesn't exist
            UserNotFoundError: If user doesn't exist
            LastAdminError: If user is the last admin
        """
        tenant = self._get_tenant(tenant_id)
        user = self._get_user_by_id(user_id)

        # Get all active roles for this user-tenant pair
        roles = self.session.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.tenant_id == tenant.id,
            UserTenantRole.is_active == True,
        ).all()

        if not roles:
            return False

        # Check if this would remove the last admin
        if self._is_last_admin(tenant.id, user.id):
            raise LastAdminError("Cannot remove the last admin from tenant")

        # Initiate grace-period revocation (Story 5.5.4)
        try:
            from src.services.access_revocation_service import AccessRevocationService

            revocation_service = AccessRevocationService(self.session)
            kwargs = {
                "user_id": user.id,
                "tenant_id": tenant.id,
                "revoked_by": revoked_by,
            }
            if grace_period_hours is not None:
                kwargs["grace_period_hours"] = grace_period_hours
            revocation_service.initiate_revocation(**kwargs)
        except ImportError:
            # Fallback: immediate deactivation if revocation service not available
            for role in roles:
                role.is_active = False

        logger.info(
            "Revoked tenant access (grace period)",
            extra={
                "user_id": user.id,
                "tenant_id": tenant.id,
                "roles_count": len(roles),
                "revoked_by": revoked_by,
            }
        )

        return True

    def update_role(
        self,
        tenant_id: str,
        user_id: str,
        new_role: str,
        updated_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update a user's role in a tenant.

        Args:
            tenant_id: Tenant ID
            user_id: User ID to update
            new_role: New role to assign
            updated_by: clerk_user_id of user making the update

        Returns:
            Dict with updated role details

        Raises:
            TenantNotFoundError: If tenant doesn't exist
            UserNotFoundError: If user doesn't exist
            LastAdminError: If downgrading the last admin
        """
        tenant = self._get_tenant(tenant_id)
        user = self._get_user_by_id(user_id)
        validated_role = self._validate_role(new_role)

        # Get current active roles
        current_roles = self.session.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.tenant_id == tenant.id,
            UserTenantRole.is_active == True,
        ).all()

        # Check if downgrading from admin and is last admin
        current_is_admin = any(r.role in self.ADMIN_ROLES for r in current_roles)
        new_is_admin = validated_role in self.ADMIN_ROLES

        if current_is_admin and not new_is_admin:
            if self._is_last_admin(tenant.id, user.id):
                raise LastAdminError("Cannot downgrade the last admin")

        # Deactivate all current roles
        for role in current_roles:
            role.is_active = False

        # Create or reactivate new role
        existing_new_role = self.session.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.tenant_id == tenant.id,
            UserTenantRole.role == validated_role,
        ).first()

        if existing_new_role:
            existing_new_role.is_active = True
            existing_new_role.assigned_by = updated_by
            self.session.flush()
            return self._role_to_dict(existing_new_role)

        # Create new role
        new_user_role = UserTenantRole.create_from_grant(
            user_id=user.id,
            tenant_id=tenant.id,
            role=validated_role,
            granted_by=updated_by,
        )
        self.session.add(new_user_role)
        self.session.flush()

        logger.info(
            "Updated tenant role",
            extra={
                "user_id": user.id,
                "tenant_id": tenant.id,
                "new_role": validated_role,
                "updated_by": updated_by,
            }
        )

        return self._role_to_dict(new_user_role)

    def get_user_tenants(
        self,
        clerk_user_id: str,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Get all tenants a user has access to.

        Used for building the store selector and validating tenant access.

        Args:
            clerk_user_id: Clerk user ID
            include_inactive: Include deactivated tenants/roles

        Returns:
            List of tenant details with role information
        """
        user = self.clerk_sync.get_user_by_clerk_id(clerk_user_id)
        if not user:
            return []

        query = self.session.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id
        )

        if not include_inactive:
            query = query.filter(UserTenantRole.is_active == True)

        roles = query.all()

        tenants = []
        seen_tenant_ids = set()

        for role in roles:
            tenant = role.tenant

            # Skip inactive tenants unless requested
            if not include_inactive and tenant.status != TenantStatus.ACTIVE:
                continue

            # Handle multiple roles in same tenant
            if tenant.id in seen_tenant_ids:
                # Find existing and add role
                for t in tenants:
                    if t["id"] == tenant.id:
                        if role.role not in t["roles"]:
                            t["roles"].append(role.role)
                        break
                continue

            seen_tenant_ids.add(tenant.id)
            tenants.append({
                "id": tenant.id,
                "name": tenant.name,
                "slug": tenant.slug,
                "billing_tier": tenant.billing_tier,
                "status": tenant.status.value if hasattr(tenant.status, 'value') else str(tenant.status),
                "roles": [role.role],
                "is_admin": role.role in self.ADMIN_ROLES,
            })

        logger.info(
            "Got user tenants",
            extra={"clerk_user_id": clerk_user_id, "tenant_count": len(tenants)}
        )

        return tenants

    def check_user_has_access(
        self,
        clerk_user_id: str,
        tenant_id: str,
        required_role: Optional[str] = None,
    ) -> bool:
        """
        Check if user has access to a tenant.

        Args:
            clerk_user_id: Clerk user ID
            tenant_id: Tenant ID to check access for
            required_role: Optional specific role required

        Returns:
            True if user has access (with required role if specified)
        """
        user = self.clerk_sync.get_user_by_clerk_id(clerk_user_id)
        if not user:
            return False

        query = self.session.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.tenant_id == tenant_id,
            UserTenantRole.is_active == True,
        )

        if required_role:
            validated_role = self._validate_role(required_role)
            query = query.filter(UserTenantRole.role == validated_role)

        return query.first() is not None

    def check_user_is_admin(self, clerk_user_id: str, tenant_id: str) -> bool:
        """
        Check if user has admin role in a tenant.

        Args:
            clerk_user_id: Clerk user ID
            tenant_id: Tenant ID

        Returns:
            True if user has an admin role
        """
        user = self.clerk_sync.get_user_by_clerk_id(clerk_user_id)
        if not user:
            return False

        role = self.session.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.tenant_id == tenant_id,
            UserTenantRole.is_active == True,
            UserTenantRole.role.in_(self.ADMIN_ROLES),
        ).first()

        return role is not None

    # =========================================================================
    # Private Helper Methods
    # =========================================================================

    def _get_tenant(self, tenant_id: str) -> Tenant:
        """Get tenant by ID or raise error."""
        tenant = self.session.query(Tenant).filter(
            Tenant.id == tenant_id
        ).first()

        if not tenant:
            raise TenantNotFoundError(f"Tenant not found: {tenant_id}")

        return tenant

    def _get_user_by_id(self, user_id: str) -> User:
        """Get user by internal ID or raise error."""
        user = self.session.query(User).filter(User.id == user_id).first()

        if not user:
            raise UserNotFoundError(f"User not found: {user_id}")

        return user

    def _get_or_create_user(
        self,
        clerk_user_id: Optional[str],
        email: Optional[str],
    ) -> User:
        """
        Get or create user by clerk_user_id or email.

        Args:
            clerk_user_id: Clerk user ID
            email: User email

        Returns:
            User instance

        Raises:
            UserNotFoundError: If user can't be found and no clerk_user_id
        """
        user = None

        if clerk_user_id:
            user = self.clerk_sync.get_user_by_clerk_id(clerk_user_id)
            if not user:
                # Create user with minimal data (webhook should provide more)
                user = self.clerk_sync.sync_user(
                    clerk_user_id=clerk_user_id,
                    email=email,
                )
                self.session.flush()
        elif email:
            user = self.clerk_sync.get_user_by_email(email)

        if not user:
            raise UserNotFoundError(
                f"User not found: clerk_id={clerk_user_id}, email={email}"
            )

        return user

    def _validate_role(self, role: str) -> str:
        """
        Validate and normalize role string.

        Args:
            role: Role string to validate

        Returns:
            Uppercase normalized role

        Raises:
            ValueError: If role is invalid
        """
        normalized = role.upper().replace("-", "_")

        # Check against Role enum
        valid_roles = {r.value if hasattr(r, 'value') else str(r) for r in Role}

        if normalized not in valid_roles:
            # Also allow the string versions
            string_roles = {
                "MERCHANT_ADMIN", "MERCHANT_VIEWER",
                "AGENCY_ADMIN", "AGENCY_VIEWER",
                "ADMIN", "OWNER", "EDITOR", "VIEWER",
                "SUPER_ADMIN",
            }
            if normalized not in string_roles:
                raise ValueError(f"Invalid role: {role}")

        return normalized

    def _is_last_admin(self, tenant_id: str, user_id: str) -> bool:
        """
        Check if user is the last admin of a tenant.

        Args:
            tenant_id: Tenant ID
            user_id: User ID to check

        Returns:
            True if this is the last admin
        """
        # Count active admins excluding this user
        other_admin_count = self.session.query(UserTenantRole).filter(
            UserTenantRole.tenant_id == tenant_id,
            UserTenantRole.user_id != user_id,
            UserTenantRole.is_active == True,
            UserTenantRole.role.in_(self.ADMIN_ROLES),
        ).count()

        return other_admin_count == 0

    def _role_to_dict(self, role: UserTenantRole) -> Dict[str, Any]:
        """Convert UserTenantRole to dict response."""
        return {
            "id": role.id,
            "user_id": role.user_id,
            "tenant_id": role.tenant_id,
            "role": role.role,
            "assigned_by": role.assigned_by,
            "assigned_at": role.assigned_at.isoformat() if role.assigned_at else None,
            "source": role.source,
            "is_active": role.is_active,
        }
