"""
Tenant Guard Service for cross-tenant access prevention.

This service provides centralized tenant validation logic for ensuring
every authenticated request executes within a valid tenant context.

SECURITY REQUIREMENTS:
- Resolve clerk_user_id -> allowed tenant_ids from database
- Reject requests missing tenant context
- Prevent cross-tenant access attempts
- Emit audit logs on all violations

USAGE:
    from src.services.tenant_guard import TenantGuard, get_tenant_guard

    # In route handlers
    @router.get("/data")
    async def get_data(
        request: Request,
        guard: TenantGuard = Depends(get_tenant_guard),
    ):
        # Guard validates access and raises HTTPException on violation
        context = guard.validate_request(request, tenant_id="tenant-123")
        ...

    # As FastAPI dependency
    @router.get("/protected")
    async def protected(
        tenant_context: TenantContext = Depends(require_tenant_guard),
    ):
        # tenant_context is guaranteed valid
        ...
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Any

from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.orm import Session

from src.auth.context_resolver import AuthContext
from src.auth.middleware import get_auth_context, require_auth
from src.models.user import User
from src.models.tenant import Tenant, TenantStatus
from src.models.user_tenant_roles import UserTenantRole
from src.database.session import get_db_session_sync
from src.platform.audit import (
    AuditEvent,
    AuditAction,
    AuditOutcome,
    write_audit_log_sync,
    extract_client_info,
)
from src.constants.permissions import (
    is_role_allowed_for_billing_tier,
    get_allowed_roles_for_billing_tier,
)

logger = logging.getLogger(__name__)


class ViolationType(str, Enum):
    """Types of tenant context violations."""
    MISSING_AUTH = "missing_auth"
    MISSING_TENANT = "missing_tenant"
    INVALID_TENANT = "invalid_tenant"
    CROSS_TENANT = "cross_tenant"
    SUSPENDED_TENANT = "suspended_tenant"
    INACTIVE_USER = "inactive_user"
    # Authorization enforcement violations
    ACCESS_REVOKED = "access_revoked"
    ROLE_INVALID_FOR_BILLING = "role_invalid_for_billing"
    USER_NOT_FOUND = "user_not_found"


@dataclass
class TenantViolation:
    """
    Details of a tenant context violation.

    Used for audit logging and error responses.
    """
    violation_type: ViolationType
    clerk_user_id: Optional[str] = None
    user_id: Optional[str] = None
    requested_tenant_id: Optional[str] = None
    allowed_tenant_ids: List[str] = field(default_factory=list)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    path: Optional[str] = None
    method: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    details: dict = field(default_factory=dict)

    def to_audit_metadata(self) -> dict:
        """Convert to metadata dict for audit logging."""
        return {
            "violation_type": self.violation_type.value,
            "clerk_user_id": self.clerk_user_id,
            "user_id": self.user_id,
            "requested_tenant_id": self.requested_tenant_id,
            "allowed_tenant_ids": self.allowed_tenant_ids,
            "path": self.path,
            "method": self.method,
            **self.details,
        }


@dataclass
class ValidationResult:
    """Result of tenant access validation."""
    is_valid: bool
    tenant_id: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    violation: Optional[TenantViolation] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None


@dataclass
class AuthorizationResult:
    """
    Result of DB-based authorization enforcement.

    Used by enforce_authorization to return detailed authorization state.
    """
    is_authorized: bool
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    billing_tier: Optional[str] = None
    denial_reason: Optional[str] = None
    error_code: Optional[str] = None
    # For role change detection
    roles_changed: bool = False
    previous_roles: List[str] = field(default_factory=list)
    # For audit event emission
    audit_action: Optional[AuditAction] = None
    audit_metadata: dict = field(default_factory=dict)


class TenantGuard:
    """
    Centralized tenant access control service.

    Responsibilities:
    - Resolve clerk_user_id -> allowed tenant_ids from database
    - Validate tenant access for each request
    - Prevent cross-tenant access attempts
    - Emit structured audit logs on violations

    Thread-safety: This class is thread-safe. Each method receives
    its dependencies (db session, request) as parameters.
    """

    def __init__(self, db: Session):
        """
        Initialize TenantGuard with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def resolve_allowed_tenants(self, clerk_user_id: str) -> List[str]:
        """
        Resolve clerk_user_id to list of allowed tenant IDs.

        Queries the UserTenantRole table to get all tenants the user
        has active access to.

        Args:
            clerk_user_id: Clerk user ID from JWT

        Returns:
            List of tenant_ids the user has access to
        """
        if not clerk_user_id:
            return []

        # Get user by clerk_user_id
        user = self.db.query(User).filter(
            User.clerk_user_id == clerk_user_id,
            User.is_active == True,
        ).first()

        if not user:
            logger.debug(
                "User not found for clerk_user_id",
                extra={"clerk_user_id": clerk_user_id}
            )
            return []

        # Get all active tenant roles for this user
        roles = self.db.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.is_active == True,
        ).all()

        # Filter to active tenants only
        allowed_tenants = []
        for role in roles:
            tenant = self.db.query(Tenant).filter(
                Tenant.id == role.tenant_id,
                Tenant.status == TenantStatus.ACTIVE,
            ).first()
            if tenant and tenant.id not in allowed_tenants:
                allowed_tenants.append(tenant.id)

        logger.debug(
            "Resolved allowed tenants",
            extra={
                "clerk_user_id": clerk_user_id,
                "user_id": user.id,
                "allowed_tenants_count": len(allowed_tenants),
            }
        )

        return allowed_tenants

    def get_user_roles_for_tenant(
        self,
        clerk_user_id: str,
        tenant_id: str,
    ) -> List[str]:
        """
        Get user's roles for a specific tenant.

        Args:
            clerk_user_id: Clerk user ID
            tenant_id: Tenant ID to check

        Returns:
            List of role names for the tenant
        """
        if not clerk_user_id or not tenant_id:
            return []

        user = self.db.query(User).filter(
            User.clerk_user_id == clerk_user_id,
            User.is_active == True,
        ).first()

        if not user:
            return []

        roles = self.db.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.tenant_id == tenant_id,
            UserTenantRole.is_active == True,
        ).all()

        return [role.role for role in roles]

    def enforce_authorization(
        self,
        clerk_user_id: str,
        active_tenant_id: str,
        jwt_roles: Optional[List[str]] = None,
        request_path: Optional[str] = None,
        request_method: Optional[str] = None,
    ) -> AuthorizationResult:
        """
        Enforce DB-as-source-of-truth authorization checks.

        This method performs immediate enforcement for authorization changes
        that occur mid-session:
        - tenant access revoked
        - role changed
        - billing downgrade removes permissions

        Args:
            clerk_user_id: Clerk user ID from JWT
            active_tenant_id: The tenant the user is trying to access
            jwt_roles: Roles from the JWT (for change detection)
            request_path: Request path (for audit logging)
            request_method: HTTP method (for audit logging)

        Returns:
            AuthorizationResult with authorization state and any audit events
        """
        # 1. Check if clerk_user_id exists in local DB
        user = self.db.query(User).filter(
            User.clerk_user_id == clerk_user_id,
        ).first()

        if not user:
            # Best-effort lazy bootstrap to avoid first-request auth deadlocks
            # when Clerk webhook delivery lags behind user traffic.
            logger.warning(
                "User not found in local DB during authorization enforcement; attempting bootstrap",
                extra={"clerk_user_id": clerk_user_id, "tenant_id": active_tenant_id},
            )

            user = User(
                id=str(uuid.uuid4()),
                clerk_user_id=clerk_user_id,
                is_active=True,
            )
            self.db.add(user)
            self.db.flush()

            bootstrap_role = (jwt_roles[0] if jwt_roles else "viewer").lower()
            existing_bootstrap_role = self.db.query(UserTenantRole).filter(
                UserTenantRole.user_id == user.id,
                UserTenantRole.tenant_id == active_tenant_id,
                UserTenantRole.role == bootstrap_role,
            ).first()

            if not existing_bootstrap_role:
                self.db.add(UserTenantRole(
                    user_id=user.id,
                    tenant_id=active_tenant_id,
                    role=bootstrap_role,
                    assigned_by=clerk_user_id,
                    source="lazy_sync",
                    is_active=True,
                ))
                self.db.flush()

        # Check if user is active
        if not user.is_active:
            logger.info(
                "Inactive user attempted access",
                extra={"clerk_user_id": clerk_user_id, "user_id": user.id}
            )
            return AuthorizationResult(
                is_authorized=False,
                user_id=user.id,
                denial_reason="User account is deactivated",
                error_code="USER_INACTIVE",
                audit_action=AuditAction.IDENTITY_ACCESS_REVOKED_ENFORCED,
                audit_metadata={
                    "clerk_user_id": clerk_user_id,
                    "tenant_id": active_tenant_id,
                    "enforcement_reason": "user_deactivated",
                    "request_path": request_path,
                    "request_method": request_method,
                },
            )

        # 2. Check if active_tenant_id is still allowed for this user
        tenant = self.db.query(Tenant).filter(
            Tenant.id == active_tenant_id,
        ).first()

        if not tenant:
            return AuthorizationResult(
                is_authorized=False,
                user_id=user.id,
                denial_reason="Tenant not found",
                error_code="TENANT_NOT_FOUND",
            )

        # Check tenant status
        if tenant.status != TenantStatus.ACTIVE:
            logger.info(
                "Access attempted to non-active tenant",
                extra={
                    "clerk_user_id": clerk_user_id,
                    "tenant_id": active_tenant_id,
                    "tenant_status": tenant.status.value,
                }
            )
            return AuthorizationResult(
                is_authorized=False,
                user_id=user.id,
                tenant_id=active_tenant_id,
                denial_reason=f"Tenant is {tenant.status.value}",
                error_code="TENANT_SUSPENDED",
                audit_action=AuditAction.IDENTITY_ACCESS_REVOKED_ENFORCED,
                audit_metadata={
                    "clerk_user_id": clerk_user_id,
                    "tenant_id": active_tenant_id,
                    "enforcement_reason": "tenant_suspended",
                    "tenant_status": tenant.status.value,
                    "request_path": request_path,
                    "request_method": request_method,
                },
            )

        # 3. Check if user still has active role for this tenant
        user_tenant_roles = self.db.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.tenant_id == active_tenant_id,
            UserTenantRole.is_active == True,
        ).all()

        if not user_tenant_roles:
            # User's access to this tenant has been revoked
            logger.info(
                "User access revoked - no active roles",
                extra={
                    "clerk_user_id": clerk_user_id,
                    "tenant_id": active_tenant_id,
                }
            )
            return AuthorizationResult(
                is_authorized=False,
                user_id=user.id,
                tenant_id=active_tenant_id,
                denial_reason="Access to this tenant has been revoked",
                error_code="ACCESS_REVOKED",
                previous_roles=jwt_roles or [],
                audit_action=AuditAction.IDENTITY_ACCESS_REVOKED_ENFORCED,
                audit_metadata={
                    "clerk_user_id": clerk_user_id,
                    "tenant_id": active_tenant_id,
                    "previous_roles": jwt_roles or [],
                    "enforcement_reason": "membership_deleted",
                    "request_path": request_path,
                    "request_method": request_method,
                },
            )

        # Extract current roles from DB
        db_roles = [r.role for r in user_tenant_roles]
        billing_tier = tenant.billing_tier

        # 4. Check if billing_tier permits the roles
        valid_roles = []
        invalid_roles = []
        for role in db_roles:
            if is_role_allowed_for_billing_tier(role, billing_tier):
                valid_roles.append(role)
            else:
                invalid_roles.append(role)

        if not valid_roles:
            # All roles are invalid for the current billing tier
            allowed_roles = get_allowed_roles_for_billing_tier(billing_tier)
            logger.info(
                "All user roles invalid for billing tier",
                extra={
                    "clerk_user_id": clerk_user_id,
                    "tenant_id": active_tenant_id,
                    "invalid_roles": invalid_roles,
                    "billing_tier": billing_tier,
                    "allowed_roles": allowed_roles,
                }
            )
            return AuthorizationResult(
                is_authorized=False,
                user_id=user.id,
                tenant_id=active_tenant_id,
                roles=db_roles,
                billing_tier=billing_tier,
                denial_reason="Your role is not available on the current billing plan",
                error_code="BILLING_ROLE_NOT_ALLOWED",
                audit_action=AuditAction.BILLING_ROLE_REVOKED_DUE_TO_DOWNGRADE,
                audit_metadata={
                    "clerk_user_id": clerk_user_id,
                    "tenant_id": active_tenant_id,
                    "previous_billing_tier": billing_tier,  # We don't know the previous tier
                    "new_billing_tier": billing_tier,
                    "invalid_role": invalid_roles[0] if invalid_roles else None,
                    "allowed_roles": allowed_roles,
                    "request_path": request_path,
                },
            )

        # Check for role changes (compare JWT roles with DB roles)
        roles_changed = False
        if jwt_roles is not None:
            jwt_roles_set = set(r.lower() for r in jwt_roles)
            db_roles_set = set(r.lower() for r in valid_roles)
            roles_changed = jwt_roles_set != db_roles_set

        # Authorization successful
        result = AuthorizationResult(
            is_authorized=True,
            user_id=user.id,
            tenant_id=active_tenant_id,
            roles=valid_roles,
            billing_tier=billing_tier,
            roles_changed=roles_changed,
            previous_roles=jwt_roles or [],
        )

        # If roles changed, add audit event for tracking
        if roles_changed:
            result.audit_action = AuditAction.IDENTITY_ROLE_CHANGE_ENFORCED
            result.audit_metadata = {
                "clerk_user_id": clerk_user_id,
                "tenant_id": active_tenant_id,
                "previous_roles": jwt_roles or [],
                "new_roles": valid_roles,
                "change_source": "db_enforcement",
                "permissions_removed": [],  # Would need permission diffing
            }

        return result

    def validate_tenant_access(
        self,
        auth_context: AuthContext,
        requested_tenant_id: Optional[str] = None,
    ) -> ValidationResult:
        """
        Validate that user has access to the specified or current tenant.

        Args:
            auth_context: AuthContext from request
            requested_tenant_id: Optional specific tenant to validate.
                               If None, uses auth_context.current_tenant_id

        Returns:
            ValidationResult with validation outcome
        """
        # Check authentication
        if not auth_context.is_authenticated:
            return ValidationResult(
                is_valid=False,
                error_message="Authentication required",
                error_code="AUTH_REQUIRED",
                violation=TenantViolation(
                    violation_type=ViolationType.MISSING_AUTH,
                ),
            )

        # Determine tenant to validate
        tenant_id = requested_tenant_id or auth_context.current_tenant_id

        # Check if tenant context exists
        if not tenant_id:
            return ValidationResult(
                is_valid=False,
                error_message="No tenant context. Please select a tenant.",
                error_code="TENANT_REQUIRED",
                violation=TenantViolation(
                    violation_type=ViolationType.MISSING_TENANT,
                    clerk_user_id=auth_context.clerk_user_id,
                    user_id=auth_context.user_id,
                    allowed_tenant_ids=auth_context.allowed_tenant_ids,
                ),
            )

        # Check if user has access to this tenant
        if not auth_context.has_access_to_tenant(tenant_id):
            # This is a cross-tenant access attempt
            return ValidationResult(
                is_valid=False,
                tenant_id=tenant_id,
                error_message="Access denied to tenant",
                error_code="CROSS_TENANT_DENIED",
                violation=TenantViolation(
                    violation_type=ViolationType.CROSS_TENANT,
                    clerk_user_id=auth_context.clerk_user_id,
                    user_id=auth_context.user_id,
                    requested_tenant_id=tenant_id,
                    allowed_tenant_ids=auth_context.allowed_tenant_ids,
                ),
            )

        # Check tenant status via TenantAccess
        tenant_access = auth_context.tenant_access.get(tenant_id)
        if tenant_access and not tenant_access.is_active:
            return ValidationResult(
                is_valid=False,
                tenant_id=tenant_id,
                error_message="Tenant is suspended or inactive",
                error_code="TENANT_INACTIVE",
                violation=TenantViolation(
                    violation_type=ViolationType.SUSPENDED_TENANT,
                    clerk_user_id=auth_context.clerk_user_id,
                    user_id=auth_context.user_id,
                    requested_tenant_id=tenant_id,
                    allowed_tenant_ids=auth_context.allowed_tenant_ids,
                ),
            )

        # Get roles for this tenant
        roles = list(auth_context.get_roles_for_tenant(tenant_id))

        return ValidationResult(
            is_valid=True,
            tenant_id=tenant_id,
            roles=roles,
        )

    def guard_request(
        self,
        request: Request,
        requested_tenant_id: Optional[str] = None,
    ) -> AuthContext:
        """
        Guard a request and ensure valid tenant context.

        This is the main entry point for protecting routes. It:
        1. Gets auth context from request
        2. Validates tenant access
        3. Emits audit log on violations
        4. Raises HTTPException on failure
        5. Returns validated auth context on success

        Args:
            request: FastAPI Request object
            requested_tenant_id: Optional specific tenant to validate

        Returns:
            Validated AuthContext

        Raises:
            HTTPException: 401 for auth failures, 403 for access denied
        """
        # Get auth context
        auth_context = get_auth_context(request)

        # Validate access
        result = self.validate_tenant_access(auth_context, requested_tenant_id)

        if not result.is_valid:
            # Emit audit log for violation
            self._emit_violation_audit_log(request, result.violation)

            # Determine HTTP status code
            if result.error_code == "AUTH_REQUIRED":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=result.error_message,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=result.error_message,
                    headers={
                        "X-Tenant-Error": result.error_code or "ACCESS_DENIED",
                    },
                )

        return auth_context

    def _emit_violation_audit_log(
        self,
        request: Request,
        violation: TenantViolation,
    ) -> None:
        """
        Emit audit log for a tenant violation.

        Args:
            request: FastAPI Request object
            violation: Violation details
        """
        # Extract client info
        ip_address, user_agent = extract_client_info(request)

        # Update violation with request info
        violation.ip_address = ip_address
        violation.user_agent = user_agent
        violation.path = str(request.url.path)
        violation.method = request.method

        # Determine tenant_id for audit log (use a placeholder for violations)
        audit_tenant_id = violation.requested_tenant_id or "UNKNOWN"

        # Create audit event
        event = AuditEvent(
            tenant_id=audit_tenant_id,
            action=AuditAction.SECURITY_CROSS_TENANT_DENIED,
            user_id=violation.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            resource_type="tenant_access",
            resource_id=violation.requested_tenant_id,
            metadata=violation.to_audit_metadata(),
            correlation_id=violation.correlation_id,
            source="api",
            outcome=AuditOutcome.DENIED,
            error_code=violation.violation_type.value,
        )

        # Write audit log (never fails request on audit error)
        try:
            write_audit_log_sync(self.db, event)
        except Exception as e:
            # Log error but don't fail the request
            logger.error(
                "Failed to write tenant violation audit log",
                extra={
                    "error": str(e),
                    "violation_type": violation.violation_type.value,
                    "correlation_id": violation.correlation_id,
                }
            )

        # Also log at WARNING level for monitoring
        logger.warning(
            "Tenant context violation",
            extra={
                "violation_type": violation.violation_type.value,
                "clerk_user_id": violation.clerk_user_id,
                "user_id": violation.user_id,
                "requested_tenant_id": violation.requested_tenant_id,
                "allowed_tenant_ids": violation.allowed_tenant_ids,
                "path": violation.path,
                "method": violation.method,
                "ip_address": ip_address,
                "correlation_id": violation.correlation_id,
            }
        )

    def emit_enforcement_audit_event(
        self,
        request: Request,
        authz_result: AuthorizationResult,
    ) -> None:
        """
        Emit audit event for authorization enforcement.

        Called when enforce_authorization detects an authorization change
        or denial that should be audited.

        Args:
            request: FastAPI Request object
            authz_result: Result from enforce_authorization
        """
        if not authz_result.audit_action:
            return

        # Extract client info
        ip_address, user_agent = extract_client_info(request)
        correlation_id = str(uuid.uuid4())

        # Determine outcome
        outcome = AuditOutcome.DENIED if not authz_result.is_authorized else AuditOutcome.SUCCESS

        # Create audit event
        event = AuditEvent(
            tenant_id=authz_result.tenant_id or "UNKNOWN",
            action=authz_result.audit_action,
            user_id=authz_result.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            resource_type="authorization",
            resource_id=authz_result.tenant_id,
            metadata=authz_result.audit_metadata,
            correlation_id=correlation_id,
            source="api",
            outcome=outcome,
            error_code=authz_result.error_code,
        )

        # Write audit log (never fails request on audit error)
        try:
            write_audit_log_sync(self.db, event)
        except Exception as e:
            logger.error(
                "Failed to write enforcement audit log",
                extra={
                    "error": str(e),
                    "audit_action": authz_result.audit_action.value,
                    "correlation_id": correlation_id,
                }
            )

        # Log at appropriate level based on outcome
        log_level = logging.WARNING if not authz_result.is_authorized else logging.INFO
        logger.log(
            log_level,
            "Authorization enforcement event",
            extra={
                "audit_action": authz_result.audit_action.value,
                "is_authorized": authz_result.is_authorized,
                "tenant_id": authz_result.tenant_id,
                "user_id": authz_result.user_id,
                "error_code": authz_result.error_code,
                "correlation_id": correlation_id,
            }
        )

    def validate_and_inject_context(
        self,
        request: Request,
        requested_tenant_id: Optional[str] = None,
    ) -> AuthContext:
        """
        Validate tenant access and inject context into request state.

        This method combines validation with context injection for
        downstream handlers.

        Args:
            request: FastAPI Request object
            requested_tenant_id: Optional specific tenant to validate

        Returns:
            Validated AuthContext (also injected into request.state)

        Raises:
            HTTPException: On validation failure
        """
        auth_context = self.guard_request(request, requested_tenant_id)

        # Ensure current tenant is set if not already
        if requested_tenant_id and auth_context.current_tenant_id != requested_tenant_id:
            auth_context.switch_tenant(requested_tenant_id)

        return auth_context


