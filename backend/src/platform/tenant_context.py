"""
Multi-tenant context enforcement for AI Growth Analytics.

CRITICAL SECURITY REQUIREMENTS:
- tenant_id is ALWAYS extracted from JWT (org_id), NEVER from request body/query
- All requests without valid tenant context return 403
- All database queries are scoped by tenant_id
- Cross-tenant access is strictly prohibited

AGENCY USER SUPPORT:
- Agency users have access to multiple tenant_ids via JWT allowed_tenants[] claim
- Active tenant_id can be switched via store selector (updates JWT context)
- RLS enforces: tenant_id IN ({{ current_user.allowed_tenants }})
- No wildcard access - explicit tenant_id list required

AUTHENTICATION PROVIDER: Clerk
- JWT verification via Clerk JWKS endpoint
- Supports Clerk Organizations for multi-tenancy

AUDIT LOGGING:
- All tenant context violations are logged to audit trail
- Violations include: missing auth, missing tenant, cross-tenant access
- Audit logs are append-only for compliance (SOC2, GDPR)
"""

import os
import logging
import uuid
from typing import Optional
from datetime import datetime, timezone, timedelta
from enum import Enum

import httpx
from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt import PyJWKClient, PyJWKClientError
from jwt.exceptions import InvalidTokenError, DecodeError
import json

from src.constants.permissions import has_multi_tenant_access, RoleCategory, get_primary_role_category
from src.database.session import get_db_session_sync

logger = logging.getLogger(__name__)

# Lazy import for TenantGuard to avoid circular imports
# Imported at module level so it can be mocked in tests
_tenant_guard_class = None


def _get_tenant_guard_class():
    """Get TenantGuard class (lazy import to avoid circular dependencies)."""
    global _tenant_guard_class
    if _tenant_guard_class is None:
        from src.services.tenant_guard import TenantGuard
        _tenant_guard_class = TenantGuard
    return _tenant_guard_class


class TenantViolationType(str, Enum):
    """Types of tenant context violations for audit logging."""
    MISSING_AUTH_TOKEN = "missing_auth_token"
    INVALID_TOKEN = "invalid_token"
    MISSING_ORG_ID = "missing_org_id"
    AUTHORIZATION_ENFORCEMENT_FAILED = "authorization_enforcement_failed"
    MISSING_USER_ID = "missing_user_id"
    SERVICE_UNAVAILABLE = "service_unavailable"
    TENANT_SELECTION_REQUIRED = "tenant_selection_required"
    NO_TENANT_ACCESS = "no_tenant_access"


class TenantSelectionRequiredException(Exception):
    """Raised when user has multiple tenants but no active selection."""
    def __init__(self, message: str, tenant_count: int):
        super().__init__(message)
        self.tenant_count = tenant_count


class NoTenantAccessException(Exception):
    """Raised when user has no tenant access."""
    pass


