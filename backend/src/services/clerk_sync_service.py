"""
Clerk Sync Service for synchronizing identity data from Clerk.

This service handles:
- User sync: Create/update local User records from Clerk data
- Organization sync: Create/update local Organization records
- Tenant sync: Create Tenant records for Clerk Organizations
- Membership sync: Create/update UserTenantRole records

Data flows:
1. Clerk webhooks → clerk_webhook_handler → clerk_sync_service → database
2. Lazy sync (JWT auth) → clerk_sync_service.get_or_create_user → database

SECURITY:
- Clerk is source of truth for authentication
- Local database stores authorization and relationships
- NO passwords stored locally
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.models.organization import Organization
from src.models.tenant import Tenant, TenantStatus
from src.models.user import User
from src.models.user_tenant_roles import UserTenantRole

logger = logging.getLogger(__name__)


class ClerkSyncService:
    """
    Service for syncing Clerk identity data to local database.

    Handles user, organization, tenant, and membership synchronization.
    Used by webhook handlers and lazy sync in auth middleware.
    """

    def __init__(self, session: Session):
        """
        Initialize sync service with database session.

        Args:
            session: SQLAlchemy session for database operations
        """
        self.session = session

    # =========================================================================
    # User Sync Methods
    # =========================================================================

    def sync_user(
        self,
        clerk_user_id: str,
        email: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        avatar_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> User:
        """
        Create or update a User from Clerk data.

        Args:
            clerk_user_id: Clerk user ID (unique identifier)
            email: User email address
            first_name: User first name
            last_name: User last name
            avatar_url: Profile image URL
            metadata: Additional metadata from Clerk

        Returns:
            Created or updated User instance
        """
        user = self.session.query(User).filter(
            User.clerk_user_id == clerk_user_id
        ).first()

        if user:
            # Update existing user
            if email is not None:
                user.email = email
            if first_name is not None:
                user.first_name = first_name
            if last_name is not None:
                user.last_name = last_name
            if avatar_url is not None:
                user.avatar_url = avatar_url
            if metadata is not None:
                user.extra_metadata = metadata
            user.mark_synced()

            logger.info(
                "Updated user from Clerk",
                extra={"clerk_user_id": clerk_user_id, "email": email}
            )
        else:
            # Create new user
            user = User(
                clerk_user_id=clerk_user_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
                avatar_url=avatar_url,
                extra_metadata=metadata,
                is_active=True,
                last_synced_at=datetime.now(timezone.utc),
            )
            self.session.add(user)

            logger.info(
                "Created user from Clerk",
                extra={"clerk_user_id": clerk_user_id, "email": email}
            )

        return user

    def get_or_create_user(
        self,
        clerk_user_id: str,
        email: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> User:
        """
        Get existing user or create from Clerk data.

        Used by lazy sync in auth middleware when webhook was missed.

        Args:
            clerk_user_id: Clerk user ID
            email: User email (optional)
            first_name: User first name (optional)
            last_name: User last name (optional)

        Returns:
            Existing or newly created User
        """
        user = self.session.query(User).filter(
            User.clerk_user_id == clerk_user_id
        ).first()

        if user:
            return user

        return self.sync_user(
            clerk_user_id=clerk_user_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )

    def get_user_by_clerk_id(self, clerk_user_id: str) -> Optional[User]:
        """
        Get user by Clerk user ID.

        Args:
            clerk_user_id: Clerk user ID

        Returns:
            User if found, None otherwise
        """
        return self.session.query(User).filter(
            User.clerk_user_id == clerk_user_id
        ).first()

    def get_user_by_email(self, email: str) -> Optional[User]:
        """
        Get user by email address.

        Args:
            email: User email address

        Returns:
            User if found, None otherwise
        """
        return self.session.query(User).filter(
            User.email == email
        ).first()

    def deactivate_user(self, clerk_user_id: str) -> bool:
        """
        Deactivate a user (soft delete).

        Called when user.deleted webhook is received.

        Args:
            clerk_user_id: Clerk user ID

        Returns:
            True if user was deactivated, False if not found
        """
        user = self.get_user_by_clerk_id(clerk_user_id)
        if not user:
            logger.warning(
                "Cannot deactivate user: not found",
                extra={"clerk_user_id": clerk_user_id}
            )
            return False

        user.is_active = False
        user.mark_synced()

        # Also deactivate all tenant role assignments
        for role in user.tenant_roles.all():
            role.is_active = False

        logger.info(
            "Deactivated user",
            extra={"clerk_user_id": clerk_user_id, "user_id": user.id}
        )
        return True

    # =========================================================================
    # Organization Sync Methods
    # =========================================================================

    def sync_organization(
        self,
        clerk_org_id: str,
        name: str,
        slug: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Organization:
        """
        Create or update an Organization from Clerk data.

        Args:
            clerk_org_id: Clerk organization ID
            name: Organization name
            slug: URL-friendly identifier
            settings: Organization settings

        Returns:
            Created or updated Organization
        """
        org = self.session.query(Organization).filter(
            Organization.clerk_org_id == clerk_org_id
        ).first()

        if org:
            # Update existing organization
            org.name = name
            if slug is not None:
                org.slug = slug
            if settings is not None:
                org.settings = settings

            logger.info(
                "Updated organization from Clerk",
                extra={"clerk_org_id": clerk_org_id, "name": name}
            )
        else:
            # Create new organization
            org = Organization(
                clerk_org_id=clerk_org_id,
                name=name,
                slug=slug,
                settings=settings,
                is_active=True,
            )
            self.session.add(org)

            logger.info(
                "Created organization from Clerk",
                extra={"clerk_org_id": clerk_org_id, "name": name}
            )

        return org

    def deactivate_organization(self, clerk_org_id: str) -> bool:
        """
        Deactivate an organization.

        Args:
            clerk_org_id: Clerk organization ID

        Returns:
            True if deactivated, False if not found
        """
        org = self.session.query(Organization).filter(
            Organization.clerk_org_id == clerk_org_id
        ).first()

        if not org:
            logger.warning(
                "Cannot deactivate organization: not found",
                extra={"clerk_org_id": clerk_org_id}
            )
            return False

        org.is_active = False

        logger.info(
            "Deactivated organization",
            extra={"clerk_org_id": clerk_org_id, "org_id": org.id}
        )
        return True

    # =========================================================================
    # Tenant Sync Methods
    # =========================================================================

    def sync_tenant_from_org(
        self,
        clerk_org_id: str,
        name: str,
        slug: Optional[str] = None,
        billing_tier: str = "free",
        organization_id: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Tenant:
        """
        Create or update a Tenant from Clerk Organization data.

        When a Clerk Organization is created, we create a corresponding Tenant.
        The Tenant.id becomes the tenant_id used across the application.

        Args:
            clerk_org_id: Clerk organization ID
            name: Tenant name
            slug: URL-friendly identifier
            billing_tier: Billing tier (free, growth, enterprise)
            organization_id: Optional parent Organization ID
            settings: Tenant settings

        Returns:
            Created or updated Tenant
        """
        tenant = self.session.query(Tenant).filter(
            Tenant.clerk_org_id == clerk_org_id
        ).first()

        if tenant:
            # Update existing tenant
            tenant.name = name
            if slug is not None:
                tenant.slug = slug
            if billing_tier is not None:
                tenant.billing_tier = billing_tier
            if settings is not None:
                tenant.settings = settings

            logger.info(
                "Updated tenant from Clerk org",
                extra={"clerk_org_id": clerk_org_id, "tenant_id": tenant.id}
            )
        else:
            # Create new tenant
            tenant = Tenant(
                clerk_org_id=clerk_org_id,
                name=name,
                slug=slug,
                billing_tier=billing_tier,
                organization_id=organization_id,
                settings=settings,
                status=TenantStatus.ACTIVE,
            )
            self.session.add(tenant)

            logger.info(
                "Created tenant from Clerk org",
                extra={"clerk_org_id": clerk_org_id, "name": name}
            )

        return tenant

    def get_tenant_by_clerk_org_id(self, clerk_org_id: str) -> Optional[Tenant]:
        """
        Get tenant by Clerk organization ID.

        Args:
            clerk_org_id: Clerk organization ID

        Returns:
            Tenant if found, None otherwise
        """
        return self.session.query(Tenant).filter(
            Tenant.clerk_org_id == clerk_org_id
        ).first()

    def deactivate_tenant(self, clerk_org_id: str) -> bool:
        """
        Deactivate a tenant.

        Args:
            clerk_org_id: Clerk organization ID

        Returns:
            True if deactivated, False if not found
        """
        tenant = self.get_tenant_by_clerk_org_id(clerk_org_id)
        if not tenant:
            logger.warning(
                "Cannot deactivate tenant: not found",
                extra={"clerk_org_id": clerk_org_id}
            )
            return False

        tenant.status = TenantStatus.DEACTIVATED

        logger.info(
            "Deactivated tenant",
            extra={"clerk_org_id": clerk_org_id, "tenant_id": tenant.id}
        )
        return True

    # =========================================================================
    # Membership Sync Methods
    # =========================================================================

    def sync_membership(
        self,
        clerk_user_id: str,
        clerk_org_id: str,
        role: str,
    ) -> Optional[UserTenantRole]:
        """
        Create or update a user's membership in a tenant.

        Called when organizationMembership webhook is received.

        Args:
            clerk_user_id: Clerk user ID
            clerk_org_id: Clerk organization ID
            role: Role name (will be mapped to application role)

        Returns:
            Created or updated UserTenantRole, None if user/tenant not found
        """
        # Get user
        user = self.get_user_by_clerk_id(clerk_user_id)
        if not user:
            logger.warning(
                "Cannot sync membership: user not found",
                extra={"clerk_user_id": clerk_user_id, "clerk_org_id": clerk_org_id}
            )
            return None

        # Get tenant
        tenant = self.get_tenant_by_clerk_org_id(clerk_org_id)
        if not tenant:
            logger.warning(
                "Cannot sync membership: tenant not found",
                extra={"clerk_user_id": clerk_user_id, "clerk_org_id": clerk_org_id}
            )
            return None

        # Map Clerk role to application role
        app_role = self._map_clerk_role(role)

        # Check for existing role
        existing_role = self.session.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.tenant_id == tenant.id,
            UserTenantRole.role == app_role,
        ).first()

        if existing_role:
            # Reactivate if previously deactivated
            existing_role.is_active = True
            logger.info(
                "Reactivated membership",
                extra={
                    "user_id": user.id,
                    "tenant_id": tenant.id,
                    "role": app_role,
                }
            )
            return existing_role

        # Create new role assignment
        user_role = UserTenantRole.create_from_clerk(
            user_id=user.id,
            tenant_id=tenant.id,
            role=app_role,
        )
        self.session.add(user_role)

        logger.info(
            "Created membership from Clerk",
            extra={
                "clerk_user_id": clerk_user_id,
                "clerk_org_id": clerk_org_id,
                "role": app_role,
            }
        )
        return user_role

    def remove_membership(
        self,
        clerk_user_id: str,
        clerk_org_id: str,
    ) -> bool:
        """
        Remove a user's membership from a tenant.

        Deactivates all role assignments for the user in that tenant.

        Args:
            clerk_user_id: Clerk user ID
            clerk_org_id: Clerk organization ID

        Returns:
            True if membership removed, False if not found
        """
        user = self.get_user_by_clerk_id(clerk_user_id)
        if not user:
            return False

        tenant = self.get_tenant_by_clerk_org_id(clerk_org_id)
        if not tenant:
            return False

        # Deactivate all roles for this user-tenant pair
        roles = self.session.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.tenant_id == tenant.id,
        ).all()

        if not roles:
            return False

        for role in roles:
            role.is_active = False

        logger.info(
            "Removed membership",
            extra={
                "clerk_user_id": clerk_user_id,
                "clerk_org_id": clerk_org_id,
                "roles_deactivated": len(roles),
            }
        )
        return True

    def update_membership_role(
        self,
        clerk_user_id: str,
        clerk_org_id: str,
        old_role: str,
        new_role: str,
    ) -> Optional[UserTenantRole]:
        """
        Update a user's role in a tenant.

        Args:
            clerk_user_id: Clerk user ID
            clerk_org_id: Clerk organization ID
            old_role: Previous role
            new_role: New role

        Returns:
            Updated UserTenantRole, None if not found
        """
        user = self.get_user_by_clerk_id(clerk_user_id)
        if not user:
            return None

        tenant = self.get_tenant_by_clerk_org_id(clerk_org_id)
        if not tenant:
            return None

        old_app_role = self._map_clerk_role(old_role)
        new_app_role = self._map_clerk_role(new_role)

        # Find existing role
        existing = self.session.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.tenant_id == tenant.id,
            UserTenantRole.role == old_app_role,
        ).first()

        if existing:
            # Deactivate old role
            existing.is_active = False

        # Create or reactivate new role
        return self.sync_membership(clerk_user_id, clerk_org_id, new_role)

    def get_user_tenants(self, clerk_user_id: str) -> List[Tenant]:
        """
        Get all tenants a user has access to.

        Args:
            clerk_user_id: Clerk user ID

        Returns:
            List of Tenants the user has active access to
        """
        user = self.get_user_by_clerk_id(clerk_user_id)
        if not user:
            return []

        return user.get_tenants()

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _map_clerk_role(self, clerk_role: str) -> str:
        """
        Map Clerk organization role to application role.

        Clerk roles: org:admin, org:member, org:billing, etc.
        App roles: MERCHANT_ADMIN, MERCHANT_VIEWER, AGENCY_ADMIN, etc.

        Args:
            clerk_role: Clerk role string

        Returns:
            Mapped application role string
        """
        # Remove 'org:' prefix if present
        role = clerk_role.replace("org:", "").lower()

        role_mapping = {
            "admin": "MERCHANT_ADMIN",
            "owner": "MERCHANT_ADMIN",
            "member": "MERCHANT_VIEWER",
            "viewer": "MERCHANT_VIEWER",
            "billing": "MERCHANT_VIEWER",
        }

        return role_mapping.get(role, "MERCHANT_VIEWER")
