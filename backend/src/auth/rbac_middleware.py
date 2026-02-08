"""
RBAC enforcement middleware for default-deny permission checking.

Provides two complementary enforcement patterns:

1. **Decorator-based** (existing, enhanced): `require_permission`, `require_any_permission`
   decorators on individual route handlers now emit `rbac.denied` audit events.

2. **Middleware-based** (new): `RBACMiddleware` enforces that all protected
   endpoints have declared required permissions via an endpoint registry.
   Endpoints not registered are denied by default (default-deny).

Super admin rules:
- Super admin can access all tenants but MUST have an active tenant context
  selected. Requests without a tenant context are rejected even for super admins.

Story 5.5.5 — RBAC Enforcement Middleware
"""

import logging
from typing import Optional

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, JSONResponse

from src.constants.permissions import Permission, Role

logger = logging.getLogger(__name__)

# Paths that bypass RBAC enforcement (auth-exempt or public)
RBAC_EXEMPT_PATHS = {
    "/health",
    "/api/health",
    "/api/webhooks/clerk",
    "/api/webhooks/clerk/health",
    "/api/webhooks/shopify",
    "/docs",
    "/openapi.json",
    "/redoc",
}

RBAC_EXEMPT_PREFIXES = [
    "/api/webhooks/",
    "/static/",
]

# Endpoint permission registry: maps (method, path_pattern) to required permissions.
# Populated via `register_endpoint_permissions()` at app startup.
# Endpoints not in this registry are denied by default.
_endpoint_permissions: dict[tuple[str, str], list[Permission]] = {}

# Set of (method, path_pattern) tuples that are explicitly public (no perms needed,
# but still require authentication — auth-exempt paths are handled separately).
_public_endpoints: set[tuple[str, str]] = set()


def register_endpoint_permissions(
    method: str,
    path: str,
    permissions: list[Permission],
) -> None:
    """
    Register required permissions for an endpoint.

    Args:
        method: HTTP method (GET, POST, etc.)
        path: Route path pattern (e.g. "/api/stores/{store_id}")
        permissions: List of permissions required (any of them grants access)
    """
    key = (method.upper(), path)
    _endpoint_permissions[key] = permissions


def register_public_endpoint(method: str, path: str) -> None:
    """
    Register an endpoint as public (requires auth but no specific permissions).

    Args:
        method: HTTP method
        path: Route path pattern
    """
    _public_endpoints.add((method.upper(), path))


def clear_endpoint_registry() -> None:
    """Clear endpoint registrations. Useful for tests."""
    _endpoint_permissions.clear()
    _public_endpoints.clear()


def _is_rbac_exempt(path: str) -> bool:
    """Check if path is exempt from RBAC enforcement."""
    if path in RBAC_EXEMPT_PATHS:
        return True
    for prefix in RBAC_EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _match_path(request_path: str, pattern: str) -> bool:
    """
    Simple path pattern matching.

    Matches path patterns like "/api/stores/{store_id}" against
    actual paths like "/api/stores/abc-123".
    """
    pattern_parts = pattern.rstrip("/").split("/")
    path_parts = request_path.rstrip("/").split("/")

    if len(pattern_parts) != len(path_parts):
        return False

    for pattern_part, path_part in zip(pattern_parts, path_parts):
        if pattern_part.startswith("{") and pattern_part.endswith("}"):
            continue  # Path parameter — matches anything
        if pattern_part != path_part:
            return False

    return True


def _find_endpoint_permissions(
    method: str, path: str
) -> tuple[bool, Optional[list[Permission]]]:
    """
    Find registered permissions for a request.

    Returns:
        (found, permissions): found=True if endpoint is registered,
        permissions=list of required permissions (empty list for public endpoints).
    """
    method = method.upper()

    # Check public endpoints first
    for pub_method, pub_path in _public_endpoints:
        if pub_method == method and _match_path(path, pub_path):
            return True, []

    # Check permission-protected endpoints
    for (reg_method, reg_path), perms in _endpoint_permissions.items():
        if reg_method == method and _match_path(path, reg_path):
            return True, perms

    return False, None


def validate_super_admin_context(
    tenant_context,
) -> Optional[str]:
    """
    Validate super admin tenant context.

    Super admins can access all tenants but MUST have an active tenant
    context selected. Returns error message if validation fails, None if OK.

    Args:
        tenant_context: The TenantContext from the request

    Returns:
        Error message string if invalid, None if valid
    """
    roles_lower = [r.lower() for r in tenant_context.roles]
    if Role.SUPER_ADMIN.value not in roles_lower:
        return None  # Not a super admin, skip validation

    if not tenant_context.tenant_id:
        return "Super admin must select an active tenant context"

    return None


