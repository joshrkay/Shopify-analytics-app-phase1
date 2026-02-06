"""
Merchant health guard middleware for feature gating based on trust state.

Gates features based on the unified merchant data health state:

    HEALTHY     → All features enabled
    DELAYED     → AI disabled, exports disabled, dashboards allowed
    UNAVAILABLE → All features blocked

Provides:
- MerchantHealthGuard:       Dependency-injection guard for Depends()
- require_merchant_healthy:  Decorator requiring HEALTHY for AI
- require_merchant_available: Decorator requiring not-UNAVAILABLE for dashboards

Error responses are merchant-safe and never expose internal system details.

SECURITY: tenant_id is extracted from JWT via TenantContext.

Usage (dependency injection):
    @router.get("/api/insights")
    async def get_insights(
        request: Request,
        guard: MerchantHealthGuard = Depends(MerchantHealthGuard),
    ):
        guard.require_healthy_for_ai(request)
        ...

Usage (decorator):
    @router.get("/api/insights")
    @require_merchant_healthy()
    async def get_insights(request: Request):
        ...

Story 4.3 - Merchant Data Health Trust Layer
"""

import logging
from functools import wraps
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.database.session import get_db_session
from src.models.merchant_data_health import MerchantHealthState
from src.platform.tenant_context import get_tenant_context

logger = logging.getLogger(__name__)

_DEFAULT_RETRY_AFTER_SECONDS = 300

# ---------------------------------------------------------------------------
# Merchant-safe error messages (no internal details)
# ---------------------------------------------------------------------------

_MSG_AI_DISABLED = (
    "AI insights are temporarily paused while your data is being updated. "
    "They will resume automatically."
)

_MSG_DASHBOARD_BLOCKED = (
    "Your data is temporarily unavailable. "
    "Please try again in a few minutes."
)

_MSG_EXPORT_DISABLED = (
    "Data exports are temporarily unavailable while your data is being updated. "
    "Please try again shortly."
)


# ---------------------------------------------------------------------------
# Internal helper: evaluate merchant health
# ---------------------------------------------------------------------------

def _evaluate_merchant_health(
    request: Request,
) -> "MerchantDataHealthResult":
    """
    Evaluate merchant health and cache on request.state.

    Returns the cached result if already evaluated for this request.
    """
    from src.services.merchant_data_health import (
        MerchantDataHealthResult,
        MerchantDataHealthService,
    )

    cached = getattr(request.state, "merchant_health", None)
    if cached is not None:
        return cached

    tenant_ctx = get_tenant_context(request)
    db_session: Optional[Session] = getattr(request.state, "db", None)

    if db_session is None:
        logger.warning(
            "No database session on request.state; "
            "defaulting to HEALTHY for merchant health",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "path": request.url.path,
            },
        )
        from datetime import datetime, timezone
        result = MerchantDataHealthResult(
            state=MerchantHealthState.HEALTHY,
            message="Your data is up to date.",
            ai_insights_enabled=True,
            dashboards_enabled=True,
            exports_enabled=True,
            evaluated_at=datetime.now(timezone.utc),
        )
        request.state.merchant_health = result
        return result

    service = MerchantDataHealthService(
        db_session=db_session,
        tenant_id=tenant_ctx.tenant_id,
        billing_tier=getattr(tenant_ctx, "billing_tier", "free"),
    )
    result = service.evaluate()
    request.state.merchant_health = result
    return result


# ---------------------------------------------------------------------------
# Dependency-injection guard
# ---------------------------------------------------------------------------

