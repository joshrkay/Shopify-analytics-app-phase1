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
"""

import os
import logging
from typing import Optional
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt import PyJWKClient, PyJWKClientError
from jwt.exceptions import InvalidTokenError, DecodeError
import json

from src.constants.permissions import has_multi_tenant_access, RoleCategory, get_primary_role_category

logger = logging.getLogger(__name__)

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
        org_id: str,  # Original Frontegg org_id for reference
        allowed_tenants: Optional[list[str]] = None,
        billing_tier: Optional[str] = None,
    ):
        if not tenant_id:
            raise ValueError("tenant_id cannot be empty")
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.roles = roles
        self.org_id = org_id
        self.billing_tier = billing_tier or "free"

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


# Backwards compatibility alias
FronteggJWKSClient = ClerkJWKSClient


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
    
    async def __call__(self, request: Request, call_next):
        """
        Process request and extract tenant context from JWT.

        SECURITY: tenant_id is ONLY extracted from JWT, never from request body/query.
        """
        # Skip tenant check for health endpoint, webhooks, and API documentation (public)
        if request.url.path in ("/health", "/docs", "/redoc", "/openapi.json") or request.url.path.startswith("/api/webhooks/"):
            return await call_next(request)

        # Check if authentication is configured (set in app lifespan)
        if hasattr(request.app.state, "auth_configured") and not request.app.state.auth_configured:
            logger.warning(
                "Authentication not configured - protected endpoint accessed",
                extra={"path": request.url.path, "method": request.method}
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
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Token missing organization identifier. Ensure user is part of a Clerk Organization."
                )

            if not user_id:
                logger.error("JWT missing user_id (sub)", extra={
                    "payload_keys": list(payload.keys())
                })
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