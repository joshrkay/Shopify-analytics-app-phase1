"""
Feature flags for AI Growth Analytics.

CRITICAL SECURITY REQUIREMENTS:
- Feature flags MUST be evaluated server-side for security-relevant gating
- Any "AI actions / write-back" feature MUST be behind a kill switch flag
- Kill switch must take effect <10 seconds
- All flag usage MUST go through this module

Usage:
    from src.platform.feature_flags import is_feature_enabled, require_feature_flag, FeatureFlag

    # Check a flag
    if await is_feature_enabled(FeatureFlag.AI_WRITE_BACK, tenant_id, user_id):
        # Feature is enabled
        ...

    # Use as decorator
    @app.post("/api/ai/execute")
    @require_feature_flag(FeatureFlag.AI_WRITE_BACK)
    async def execute_ai_action(request: Request):
        ...
"""

import logging
import os
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional

from fastapi import Request, HTTPException, status

logger = logging.getLogger(__name__)


class FeatureFlag(str, Enum):
    """
    Enumeration of all feature flags.

    Add new flags here as features are developed.
    Feature flags can be configured via environment variables.
    """
    # AI features (all must have kill switches)
    AI_INSIGHTS = "ai-insights"
    AI_WRITE_BACK = "ai-write-back"  # CRITICAL: Kill switch for AI actions
    AI_AUTOMATION = "ai-automation"

    # Billing/entitlement features
    PREMIUM_ANALYTICS = "premium-analytics"
    ADVANCED_EXPORTS = "advanced-exports"
    CUSTOM_DASHBOARDS = "custom-dashboards"

    # Platform features
    MULTI_STORE = "multi-store"
    TEAM_COLLABORATION = "team-collaboration"
    API_ACCESS = "api-access"

    # Beta/experimental features
    BETA_NEW_UI = "beta-new-ui"
    BETA_ADVANCED_AI = "beta-advanced-ai"

    # Operational flags
    MAINTENANCE_MODE = "maintenance-mode"
    RATE_LIMITING_STRICT = "rate-limiting-strict"