class MerchantHealthGuard:
    """
    FastAPI dependency-injection guard for merchant data health.

    Usage::

        @router.get("/api/insights")
        async def get_insights(
            request: Request,
            guard: MerchantHealthGuard = Depends(MerchantHealthGuard),
        ):
            guard.require_healthy_for_ai(request)
            ...
    """

    def require_healthy_for_ai(self, request: Request) -> None:
        """
        Raise HTTP 503 unless merchant health is HEALTHY.

        AI insights require full data trust.

        Raises:
            HTTPException: 503 when state is DELAYED or UNAVAILABLE.
        """
        result = _evaluate_merchant_health(request)
        if not result.ai_insights_enabled:
            tenant_ctx = get_tenant_context(request)
            logger.warning(
                "AI blocked by merchant health guard",
                extra={
                    "tenant_id": tenant_ctx.tenant_id,
                    "path": request.url.path,
                    "merchant_state": result.state.value,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "ai_insights_paused",
                    "error_code": "AI_INSIGHTS_PAUSED",
                    "message": _MSG_AI_DISABLED,
                    "health_state": result.state.value,
                    "retry_after_seconds": _DEFAULT_RETRY_AFTER_SECONDS,
                },
            )

    def require_available_for_dashboards(self, request: Request) -> None:
        """
        Raise HTTP 503 if merchant health is UNAVAILABLE.

        Dashboards are allowed for HEALTHY and DELAYED states.

        Raises:
            HTTPException: 503 when state is UNAVAILABLE.
        """
        result = _evaluate_merchant_health(request)
        if not result.dashboards_enabled:
            tenant_ctx = get_tenant_context(request)
            logger.warning(
                "Dashboard blocked by merchant health guard",
                extra={
                    "tenant_id": tenant_ctx.tenant_id,
                    "path": request.url.path,
                    "merchant_state": result.state.value,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "data_unavailable",
                    "error_code": "DATA_UNAVAILABLE",
                    "message": _MSG_DASHBOARD_BLOCKED,
                    "health_state": result.state.value,
                    "retry_after_seconds": _DEFAULT_RETRY_AFTER_SECONDS,
                },
            )

    def require_healthy_for_export(self, request: Request) -> None:
        """
        Raise HTTP 503 if merchant health is DELAYED or UNAVAILABLE.

        Exports require full data trust to avoid partial data.

        Raises:
            HTTPException: 503 when state is not HEALTHY.
        """
        result = _evaluate_merchant_health(request)
        if not result.exports_enabled:
            tenant_ctx = get_tenant_context(request)
            logger.warning(
                "Export blocked by merchant health guard",
                extra={
                    "tenant_id": tenant_ctx.tenant_id,
                    "path": request.url.path,
                    "merchant_state": result.state.value,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "export_paused",
                    "error_code": "EXPORT_PAUSED",
                    "message": _MSG_EXPORT_DISABLED,
                    "health_state": result.state.value,
                    "retry_after_seconds": _DEFAULT_RETRY_AFTER_SECONDS,
                },
            )

    def check(self, request: Request) -> "MerchantDataHealthResult":
        """
        Non-blocking check: evaluate and cache the merchant health state
        without raising. Returns the result for caller inspection.
        """
        return _evaluate_merchant_health(request)


# ---------------------------------------------------------------------------
# Decorator: require_merchant_healthy
# ---------------------------------------------------------------------------

def require_merchant_healthy():
    """
    Decorator that blocks requests unless merchant health is HEALTHY.

    Intended for AI insight endpoints that require full data trust.

    Usage::

        @router.get("/api/ai/insights")
        @require_merchant_healthy()
        async def generate_insights(request: Request):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Optional[Request] = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if request is None:
                request = kwargs.get("request")
            if request is None:
                raise ValueError(
                    "Request object not found in function arguments"
                )

            result = _evaluate_merchant_health(request)
            if result.state != MerchantHealthState.HEALTHY:
                tenant_ctx = get_tenant_context(request)
                logger.warning(
                    "Request blocked: merchant health not HEALTHY",
                    extra={
                        "tenant_id": tenant_ctx.tenant_id,
                        "path": request.url.path,
                        "merchant_state": result.state.value,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "error": "ai_insights_paused",
                        "error_code": "AI_INSIGHTS_PAUSED",
                        "message": _MSG_AI_DISABLED,
                        "health_state": result.state.value,
                        "retry_after_seconds": _DEFAULT_RETRY_AFTER_SECONDS,
                    },
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Decorator: require_merchant_available
# ---------------------------------------------------------------------------

def require_merchant_available():
    """
    Decorator that blocks requests when merchant health is UNAVAILABLE.

    DELAYED state is allowed through. Use for dashboard and analytics
    endpoints where slightly stale data is acceptable.

    Usage::

        @router.get("/api/analytics/orders")
        @require_merchant_available()
        async def get_orders(request: Request):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Optional[Request] = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if request is None:
                request = kwargs.get("request")
            if request is None:
                raise ValueError(
                    "Request object not found in function arguments"
                )

            result = _evaluate_merchant_health(request)
            if result.state == MerchantHealthState.UNAVAILABLE:
                tenant_ctx = get_tenant_context(request)
                logger.warning(
                    "Request blocked: merchant health UNAVAILABLE",
                    extra={
                        "tenant_id": tenant_ctx.tenant_id,
                        "path": request.url.path,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "error": "data_unavailable",
                        "error_code": "DATA_UNAVAILABLE",
                        "message": _MSG_DASHBOARD_BLOCKED,
                        "health_state": result.state.value,
                        "retry_after_seconds": _DEFAULT_RETRY_AFTER_SECONDS,
                    },
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
