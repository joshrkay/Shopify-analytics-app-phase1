"""
Role-Based Access Control (RBAC) enforcement for AI Growth Analytics.

CRITICAL SECURITY REQUIREMENTS:
- RBAC MUST be enforced server-side for every protected endpoint
- UI permission gating is NOT security; treat it as UX only
- All permission checks MUST be centralized in this module
- Uses Clerk for authentication and roles

Usage:
    from src.platform.rbac import require_permission, require_any_permission, require_role

    @app.get("/api/admin/plans")
    @require_permission(Permission.ADMIN_PLANS_VIEW)
    async def list_plans(request: Request):
        ...

    @app.post("/api/data/export")
    @require_any_permission(Permission.ANALYTICS_EXPORT, Permission.ADMIN_SYSTEM_CONFIG)
    async def export_data(request: Request):
        ...

    @app.get("/api/admin/system")
    @require_role(Role.ADMIN)
    async def admin_system(request: Request):
        ...
"""

import logging
from functools import wraps
from typing import Callable, Union

from fastapi import Request, HTTPException, status

from src.platform.tenant_context import TenantContext, get_tenant_context
from src.platform.errors import PermissionDeniedError
from src.constants.permissions import (
    Permission,
    Role,
    roles_have_permission,
    get_permissions_for_roles,
)

logger = logging.getLogger(__name__)


class RBACError(PermissionDeniedError):
    """RBAC-specific permission denied error."""

    def __init__(self, required: str, user_roles: list[str]):
        super().__init__(
            message="You do not have permission to perform this action",
            details={"required": required},
        )
        # Log detailed info server-side but don't expose to client
        logger.warning(
            "RBAC check failed",
            extra={
                "required": required,
                "user_roles": user_roles,
            }
        )


def _get_request_from_args(args, kwargs) -> Request:
    """Extract Request object from function arguments."""
    for arg in args:
        if isinstance(arg, Request):
            return arg
    if "request" in kwargs:
        return kwargs["request"]
    raise ValueError("Request object not found in function arguments")


def has_permission(tenant_context: TenantContext, permission: Permission) -> bool:
    """
    Check if tenant context has the specified permission.

    Checks data-driven resolved_permissions first (Story 5.5.1).
    Falls back to hardcoded ROLE_PERMISSIONS matrix if resolved_permissions is None.

    Args:
        tenant_context: The current tenant context from JWT
        permission: The permission to check

    Returns:
        True if any of the user's roles grant this permission
    """
    resolved = getattr(tenant_context, "resolved_permissions", None)
    if resolved is not None:
        return permission.value in resolved
    return roles_have_permission(tenant_context.roles, permission)


def has_any_permission(tenant_context: TenantContext, permissions: list[Permission]) -> bool:
    """
    Check if tenant context has any of the specified permissions.

    Checks data-driven resolved_permissions first (Story 5.5.1).
    Falls back to hardcoded ROLE_PERMISSIONS matrix if resolved_permissions is None.

    Args:
        tenant_context: The current tenant context from JWT
        permissions: List of permissions to check

    Returns:
        True if any of the user's roles grant any of the permissions
    """
    resolved = getattr(tenant_context, "resolved_permissions", None)
    if resolved is not None:
        return any(p.value in resolved for p in permissions)
    user_permissions = get_permissions_for_roles(tenant_context.roles)
    return bool(user_permissions.intersection(permissions))


def has_all_permissions(tenant_context: TenantContext, permissions: list[Permission]) -> bool:
    """
    Check if tenant context has all of the specified permissions.

    Checks data-driven resolved_permissions first (Story 5.5.1).
    Falls back to hardcoded ROLE_PERMISSIONS matrix if resolved_permissions is None.

    Args:
        tenant_context: The current tenant context from JWT
        permissions: List of permissions to check

    Returns:
        True if user has all of the specified permissions
    """
    resolved = getattr(tenant_context, "resolved_permissions", None)
    if resolved is not None:
        return all(p.value in resolved for p in permissions)
    user_permissions = get_permissions_for_roles(tenant_context.roles)
    return all(p in user_permissions for p in permissions)


def has_role(tenant_context: TenantContext, role: Role) -> bool:
    """
    Check if tenant context has the specified role.

    Args:
        tenant_context: The current tenant context from JWT
        role: The role to check

    Returns:
        True if user has this role
    """
    return role.value in [r.lower() for r in tenant_context.roles]