def _emit_tenant_violation_audit_log(
    request: Request,
    violation_type: TenantViolationType,
    error_message: str,
    user_id: Optional[str] = None,
    org_id: Optional[str] = None,
    extra_metadata: Optional[dict] = None,
) -> str:
    """
    Emit an audit log for tenant context violations.

    This function is designed to never fail - if audit logging fails,
    it logs to the fallback logger but doesn't crash the request.

    Args:
        request: FastAPI Request object
        violation_type: Type of violation
        error_message: Human-readable error message
        user_id: User ID if available
        org_id: Organization/tenant ID if available
        extra_metadata: Additional metadata to include

    Returns:
        Correlation ID for the violation
    """
    correlation_id = str(uuid.uuid4())

    # Extract client info
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip_address = forwarded_for.split(",")[0].strip()
    else:
        ip_address = request.client.host if request.client else None

    user_agent = request.headers.get("User-Agent")

    # Build violation metadata
    metadata = {
        "violation_type": violation_type.value,
        "error_message": error_message,
        "path": str(request.url.path),
        "method": request.method,
        "user_id": user_id,
        "org_id": org_id,
        **(extra_metadata or {}),
    }

    # Log at WARNING level (for monitoring and alerting)
    logger.warning(
        "Tenant context violation",
        extra={
            "correlation_id": correlation_id,
            "violation_type": violation_type.value,
            "path": request.url.path,
            "method": request.method,
            "ip_address": ip_address,
            "user_id": user_id,
            "org_id": org_id,
        }
    )

    # Try to write to audit database (lazy import for audit module to avoid circular deps)
    # Note: get_db_session_sync is already imported at module level
    try:
        from src.platform.audit import (
            AuditEvent,
            AuditAction,
            AuditOutcome,
            write_audit_log_sync,
        )

        db_gen = get_db_session_sync()
        db = next(db_gen)
        try:
            event = AuditEvent(
                tenant_id=org_id or "UNKNOWN",
                action=AuditAction.SECURITY_CROSS_TENANT_DENIED,
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                resource_type="tenant_context",
                resource_id=org_id,
                metadata=metadata,
                correlation_id=correlation_id,
                source="api",
                outcome=AuditOutcome.DENIED,
                error_code=violation_type.value,
            )
            write_audit_log_sync(db, event)
        except Exception as audit_error:
            # Never fail on audit logging errors
            logger.error(
                "Failed to write tenant violation to audit log",
                extra={
                    "error": str(audit_error),
                    "correlation_id": correlation_id,
                }
            )
        finally:
            db.close()
    except ImportError:
        # Audit module not available - log to fallback
        logger.error(
            "Audit module not available for tenant violation logging",
            extra={"correlation_id": correlation_id}
        )

    return correlation_id

# Security scheme for extracting Bearer token
security = HTTPBearer(auto_error=False)


class TenantContext:
    """
    Immutable tenant context extracted from JWT.

    For merchant users:
        - tenant_id: Single tenant_id from org_id
        - allowed_tenants: [tenant_id] (same as tenant_id)
        - is_agency_user: False

    For agency users:
        - tenant_id: Currently active tenant_id (selected store)
        - allowed_tenants: List of all accessible tenant_ids
        - is_agency_user: True
    """

    def __init__(
        self,
        tenant_id: str,
        user_id: str,
        roles: list[str],
        org_id: str,  # Clerk org_id for reference
        allowed_tenants: Optional[list[str]] = None,
        billing_tier: Optional[str] = None,
        resolved_permissions: Optional[set[str]] = None,
    ):
        if not tenant_id:
            raise ValueError("tenant_id cannot be empty")
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.roles = roles
        self.org_id = org_id
        self.billing_tier = billing_tier or "free"
        # Data-driven permissions resolved from DB (Story 5.5.1)
        # When set, RBAC decorators check this first before hardcoded matrix.
        # None = fall back to hardcoded ROLE_PERMISSIONS matrix.
        self.resolved_permissions = resolved_permissions

        # Determine role category and multi-tenant access
        self._role_category = get_primary_role_category(roles)
        self._is_agency_user = has_multi_tenant_access(roles)

        # Set allowed tenants based on role type
        if self._is_agency_user and allowed_tenants:
            # Agency users: explicit list of allowed tenant_ids (NO wildcards)
            self.allowed_tenants = allowed_tenants
        else:
            # Merchant users: single tenant_id only
            self.allowed_tenants = [tenant_id]

        # Validate active tenant is in allowed list
        if tenant_id not in self.allowed_tenants:
            raise ValueError(
                f"Active tenant_id {tenant_id} not in allowed_tenants list"
            )

    @property
    def is_agency_user(self) -> bool:
        """Check if this is an agency user with multi-tenant access."""
        return self._is_agency_user

    @property
    def role_category(self) -> RoleCategory:
        """Get the primary role category for this user."""
        return self._role_category

    def can_access_tenant(self, tenant_id: str) -> bool:
        """
        Check if user can access a specific tenant_id.

        SECURITY: Always use this method before accessing data from another tenant.
        """
        return tenant_id in self.allowed_tenants

    def get_rls_clause(self) -> str:
        """
        Generate RLS WHERE clause for query filtering.

        Returns:
            SQL clause for tenant isolation:
            - Single tenant: "tenant_id = 'tenant_123'"
            - Multi-tenant: "tenant_id IN ('tenant_123', 'tenant_456')"
        """
        if not self.allowed_tenants:
            return "1=0"  # Guarantees no rows are returned
        if len(self.allowed_tenants) == 1:
            return f"tenant_id = '{self.allowed_tenants[0]}'"
        else:
            tenant_ids = "', '".join(self.allowed_tenants)
            return f"tenant_id IN ('{tenant_ids}')"

    def __repr__(self) -> str:
        if self._is_agency_user:
            return (
                f"TenantContext(tenant_id={self.tenant_id}, user_id={self.user_id}, "
                f"is_agency=True, allowed_tenants={len(self.allowed_tenants)})"
            )
        return f"TenantContext(tenant_id={self.tenant_id}, user_id={self.user_id})"