class FeatureFlagClient:
    """
    Feature flag client with graceful degradation.

    Feature flags can be managed via:
    1. Environment variables for global defaults (FEATURE_FLAG_<NAME>)
    2. JWT claims for feature entitlements
    3. Database-backed configuration (future)

    If no configuration is found, flags return their default values.
    """

    def __init__(self):
        self._initialized = False
        self._flag_defaults: dict[str, bool] = {}

    def _initialize(self):
        """Lazy initialization of feature flag defaults."""
        if self._initialized:
            return

        # Load flag defaults from environment variables
        # Format: FEATURE_FLAG_<FLAG_NAME>=true/false
        for flag in FeatureFlag:
            env_key = f"FEATURE_FLAG_{flag.name}"
            env_value = os.getenv(env_key, "").lower()
            if env_value in ("true", "1", "yes"):
                self._flag_defaults[flag.value] = True
            elif env_value in ("false", "0", "no"):
                self._flag_defaults[flag.value] = False
            # If not set, will use the default passed to is_enabled()

        logger.info("Feature flags initialized from environment")

        self._initialized = True

    def _build_context(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        custom_attributes: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Build feature flag context for evaluation.

        The context is used for tenant-level and user-level targeting.
        """
        context = {
            "tenant_id": tenant_id,
            **(custom_attributes or {}),
        }
        if user_id:
            context["user_id"] = user_id
        return context

    def is_enabled(
        self,
        flag: FeatureFlag,
        tenant_id: str,
        user_id: Optional[str] = None,
        default: bool = False,
        custom_attributes: Optional[dict[str, Any]] = None,
    ) -> bool:
        """
        Check if a feature flag is enabled.

        Evaluation order:
        1. Check environment variable override (FEATURE_FLAG_<NAME>)
        2. Check entitlements from JWT claims (if configured)
        3. Fall back to default value

        Args:
            flag: The feature flag to check
            tenant_id: The tenant ID for targeting
            user_id: Optional user ID for user-level targeting
            default: Default value if flag evaluation fails
            custom_attributes: Optional custom attributes for targeting

        Returns:
            True if the flag is enabled, False otherwise
        """
        self._initialize()

        try:
            # Check environment variable override first
            if flag.value in self._flag_defaults:
                result = self._flag_defaults[flag.value]
                logger.debug(
                    "Feature flag evaluated from environment",
                    extra={
                        "flag": flag.value,
                        "tenant_id": tenant_id,
                        "result": result,
                    }
                )
                return result

            # Build context for potential entitlement evaluation
            context = self._build_context(tenant_id, user_id, custom_attributes)

            # For now, return default - JWT entitlements can be checked later
            # when specific integration is needed
            logger.debug(
                "Feature flag using default",
                extra={
                    "flag": flag.value,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "default": default,
                }
            )

            return default

        except Exception as e:
            logger.error(
                "Feature flag evaluation failed - using default",
                extra={
                    "flag": flag.value,
                    "error": str(e),
                    "default": default,
                }
            )
            return default

    def get_variation(
        self,
        flag: FeatureFlag,
        tenant_id: str,
        user_id: Optional[str] = None,
        default: Any = None,
        custom_attributes: Optional[dict[str, Any]] = None,
    ) -> Any:
        """
        Get a feature flag variation (for non-boolean flags).

        Args:
            flag: The feature flag to check
            tenant_id: The tenant ID for targeting
            user_id: Optional user ID for user-level targeting
            default: Default value if flag evaluation fails
            custom_attributes: Optional custom attributes for targeting

        Returns:
            The flag variation value
        """
        self._initialize()

        try:
            # Check environment variable override
            env_key = f"FEATURE_FLAG_{flag.name}"
            env_value = os.getenv(env_key)
            if env_value is not None:
                return env_value

            return default
        except Exception as e:
            logger.error(
                "Feature flag variation failed - using default",
                extra={
                    "flag": flag.value,
                    "error": str(e),
                    "default": default,
                }
            )
            return default


# Singleton instance
_client = FeatureFlagClient()


def get_feature_flag_client() -> FeatureFlagClient:
    """Get the global feature flag client instance."""
    return _client


# Backwards compatibility alias
FronteggFeatureFlagClient = FeatureFlagClient


async def is_feature_enabled(
    flag: FeatureFlag,
    tenant_id: str,
    user_id: Optional[str] = None,
    default: bool = False,
) -> bool:
    """
    Check if a feature flag is enabled for a tenant/user.

    This is the primary API for checking feature flags.

    Args:
        flag: The feature flag to check
        tenant_id: The tenant ID
        user_id: Optional user ID for user-level targeting
        default: Default value if evaluation fails

    Returns:
        True if enabled, False otherwise
    """
    return _client.is_enabled(flag, tenant_id, user_id, default)


async def is_kill_switch_active(flag: FeatureFlag) -> bool:
    """
    Check if a kill switch is active (feature is disabled globally).

    Kill switches use a special "global" tenant context.

    Args:
        flag: The kill switch flag to check

    Returns:
        True if kill switch is ACTIVE (feature disabled), False otherwise
    """
    # For kill switches, we check if the flag is DISABLED (returns False)
    # A kill switch being "active" means the feature should be blocked
    # Default to True (flag enabled) so kill switch is inactive when not configured
    return not _client.is_enabled(flag, tenant_id="__global__", default=True)


def require_feature_flag(
    flag: FeatureFlag,
    default: bool = False,
    error_message: Optional[str] = None,
) -> Callable:
    """
    Decorator to require a feature flag for an endpoint.

    Raises 503 if the feature is disabled.

    Args:
        flag: The feature flag to check
        default: Default value if evaluation fails
        error_message: Custom error message

    Usage:
        @app.post("/api/ai/execute")
        @require_feature_flag(FeatureFlag.AI_WRITE_BACK)
        async def execute_ai_action(request: Request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find Request object
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                request = kwargs.get("request")

            if not request:
                raise ValueError("Request object not found in function arguments")

            # Get tenant context
            from src.platform.tenant_context import get_tenant_context
            tenant_context = get_tenant_context(request)

            # Check feature flag
            enabled = await is_feature_enabled(
                flag,
                tenant_context.tenant_id,
                tenant_context.user_id,
                default,
            )

            if not enabled:
                logger.info(
                    "Feature flag blocked request",
                    extra={
                        "flag": flag.value,
                        "tenant_id": tenant_context.tenant_id,
                        "user_id": tenant_context.user_id,
                        "path": request.url.path,
                    }
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=error_message or f"Feature '{flag.value}' is currently disabled"
                )

            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_kill_switch_inactive(
    flag: FeatureFlag,
    error_message: Optional[str] = None,
) -> Callable:
    """
    Decorator to require a kill switch to be inactive (feature enabled).

    Use this for critical features that have a global kill switch.
    This checks the kill switch status independently of tenant targeting.

    Args:
        flag: The kill switch flag to check
        error_message: Custom error message

    Usage:
        @app.post("/api/ai/write")
        @require_kill_switch_inactive(FeatureFlag.AI_WRITE_BACK)
        async def ai_write_action(request: Request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Check global kill switch
            if await is_kill_switch_active(flag):
                logger.warning(
                    "Kill switch blocked request",
                    extra={"flag": flag.value}
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=error_message or f"Feature '{flag.value}' is currently disabled"
                )

            return await func(*args, **kwargs)
        return wrapper
    return decorator


async def check_feature_or_raise(
    flag: FeatureFlag,
    tenant_id: str,
    user_id: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """
    Programmatic feature flag check that raises HTTPException if disabled.

    Use this when you need to check a flag inside a function body.

    Args:
        flag: The feature flag to check
        tenant_id: The tenant ID
        user_id: Optional user ID
        error_message: Custom error message

    Raises:
        HTTPException: If the feature is disabled
    """
    if not await is_feature_enabled(flag, tenant_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_message or f"Feature '{flag.value}' is currently disabled"
        )
