"""
Multi-tenant context enforcement for AI Growth Analytics.

CRITICAL SECURITY REQUIREMENTS:
- tenant_id is ALWAYS extracted from JWT (org_id), NEVER from request body/query
- All requests without valid tenant context return 403
- All database queries are scoped by tenant_id
- Cross-tenant access is strictly prohibited
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

logger = logging.getLogger(__name__)

# Security scheme for extracting Bearer token
security = HTTPBearer(auto_error=False)


class TenantContext:
    """Immutable tenant context extracted from JWT."""
    
    def __init__(
        self,
        tenant_id: str,
        user_id: str,
        roles: list[str],
        org_id: str,  # Original Frontegg org_id for reference
    ):
        if not tenant_id:
            raise ValueError("tenant_id cannot be empty")
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.roles = roles
        self.org_id = org_id
    
    def __repr__(self) -> str:
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
        Process request and extract tenant context from JWT or Shopify session token.

        SECURITY: tenant_id is ONLY extracted from JWT/session token, never from request body/query.
        
        Supports dual authentication:
        - Shopify session tokens (for embedded app routes)
        - Frontegg JWT (for admin routes)
        """
        # Skip tenant check for health endpoint, webhooks, and OAuth routes
        if (request.url.path == "/health" or 
            request.url.path.startswith("/api/webhooks/") or
            request.url.path.startswith("/api/auth/")):
            return await call_next(request)

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
        
        # Try Shopify session token first (for embedded app routes)
        try:
            from src.platform.shopify_session import get_session_token_verifier
            
            verifier = get_session_token_verifier()
            
            # If verifier is None, Shopify credentials not configured - skip to Frontegg
            if verifier is None:
                # Raise a specific exception that will be caught and fall through to Frontegg
                raise ValueError("Shopify session token verification not configured")
            
            shopify_session = verifier.verify_session_token(token)
            
            # Convert Shopify session to TenantContext
            tenant_context = TenantContext(
                tenant_id=shopify_session.tenant_id,
                user_id=shopify_session.user_id or "shopify-user",
                roles=[],  # Shopify session tokens don't include roles
                org_id=shopify_session.shop_domain,  # Use shop_domain as org_id for reference
            )
            
            # Attach to request state
            request.state.tenant_context = tenant_context
            
            logger.info("Request authenticated via Shopify session token", extra={
                "tenant_id": tenant_context.tenant_id,
                "shop_domain": shopify_session.shop_domain,
                "path": request.url.path,
                "method": request.method
            })
            
            # Continue to next middleware/handler
            response = await call_next(request)
            
            # Add tenant_id to response headers for debugging (optional)
            if hasattr(request.state, "tenant_context"):
                response.headers["X-Tenant-ID"] = request.state.tenant_context.tenant_id
            
            return response
            
        except ValueError as shopify_config_error:
            # Shopify not configured - fall through to Frontegg
            if "not configured" in str(shopify_config_error):
                logger.debug("Shopify session token verification not configured, trying Frontegg JWT", extra={
                    "path": request.url.path
                })
            else:
                # Other ValueError - re-raise
                raise
        except HTTPException as shopify_auth_error:
            # Shopify token verification failed (invalid token) - do NOT fall back to Frontegg
            # This is a security requirement: invalid tokens should be rejected, not tried with another auth method
            logger.warning("Shopify session token verification failed", extra={
                "error": str(shopify_auth_error.detail),
                "path": request.url.path
            })
            raise
        
        # Fall through to Frontegg JWT verification (only if Shopify not configured)
        # Check if Frontegg authentication is configured
        if hasattr(request.app.state, "auth_configured") and not request.app.state.auth_configured:
            logger.warning(
                "Authentication not configured - protected endpoint accessed",
                extra={"path": request.url.path, "method": request.method}
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service not configured. Please set FRONTEGG_CLIENT_ID environment variable."
            )
        
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
            
            # CRITICAL: tenant_id = org_id (from JWT, never from request)
            tenant_context = TenantContext(
                tenant_id=str(org_id),
                user_id=str(user_id),
                roles=roles if isinstance(roles, list) else [],
                org_id=str(org_id),
            )
            
            # Attach to request state
            request.state.tenant_context = tenant_context
            
            # Log with tenant context (for audit trail)
            logger.info("Request authenticated via Frontegg JWT", extra={
                "tenant_id": tenant_context.tenant_id,
                "user_id": tenant_context.user_id,
                "path": request.url.path,
                "method": request.method
            })
            
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
        
        # Add tenant_id to response headers for debugging (optional)
        if hasattr(request.state, "tenant_context"):
            response.headers["X-Tenant-ID"] = request.state.tenant_context.tenant_id
        
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