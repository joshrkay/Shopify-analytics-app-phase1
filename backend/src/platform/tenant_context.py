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


class FronteggJWKSClient:
    """
    Fetches and manages Frontegg JWKS for JWT verification.
    
    Uses PyJWT's PyJWKClient for robust JWKS handling.
    """
    
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.jwks_url = "https://api.frontegg.com/.well-known/jwks.json"
        # PyJWT's PyJWKClient handles caching automatically
        self._jwks_client = PyJWKClient(self.jwks_url)
    
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
            logger.error("Failed to get signing key from JWKS", extra={"error": str(e)})
            raise
        except Exception as e:
            logger.error("Unexpected error getting signing key", extra={"error": str(e)})
            raise


class TenantContextMiddleware:
    """
    FastAPI middleware that enforces tenant isolation.
    
    Extracts tenant_id from Frontegg JWT and attaches to request.state.
    Rejects all requests without valid tenant context.
    """
    
    def __init__(self):
        """
        Initialize middleware with lazy JWKS client creation.
        
        Environment variables are NOT checked here to allow module import
        without env vars present. Validation happens in app lifespan startup,
        and JWKS client is created lazily on first request.
        """
        self._jwks_client = None
        self.issuer = "https://api.frontegg.com"
    
    def _get_jwks_client(self):
        """Get or create JWKS client (lazy initialization)."""
        if self._jwks_client is None:
            client_id = os.getenv("FRONTEGG_CLIENT_ID")
            if not client_id:
                raise ValueError("FRONTEGG_CLIENT_ID environment variable is required")
            self._jwks_client = FronteggJWKSClient(client_id)
        return self._jwks_client
    
    async def __call__(self, request: Request, call_next):
        """
        Process request and extract tenant context from JWT.

        SECURITY: tenant_id is ONLY extracted from JWT, never from request body/query.
        """
        # Skip tenant check for health endpoint and webhooks (webhooks use HMAC verification)
        if request.url.path == "/health" or request.url.path.startswith("/api/webhooks/"):
            return await call_next(request)

        # Check if authentication is configured (set in app lifespan)
        if hasattr(request.app.state, "auth_configured") and not request.app.state.auth_configured:
            logger.warning(
                "Authentication not configured - protected endpoint accessed",
                extra={"path": request.url.path, "method": request.method}
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service not configured. Please set FRONTEGG_CLIENT_ID environment variable."
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
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],  # Frontegg uses RS256
                audience=jwks_client.client_id,
                issuer=self.issuer,
                options={
                    "verify_signature": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": True
                }
            )
            
            # Extract tenant context from payload
            org_id = payload.get("org_id") or payload.get("organizationId")
            user_id = payload.get("sub") or payload.get("userId") or payload.get("user_id")
            roles = payload.get("roles", [])
            
            if not org_id:
                logger.error("JWT missing org_id", extra={
                    "payload_keys": list(payload.keys())
                })
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Token missing organization identifier"
                )
            
            if not user_id:
                logger.error("JWT missing user_id", extra={
                    "payload_keys": list(payload.keys())
                })
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Token missing user identifier"
                )
            
            # Extract allowed_tenants for agency users (from JWT claim)
            allowed_tenants = payload.get("allowed_tenants", [])
            billing_tier = payload.get("billing_tier", "free")

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