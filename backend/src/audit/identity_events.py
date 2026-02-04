"""
Identity Audit Events for tracking identity-related changes.

This module provides the IdentityAuditEmitter service for emitting audit events
related to user and tenant identity lifecycle changes from Clerk authentication.

SECURITY REQUIREMENTS:
- NEVER include email or other PII in metadata - use clerk_user_id only
- ALL events MUST include correlation_id for request tracing
- Events are immutable once written (append-only audit log)

Events emitted:
- identity.user_first_seen: First time a Clerk user is seen in the system
- identity.user_linked_to_tenant: User membership created for a tenant
- identity.role_assigned: Role granted to a user on a tenant
- identity.role_revoked: Role removed from a user on a tenant
- identity.tenant_created: New tenant created from Clerk organization
- identity.tenant_deactivated: Tenant deactivated
"""

import logging
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from src.platform.audit import (
    AuditAction,
    AuditEvent,
    AuditOutcome,
    write_audit_log_sync,
)

logger = logging.getLogger(__name__)


class IdentityAuditEmitter:
    """
    Service for emitting identity-related audit events.

    This class provides methods to emit audit events for identity lifecycle
    changes, ensuring compliance with security requirements:
    - No PII in metadata (clerk_user_id only, never email)
    - All events include correlation_id
    - Proper tenant context for multi-tenant isolation

    Usage:
        emitter = IdentityAuditEmitter(db, correlation_id="abc-123")
        emitter.emit_user_first_seen(clerk_user_id="user_xyz", source="webhook")
    """

    # Valid sources for events
    SOURCES_USER = frozenset({"webhook", "lazy_sync"})
    SOURCES_ROLE = frozenset({"clerk_webhook", "agency_grant", "admin_grant"})
    SOURCES_TENANT = frozenset({"clerk_webhook", "admin_action"})

    # Valid reasons for role revocation
    REASONS_REVOKE = frozenset({"membership_deleted", "admin_action", "user_deleted"})

    # Valid reasons for tenant deactivation
    REASONS_DEACTIVATE = frozenset({"org_deleted", "admin_action", "billing"})

    def __init__(
        self,
        db: Session,
        correlation_id: Optional[str] = None,
    ):
        """
        Initialize the identity audit emitter.

        Args:
            db: SQLAlchemy database session
            correlation_id: Optional correlation ID for request tracing.
                           If not provided, a new UUID will be generated.
        """
        self.db = db
        self.correlation_id = correlation_id or str(uuid.uuid4())

    def emit_user_first_seen(
        self,
        clerk_user_id: str,
        source: str,
        tenant_id: Optional[str] = None,
    ) -> str:
        """
        Emit event when a Clerk user is first seen in the system.

        This should be called when a new user record is created (not updated).

        Args:
            clerk_user_id: Clerk user identifier (NO email/PII)
            source: How the user was discovered ("webhook" or "lazy_sync")
            tenant_id: Optional tenant context (may be None for new users)

        Returns:
            The correlation_id for this event

        Raises:
            ValueError: If source is not valid
        """
        if source not in self.SOURCES_USER:
            raise ValueError(f"Invalid source '{source}'. Must be one of: {self.SOURCES_USER}")

        # Use a system tenant placeholder if no tenant context
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

        write_audit_log_sync(self.db, event)

        logger.info(
            "Emitted identity.user_first_seen audit event",
            extra={
                "clerk_user_id": clerk_user_id,
                "source": source,
                "correlation_id": self.correlation_id,
            }
        )

        return self.correlation_id

    def emit_user_linked_to_tenant(
        self,
        clerk_user_id: str,
        tenant_id: str,
        role: str,
        source: str,
    ) -> str:
        """
        Emit event when a user is linked to a tenant (membership created).

        Args:
            clerk_user_id: Clerk user identifier (NO email/PII)
            tenant_id: Tenant the user is being linked to
            role: Role being assigned
            source: How the link was created ("clerk_webhook" or "agency_grant")

        Returns:
            The correlation_id for this event

        Raises:
            ValueError: If source is not valid
        """
        if source not in self.SOURCES_ROLE:
            raise ValueError(f"Invalid source '{source}'. Must be one of: {self.SOURCES_ROLE}")

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

        write_audit_log_sync(self.db, event)

        logger.info(
            "Emitted identity.user_linked_to_tenant audit event",
            extra={
                "clerk_user_id": clerk_user_id,
                "tenant_id": tenant_id,
                "role": role,
                "correlation_id": self.correlation_id,
            }
        )

        return self.correlation_id

    def emit_role_assigned(
        self,
        clerk_user_id: str,
        tenant_id: str,
        role: str,
        assigned_by: str,
        source: str,
    ) -> str:
        """
        Emit event when a role is assigned to a user.

        Args:
            clerk_user_id: User receiving the role (NO email/PII)
            tenant_id: Tenant context for the role
            role: Role being assigned (e.g., "MERCHANT_ADMIN")
            assigned_by: clerk_user_id of assigner, or "system" for automated
            source: How the role was assigned ("clerk_webhook", "agency_grant", "admin_grant")

        Returns:
            The correlation_id for this event

        Raises:
            ValueError: If source is not valid
        """
        if source not in self.SOURCES_ROLE:
            raise ValueError(f"Invalid source '{source}'. Must be one of: {self.SOURCES_ROLE}")

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

        write_audit_log_sync(self.db, event)

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

        return self.correlation_id

    def emit_role_revoked(
        self,
        clerk_user_id: str,
        tenant_id: str,
        previous_role: str,
        revoked_by: str,
        reason: str,
    ) -> str:
        """
        Emit event when a role is revoked from a user.

        Args:
            clerk_user_id: User losing the role (NO email/PII)
            tenant_id: Tenant context for the role
            previous_role: Role being revoked
            revoked_by: clerk_user_id of revoker, or "system" for automated
            reason: Why the role was revoked ("membership_deleted", "admin_action", "user_deleted")

        Returns:
            The correlation_id for this event

        Raises:
            ValueError: If reason is not valid
        """
        if reason not in self.REASONS_REVOKE:
            raise ValueError(f"Invalid reason '{reason}'. Must be one of: {self.REASONS_REVOKE}")

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

        write_audit_log_sync(self.db, event)

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

        return self.correlation_id

    def emit_tenant_created(
        self,
        tenant_id: str,
        clerk_org_id: str,
        billing_tier: str,
        source: str,
    ) -> str:
        """
        Emit event when a new tenant is created.

        Args:
            tenant_id: ID of the created tenant
            clerk_org_id: Clerk organization ID
            billing_tier: Initial billing tier (e.g., "free", "growth")
            source: How the tenant was created ("clerk_webhook" or "admin_action")

        Returns:
            The correlation_id for this event

        Raises:
            ValueError: If source is not valid
        """
        if source not in self.SOURCES_TENANT:
            raise ValueError(f"Invalid source '{source}'. Must be one of: {self.SOURCES_TENANT}")

        event = AuditEvent(
            tenant_id=tenant_id,
            action=AuditAction.IDENTITY_TENANT_CREATED,
            user_id=None,  # System-level event
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

        write_audit_log_sync(self.db, event)

        logger.info(
            "Emitted identity.tenant_created audit event",
            extra={
                "tenant_id": tenant_id,
                "clerk_org_id": clerk_org_id,
                "billing_tier": billing_tier,
                "correlation_id": self.correlation_id,
            }
        )

        return self.correlation_id

    def emit_tenant_deactivated(
        self,
        tenant_id: str,
        clerk_org_id: str,
        reason: str,
    ) -> str:
        """
        Emit event when a tenant is deactivated.

        Args:
            tenant_id: ID of the deactivated tenant
            clerk_org_id: Clerk organization ID
            reason: Why the tenant was deactivated ("org_deleted", "admin_action", "billing")

        Returns:
            The correlation_id for this event

        Raises:
            ValueError: If reason is not valid
        """
        if reason not in self.REASONS_DEACTIVATE:
            raise ValueError(f"Invalid reason '{reason}'. Must be one of: {self.REASONS_DEACTIVATE}")

        event = AuditEvent(
            tenant_id=tenant_id,
            action=AuditAction.IDENTITY_TENANT_DEACTIVATED,
            user_id=None,  # System-level event
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

        write_audit_log_sync(self.db, event)

        logger.info(
            "Emitted identity.tenant_deactivated audit event",
            extra={
                "tenant_id": tenant_id,
                "clerk_org_id": clerk_org_id,
                "reason": reason,
                "correlation_id": self.correlation_id,
            }
        )

        return self.correlation_id
