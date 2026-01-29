"""
Audit log access control service.

Enforces RBAC on audit log access for both API and UI.
Shared logic ensures consistent enforcement.

Role-based access:
- SUPER_ADMIN: All tenants (unrestricted)
- MERCHANT_ADMIN/VIEWER: Own tenant only
- AGENCY_ADMIN/VIEWER: allowed_tenants[] only

Story 10.6 - Audit Log Access Controls
"""

import logging
from dataclasses import dataclass
from typing import Optional, Set

from fastapi import Request, HTTPException

from src.platform.tenant_context import TenantContext, get_tenant_context
from src.constants.permissions import Role

logger = logging.getLogger(__name__)


@dataclass
class AuditAccessContext:
    """
    Context for audit log access control.

    Extracted from request and used for all access decisions.
    """
    user_id: str
    role: str
    tenant_id: str  # User's primary/active tenant
    allowed_tenants: Set[str]  # For agency roles
    is_super_admin: bool

    @classmethod
    def from_tenant_context(cls, tenant_ctx: TenantContext) -> "AuditAccessContext":
        """
        Create AuditAccessContext from TenantContext.

        Args:
            tenant_ctx: TenantContext from request

        Returns:
            AuditAccessContext instance
        """
        # Determine if user is super admin
        is_super_admin = any(
            role.lower() == Role.SUPER_ADMIN.value
            for role in tenant_ctx.roles
        )

        return cls(
            user_id=tenant_ctx.user_id,
            role=tenant_ctx.roles[0] if tenant_ctx.roles else "unknown",
            tenant_id=tenant_ctx.tenant_id,
            allowed_tenants=set(tenant_ctx.allowed_tenants or []),
            is_super_admin=is_super_admin,
        )


class AuditAccessControl:
    """
    Enforces access control on audit log queries.

    Key methods:
    - can_access_tenant(): Check if user can view tenant's logs
    - get_accessible_tenants(): Get set of accessible tenant IDs
    - filter_query(): Add tenant filters to SQLAlchemy query
    - validate_access(): Check access and raise if denied
    """

    def __init__(self, context: AuditAccessContext):
        """
        Initialize with access context.

        Args:
            context: AuditAccessContext from request
        """
        self.context = context

    def can_access_tenant(self, target_tenant_id: str) -> bool:
        """
        Check if user can access audit logs for a tenant.

        Rules:
        1. Super admins can access all tenants
        2. Agency roles can access allowed_tenants[]
        3. Merchant roles can only access their own tenant

        Args:
            target_tenant_id: Tenant ID to check access for

        Returns:
            True if access is allowed, False otherwise
        """
        # Super admin has unrestricted access
        if self.context.is_super_admin:
            return True

        # User can always access their own tenant
        if target_tenant_id == self.context.tenant_id:
            return True

        # Agency users can access allowed_tenants
        if target_tenant_id in self.context.allowed_tenants:
            return True

        return False

    def get_accessible_tenants(self) -> Optional[Set[str]]:
        """
        Get set of tenants user can access.

        Returns:
            Set of accessible tenant IDs, or None for super admins (unrestricted)
        """
        if self.context.is_super_admin:
            return None  # No restriction - can access all

        # Build set of accessible tenants
        accessible = {self.context.tenant_id}
        accessible.update(self.context.allowed_tenants)
        return accessible

    def filter_query(self, query, tenant_id_column):
        """
        Add tenant filter to SQLAlchemy query.

        Automatically applies the appropriate filter based on user's access level.

        Args:
            query: SQLAlchemy query object
            tenant_id_column: Column to filter on (e.g., AuditLog.tenant_id)

        Returns:
            Filtered query
        """
        accessible = self.get_accessible_tenants()

        if accessible is None:
            # Super admin - no filter needed
            return query

        if len(accessible) == 1:
            # Single tenant - use equality for better index usage
            return query.filter(tenant_id_column == list(accessible)[0])

        # Multiple tenants - use IN clause
        return query.filter(tenant_id_column.in_(accessible))

    def validate_access(self, target_tenant_id: str, db_session=None) -> None:
        """
        Validate access and raise HTTPException if denied.

        Use this when a specific tenant is requested explicitly.

        Args:
            target_tenant_id: Tenant ID to validate access for
            db_session: Optional database session for audit logging

        Raises:
            HTTPException: 403 if access is denied
        """
        if not self.can_access_tenant(target_tenant_id):
            logger.warning(
                "Cross-tenant audit access denied",
                extra={
                    "user_id": self.context.user_id,
                    "requesting_tenant": self.context.tenant_id,
                    "target_tenant": target_tenant_id,
                    "role": self.context.role,
                }
            )

            # Log to audit system if db session provided
            if db_session is not None:
                _log_cross_tenant_attempt(
                    db_session=db_session,
                    user_id=self.context.user_id,
                    requesting_tenant=self.context.tenant_id,
                    target_tenant=target_tenant_id,
                    role=self.context.role,
                )

            raise HTTPException(
                status_code=403,
                detail=f"Access denied to tenant {target_tenant_id}"
            )


def get_audit_access_context(request: Request) -> AuditAccessContext:
    """
    Extract audit access context from request.

    Uses existing tenant_context from request state.

    Args:
        request: FastAPI request object

    Returns:
        AuditAccessContext instance

    Raises:
        HTTPException: 403 if tenant context is missing
    """
    tenant_ctx = get_tenant_context(request)
    return AuditAccessContext.from_tenant_context(tenant_ctx)


def get_audit_access_control(request: Request) -> AuditAccessControl:
    """
    Get AuditAccessControl instance from request.

    Convenience function that creates both context and control.

    Args:
        request: FastAPI request object

    Returns:
        AuditAccessControl instance ready to use
    """
    context = get_audit_access_context(request)
    return AuditAccessControl(context)


def _log_cross_tenant_attempt(
    db_session,
    user_id: str,
    requesting_tenant: str,
    target_tenant: str,
    role: str,
) -> None:
    """
    Log cross-tenant access attempt to audit system and trigger alert.

    Internal function called by validate_access when db_session is provided.
    """
    # Lazy imports to avoid circular dependency
    from src.platform.audit import (
        AuditAction,
        AuditOutcome,
        log_system_audit_event_sync,
    )
    from src.monitoring.audit_alerts import get_audit_alert_manager

    try:
        log_system_audit_event_sync(
            db=db_session,
            tenant_id=requesting_tenant,
            action=AuditAction.SECURITY_CROSS_TENANT_DENIED,
            metadata={
                "target_tenant": target_tenant,
                "user_id": user_id,
                "role": role,
            },
            outcome=AuditOutcome.DENIED,
        )
    except Exception as e:
        # Don't fail the request if audit logging fails
        logger.error(
            "Failed to log cross-tenant access attempt",
            extra={"error": str(e), "user_id": user_id},
        )

    # Trigger security alert
    get_audit_alert_manager().alert_cross_tenant_access(
        requesting_tenant=requesting_tenant,
        target_tenant=target_tenant,
        user_id=user_id,
    )