# =============================================================================
# FastAPI Dependencies
# =============================================================================


def get_tenant_guard(request: Request) -> TenantGuard:
    """
    FastAPI dependency to get TenantGuard instance.

    Usage:
        @router.get("/data")
        async def get_data(guard: TenantGuard = Depends(get_tenant_guard)):
            guard.guard_request(request)
    """
    db = next(get_db_session_sync())
    return TenantGuard(db)


def require_tenant_guard(
    request: Request,
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    """
    FastAPI dependency that requires valid tenant context.

    Validates that:
    1. User is authenticated
    2. User has a current tenant context
    3. User has access to the current tenant

    Raises HTTPException on any validation failure.
    Emits audit log on violations.

    Usage:
        @router.get("/protected")
        async def protected_route(
            auth: AuthContext = Depends(require_tenant_guard),
        ):
            # auth.current_tenant_id is guaranteed to be valid
            tenant_id = auth.current_tenant_id
            ...
    """
    db = next(get_db_session_sync())
    guard = TenantGuard(db)

    try:
        return guard.guard_request(request)
    finally:
        db.close()


def require_tenant_access(tenant_id: str):
    """
    Create a dependency that validates access to a specific tenant.

    Use this when the tenant_id comes from a path parameter.

    Usage:
        @router.get("/tenants/{tenant_id}/data")
        async def get_tenant_data(
            tenant_id: str,
            auth: AuthContext = Depends(require_tenant_access(tenant_id)),
        ):
            ...

    Note: For dynamic tenant_id from path, use require_tenant_guard_for_path instead.
    """
    def dependency(
        request: Request,
        auth: AuthContext = Depends(require_auth),
    ) -> AuthContext:
        db = next(get_db_session_sync())
        guard = TenantGuard(db)

        try:
            return guard.guard_request(request, requested_tenant_id=tenant_id)
        finally:
            db.close()

    return dependency


async def require_tenant_guard_for_path(
    request: Request,
    tenant_id: str,
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    """
    FastAPI dependency that validates access to a tenant from path parameter.

    Usage:
        @router.get("/tenants/{tenant_id}/data")
        async def get_tenant_data(
            tenant_id: str,
            auth: AuthContext = Depends(require_tenant_guard_for_path),
        ):
            # auth is validated for access to tenant_id
            ...
    """
    db = next(get_db_session_sync())
    guard = TenantGuard(db)

    try:
        return guard.guard_request(request, requested_tenant_id=tenant_id)
    finally:
        db.close()


# =============================================================================
# Utility Functions
# =============================================================================


def check_tenant_access(
    db: Session,
    clerk_user_id: str,
    tenant_id: str,
) -> bool:
    """
    Check if a user has access to a specific tenant.

    Utility function for non-request contexts (e.g., background jobs).

    Args:
        db: Database session
        clerk_user_id: Clerk user ID
        tenant_id: Tenant ID to check

    Returns:
        True if user has access, False otherwise
    """
    guard = TenantGuard(db)
    allowed_tenants = guard.resolve_allowed_tenants(clerk_user_id)
    return tenant_id in allowed_tenants


def get_user_tenants(
    db: Session,
    clerk_user_id: str,
) -> List[dict]:
    """
    Get all tenants accessible by a user with their roles.

    Utility function for listing user's tenants.

    Args:
        db: Database session
        clerk_user_id: Clerk user ID

    Returns:
        List of dicts with tenant_id, tenant_name, roles, billing_tier
    """
    if not clerk_user_id:
        return []

    # Get user
    user = db.query(User).filter(
        User.clerk_user_id == clerk_user_id,
        User.is_active == True,
    ).first()

    if not user:
        return []

    # Get all active tenant roles
    roles = db.query(UserTenantRole).filter(
        UserTenantRole.user_id == user.id,
        UserTenantRole.is_active == True,
    ).all()

    # Group roles by tenant
    tenant_roles: dict[str, list[str]] = {}
    for role in roles:
        if role.tenant_id not in tenant_roles:
            tenant_roles[role.tenant_id] = []
        tenant_roles[role.tenant_id].append(role.role)

    # Build result with tenant info
    result = []
    for tenant_id, role_names in tenant_roles.items():
        tenant = db.query(Tenant).filter(
            Tenant.id == tenant_id,
            Tenant.status == TenantStatus.ACTIVE,
        ).first()

        if tenant:
            result.append({
                "tenant_id": tenant.id,
                "tenant_name": tenant.name,
                "clerk_org_id": tenant.clerk_org_id,
                "roles": role_names,
                "billing_tier": tenant.billing_tier,
                "is_active": True,
            })

    return result
