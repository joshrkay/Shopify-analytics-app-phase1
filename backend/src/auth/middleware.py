"""
FastAPI authentication middleware for Clerk JWT verification.

This module provides:
- Starlette middleware for request-level authentication
- FastAPI dependencies for route-level authentication
- Support for both session-based and token-based auth

Request Flow:
1. Middleware extracts JWT from Authorization header or cookie
2. JWT verified using clerk_verifier
3. Session checked against revocation list
4. AuthContext resolved and attached to request.state
5. Route handlers access AuthContext via dependency injection

Usage:

    # Add middleware to FastAPI app
    app.add_middleware(ClerkAuthMiddleware)

    # Require authentication in routes
    @router.get("/protected")
    async def protected_route(user: User = Depends(require_auth)):
        return {"user_id": user.id}

    # Optional authentication
    @router.get("/public")
    async def public_route(auth: AuthContext = Depends(get_auth_context)):
        if auth.is_authenticated:
            return {"user": auth.user_id}
        return {"message": "Welcome, guest"}
"""

import os
import logging
from typing import Optional, Callable, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.auth.clerk_verifier import (
    ClerkJWTVerifier,
    ClerkVerificationError,
    get_verifier,
)
from src.auth.jwt import extract_claims
from src.auth.context_resolver import AuthContext, AuthContextResolver, ANONYMOUS_CONTEXT
from src.auth.token_service import get_token_service
from src.database.session import get_db_session_sync

logger = logging.getLogger(__name__)

# HTTP Bearer security scheme
security = HTTPBearer(auto_error=False)

# Paths that don't require authentication
EXEMPT_PATHS = {
    "/health",
    "/api/health",
    "/api/webhooks/clerk",
    "/api/webhooks/clerk/health",
    "/api/webhooks/shopify",
    "/docs",
    "/openapi.json",
    "/redoc",
}

# Path prefixes that don't require authentication
EXEMPT_PREFIXES = [
    "/api/webhooks/",
    "/static/",
]


def is_exempt_path(path: str) -> bool:
    """Check if path is exempt from authentication."""
    if path in EXEMPT_PATHS:
        return True

    for prefix in EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return True

    return False


class ClerkAuthMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware for Clerk JWT authentication.

    Extracts JWT from Authorization header, verifies it using Clerk's JWKS,
    checks against revocation list, and attaches AuthContext to request.state.

    If authentication fails for protected routes, returns 401 response.
    For exempt paths, allows request to proceed without authentication.
    """

    def __init__(
        self,
        app,
        verifier: Optional[ClerkJWTVerifier] = None,
        exempt_paths: Optional[set] = None,
        exempt_prefixes: Optional[list] = None,
        cookie_name: str = "__session",
    ):
        """
        Initialize middleware.

        Args:
            app: ASGI application
            verifier: ClerkJWTVerifier instance (uses singleton if not provided)
            exempt_paths: Set of paths to exempt from authentication
            exempt_prefixes: List of path prefixes to exempt
            cookie_name: Name of session cookie (Clerk default: __session)
        """
        super().__init__(app)
        self._verifier = verifier
        self._exempt_paths = exempt_paths or EXEMPT_PATHS
        self._exempt_prefixes = exempt_prefixes or EXEMPT_PREFIXES
        self._cookie_name = cookie_name
        self._token_service = get_token_service()

    def _get_verifier(self) -> ClerkJWTVerifier:
        """Get verifier instance (lazy loading)."""
        if self._verifier is None:
            self._verifier = get_verifier()
        return self._verifier

    def _is_exempt(self, path: str) -> bool:
        """Check if path is exempt from authentication."""
        if path in self._exempt_paths:
            return True

        for prefix in self._exempt_prefixes:
            if path.startswith(prefix):
                return True

        return False

    def _extract_token(self, request: Request) -> Optional[str]:
        """
        Extract JWT from request.

        Checks in order:
        1. Authorization header (Bearer token)
        2. Session cookie (__session)

        Args:
            request: Incoming request

        Returns:
            JWT string or None if not found
        """
        # 1. Check Authorization header
        auth_header = request.headers.get("Authorization")
        if auth_header:
            if auth_header.startswith("Bearer "):
                return auth_header[7:]
            return auth_header

        # 2. Check session cookie
        cookie_token = request.cookies.get(self._cookie_name)
        if cookie_token:
            return cookie_token

        return None

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """
        Process request through authentication middleware.

        Args:
            request: Incoming request
            call_next: Next middleware/route handler

        Returns:
            Response from downstream handler or error response
        """
        path = request.url.path

        # Set default anonymous context
        request.state.auth_context = ANONYMOUS_CONTEXT

        # Check if path is exempt
        if self._is_exempt(path):
            return await call_next(request)

        # Extract token
        token = self._extract_token(request)

        if not token:
            # No token provided - allow OPTIONS requests and some methods
            if request.method == "OPTIONS":
                return await call_next(request)

            # For other methods, set anonymous context and let route decide
            logger.debug(f"No auth token for {path}")
            return await call_next(request)

        try:
            # Verify token
            verifier = self._get_verifier()
            claims = verifier.verify_token(token)

            # Extract claim data
            extracted = extract_claims(claims)

            # Check revocation
            if self._token_service.is_revoked(
                session_id=extracted.session_id,
                clerk_user_id=extracted.clerk_user_id,
                token_issued_at=extracted.issued_at,
            ):
                logger.warning(
                    "Revoked token used",
                    extra={
                        "clerk_user_id": extracted.clerk_user_id,
                        "session_id": extracted.session_id,
                    },
                )
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={
                        "detail": "Session has been revoked",
                        "error_code": "session_revoked",
                    },
                )

            # Resolve auth context with database
            session = next(get_db_session_sync())
            try:
                resolver = AuthContextResolver(session)
                auth_context = resolver.resolve(extracted, lazy_sync=True)
                session.commit()

                # Attach to request state
                request.state.auth_context = auth_context

                # Record session activity
                self._token_service.record_activity(
                    session_id=extracted.session_id or "",
                    clerk_user_id=extracted.clerk_user_id,
                    expires_at=extracted.expires_at,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("User-Agent"),
                )

                logger.debug(
                    "Authenticated request",
                    extra={
                        "path": path,
                        "clerk_user_id": extracted.clerk_user_id,
                        "tenant_id": auth_context.current_tenant_id,
                    },
                )

            except Exception as e:
                session.rollback()
                logger.error(f"Error resolving auth context: {e}")
                raise
            finally:
                session.close()

            return await call_next(request)

        except ClerkVerificationError as e:
            logger.warning(
                f"Token verification failed: {e.message}",
                extra={"path": path, "error_code": e.error_code},
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "detail": e.message,
                    "error_code": e.error_code,
                },
            )

        except Exception as e:
            logger.error(f"Unexpected auth error: {e}", exc_info=True)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "detail": "Authentication error",
                    "error_code": "auth_error",
                },
            )


# =============================================================================
# FastAPI Dependencies
# =============================================================================


def get_auth_context(request: Request) -> AuthContext:
    """
    FastAPI dependency to get AuthContext from request.

    Returns the AuthContext set by middleware, or ANONYMOUS_CONTEXT
    if no authentication was performed.

    Usage:
        @router.get("/data")
        async def get_data(auth: AuthContext = Depends(get_auth_context)):
            if auth.is_authenticated:
                ...
    """
    return getattr(request.state, "auth_context", ANONYMOUS_CONTEXT)


def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> AuthContext:
    """
    FastAPI dependency that requires authentication.

    Raises HTTPException 401 if user is not authenticated.

    Usage:
        @router.get("/protected")
        async def protected_route(auth: AuthContext = Depends(require_auth)):
            return {"user": auth.user_id}
    """
    auth_context = get_auth_context(request)

    if not auth_context.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return auth_context


def require_tenant(
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    """
    FastAPI dependency that requires authenticated user with tenant context.

    Raises HTTPException 400 if no tenant is selected.

    Usage:
        @router.get("/tenant-data")
        async def get_tenant_data(auth: AuthContext = Depends(require_tenant)):
            tenant_id = auth.current_tenant_id
            ...
    """
    if not auth.current_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No tenant selected. Please select a tenant.",
            headers={"X-Tenant-Required": "true"},
        )

    return auth


def get_current_user(
    auth: AuthContext = Depends(require_auth),
):
    """
    FastAPI dependency to get the current authenticated user.

    Returns the User model instance.

    Usage:
        @router.get("/me")
        async def get_me(user: User = Depends(get_current_user)):
            return {"id": user.id, "email": user.email}
    """
    if not auth.user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return auth.user


def get_current_tenant_id(
    auth: AuthContext = Depends(require_tenant),
) -> str:
    """
    FastAPI dependency to get the current tenant ID.

    Usage:
        @router.get("/data")
        async def get_data(tenant_id: str = Depends(get_current_tenant_id)):
            ...
    """
    return auth.current_tenant_id


# =============================================================================
# Permission Checking Dependencies
# =============================================================================


def require_permission(permission):
    """
    Create a dependency that requires a specific permission.

    Usage:
        @router.delete("/resource")
        async def delete_resource(
            auth: AuthContext = Depends(require_permission(Permission.RESOURCE_DELETE))
        ):
            ...
    """
    def dependency(auth: AuthContext = Depends(require_tenant)) -> AuthContext:
        if not auth.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value}",
            )
        return auth

    return dependency


def require_any_permission(*permissions):
    """
    Create a dependency that requires any of the specified permissions.

    Usage:
        @router.get("/resource")
        async def get_resource(
            auth: AuthContext = Depends(require_any_permission(
                Permission.RESOURCE_VIEW,
                Permission.ADMIN_VIEW,
            ))
        ):
            ...
    """
    def dependency(auth: AuthContext = Depends(require_tenant)) -> AuthContext:
        for permission in permissions:
            if auth.has_permission(permission):
                return auth

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied. Required one of: {[p.value for p in permissions]}",
        )

    return dependency


def require_role(role: str):
    """
    Create a dependency that requires a specific role.

    Usage:
        @router.post("/admin-action")
        async def admin_action(
            auth: AuthContext = Depends(require_role("admin"))
        ):
            ...
    """
    def dependency(auth: AuthContext = Depends(require_tenant)) -> AuthContext:
        if role.lower() not in {r.lower() for r in auth.current_roles}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: {role}",
            )
        return auth

    return dependency
