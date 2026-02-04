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
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.platform.audit import (
    AuditAction,
    AuditEvent,
    AuditOutcome,
    write_audit_log_sync,
)
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

    Also emits identity audit events for compliance tracking:
    - identity.user_first_seen: First time a Clerk user is seen
    - identity.user_linked_to_tenant: User membership created
    - identity.role_assigned: Role granted to a user
    - identity.role_revoked: Role removed from a user
    - identity.tenant_created: New tenant created
    - identity.tenant_deactivated: Tenant deactivated
    """

    # Valid sources for user events
    _SOURCES_USER = frozenset({"webhook", "lazy_sync"})
    # Valid sources for role events
    _SOURCES_ROLE = frozenset({"clerk_webhook", "agency_grant", "admin_grant"})
    # Valid sources for tenant events
    _SOURCES_TENANT = frozenset({"clerk_webhook", "admin_action"})
    # Valid reasons for role revocation
    _REASONS_REVOKE = frozenset({"membership_deleted", "admin_action", "user_deleted"})
    # Valid reasons for tenant deactivation
    _REASONS_DEACTIVATE = frozenset({"org_deleted", "admin_action", "billing"})

    def __init__(self, session: Session, correlation_id: Optional[str] = None):
        """
        Initialize sync service with database session.

        Args:
            session: SQLAlchemy session for database operations
            correlation_id: Optional correlation ID for audit event tracing
        """
        self.session = session
        self.correlation_id = correlation_id or str(uuid.uuid4())

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
        source: str = "webhook",
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
            source: How the user was synced ("webhook" or "lazy_sync")

        Returns:
            Created or updated User instance
        """
        user = self.session.query(User).filter(
            User.clerk_user_id == clerk_user_id
        ).first()

        is_new_user = user is None

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

        # Emit audit event for new users only
        if is_new_user:
            self._emit_user_first_seen(
                clerk_user_id=clerk_user_id,
                source=source,
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
            source="lazy_sync",
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
        source: str = "clerk_webhook",
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
            source: How the tenant was created ("clerk_webhook" or "admin_action")

        Returns:
            Created or updated Tenant
        """
        tenant = self.session.query(Tenant).filter(
            Tenant.clerk_org_id == clerk_org_id
        ).first()

        is_new_tenant = tenant is None

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
            # Flush to get the tenant.id for audit event
            self.session.flush()

            logger.info(
                "Created tenant from Clerk org",
                extra={"clerk_org_id": clerk_org_id, "name": name}
            )

        # Emit audit event for new tenants only
        if is_new_tenant:
            self._emit_tenant_created(
                tenant_id=tenant.id,
                clerk_org_id=clerk_org_id,
                billing_tier=billing_tier,
                source=source,
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

    def deactivate_tenant(
        self,
        clerk_org_id: str,
        reason: str = "org_deleted",
    ) -> bool:
        """
        Deactivate a tenant.

        Args:
            clerk_org_id: Clerk organization ID
            reason: Why the tenant was deactivated ("org_deleted", "admin_action", "billing")

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

        # Emit audit event for tenant deactivation
        self._emit_tenant_deactivated(
            tenant_id=tenant.id,
            clerk_org_id=clerk_org_id,
            reason=reason,
        )

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
        source: str = "clerk_webhook",
        assigned_by: str = "system",
    ) -> Optional[UserTenantRole]:
        """
        Create or update a user's membership in a tenant.

        Called when organizationMembership webhook is received.

        Args:
            clerk_user_id: Clerk user ID
            clerk_org_id: Clerk organization ID
            role: Role name (will be mapped to application role)
            source: How the membership was created ("clerk_webhook", "agency_grant", "admin_grant")
            assigned_by: clerk_user_id of assigner, or "system" for automated

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

        is_new_membership = existing_role is None
        was_reactivated = existing_role is not None and not existing_role.is_active

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

            # Emit role_assigned for reactivation
            if was_reactivated:
                self._emit_role_assigned(
                    clerk_user_id=clerk_user_id,
                    tenant_id=tenant.id,
                    role=app_role,
                    assigned_by=assigned_by,
                    source=source,
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

        # Emit audit events for new membership
        if is_new_membership:
            # Emit user_linked_to_tenant
            self._emit_user_linked_to_tenant(
                clerk_user_id=clerk_user_id,
                tenant_id=tenant.id,
                role=app_role,
                source=source,
            )
            # Emit role_assigned
            self._emit_role_assigned(
                clerk_user_id=clerk_user_id,
                tenant_id=tenant.id,
                role=app_role,
                assigned_by=assigned_by,
                source=source,
            )

        return user_role

    def remove_membership(
        self,
        clerk_user_id: str,
        clerk_org_id: str,
        reason: str = "membership_deleted",
        revoked_by: str = "system",
    ) -> bool:
        """
        Remove a user's membership from a tenant.

        Deactivates all role assignments for the user in that tenant.

        Args:
            clerk_user_id: Clerk user ID
            clerk_org_id: Clerk organization ID
            reason: Why the membership was removed ("membership_deleted", "admin_action", "user_deleted")
            revoked_by: clerk_user_id of revoker, or "system" for automated

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
            UserTenantRole.is_active == True,  # noqa: E712 - SQLAlchemy needs ==
        ).all()

        if not roles:
            return False

        for role_assignment in roles:
            role_assignment.is_active = False

            # Emit role_revoked for each deactivated role
            self._emit_role_revoked(
                clerk_user_id=clerk_user_id,
                tenant_id=tenant.id,
                previous_role=role_assignment.role,
                revoked_by=revoked_by,
                reason=reason,
            )

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
        source: str = "clerk_webhook",
        changed_by: str = "system",
    ) -> Optional[UserTenantRole]:
        """
        Update a user's role in a tenant.

        Args:
            clerk_user_id: Clerk user ID
            clerk_org_id: Clerk organization ID
            old_role: Previous role
            new_role: New role
            source: How the change was initiated ("clerk_webhook", "agency_grant", "admin_grant")
            changed_by: clerk_user_id of who made the change, or "system" for automated

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

        if existing and existing.is_active:
            # Deactivate old role
            existing.is_active = False

            # Emit role_revoked for old role
            self._emit_role_revoked(
                clerk_user_id=clerk_user_id,
                tenant_id=tenant.id,
                previous_role=old_app_role,
                revoked_by=changed_by,
                reason="admin_action",
            )

        # Create or reactivate new role (this will emit role_assigned)
        return self.sync_membership(
            clerk_user_id,
            clerk_org_id,
            new_role,
            source=source,
            assigned_by=changed_by,
        )

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

    # =========================================================================
    # Identity Audit Event Methods
    # =========================================================================

    def _emit_user_first_seen(
        self,
        clerk_user_id: str,
        source: str,
        tenant_id: Optional[str] = None,
    ) -> None:
        """
        Emit audit event when a Clerk user is first seen in the system.

        Args:
            clerk_user_id: Clerk user identifier (NO email/PII)
            source: How the user was discovered ("webhook" or "lazy_sync")
            tenant_id: Optional tenant context
        """
        if source not in self._SOURCES_USER:
            raise ValueError(f"Invalid source '{source}'. Must be one of: {self._SOURCES_USER}")

        effective_tenant_id = tenant_id or "system"

        event = AuditEvent(
            tenant_id=effective_tenant_id,
            action=AuditAction.IDENTITY_USER_FIRST_SEEN,
            user_id=clerk_user_id,
            resource_type="user",
            resource_id=clerk_user_id,
            metadata={
                "clerk_user_id": clerk_user_id,
                "source": source,
            },
            correlation_id=self.correlation_id,
            source="webhook" if source == "webhook" else "api",
            outcome=AuditOutcome.SUCCESS,
        )

        write_audit_log_sync(self.session, event)

        logger.info(
            "Emitted identity.user_first_seen audit event",
            extra={
                "clerk_user_id": clerk_user_id,
                "source": source,
                "correlation_id": self.correlation_id,
            }
        )

    def _emit_user_linked_to_tenant(
        self,
        clerk_user_id: str,
        tenant_id: str,
        role: str,
        source: str,
    ) -> None:
        """
        Emit audit event when a user is linked to a tenant (membership created).

        Args:
            clerk_user_id: Clerk user identifier (NO email/PII)
            tenant_id: Tenant the user is being linked to
            role: Role being assigned
            source: How the link was created
        """
        if source not in self._SOURCES_ROLE:
            raise ValueError(f"Invalid source '{source}'. Must be one of: {self._SOURCES_ROLE}")

        event = AuditEvent(
            tenant_id=tenant_id,
            action=AuditAction.IDENTITY_USER_LINKED_TO_TENANT,
            user_id=clerk_user_id,
            resource_type="membership",
            resource_id=f"{clerk_user_id}:{tenant_id}",
            metadata={
                "clerk_user_id": clerk_user_id,
                "tenant_id": tenant_id,
                "role": role,
                "source": source,
            },
            correlation_id=self.correlation_id,
            source="webhook" if source == "clerk_webhook" else "api",
            outcome=AuditOutcome.SUCCESS,
        )

        write_audit_log_sync(self.session, event)

        logger.info(
            "Emitted identity.user_linked_to_tenant audit event",
            extra={
                "clerk_user_id": clerk_user_id,
                "tenant_id": tenant_id,
                "role": role,
                "correlation_id": self.correlation_id,
            }
        )

    def _emit_role_assigned(
        self,
        clerk_user_id: str,
        tenant_id: str,
        role: str,
        assigned_by: str,
        source: str,
    ) -> None:
        """
        Emit audit event when a role is assigned to a user.

        Args:
            clerk_user_id: User receiving the role (NO email/PII)
            tenant_id: Tenant context for the role
            role: Role being assigned (e.g., "MERCHANT_ADMIN")
            assigned_by: clerk_user_id of assigner, or "system" for automated
            source: How the role was assigned
        """
        if source not in self._SOURCES_ROLE:
            raise ValueError(f"Invalid source '{source}'. Must be one of: {self._SOURCES_ROLE}")

        event = AuditEvent(
            tenant_id=tenant_id,
            action=AuditAction.IDENTITY_ROLE_ASSIGNED,
            user_id=clerk_user_id,
            resource_type="role",
            resource_id=f"{clerk_user_id}:{tenant_id}:{role}",
            metadata={
                "clerk_user_id": clerk_user_id,
                "tenant_id": tenant_id,
                "role": role,
                "assigned_by": assigned_by,
                "source": source,
            },
            correlation_id=self.correlation_id,
            source="webhook" if source == "clerk_webhook" else "api",
            outcome=AuditOutcome.SUCCESS,
        )

        write_audit_log_sync(self.session, event)

        logger.info(
            "Emitted identity.role_assigned audit event",
            extra={
                "clerk_user_id": clerk_user_id,
                "tenant_id": tenant_id,
                "role": role,
                "assigned_by": assigned_by,
                "correlation_id": self.correlation_id,
            }
        )

    def _emit_role_revoked(
        self,
        clerk_user_id: str,
        tenant_id: str,
        previous_role: str,
        revoked_by: str,
        reason: str,
    ) -> None:
        """
        Emit audit event when a role is revoked from a user.

        Args:
            clerk_user_id: User losing the role (NO email/PII)
            tenant_id: Tenant context for the role
            previous_role: Role being revoked
            revoked_by: clerk_user_id of revoker, or "system" for automated
            reason: Why the role was revoked
        """
        if reason not in self._REASONS_REVOKE:
            raise ValueError(f"Invalid reason '{reason}'. Must be one of: {self._REASONS_REVOKE}")

        event = AuditEvent(
            tenant_id=tenant_id,
            action=AuditAction.IDENTITY_ROLE_REVOKED,
            user_id=clerk_user_id,
            resource_type="role",
            resource_id=f"{clerk_user_id}:{tenant_id}:{previous_role}",
            metadata={
                "clerk_user_id": clerk_user_id,
                "tenant_id": tenant_id,
                "previous_role": previous_role,
                "revoked_by": revoked_by,
                "reason": reason,
            },
            correlation_id=self.correlation_id,
            source="webhook" if reason == "membership_deleted" else "api",
            outcome=AuditOutcome.SUCCESS,
        )

        write_audit_log_sync(self.session, event)

        logger.info(
            "Emitted identity.role_revoked audit event",
            extra={
                "clerk_user_id": clerk_user_id,
                "tenant_id": tenant_id,
                "previous_role": previous_role,
                "revoked_by": revoked_by,
                "correlation_id": self.correlation_id,
            }
        )

    def _emit_tenant_created(
        self,
        tenant_id: str,
        clerk_org_id: str,
        billing_tier: str,
        source: str,
    ) -> None:
        """
        Emit audit event when a new tenant is created.

        Args:
            tenant_id: ID of the created tenant
            clerk_org_id: Clerk organization ID
            billing_tier: Initial billing tier (e.g., "free", "growth")
            source: How the tenant was created
        """
        if source not in self._SOURCES_TENANT:
            raise ValueError(f"Invalid source '{source}'. Must be one of: {self._SOURCES_TENANT}")

        event = AuditEvent(
            tenant_id=tenant_id,
            action=AuditAction.IDENTITY_TENANT_CREATED,
            user_id=None,
            resource_type="tenant",
            resource_id=tenant_id,
            metadata={
                "tenant_id": tenant_id,
                "clerk_org_id": clerk_org_id,
                "billing_tier": billing_tier,
                "source": source,
            },
            correlation_id=self.correlation_id,
            source="webhook" if source == "clerk_webhook" else "system",
            outcome=AuditOutcome.SUCCESS,
        )

        write_audit_log_sync(self.session, event)

        logger.info(
            "Emitted identity.tenant_created audit event",
            extra={
                "tenant_id": tenant_id,
                "clerk_org_id": clerk_org_id,
                "billing_tier": billing_tier,
                "correlation_id": self.correlation_id,
            }
        )

    def _emit_tenant_deactivated(
        self,
        tenant_id: str,
        clerk_org_id: str,
        reason: str,
    ) -> None:
        """
        Emit audit event when a tenant is deactivated.

        Args:
            tenant_id: ID of the deactivated tenant
            clerk_org_id: Clerk organization ID
            reason: Why the tenant was deactivated
        """
        if reason not in self._REASONS_DEACTIVATE:
            raise ValueError(f"Invalid reason '{reason}'. Must be one of: {self._REASONS_DEACTIVATE}")

        event = AuditEvent(
            tenant_id=tenant_id,
            action=AuditAction.IDENTITY_TENANT_DEACTIVATED,
            user_id=None,
            resource_type="tenant",
            resource_id=tenant_id,
            metadata={
                "tenant_id": tenant_id,
                "clerk_org_id": clerk_org_id,
                "reason": reason,
            },
            correlation_id=self.correlation_id,
            source="webhook" if reason == "org_deleted" else "system",
            outcome=AuditOutcome.SUCCESS,
        )

        write_audit_log_sync(self.session, event)

        logger.info(
            "Emitted identity.tenant_deactivated audit event",
            extra={
                "tenant_id": tenant_id,
                "clerk_org_id": clerk_org_id,
                "reason": reason,
                "correlation_id": self.correlation_id,
            }
        )