class ClerkJWKSClient:
    """
    Fetches and manages Clerk JWKS for JWT verification.

    Uses PyJWT's PyJWKClient for robust JWKS handling.

    Clerk JWKS endpoint: https://<clerk-frontend-api>/.well-known/jwks.json
    """

    def __init__(self, clerk_frontend_api: str):
        """
        Initialize Clerk JWKS client.

        Args:
            clerk_frontend_api: Clerk Frontend API URL (e.g., 'clerk.your-domain.com' or 'your-app.clerk.accounts.dev')
        """
        self.clerk_frontend_api = clerk_frontend_api.rstrip('/')
        # Construct JWKS URL from Clerk Frontend API
        if not self.clerk_frontend_api.startswith('http'):
            self.clerk_frontend_api = f"https://{self.clerk_frontend_api}"
        self.jwks_url = f"{self.clerk_frontend_api}/.well-known/jwks.json"
        # PyJWT's PyJWKClient handles caching automatically
        self._jwks_client = PyJWKClient(self.jwks_url)
        logger.info(f"Clerk JWKS client initialized with URL: {self.jwks_url}")

    def get_signing_key(self, token: str):
        """
        Get signing key for token from JWKS.

        Returns the signing key object from PyJWKClient.
        """
        try:
            # PyJWKClient automatically fetches and caches JWKS
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            return signing_key
        except PyJWKClientError as e:
            logger.error("Failed to get signing key from Clerk JWKS", extra={"error": str(e), "jwks_url": self.jwks_url})
            raise
        except Exception as e:
            logger.error("Unexpected error getting signing key", extra={"error": str(e)})
            raise