def _try_emit_rbac_denied(
    tenant_id: str,
    user_id: str,
    permission_str: str,
    endpoint: str,
    method: str,
    roles: list[str],
) -> None:
    """Emit rbac.denied audit event, never crashing the caller."""
    try:
        from src.database.session import get_db_session_sync
        from src.services.audit_logger import emit_rbac_denied

        session = next(get_db_session_sync())
        try:
            emit_rbac_denied(
                db=session,
                tenant_id=tenant_id,
                user_id=user_id,
                permission=permission_str,
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
        logger.debug(
            "rbac.emit_audit_failed",
            extra={"user_id": user_id, "permission": permission_str},
            exc_info=True,
        )


def require_permission(permission: Permission) -> Callable:
    """
    Decorator to require a specific permission for an endpoint.

    Raises 403 if the user doesn't have the required permission.
    Emits rbac.denied audit event on denial (Story 5.5.5).

    Usage:
        @app.get("/api/billing")
        @require_permission(Permission.BILLING_VIEW)
        async def view_billing(request: Request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = _get_request_from_args(args, kwargs)
            tenant_context = get_tenant_context(request)

            if not has_permission(tenant_context, permission):
                logger.warning(
                    "Permission denied",
                    extra={
                        "tenant_id": tenant_context.tenant_id,
                        "user_id": tenant_context.user_id,
                        "required_permission": permission.value,
                        "user_roles": tenant_context.roles,
                        "path": request.url.path,
                        "method": request.method,
                    }
                )
                _try_emit_rbac_denied(
                    tenant_id=tenant_context.tenant_id,
                    user_id=tenant_context.user_id,
                    permission_str=permission.value,
                    endpoint=request.url.path,
                    method=request.method,
                    roles=tenant_context.roles,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to perform this action"
                )

            logger.debug(
                "Permission check passed",
                extra={
                    "tenant_id": tenant_context.tenant_id,
                    "user_id": tenant_context.user_id,
                    "permission": permission.value,
                }
            )
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_any_permission(*permissions: Permission) -> Callable:
    """
    Decorator to require any of the specified permissions.

    Raises 403 if the user doesn't have at least one of the required permissions.

    Usage:
        @app.get("/api/data")
        @require_any_permission(Permission.ANALYTICS_VIEW, Permission.ADMIN_SYSTEM_CONFIG)
        async def view_data(request: Request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = _get_request_from_args(args, kwargs)
            tenant_context = get_tenant_context(request)

            if not has_any_permission(tenant_context, list(permissions)):
                perm_str = ",".join(p.value for p in permissions)
                logger.warning(
                    "Permission denied (any)",
                    extra={
                        "tenant_id": tenant_context.tenant_id,
                        "user_id": tenant_context.user_id,
                        "required_permissions": [p.value for p in permissions],
                        "user_roles": tenant_context.roles,
                        "path": request.url.path,
                        "method": request.method,
                    }
                )
                _try_emit_rbac_denied(
                    tenant_id=tenant_context.tenant_id,
                    user_id=tenant_context.user_id,
                    permission_str=perm_str,
                    endpoint=request.url.path,
                    method=request.method,
                    roles=tenant_context.roles,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to perform this action"
                )

            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_all_permissions(*permissions: Permission) -> Callable:
    """
    Decorator to require all of the specified permissions.

    Raises 403 if the user doesn't have all of the required permissions.

    Usage:
        @app.post("/api/automation/execute")
        @require_all_permissions(Permission.AUTOMATION_CREATE, Permission.AUTOMATION_EXECUTE)
        async def execute_automation(request: Request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = _get_request_from_args(args, kwargs)
            tenant_context = get_tenant_context(request)

            if not has_all_permissions(tenant_context, list(permissions)):
                perm_str = ",".join(p.value for p in permissions)
                logger.warning(
                    "Permission denied (all)",
                    extra={
                        "tenant_id": tenant_context.tenant_id,
                        "user_id": tenant_context.user_id,
                        "required_permissions": [p.value for p in permissions],
                        "user_roles": tenant_context.roles,
                        "path": request.url.path,
                        "method": request.method,
                    }
                )
                _try_emit_rbac_denied(
                    tenant_id=tenant_context.tenant_id,
                    user_id=tenant_context.user_id,
                    permission_str=perm_str,
                    endpoint=request.url.path,
                    method=request.method,
                    roles=tenant_context.roles,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to perform this action"
                )

            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_role(role: Role) -> Callable:
    """
    Decorator to require a specific role.

    Prefer using require_permission() over require_role() when possible,
    as it's more flexible and easier to refactor permissions later.

    Raises 403 if the user doesn't have the required role.

    Usage:
        @app.get("/api/admin/system")
        @require_role(Role.ADMIN)
        async def admin_system(request: Request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = _get_request_from_args(args, kwargs)
            tenant_context = get_tenant_context(request)

            if not has_role(tenant_context, role):
                logger.warning(
                    "Role check failed",
                    extra={
                        "tenant_id": tenant_context.tenant_id,
                        "user_id": tenant_context.user_id,
                        "required_role": role.value,
                        "user_roles": tenant_context.roles,
                        "path": request.url.path,
                        "method": request.method,
                    }
                )
                _try_emit_rbac_denied(
                    tenant_id=tenant_context.tenant_id,
                    user_id=tenant_context.user_id,
                    permission_str=f"role:{role.value}",
                    endpoint=request.url.path,
                    method=request.method,
                    roles=tenant_context.roles,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to perform this action"
                )

            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_admin(func: Callable) -> Callable:
    """
    Shorthand decorator for admin-only endpoints.

    Equivalent to @require_role(Role.ADMIN).
    """
    return require_role(Role.ADMIN)(func)


def check_permission_or_raise(
    tenant_context: TenantContext,
    permission: Permission,
    request: Request,
) -> None:
    """
    Programmatic permission check that raises HTTPException on failure.

    Use this when you need to check permissions inside a function body
    rather than using a decorator.

    Usage:
        async def complex_handler(request: Request):
            tenant_ctx = get_tenant_context(request)
            # ... do some work ...
            if needs_export:
                check_permission_or_raise(tenant_ctx, Permission.ANALYTICS_EXPORT, request)
            # ... continue ...
    """
    if not has_permission(tenant_context, permission):
        logger.warning(
            "Permission check failed (programmatic)",
            extra={
                "tenant_id": tenant_context.tenant_id,
                "user_id": tenant_context.user_id,
                "required_permission": permission.value,
                "user_roles": tenant_context.roles,
                "path": request.url.path,
                "method": request.method,
            }
        )
        _try_emit_rbac_denied(
            tenant_id=tenant_context.tenant_id,
            user_id=tenant_context.user_id,
            permission_str=permission.value,
            endpoint=request.url.path,
            method=request.method,
            roles=tenant_context.roles,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action"
        )
