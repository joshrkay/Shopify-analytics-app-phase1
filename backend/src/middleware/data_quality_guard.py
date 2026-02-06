"""
Data quality guard middleware for protecting consumers from bad data.

Blocks or degrades downstream features based on DataQualityState
(aggregated from freshness, volume anomaly, and metric consistency checks):

- FAIL -> Block dashboards, disable AI insights, return 503 on analytics APIs
- WARN -> Allow dashboards with warning banner, disable AI insights
- PASS -> All features enabled

Provides:
- require_quality_pass:    Decorator that blocks requests with HTTP 503 when
                           quality state is FAIL
- DataQualityGuard:        Dependency-injection guard for use with Depends()
- check_data_quality:      Standalone function that evaluates quality and
                           attaches result to request.state

Error responses are human-readable and never expose internal system details.

SECURITY: tenant_id is always extracted from JWT via TenantContext, never from
request body or query parameters.

Usage (decorator):
    @router.get("/api/analytics/orders")
    @require_quality_pass()
    async def get_orders(request: Request):
        ...

Usage (dependency injection):
    @router.get("/api/analytics/overview")
    async def get_overview(
        request: Request,
        guard: DataQualityGuard = Depends(DataQualityGuard),
    ):
        result = guard.require_pass(request)
        # result.has_warnings tells the frontend to show a banner
        ...
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from typing import Callable, List, Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.api.dq.service import (
    AnomalyCheckResult,
    DQService,
    DataQualityVerdict,
    FreshnessCheckResult,
)
from src.database.session import get_db_session
from src.models.dq_models import DataQualityState
from src.platform.tenant_context import get_tenant_context

logger = logging.getLogger(__name__)

# Default retry hint returned in 503 responses (seconds).
_DEFAULT_RETRY_AFTER_SECONDS = 300


# ---------------------------------------------------------------------------
# Human-readable messages (never expose internal details)
# ---------------------------------------------------------------------------

_MSG_QUALITY_FAIL = (
    "Your analytics are temporarily unavailable because we detected a data "
    "quality issue. Our team is investigating and it will be resolved shortly."
)

_MSG_QUALITY_WARN = (
    "Some data quality checks have warnings. Results are available but "
    "may not fully reflect the latest changes."
)

_MSG_AI_DISABLED_FAIL = (
    "AI insights are paused because we detected a data quality issue. "
    "They will resume automatically once the issue is resolved."
)

_MSG_AI_DISABLED_WARN = (
    "AI insights are temporarily paused while we verify data quality. "
    "They will resume automatically once verification completes."
)


# ---------------------------------------------------------------------------
# Guard result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DataQualityCheckResult:
    """
    Result of a data-quality evaluation for a tenant.

    Attached to ``request.state.data_quality`` by
    :func:`check_data_quality` so downstream handlers can inspect it.
    """

    state: DataQualityState
    is_passed: bool
    has_warnings: bool = False
    is_failed: bool = False
    warning_message: Optional[str] = None
    failing_checks: List[str] = field(default_factory=list)
    ai_allowed: bool = True
    dashboard_allowed: bool = True
    dashboard_warning: Optional[str] = None
    verdict: Optional[DataQualityVerdict] = None
    evaluated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "is_passed": self.is_passed,
            "has_warnings": self.has_warnings,
            "is_failed": self.is_failed,
            "warning_message": self.warning_message,
            "failing_checks": self.failing_checks,
            "ai_allowed": self.ai_allowed,
            "dashboard_allowed": self.dashboard_allowed,
            "dashboard_warning": self.dashboard_warning,
        }


# ---------------------------------------------------------------------------
# Core evaluation function
# ---------------------------------------------------------------------------

def check_data_quality(
    request: Request,
    freshness_results: Optional[List[FreshnessCheckResult]] = None,
    anomaly_results: Optional[List[AnomalyCheckResult]] = None,
    verdict: Optional[DataQualityVerdict] = None,
) -> DataQualityCheckResult:
    """
    Evaluate data quality for the current tenant and attach the result
    to ``request.state.data_quality``.

    Accepts either a pre-computed verdict or raw check results. When neither
    is provided, returns PASS (no checks = no issues).

    Args:
        request:            The incoming FastAPI request.
        freshness_results:  Optional freshness check results.
        anomaly_results:    Optional anomaly check results.
        verdict:            Optional pre-computed DataQualityVerdict.

    Returns:
        :class:`DataQualityCheckResult` summarising the evaluation.
    """
    now = datetime.now(timezone.utc)

    if verdict is None:
        verdict = DQService.aggregate_quality_state(
            freshness_results=freshness_results or [],
            anomaly_results=anomaly_results or [],
        )

    if verdict.state == DataQualityState.FAIL:
        result = DataQualityCheckResult(
            state=DataQualityState.FAIL,
            is_passed=False,
            is_failed=True,
            failing_checks=verdict.failing_checks,
            ai_allowed=False,
            dashboard_allowed=False,
            verdict=verdict,
            evaluated_at=now,
        )
    elif verdict.state == DataQualityState.WARN:
        result = DataQualityCheckResult(
            state=DataQualityState.WARN,
            is_passed=False,
            has_warnings=True,
            warning_message=_MSG_QUALITY_WARN,
            failing_checks=verdict.failing_checks,
            ai_allowed=False,
            dashboard_allowed=True,
            dashboard_warning=_MSG_QUALITY_WARN,
            verdict=verdict,
            evaluated_at=now,
        )
    else:
        result = DataQualityCheckResult(
            state=DataQualityState.PASS_STATE,
            is_passed=True,
            ai_allowed=True,
            dashboard_allowed=True,
            verdict=verdict,
            evaluated_at=now,
        )

    request.state.data_quality = result

    tenant_ctx = get_tenant_context(request)
    logger.info(
        "Data quality evaluated",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "path": request.url.path,
            "state": verdict.state.value,
            "total_checks": verdict.total_checks,
            "failure_count": verdict.failure_count,
            "warning_count": verdict.warning_count,
        },
    )

    return result


# ---------------------------------------------------------------------------
# Decorator: require_quality_pass
# ---------------------------------------------------------------------------

def require_quality_pass():
    """
    Decorator that blocks requests with HTTP 503 when quality state is FAIL.

    WARN state is allowed through with a warning attached to
    ``request.state.data_quality``.

    Usage::

        @router.get("/api/analytics/orders")
        @require_quality_pass()
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

            # Use pre-computed result if available, otherwise evaluate.
            quality_result = getattr(request.state, "data_quality", None)
            if quality_result is None:
                quality_result = check_data_quality(request)

            if quality_result.is_failed:
                tenant_ctx = get_tenant_context(request)
                logger.warning(
                    "Request blocked: data quality FAIL",
                    extra={
                        "tenant_id": tenant_ctx.tenant_id,
                        "path": request.url.path,
                        "failing_checks": quality_result.failing_checks,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "error": "data_quality_failed",
                        "error_code": "DATA_QUALITY_FAILED",
                        "message": _MSG_QUALITY_FAIL,
                        "status": "quality_failed",
                        "failing_checks": quality_result.failing_checks,
                        "retry_after_seconds": _DEFAULT_RETRY_AFTER_SECONDS,
                    },
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Dependency-injection guard
# ---------------------------------------------------------------------------

class DataQualityGuard:
    """
    FastAPI dependency-injection guard for data quality.

    Designed for use with ``Depends()`` in route signatures, following the
    same DI pattern used by :class:`DataAvailabilityGuard`.

    Usage::

        @router.get("/api/analytics/overview")
        async def get_overview(
            request: Request,
            guard: DataQualityGuard = Depends(DataQualityGuard),
        ):
            result = guard.require_pass(request)
            ...
    """

    def require_pass(
        self,
        request: Request,
        verdict: Optional[DataQualityVerdict] = None,
    ) -> DataQualityCheckResult:
        """
        Check quality and raise HTTP 503 if state is FAIL.

        WARN state is allowed through; a warning is attached to
        ``request.state.data_quality``.

        Returns:
            The :class:`DataQualityCheckResult` for further inspection.

        Raises:
            HTTPException: 503 when quality state is FAIL.
        """
        quality_result = check_data_quality(request, verdict=verdict)

        if quality_result.is_failed:
            tenant_ctx = get_tenant_context(request)
            logger.warning(
                "Guard blocked request: data quality FAIL",
                extra={
                    "tenant_id": tenant_ctx.tenant_id,
                    "path": request.url.path,
                    "failing_checks": quality_result.failing_checks,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "data_quality_failed",
                    "error_code": "DATA_QUALITY_FAILED",
                    "message": _MSG_QUALITY_FAIL,
                    "status": "quality_failed",
                    "failing_checks": quality_result.failing_checks,
                    "retry_after_seconds": _DEFAULT_RETRY_AFTER_SECONDS,
                },
            )

        return quality_result

    def require_ai_allowed(
        self,
        request: Request,
        verdict: Optional[DataQualityVerdict] = None,
    ) -> DataQualityCheckResult:
        """
        Check quality and raise HTTP 503 if AI insights should be disabled.

        AI is disabled on both FAIL and WARN states.

        Returns:
            The :class:`DataQualityCheckResult`.

        Raises:
            HTTPException: 503 when AI should be disabled (FAIL or WARN).
        """
        quality_result = check_data_quality(request, verdict=verdict)

        if not quality_result.ai_allowed:
            tenant_ctx = get_tenant_context(request)
            message = (
                _MSG_AI_DISABLED_FAIL
                if quality_result.is_failed
                else _MSG_AI_DISABLED_WARN
            )
            logger.warning(
                "Guard blocked AI: data quality %s",
                quality_result.state.value,
                extra={
                    "tenant_id": tenant_ctx.tenant_id,
                    "path": request.url.path,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "ai_quality_blocked",
                    "error_code": "AI_QUALITY_BLOCKED",
                    "message": message,
                    "status": quality_result.state.value,
                    "retry_after_seconds": _DEFAULT_RETRY_AFTER_SECONDS,
                },
            )

        return quality_result

    def check(
        self,
        request: Request,
        verdict: Optional[DataQualityVerdict] = None,
    ) -> DataQualityCheckResult:
        """
        Non-blocking check: evaluate quality and attach the result to
        ``request.state`` without raising.  Callers can inspect the returned
        :class:`DataQualityCheckResult` to adapt their behaviour.
        """
        return check_data_quality(request, verdict=verdict)