class TenantContextMiddleware:
    """
    FastAPI middleware that enforces tenant isolation.

    Extracts tenant_id from Clerk JWT and attaches to request.state.
    Rejects all requests without valid tenant context.

    Clerk JWT Claims:
    - sub: User ID
    - azp: Authorized party (publishable key)
    - org_id: Organization ID (for multi-tenancy)
    - org_role: Organization role (e.g., "org:admin")
    - org_permissions: Organization permissions
    - metadata: Custom session/user metadata
    """

    def __init__(self):
        """
        Initialize middleware with lazy JWKS client creation.

        Environment variables are NOT checked here to allow module import
        without env vars present. Validation happens in app lifespan startup,
        and JWKS client is created lazily on first request.
        """
        self._jwks_client = None
        self._issuer = None

    def _get_jwks_client(self):
        """Get or create JWKS client (lazy initialization)."""
        if self._jwks_client is None:
            clerk_frontend_api = os.getenv("CLERK_FRONTEND_API")
            if not clerk_frontend_api:
                raise ValueError("CLERK_FRONTEND_API environment variable is required")
            self._jwks_client = ClerkJWKSClient(clerk_frontend_api)
            # Clerk issuer is the frontend API URL
            self._issuer = self._jwks_client.clerk_frontend_api
        return self._jwks_client

    @property
    def issuer(self):
        """Get Clerk issuer URL (lazy initialization)."""
        if self._issuer is None:
            self._get_jwks_client()
        return self._issuer

    async def _resolve_tenant_from_db(
        self,
        request: Request,
        user_id: str,
        jwt_org_id: str,
        jwt_active_tenant_id: str,
        jwt_allowed_tenants: list[str],
    ) -> tuple[str, list[str]]:
        """
        Resolve active tenant from database.

        Resolution order:
        1. JWT-provided active_tenant_id (if valid in DB)
        2. Stored active_tenant_id in user metadata (if valid)
        3. Auto-select if user has exactly 1 tenant
        4. Raise TenantSelectionRequiredException if multiple tenants

        Args:
            request: FastAPI request
            user_id: Clerk user ID from JWT
            jwt_org_id: Organization ID from JWT
            jwt_active_tenant_id: Active tenant from JWT
            jwt_allowed_tenants: Allowed tenants from JWT metadata

        Returns:
            Tuple of (resolved_tenant_id, db_allowed_tenants)

        Raises:
            TenantSelectionRequiredException: User has >1 tenants and no selection
            NoTenantAccessException: User has no tenant access
        """
        from src.database.session import get_db_session_sync
        from src.models.user import User
        from src.models.user_tenant_roles import UserTenantRole
        from src.models.tenant import Tenant, TenantStatus

        try:
            db = next(get_db_session_sync())
        except Exception:
            # DB session unavailable - fall back to JWT
            return jwt_active_tenant_id, []

        try:
            # Find user by clerk_user_id
            user = db.query(User).filter(
                User.clerk_user_id == user_id,
                User.is_active == True,
            ).first()

            if not user:
                # User not in DB yet - use JWT-based tenant_id
                # User will be created on first authenticated request
                return jwt_active_tenant_id, []

            # Get all active tenant roles for this user
            roles = db.query(UserTenantRole).filter(
                UserTenantRole.user_id == user.id,
                UserTenantRole.is_active == True,
            ).all()

            # Get unique tenant IDs that are active
            db_tenant_ids = set()
            for role in roles:
                tenant = db.query(Tenant).filter(
                    Tenant.id == role.tenant_id,
                    Tenant.status == TenantStatus.ACTIVE,
                ).first()
                if tenant:
                    db_tenant_ids.add(tenant.id)

            # Merge with JWT-based allowed_tenants
            all_tenant_ids = list(set(jwt_allowed_tenants) | db_tenant_ids)

            # If no tenants at all, use JWT org_id
            if not all_tenant_ids:
                # User has JWT org_id but no DB records yet
                return jwt_org_id, []

            # 1. Try JWT-provided active_tenant_id (if in allowed list)
            if jwt_active_tenant_id in all_tenant_ids:
                return jwt_active_tenant_id, list(db_tenant_ids)

            # 2. Try stored active_tenant_id from user metadata
            stored_tenant_id = (user.extra_metadata or {}).get("active_tenant_id")
            if stored_tenant_id and stored_tenant_id in all_tenant_ids:
                return stored_tenant_id, list(db_tenant_ids)

            # 3. Auto-select if exactly 1 tenant
            if len(all_tenant_ids) == 1:
                auto_tenant_id = all_tenant_ids[0]
                # Store the auto-selection
                metadata = user.extra_metadata or {}
                metadata["active_tenant_id"] = auto_tenant_id
                user.extra_metadata = metadata
                db.commit()

                logger.info(
                    "Auto-selected single tenant in middleware",
                    extra={
                        "user_id": user_id,
                        "tenant_id": auto_tenant_id,
                    }
                )
                return auto_tenant_id, list(db_tenant_ids)

            # 4. Multiple tenants but no selection
            raise TenantSelectionRequiredException(
                f"User has {len(all_tenant_ids)} tenants but no active selection. "
                "Use POST /api/users/me/active-tenant to select one.",
                tenant_count=len(all_tenant_ids),
            )

        except (TenantSelectionRequiredException, NoTenantAccessException):
            raise
        except Exception as db_err:
            # DB tables may not exist (e.g. in-memory SQLite test env) or
            # other DB-level errors. Fall back to JWT-based tenant resolution.
            logger.debug(
                "DB lookup failed in _resolve_tenant_from_db, falling back to JWT",
                extra={"error": str(db_err), "error_type": type(db_err).__name__},
            )
            return jwt_active_tenant_id, []
        finally:
            db.close()

    async def __call__(self, request: Request, call_next):
        """
        Process request and extract tenant context from JWT.

        SECURITY: tenant_id is ONLY extracted from JWT, never from request body/query.
        """
        # Skip tenant check for health endpoint, webhooks, API documentation,
        # Shopify embedded app entry point, and frontend static assets.
        # The root path "/" serves the React SPA (or bootstrap page). Shopify
        # loads this URL in an iframe. Frontend assets under /assets/ are
        # hashed bundles from the Vite build and contain no tenant data.
        # The SPA catch-all also serves files like vite.svg, favicon.ico,
        # etc. from the static directory — these must not require auth.
        PUBLIC_PATHS = {"/", "/health", "/docs", "/redoc", "/openapi.json", "/api/v1/embed/health"}
        # Static file extensions served by the SPA catch-all route
        STATIC_EXTENSIONS = (".svg", ".ico", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2", ".ttf", ".map")
        if (
            request.url.path in PUBLIC_PATHS
            or request.url.path.startswith("/api/webhooks/")
            or request.url.path.startswith("/assets/")
            or request.url.path.endswith(STATIC_EXTENSIONS)
            or not request.url.path.startswith("/api/")
        ):
            return await call_next(request)

        # Check if authentication is configured (set in app lifespan)
        if hasattr(request.app.state, "auth_configured") and not request.app.state.auth_configured:
            logger.warning(
                "Authentication not configured - protected endpoint accessed",
                extra={"path": request.url.path, "method": request.method}
            )
            # Emit audit log for service unavailable
            _emit_tenant_violation_audit_log(
                request=request,
                violation_type=TenantViolationType.SERVICE_UNAVAILABLE,
                error_message="Authentication service not configured",
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service not configured. Please set CLERK_FRONTEND_API environment variable."
            )

        # Extract Bearer token
        credentials: Optional[HTTPAuthorizationCredentials] = await security(request)

        if not credentials or not credentials.credentials:
            logger.warning("Request missing authorization token", extra={
                "path": request.url.path,
                "method": request.method
            })
            # Emit audit log for missing token
            _emit_tenant_violation_audit_log(
                request=request,
                violation_type=TenantViolationType.MISSING_AUTH_TOKEN,
                error_message="Missing or invalid authorization token",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing or invalid authorization token"
            )

        token = credentials.credentials

        try:
            # Get signing key from JWKS (PyJWKClient handles fetching/caching)
            jwks_client = self._get_jwks_client()
            signing_key = jwks_client.get_signing_key(token)

            # Decode and verify token using PyJWT
            # Clerk uses RS256 and issuer is the Clerk Frontend API URL
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self.issuer,
                options={
                    "verify_signature": True,
                    "verify_aud": False,  # Clerk doesn't always include aud claim
                    "verify_iss": True,
                    "verify_exp": True
                }
            )

            # Extract tenant context from Clerk JWT payload
            # Clerk claims:
            # - sub: User ID
            # - org_id: Organization ID (Clerk Organizations)
            # - org_role: Organization role (e.g., "org:admin", "org:member")
            # - org_permissions: Organization permissions array
            # - metadata: Custom session/user metadata (contains allowed_tenants, billing_tier, etc.)

            user_id = payload.get("sub")
            org_id = payload.get("org_id")

            # Extract custom metadata (Clerk stores custom claims in metadata or public_metadata)
            metadata = payload.get("metadata", {}) or payload.get("public_metadata", {}) or {}

            # Extract roles - Clerk uses org_role (single role) or custom roles in metadata
            org_role = payload.get("org_role", "")
            org_permissions = payload.get("org_permissions", [])

            # Convert Clerk org_role to roles list
            # Clerk org_role format: "org:admin", "org:member", etc.
            roles = metadata.get("roles", [])
            if not roles and org_role:
                # Map Clerk org_role to application roles
                role_mapping = {
                    "org:admin": "MERCHANT_ADMIN",
                    "org:member": "MERCHANT_VIEWER",
                    "admin": "ADMIN",
                    "owner": "OWNER",
                }
                mapped_role = role_mapping.get(org_role, org_role.replace("org:", "").upper())
                roles = [mapped_role]

            if not org_id:
                logger.error("JWT missing org_id", extra={
                    "payload_keys": list(payload.keys())
                })
                # Emit audit log for missing org_id
                _emit_tenant_violation_audit_log(
                    request=request,
                    violation_type=TenantViolationType.MISSING_ORG_ID,
                    error_message="Token missing organization identifier",
                    user_id=str(user_id) if user_id else None,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Token missing organization identifier. Ensure user is part of a Clerk Organization."
                )

            if not user_id:
                logger.error("JWT missing user_id (sub)", extra={
                    "payload_keys": list(payload.keys())
                })
                # Emit audit log for missing user_id
                _emit_tenant_violation_audit_log(
                    request=request,
                    violation_type=TenantViolationType.MISSING_USER_ID,
                    error_message="Token missing user identifier",
                    org_id=str(org_id) if org_id else None,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Token missing user identifier"
                )

            # Extract allowed_tenants for agency users (from metadata)
            allowed_tenants = metadata.get("allowed_tenants", [])
            billing_tier = metadata.get("billing_tier", "free")

            # For agency users, active_tenant_id may differ from org_id
            # Use 'active_tenant_id' claim if present, otherwise default to org_id
            active_tenant_id = payload.get("active_tenant_id") or str(org_id)

            # =========================================================================
            # DB-BASED TENANT RESOLUTION
            # If user has multiple tenants (via agency grants), resolve active tenant
            # =========================================================================
            try:
                resolved_tenant_id, db_allowed_tenants = await self._resolve_tenant_from_db(
                    request=request,
                    user_id=str(user_id),
                    jwt_org_id=str(org_id),
                    jwt_active_tenant_id=active_tenant_id,
                    jwt_allowed_tenants=allowed_tenants,
                )
                active_tenant_id = resolved_tenant_id
                # Merge DB-based allowed_tenants with JWT-based
                if db_allowed_tenants:
                    allowed_tenants = list(set(allowed_tenants + db_allowed_tenants))
            except TenantSelectionRequiredException as e:
                # Multi-tenant user has no active tenant selected
                _emit_tenant_violation_audit_log(
                    request=request,
                    violation_type=TenantViolationType.TENANT_SELECTION_REQUIRED,
                    error_message=str(e),
                    user_id=str(user_id),
                    org_id=str(org_id),
                    extra_metadata={"tenant_count": e.tenant_count},
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "TENANT_SELECTION_REQUIRED",
                        "message": str(e),
                        "tenant_count": e.tenant_count,
                    }
                )
            except NoTenantAccessException as e:
                _emit_tenant_violation_audit_log(
                    request=request,
                    violation_type=TenantViolationType.NO_TENANT_ACCESS,
                    error_message=str(e),
                    user_id=str(user_id),
                    org_id=str(org_id),
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User has no tenant access"
                )

            # Ensure active_tenant_id is in allowed_tenants for agency users
            if allowed_tenants and active_tenant_id not in allowed_tenants:
                # Default to first allowed tenant
                active_tenant_id = allowed_tenants[0] if allowed_tenants else str(org_id)

            # CRITICAL: tenant_id = org_id (from JWT, never from request)
            # For agency users: tenant_id is the currently active tenant
            tenant_context = TenantContext(
                tenant_id=active_tenant_id,
                user_id=str(user_id),
                roles=roles if isinstance(roles, list) else [],
                org_id=str(org_id),
                allowed_tenants=allowed_tenants if allowed_tenants else None,
                billing_tier=billing_tier,
            )

            # =================================================================
            # DB-AS-SOURCE-OF-TRUTH AUTHORIZATION ENFORCEMENT
            # =================================================================
            # Verify authorization against database on every request.
            # This ensures immediate enforcement for:
            # - Tenant access revoked mid-session
            # - Role changes mid-session
            # - Billing downgrades that invalidate roles
            TenantGuard = _get_tenant_guard_class()

            db_gen = get_db_session_sync()
            db = next(db_gen)
            try:
                guard = TenantGuard(db)
                authz_result = guard.enforce_authorization(
                    clerk_user_id=str(user_id),
                    active_tenant_id=active_tenant_id,
                    jwt_roles=roles if isinstance(roles, list) else [],
                    request_path=str(request.url.path),
                    request_method=request.method,
                )

                if not authz_result.is_authorized:
                    # Emit audit event for the enforcement
                    guard.emit_enforcement_audit_event(request, authz_result)

                    # Emit violation audit log
                    _emit_tenant_violation_audit_log(
                        request=request,
                        violation_type=TenantViolationType.AUTHORIZATION_ENFORCEMENT_FAILED,
                        error_message=authz_result.denial_reason or "Authorization denied",
                        user_id=str(user_id),
                        org_id=str(org_id),
                        extra_metadata={
                            "error_code": authz_result.error_code,
                            "tenant_id": active_tenant_id,
                        },
                    )

                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=authz_result.denial_reason or "Access denied",
                        headers={
                            "X-Error-Code": authz_result.error_code or "ACCESS_DENIED",
                        },
                    )

                # Update tenant context with DB-verified roles and billing tier
                # This ensures the request uses current DB state, not stale JWT claims
                if authz_result.roles:
                    tenant_context = TenantContext(
                        tenant_id=active_tenant_id,
                        user_id=str(user_id),
                        roles=authz_result.roles,  # Use DB-verified roles
                        org_id=str(org_id),
                        allowed_tenants=allowed_tenants if allowed_tenants else None,
                        billing_tier=authz_result.billing_tier or billing_tier,
                    )

                # Emit audit event for role changes (if any)
                if authz_result.roles_changed and authz_result.audit_action:
                    guard.emit_enforcement_audit_event(request, authz_result)

                # Resolve data-driven permissions from DB (Story 5.5.1)
                # This populates resolved_permissions on TenantContext so RBAC
                # decorators check DB-driven roles instead of the hardcoded matrix.
                try:
                    from src.services.rbac import resolve_permissions_for_user
                    from src.models.user import User

                    user = db.query(User).filter(
                        User.clerk_user_id == str(user_id)
                    ).first()
                    if user:
                        perms = resolve_permissions_for_user(db, user.id, active_tenant_id)
                        if perms:
                            # Only override when DB has actual permission records.
                            # Empty set means no data-driven roles exist yet;
                            # leave as None to fall back to hardcoded matrix.
                            tenant_context.resolved_permissions = perms
                except Exception:
                    # Graceful degradation: if resolution fails, decorators
                    # fall back to the hardcoded ROLE_PERMISSIONS matrix.
                    logger.debug(
                        "Data-driven permission resolution skipped",
                        extra={
                            "user_id": str(user_id),
                            "tenant_id": active_tenant_id,
                        },
                        exc_info=True,
                    )

            finally:
                db.close()

            # Attach to request state
            request.state.tenant_context = tenant_context

            # Log with tenant context (for audit trail)
            log_extra = {
                "tenant_id": tenant_context.tenant_id,
                "user_id": tenant_context.user_id,
                "path": request.url.path,
                "method": request.method,
            }
            if tenant_context.is_agency_user:
                log_extra["is_agency_user"] = True
                log_extra["allowed_tenants_count"] = len(tenant_context.allowed_tenants)
            logger.info("Request authenticated", extra=log_extra)
            
        except (InvalidTokenError, DecodeError, PyJWKClientError) as e:
            logger.warning("JWT verification failed", extra={
                "error": str(e),
                "path": request.url.path
            })
            # Emit audit log for invalid token
            _emit_tenant_violation_audit_log(
                request=request,
                violation_type=TenantViolationType.INVALID_TOKEN,
                error_message=f"Invalid or expired token: {str(e)}",
                extra_metadata={"error_type": type(e).__name__},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Invalid or expired token: {str(e)}"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Unexpected error during tenant context extraction", extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "path": request.url.path
            })
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal error during authentication"
            )
        
        # Continue to next middleware/handler
        response = await call_next(request)
        
        # Add tenant context to response headers for debugging (optional)
        if hasattr(request.state, "tenant_context"):
            ctx = request.state.tenant_context
            response.headers["X-Tenant-ID"] = ctx.tenant_id
            if ctx.is_agency_user:
                response.headers["X-Agency-User"] = "true"
                response.headers["X-Allowed-Tenants-Count"] = str(len(ctx.allowed_tenants))

        return response


