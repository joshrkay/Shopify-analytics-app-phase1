"""
Entitlement Middleware - FastAPI middleware for API entitlement enforcement.

Provides:
- EntitlementMiddleware: ASGI middleware for request-level enforcement
- require_entitlement: Decorator for endpoint-level feature checks
- require_billing_state: Decorator for billing state requirements

Enforcement points:
- API endpoints
- Background jobs (via context manager)
- Dashboard embeds
- Data exports

Error responses use HTTP 402 (Payment Required) with clear error codes.
"""

import logging
from functools import wraps
from typing import Optional, Callable, List, Any, Dict
from datetime import datetime, timezone

from fastapi import Request, HTTPException, status, Depends
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.entitlements.rules import (
    AccessRules,
    AccessDecision,
    BillingState,
    AccessLevel,
    create_access_rules_from_subscription,
)
from src.entitlements.cache import (
    EntitlementCache,
    CachedEntitlement,
    get_entitlement_cache,
)
from src.entitlements.audit import (
    EntitlementAuditLogger,
    AccessDenialEvent,
    get_audit_logger,
)
from src.entitlements.loader import get_entitlement_loader

logger = logging.getLogger(__name__)


# HTTP 402 Payment Required error response
class PaymentRequiredError(HTTPException):
    """HTTP 402 Payment Required exception with entitlement details."""

    def __init__(
        self,
        detail: str,
        feature: Optional[str] = None,
        billing_state: Optional[str] = None,
        current_plan: Optional[str] = None,
        required_plan: Optional[str] = None,
        upgrade_url: Optional[str] = None,
    ):
        error_response = {
            "error": "entitlement_required",
            "error_code": "PAYMENT_REQUIRED",
            "message": detail,
            "feature": feature,
            "billing_state": billing_state,
            "current_plan": current_plan,
            "required_plan": required_plan,
            "upgrade_url": upgrade_url,
        }
        super().__init__(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=error_response,
        )


class EntitlementContext:
    """
    Context for entitlement checking within a request.

    Stored in request.state.entitlements for access throughout the request.
    """

    def __init__(
        self,
        tenant_id: str,
        access_rules: AccessRules,
        cached: Optional[CachedEntitlement] = None,
    ):
        self.tenant_id = tenant_id
        self.access_rules = access_rules
        self.cached = cached
        self.checked_features: Dict[str, AccessDecision] = {}
        self.warnings_shown = False

    def check_feature(
        self,
        feature_key: str,
        operation: str = "read",
    ) -> AccessDecision:
        """Check feature access with caching."""
        cache_key = f"{feature_key}:{operation}"
        if cache_key not in self.checked_features:
            self.checked_features[cache_key] = self.access_rules.check_feature_access(
                feature_key, operation
            )
        return self.checked_features[cache_key]

    @property
    def billing_state(self) -> BillingState:
        return self.access_rules.billing_state

    @property
    def plan_id(self) -> str:
        return self.access_rules.plan_id

    @property
    def warnings(self) -> List[str]:
        return [w.code for w in self.access_rules.get_warnings()]


class EntitlementMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware for entitlement enforcement.

    Attaches EntitlementContext to request.state for use by endpoints.
    Optionally enforces billing state requirements at the middleware level.

    Usage:
        app = FastAPI()
        app.add_middleware(EntitlementMiddleware)

        @app.get("/api/reports")
        async def get_reports(request: Request):
            ctx = request.state.entitlements
            if not ctx.check_feature("custom_reports").allowed:
                raise PaymentRequiredError(...)
    """

    def __init__(
        self,
        app: ASGIApp,
        excluded_paths: Optional[List[str]] = None,
        enforce_active_billing: bool = False,
        allow_health_checks: bool = True,
    ):
        """
        Initialize middleware.

        Args:
            app: FastAPI/Starlette application
            excluded_paths: Paths to skip entitlement checks (e.g., /health, /billing)
            enforce_active_billing: If True, reject requests for non-active billing states
            allow_health_checks: If True, skip checks for health/webhook endpoints
        """
        super().__init__(app)
        self.excluded_paths = excluded_paths or []
        self.enforce_active_billing = enforce_active_billing
        self.allow_health_checks = allow_health_checks
        self._cache = get_entitlement_cache()
        self._audit_logger = get_audit_logger()

        # Default excluded paths
        self.default_excluded = [
            "/health",
            "/api/health",
            "/api/webhooks",
            "/api/billing/callback",
            "/api/billing/plans",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]

    def _should_skip(self, path: str) -> bool:
        """Check if path should skip entitlement checks."""
        all_excluded = self.default_excluded + self.excluded_paths

        for excluded in all_excluded:
            if path.startswith(excluded):
                return True

        return False

    async def dispatch(self, request: Request, call_next):
        """Process request with entitlement context."""
        path = request.url.path

        # Skip excluded paths
        if self._should_skip(path):
            return await call_next(request)

        # Get tenant context
        tenant_id = self._get_tenant_id(request)
        if not tenant_id:
            # No tenant = unauthenticated or public endpoint
            return await call_next(request)

        # Build entitlement context
        try:
            entitlement_ctx = await self._build_entitlement_context(request, tenant_id)
            request.state.entitlements = entitlement_ctx

            # Optionally enforce active billing
            if self.enforce_active_billing:
                if entitlement_ctx.billing_state not in (
                    BillingState.ACTIVE,
                    BillingState.TRIALING,
                    BillingState.GRACE_PERIOD,
                    BillingState.CANCELED,  # Still has access until period end
                ):
                    self._audit_logger.log_denial(AccessDenialEvent(
                        tenant_id=tenant_id,
                        feature_name="api_access",
                        billing_state=entitlement_ctx.billing_state.value,
                        plan_id=entitlement_ctx.plan_id,
                        endpoint=path,
                        method=request.method,
                        reason="Billing state does not allow API access",
                    ))

                    return JSONResponse(
                        status_code=status.HTTP_402_PAYMENT_REQUIRED,
                        content={
                            "error": "billing_required",
                            "error_code": "SUBSCRIPTION_REQUIRED",
                            "message": "Active subscription required to access this API",
                            "billing_state": entitlement_ctx.billing_state.value,
                            "upgrade_url": "/billing/plans",
                        },
                    )

        except Exception as e:
            # FAIL CLOSED (EC2): entitlement evaluation failure MUST deny
            # access.  Returning 503 ensures the UI shows a clear error
            # rather than silently granting full access.
            logger.critical(
                "Entitlement evaluation failed — fail-closed",
                extra={
                    "tenant_id": tenant_id,
                    "path": path,
                    "error": str(e),
                    "alert_type": "entitlement_eval_failed",
                },
            )

            self._audit_logger.log_denial(AccessDenialEvent(
                tenant_id=tenant_id,
                feature_name="*",
                billing_state="unknown",
                endpoint=path,
                method=request.method,
                reason=f"Entitlement evaluation failed: {e}",
            ))

            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": "ENTITLEMENT_EVAL_FAILED",
                    "error_code": "ENTITLEMENT_EVAL_FAILED",
                    "message": "Unable to verify feature entitlements. Please retry.",
                },
            )

        response = await call_next(request)

        # Add warning headers if applicable
        if hasattr(request.state, 'entitlements') and request.state.entitlements:
            ctx = request.state.entitlements
            if ctx.warnings and not ctx.warnings_shown:
                response.headers["X-Billing-Warnings"] = ",".join(ctx.warnings)
                ctx.warnings_shown = True

        return response

    def _get_tenant_id(self, request: Request) -> Optional[str]:
        """Extract tenant ID from request."""
        # Try request state first (set by auth middleware)
        if hasattr(request.state, 'tenant_id'):
            return request.state.tenant_id

        # Try tenant context
        try:
            from src.platform.tenant_context import get_tenant_context
            ctx = get_tenant_context(request)
            return ctx.tenant_id
        except Exception:
            pass

        return None

    async def _build_entitlement_context(
        self,
        request: Request,
        tenant_id: str,
    ) -> EntitlementContext:
        """Build entitlement context for tenant."""
        # Check cache first
        cached = self._cache.get(tenant_id)
        if cached:
            # Build access rules from cached data
            access_rules = AccessRules(
                tenant_id=tenant_id,
                plan_id=cached.plan_id,
                billing_state=BillingState(cached.billing_state),
                grace_period_ends_on=(
                    datetime.fromisoformat(cached.grace_period_ends_on.replace('Z', '+00:00'))
                    if cached.grace_period_ends_on else None
                ),
                current_period_end=(
                    datetime.fromisoformat(cached.current_period_end.replace('Z', '+00:00'))
                    if cached.current_period_end else None
                ),
                feature_flags_override=self._cache.get_feature_flags_override(tenant_id),
            )
            return EntitlementContext(tenant_id, access_rules, cached)

        # Load from database
        subscription = await self._get_subscription(request, tenant_id)

        # Build access rules from subscription
        access_rules = create_access_rules_from_subscription(
            tenant_id=tenant_id,
            subscription=subscription,
            feature_flags_override=self._cache.get_feature_flags_override(tenant_id),
        )

        # Cache the result
        plan = access_rules.plan
        self._cache.set(tenant_id, CachedEntitlement(
            tenant_id=tenant_id,
            plan_id=access_rules.plan_id,
            plan_name=plan.display_name if plan else "Free",
            billing_state=access_rules.billing_state.value,
            access_level=access_rules.get_access_level().value,
            enabled_features=plan.get_enabled_features() if plan else [],
            restricted_features=plan.get_restricted_features() if plan else [],
            limits={
                "max_dashboards": plan.limits.max_dashboards if plan else 0,
                "max_users": plan.limits.max_users if plan else 0,
                "api_calls_per_month": plan.limits.api_calls_per_month if plan else 0,
            },
            warnings=[w.code for w in access_rules.get_warnings()],
            grace_period_ends_on=(
                access_rules.grace_period_ends_on.isoformat()
                if access_rules.grace_period_ends_on else None
            ),
            current_period_end=(
                access_rules.current_period_end.isoformat()
                if access_rules.current_period_end else None
            ),
        ))

        return EntitlementContext(tenant_id, access_rules)

    async def _get_subscription(self, request: Request, tenant_id: str):
        """Get subscription from database."""
        # Try to get DB session from request
        db_session = getattr(request.state, 'db', None)
        if not db_session:
            return None

        try:
            from src.models.subscription import Subscription, SubscriptionStatus

            return db_session.query(Subscription).filter(
                Subscription.tenant_id == tenant_id,
                Subscription.status.in_([
                    SubscriptionStatus.ACTIVE.value,
                    SubscriptionStatus.PENDING.value,
                    SubscriptionStatus.FROZEN.value,
                ])
            ).first()
        except Exception as e:
            logger.warning(f"Failed to get subscription: {e}")
            return None


def require_entitlement(
    feature_key: str,
    operation: str = "read",
    allow_limited: bool = True,
):
    """
    Decorator to require a specific feature entitlement.

    Args:
        feature_key: Feature to require (e.g., "ai_insights", "data_export")
        operation: Operation type ("read" or "write")
        allow_limited: If True, allow "limited" access level

    Usage:
        @app.get("/api/ai/insights")
        @require_entitlement("ai_insights")
        async def get_insights(request: Request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request in args
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                request = kwargs.get("request")

            if not request:
                raise ValueError("Request object not found in function arguments")

            # Get entitlement context
            ctx: Optional[EntitlementContext] = getattr(request.state, 'entitlements', None)
            if not ctx:
                # Fail-closed: if an endpoint explicitly requires an
                # entitlement but no context was built, deny access rather
                # than silently allowing it.  Unauthenticated/excluded
                # endpoints never reach this decorator because they are
                # excluded at the middleware level.
                raise PaymentRequiredError(
                    detail="Entitlement context unavailable",
                    feature=feature_key,
                    billing_state="unknown",
                )

            # Check feature access
            decision = ctx.check_feature(feature_key, operation)

            if not decision.allowed:
                # Log denial
                audit_logger = get_audit_logger()
                audit_logger.log_denial(AccessDenialEvent(
                    tenant_id=ctx.tenant_id,
                    feature_name=feature_key,
                    billing_state=ctx.billing_state.value,
                    plan_id=ctx.plan_id,
                    plan_name=decision.plan_name,
                    endpoint=request.url.path,
                    method=request.method,
                    reason=decision.reason,
                    required_plan=decision.required_plan,
                ))

                raise PaymentRequiredError(
                    detail=decision.reason or f"Feature '{feature_key}' requires upgrade",
                    feature=feature_key,
                    billing_state=ctx.billing_state.value,
                    current_plan=decision.plan_name,
                    required_plan=decision.required_plan,
                    upgrade_url=decision.upgrade_url,
                )

            # Check if limited access is sufficient
            if not allow_limited:
                feat = ctx.access_rules.plan.get_feature(feature_key) if ctx.access_rules.plan else None
                if feat and feat.is_limited():
                    raise PaymentRequiredError(
                        detail=f"Feature '{feature_key}' requires full access (currently limited)",
                        feature=feature_key,
                        billing_state=ctx.billing_state.value,
                        current_plan=decision.plan_name,
                        required_plan=decision.required_plan,
                        upgrade_url=decision.upgrade_url,
                    )

            return await func(*args, **kwargs)

        return wrapper
    return decorator


def require_billing_state(
    allowed_states: List[BillingState],
    message: Optional[str] = None,
):
    """
    Decorator to require specific billing states.

    Args:
        allowed_states: List of allowed billing states
        message: Custom error message

    Usage:
        @app.post("/api/exports")
        @require_billing_state([BillingState.ACTIVE, BillingState.TRIALING])
        async def create_export(request: Request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                request = kwargs.get("request")

            if not request:
                raise ValueError("Request object not found")

            ctx: Optional[EntitlementContext] = getattr(request.state, 'entitlements', None)
            if not ctx:
                return await func(*args, **kwargs)

            if ctx.billing_state not in allowed_states:
                allowed_str = ", ".join(s.value for s in allowed_states)
                error_msg = message or f"This action requires one of these billing states: {allowed_str}"

                audit_logger = get_audit_logger()
                audit_logger.log_denial(AccessDenialEvent(
                    tenant_id=ctx.tenant_id,
                    feature_name="billing_state_requirement",
                    billing_state=ctx.billing_state.value,
                    plan_id=ctx.plan_id,
                    endpoint=request.url.path,
                    method=request.method,
                    reason=error_msg,
                ))

                raise PaymentRequiredError(
                    detail=error_msg,
                    billing_state=ctx.billing_state.value,
                    current_plan=ctx.access_rules.plan.display_name if ctx.access_rules.plan else None,
                )

            return await func(*args, **kwargs)

        return wrapper
    return decorator


def require_limit_not_exceeded(
    limit_key: str,
    get_current_usage: Callable[[str], int],
):
    """
    Decorator to check usage limits.

    Args:
        limit_key: Limit to check (e.g., "max_dashboards")
        get_current_usage: Function that takes tenant_id and returns current usage

    Usage:
        @app.post("/api/dashboards")
        @require_limit_not_exceeded("max_dashboards", lambda tid: get_dashboard_count(tid))
        async def create_dashboard(request: Request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                request = kwargs.get("request")

            if not request:
                raise ValueError("Request object not found")

            ctx: Optional[EntitlementContext] = getattr(request.state, 'entitlements', None)
            if not ctx:
                return await func(*args, **kwargs)

            # Get current usage
            current_usage = get_current_usage(ctx.tenant_id)

            # Check limit
            decision = ctx.access_rules.check_limit(limit_key, current_usage)

            if not decision.allowed:
                audit_logger = get_audit_logger()
                audit_logger.log_denial(AccessDenialEvent(
                    tenant_id=ctx.tenant_id,
                    feature_name=f"limit:{limit_key}",
                    billing_state=ctx.billing_state.value,
                    plan_id=ctx.plan_id,
                    endpoint=request.url.path,
                    method=request.method,
                    reason=decision.reason,
                    required_plan=decision.required_plan,
                ))

                raise PaymentRequiredError(
                    detail=decision.reason or f"Limit '{limit_key}' exceeded",
                    feature=f"limit:{limit_key}",
                    billing_state=ctx.billing_state.value,
                    current_plan=decision.plan_name,
                    required_plan=decision.required_plan,
                    upgrade_url=decision.upgrade_url,
                )

            return await func(*args, **kwargs)

        return wrapper
    return decorator


class BackgroundJobEntitlementChecker:
    """
    Entitlement checker for background jobs.

    Background jobs don't have Request context, so we check directly.

    Usage:
        checker = BackgroundJobEntitlementChecker(tenant_id, db_session)
        if checker.can_execute("data_export"):
            # Run the job
        else:
            # Skip or log
    """

    def __init__(self, tenant_id: str, db_session: Any):
        self.tenant_id = tenant_id
        self.db_session = db_session
        self._cache = get_entitlement_cache()
        self._audit_logger = get_audit_logger()
        self._access_rules: Optional[AccessRules] = None

    def _get_access_rules(self) -> AccessRules:
        """Get or create access rules."""
        if self._access_rules:
            return self._access_rules

        # Check cache
        cached = self._cache.get(self.tenant_id)
        if cached:
            self._access_rules = AccessRules(
                tenant_id=self.tenant_id,
                plan_id=cached.plan_id,
                billing_state=BillingState(cached.billing_state),
            )
            return self._access_rules

        # Load from database
        try:
            from src.models.subscription import Subscription, SubscriptionStatus

            subscription = self.db_session.query(Subscription).filter(
                Subscription.tenant_id == self.tenant_id,
                Subscription.status.in_([
                    SubscriptionStatus.ACTIVE.value,
                    SubscriptionStatus.PENDING.value,
                    SubscriptionStatus.FROZEN.value,
                ])
            ).first()

            self._access_rules = create_access_rules_from_subscription(
                tenant_id=self.tenant_id,
                subscription=subscription,
            )

        except Exception as e:
            logger.warning(f"Failed to load subscription for background job: {e}")
            self._access_rules = AccessRules(
                tenant_id=self.tenant_id,
                plan_id="plan_free",
                billing_state=BillingState.NONE,
            )

        return self._access_rules

    def can_execute(self, feature_key: str, job_name: Optional[str] = None) -> bool:
        """
        Check if a background job can execute.

        Args:
            feature_key: Feature required by the job
            job_name: Optional job name for logging

        Returns:
            True if job can execute
        """
        rules = self._get_access_rules()
        decision = rules.check_feature_access(feature_key, "write")

        if not decision.allowed:
            self._audit_logger.log_denial(AccessDenialEvent(
                tenant_id=self.tenant_id,
                feature_name=feature_key,
                billing_state=rules.billing_state.value,
                plan_id=rules.plan_id,
                endpoint=f"background_job:{job_name}" if job_name else "background_job",
                method="EXECUTE",
                reason=decision.reason,
            ))
            logger.info(
                f"Background job skipped due to entitlement: {job_name}",
                extra={
                    "tenant_id": self.tenant_id,
                    "feature": feature_key,
                    "reason": decision.reason,
                }
            )
            return False

        return True

    def check_limit(self, limit_key: str, current_usage: int) -> bool:
        """Check if usage is within limits."""
        rules = self._get_access_rules()
        decision = rules.check_limit(limit_key, current_usage)
        return decision.allowed