def _emit_rbac_denied_audit(
    tenant_id: str,
    user_id: str,
    permission: str,
    endpoint: str,
    method: str,
    roles: list[str],
) -> None:
    """
    Emit rbac.denied audit event. Runs in try/except to never crash the request.
    """
    try:
        from src.database.session import get_db_session_sync
        from src.services.audit_logger import emit_rbac_denied

        session = next(get_db_session_sync())
        try:
            emit_rbac_denied(
                db=session,
                tenant_id=tenant_id,
                user_id=user_id,
                permission=permission,
                endpoint=endpoint,
                method=method,
                roles=roles,
            )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()
    except Exception:
        logger.warning(
            "rbac_middleware.emit_audit_failed",
            extra={
                "user_id": user_id,
                "tenant_id": tenant_id,
                "permission": permission,
                "endpoint": endpoint,
            },
            exc_info=True,
        )


class RBACMiddleware(BaseHTTPMiddleware):
    """
    Default-deny RBAC enforcement middleware.

    For every non-exempt request:
    1. Checks if the endpoint is registered in the permission registry
    2. If not registered, denies by default (403)
    3. If registered, checks user permissions against required permissions
    4. Super admin must have an active tenant context
    5. All denials emit `rbac.denied` audit events

    This middleware runs AFTER authentication middleware, so
    `request.state.tenant_context` is expected to be set.

    Story 5.5.5 — RBAC Enforcement Middleware
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        method = request.method

        # Skip exempt paths
        if _is_rbac_exempt(path):
            return await call_next(request)

        # Skip OPTIONS requests (CORS preflight)
        if method == "OPTIONS":
            return await call_next(request)

        # Get tenant context — may not exist if auth failed or is anonymous
        tenant_context = getattr(request.state, "tenant_context", None)
        if tenant_context is None:
            # No tenant context = not authenticated, let auth middleware handle
            return await call_next(request)

        # Validate super admin has tenant context
        super_admin_error = validate_super_admin_context(tenant_context)
        if super_admin_error:
            logger.warning(
                "Super admin missing tenant context",
                extra={
                    "user_id": tenant_context.user_id,
                    "path": path,
                    "method": method,
                },
            )
            _emit_rbac_denied_audit(
                tenant_id="none",
                user_id=tenant_context.user_id,
                permission="tenant_context_required",
                endpoint=path,
                method=method,
                roles=tenant_context.roles,
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": super_admin_error,
                    "error_code": "TENANT_CONTEXT_REQUIRED",
                },
            )

        # Look up endpoint in registry
        found, required_permissions = _find_endpoint_permissions(method, path)

        if not found:
            # Default deny: endpoint not registered
            logger.warning(
                "RBAC default deny: unregistered endpoint",
                extra={
                    "user_id": tenant_context.user_id,
                    "tenant_id": tenant_context.tenant_id,
                    "path": path,
                    "method": method,
                    "roles": tenant_context.roles,
                },
            )
            _emit_rbac_denied_audit(
                tenant_id=tenant_context.tenant_id,
                user_id=tenant_context.user_id,
                permission="unregistered_endpoint",
                endpoint=path,
                method=method,
                roles=tenant_context.roles,
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": "You do not have permission to perform this action",
                    "error_code": "RBAC_DENIED",
                },
            )

        # Public endpoint (no permissions needed, just auth)
        if not required_permissions:
            return await call_next(request)

        # Check permissions (any of the required permissions grants access)
        from src.platform.rbac import has_any_permission
        if has_any_permission(tenant_context, required_permissions):
            return await call_next(request)

        # Permission denied
        perm_values = [p.value for p in required_permissions]
        logger.warning(
            "RBAC permission denied",
            extra={
                "user_id": tenant_context.user_id,
                "tenant_id": tenant_context.tenant_id,
                "required_permissions": perm_values,
                "user_roles": tenant_context.roles,
                "path": path,
                "method": method,
            },
        )
        _emit_rbac_denied_audit(
            tenant_id=tenant_context.tenant_id,
            user_id=tenant_context.user_id,
            permission=",".join(perm_values),
            endpoint=path,
            method=method,
            roles=tenant_context.roles,
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "detail": "You do not have permission to perform this action",
                "error_code": "RBAC_DENIED",
            },
        )