def get_tenant_context(request: Request) -> TenantContext:
    """
    Extract tenant context from request state.
    
    Raises 403 if tenant context is missing.
    Use this in route handlers to access tenant_id.
    """
    if not hasattr(request.state, "tenant_context"):
        logger.error("Route handler accessed without tenant context", extra={
            "path": request.url.path
        })
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context not available"
        )
    
    return request.state.tenant_context


def require_tenant_context(func):
    """
    Decorator to ensure tenant context exists before route handler executes.

    Usage:
        @app.get("/api/data")
        @require_tenant_context
        async def get_data(request: Request):
            tenant_ctx = get_tenant_context(request)
            # Use tenant_ctx.tenant_id
    """
    from functools import wraps

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Find Request object in args/kwargs
        request = None
        for arg in args:
            if isinstance(arg, Request):
                request = arg
                break
        if not request:
            request = kwargs.get("request")

        if not request:
            raise ValueError("Request object not found in function arguments")

        # Verify tenant context exists
        get_tenant_context(request)

        return await func(*args, **kwargs)

    return wrapper


def get_db_allowed_tenants(session, clerk_user_id: str) -> list[str]:
    """
    Get allowed_tenants from database (UserTenantRole table).

    This supplements the JWT-based allowed_tenants with database-granted
    access (e.g., agency grants).

    Args:
        session: SQLAlchemy database session
        clerk_user_id: Clerk user ID (from JWT sub claim)

    Returns:
        List of tenant_ids the user has access to
    """
    from src.models.user import User
    from src.models.user_tenant_roles import UserTenantRole
    from src.models.tenant import Tenant, TenantStatus

    # Get user by clerk_user_id
    user = session.query(User).filter(
        User.clerk_user_id == clerk_user_id,
        User.is_active == True,
    ).first()

    if not user:
        return []

    # Get all active tenant roles for this user
    roles = session.query(UserTenantRole).filter(
        UserTenantRole.user_id == user.id,
        UserTenantRole.is_active == True,
    ).all()

    # Filter to active tenants only
    allowed_tenants = []
    for role in roles:
        tenant = session.query(Tenant).filter(
            Tenant.id == role.tenant_id,
            Tenant.status == TenantStatus.ACTIVE,
        ).first()
        if tenant and tenant.id not in allowed_tenants:
            allowed_tenants.append(tenant.id)

    return allowed_tenants


