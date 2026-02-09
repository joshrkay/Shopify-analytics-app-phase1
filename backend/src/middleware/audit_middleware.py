"""
GA Audit Middleware — automatically emit audit events for auth + dashboard access.

Intercepts:
- Login success/failure (via TenantContextMiddleware outcome)
- Token issue / refresh / revoke
- Dashboard load attempts (embed token requests)
- Both success and failure paths

REQUIREMENTS:
- No PII leaks (all metadata sanitized by audit_logger emitters)
- Metadata includes reason codes for failures
- All events include correlation_id

This middleware is added AFTER TenantContextMiddleware so it can inspect
the authenticated request state.
"""

import logging
import uuid
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.models.audit_log import generate_correlation_id

logger = logging.getLogger(__name__)


class GAAuditMiddleware(BaseHTTPMiddleware):
    """
    Middleware that automatically emits GA audit events for auth + dashboard access.

    Intercepts request/response lifecycle and emits events to ga_audit_logs.
    Designed to never crash the request flow — all audit writes are wrapped
    in try/except.
    """

    # Paths that map to auth events
    AUTH_PATHS = {
        "/auth/refresh-jwt": "jwt_refresh",
        "/api/v1/embed/token": "jwt_issued",
        "/api/v1/embed/token/refresh": "jwt_refresh",
        "/auth/revoke-tokens": "jwt_revoked",
    }

    # Paths that map to dashboard events
    DASHBOARD_PATHS = {
        "/api/v1/embed/token": "dashboard_access",
        "/api/dashboards-allowed": "dashboard_list",
    }

    # Skip audit for these paths
    SKIP_PATHS = frozenset({
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/v1/embed/health",
    })

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request and emit appropriate GA audit events."""
        path = request.url.path

        # Skip non-auditable paths
        if path in self.SKIP_PATHS or path.startswith("/api/webhooks/"):
            return await call_next(request)

        # Generate or retrieve correlation ID
        correlation_id = (
            request.headers.get("X-Correlation-ID")
            or generate_correlation_id()
        )

        # Attach correlation_id to request state for downstream use
        if not hasattr(request.state, "correlation_id"):
            request.state.correlation_id = correlation_id

        # Execute the request
        response = await call_next(request)

        # Emit audit events based on path and outcome
        try:
            await self._emit_audit_events(request, response, path, correlation_id)
        except Exception:
            # Never crash the request flow due to audit
            logger.debug(
                "ga_audit_middleware_emit_failed",
                extra={"path": path},
                exc_info=True,
            )

        return response

    async def _emit_audit_events(
        self,
        request: Request,
        response: Response,
        path: str,
        correlation_id: str,
    ) -> None:
        """Emit audit events based on request path and response status."""
        status_code = response.status_code
        success = 200 <= status_code < 400

        # Extract tenant context (may not exist if auth failed)
        tenant_id, user_id, access_surface = self._extract_context(request)

        # Auth events
        if path in self.AUTH_PATHS:
            event_kind = self.AUTH_PATHS[path]
            await self._emit_auth_event(
                event_kind=event_kind,
                tenant_id=tenant_id,
                user_id=user_id,
                access_surface=access_surface,
                success=success,
                status_code=status_code,
                request=request,
                correlation_id=correlation_id,
            )

        # Dashboard events
        if path in self.DASHBOARD_PATHS:
            dashboard_id = self._extract_dashboard_id(request)
            await self._emit_dashboard_event(
                tenant_id=tenant_id,
                user_id=user_id,
                dashboard_id=dashboard_id,
                access_surface=access_surface,
                success=success,
                status_code=status_code,
                correlation_id=correlation_id,
            )

        # Login events (auth middleware sets tenant_context on success)
        if self._is_authenticated_request(request):
            if not hasattr(request.state, "_ga_login_logged"):
                await self._emit_login_success(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    access_surface=access_surface,
                    request=request,
                    correlation_id=correlation_id,
                )
                request.state._ga_login_logged = True

        # Failed auth (no tenant context = auth failure)
        elif status_code == 403 and not self._is_authenticated_request(request):
            await self._emit_login_failed(
                tenant_id=tenant_id,
                user_id=user_id,
                access_surface=access_surface,
                status_code=status_code,
                request=request,
                correlation_id=correlation_id,
            )

    def _extract_context(self, request: Request) -> tuple[
        Optional[str], Optional[str], str
    ]:
        """Extract tenant_id, user_id, access_surface from request."""
        tenant_id = None
        user_id = None
        access_surface = "external_app"

        if hasattr(request.state, "tenant_context"):
            ctx = request.state.tenant_context
            tenant_id = ctx.tenant_id
            user_id = ctx.user_id

        # Detect access surface from path or referer
        if request.url.path.startswith("/api/v1/embed"):
            access_surface = "shopify_embed"

        return tenant_id, user_id, access_surface

    def _extract_dashboard_id(self, request: Request) -> Optional[str]:
        """Extract dashboard_id from request body or query params."""
        # From query params
        dashboard_id = request.query_params.get("dashboard_id")
        if dashboard_id:
            return dashboard_id

        # From parsed body (if available on request state)
        if hasattr(request.state, "parsed_body"):
            body = request.state.parsed_body
            if isinstance(body, dict):
                return body.get("dashboard_id")

        return None

    def _is_authenticated_request(self, request: Request) -> bool:
        """Check if the request has a valid tenant context."""
        return hasattr(request.state, "tenant_context")

    def _get_ip_address(self, request: Request) -> Optional[str]:
        """Extract client IP from request."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else None

    async def _emit_auth_event(
        self,
        event_kind: str,
        tenant_id: Optional[str],
        user_id: Optional[str],
        access_surface: str,
        success: bool,
        status_code: int,
        request: Request,
        correlation_id: str,
    ) -> None:
        """Emit auth-related GA audit events."""
        from src.database.session import get_db_session_sync
        from src.services.audit_logger import (
            emit_ga_jwt_issued,
            emit_ga_jwt_refresh,
            emit_ga_jwt_revoked,
        )

        db_gen = get_db_session_sync()
        db = next(db_gen)
        try:
            if event_kind == "jwt_issued" and success:
                dashboard_id = self._extract_dashboard_id(request)
                emit_ga_jwt_issued(
                    db=db,
                    tenant_id=tenant_id or "unknown",
                    user_id=user_id or "unknown",
                    dashboard_id=dashboard_id,
                    access_surface=access_surface,
                    correlation_id=correlation_id,
                )
            elif event_kind == "jwt_refresh":
                reason = None if success else f"http_{status_code}"
                emit_ga_jwt_refresh(
                    db=db,
                    tenant_id=tenant_id or "unknown",
                    user_id=user_id or "unknown",
                    access_surface=access_surface,
                    success=success,
                    reason=reason,
                    correlation_id=correlation_id,
                )
            elif event_kind == "jwt_revoked" and success:
                emit_ga_jwt_revoked(
                    db=db,
                    tenant_id=tenant_id or "unknown",
                    user_id=user_id or "unknown",
                    reason="user_initiated",
                    revoked_by=user_id or "unknown",
                    correlation_id=correlation_id,
                )
        except Exception:
            logger.debug("ga_audit_auth_event_failed", exc_info=True)
        finally:
            db.close()

    async def _emit_dashboard_event(
        self,
        tenant_id: Optional[str],
        user_id: Optional[str],
        dashboard_id: Optional[str],
        access_surface: str,
        success: bool,
        status_code: int,
        correlation_id: str,
    ) -> None:
        """Emit dashboard-related GA audit events."""
        from src.database.session import get_db_session_sync
        from src.services.audit_logger import (
            emit_dashboard_viewed_ga,
            emit_dashboard_load_failed_ga,
            emit_dashboard_access_denied_ga,
        )

        db_gen = get_db_session_sync()
        db = next(db_gen)
        try:
            if success:
                emit_dashboard_viewed_ga(
                    db=db,
                    tenant_id=tenant_id or "unknown",
                    user_id=user_id or "unknown",
                    dashboard_id=dashboard_id or "unknown",
                    access_surface=access_surface,
                    correlation_id=correlation_id,
                )
            elif status_code == 403:
                emit_dashboard_access_denied_ga(
                    db=db,
                    tenant_id=tenant_id or "unknown",
                    user_id=user_id or "unknown",
                    dashboard_id=dashboard_id or "unknown",
                    reason=f"http_{status_code}",
                    access_surface=access_surface,
                    correlation_id=correlation_id,
                )
            else:
                emit_dashboard_load_failed_ga(
                    db=db,
                    tenant_id=tenant_id or "unknown",
                    user_id=user_id,
                    dashboard_id=dashboard_id,
                    reason=f"http_{status_code}",
                    access_surface=access_surface,
                    correlation_id=correlation_id,
                )
        except Exception:
            logger.debug("ga_audit_dashboard_event_failed", exc_info=True)
        finally:
            db.close()

    async def _emit_login_success(
        self,
        tenant_id: Optional[str],
        user_id: Optional[str],
        access_surface: str,
        request: Request,
        correlation_id: str,
    ) -> None:
        """Emit auth.login_success event."""
        from src.database.session import get_db_session_sync
        from src.services.audit_logger import emit_auth_login_success

        db_gen = get_db_session_sync()
        db = next(db_gen)
        try:
            emit_auth_login_success(
                db=db,
                tenant_id=tenant_id or "unknown",
                user_id=user_id or "unknown",
                access_surface=access_surface,
                ip_address=self._get_ip_address(request),
                user_agent=request.headers.get("User-Agent"),
                correlation_id=correlation_id,
            )
        except Exception:
            logger.debug("ga_audit_login_success_failed", exc_info=True)
        finally:
            db.close()

    async def _emit_login_failed(
        self,
        tenant_id: Optional[str],
        user_id: Optional[str],
        access_surface: str,
        status_code: int,
        request: Request,
        correlation_id: str,
    ) -> None:
        """Emit auth.login_failed event."""
        from src.database.session import get_db_session_sync
        from src.services.audit_logger import emit_auth_login_failed

        db_gen = get_db_session_sync()
        db = next(db_gen)
        try:
            emit_auth_login_failed(
                db=db,
                tenant_id=tenant_id,
                user_id=user_id,
                reason=f"authentication_failed_http_{status_code}",
                access_surface=access_surface,
                ip_address=self._get_ip_address(request),
                user_agent=request.headers.get("User-Agent"),
                correlation_id=correlation_id,
            )
        except Exception:
            logger.debug("ga_audit_login_failed_failed", exc_info=True)
        finally:
            db.close()


# Backward-compatible alias used by main.py
AuditLoggingMiddleware = GAAuditMiddleware