def enrich_tenant_context_from_db(
    request: Request,
    session,
) -> TenantContext:
    """
    Enrich the existing TenantContext with database-based allowed_tenants.

    This function merges JWT-based allowed_tenants with database-granted
    access (e.g., agency grants). Use this in routes that need the complete
    list of accessible tenants.

    The active_tenant_id remains unchanged (from JWT), but allowed_tenants
    is updated to include database grants.

    Args:
        request: FastAPI request with tenant_context in state
        session: SQLAlchemy database session

    Returns:
        Updated TenantContext with merged allowed_tenants

    Example:
        @router.get("/my-tenants")
        async def list_tenants(request: Request):
            db = get_db_session(request)
            tenant_ctx = enrich_tenant_context_from_db(request, db)
            return {"tenants": tenant_ctx.allowed_tenants}
    """
    current_ctx = get_tenant_context(request)

    # Get database-based allowed_tenants
    db_tenants = get_db_allowed_tenants(session, current_ctx.user_id)

    # Merge with JWT-based allowed_tenants
    merged_tenants = list(set(current_ctx.allowed_tenants + db_tenants))

    # If no change, return current context
    if set(merged_tenants) == set(current_ctx.allowed_tenants):
        return current_ctx

    # Ensure active tenant is in merged list
    if current_ctx.tenant_id not in merged_tenants:
        merged_tenants.insert(0, current_ctx.tenant_id)

    # Create enriched context
    enriched_ctx = TenantContext(
        tenant_id=current_ctx.tenant_id,
        user_id=current_ctx.user_id,
        roles=current_ctx.roles,
        org_id=current_ctx.org_id,
        allowed_tenants=merged_tenants,
        billing_tier=current_ctx.billing_tier,
    )

    # Update request state
    request.state.tenant_context = enriched_ctx

    logger.debug(
        "Enriched tenant context from database",
        extra={
            "user_id": current_ctx.user_id,
            "jwt_tenants": len(current_ctx.allowed_tenants),
            "db_tenants": len(db_tenants),
            "merged_tenants": len(merged_tenants),
        }
    )

    return enriched_ctx