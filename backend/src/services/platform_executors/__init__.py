"""
Platform executors for external API integrations.

This package provides executors for executing actions on external
advertising and e-commerce platforms.

Supported Platforms:
- Meta (Facebook/Instagram) Ads
- Google Ads
- Shopify (planned)

Each executor implements the BasePlatformExecutor interface and handles:
- API authentication
- Rate limiting with exponential backoff
- State capture (before/after)
- Action execution
- Rollback instruction generation

Story 8.5 - Action Execution (Scoped & Reversible)
"""

from src.services.platform_executors.base_executor import (
    BasePlatformExecutor,
    ExecutionResult,
    ExecutionResultStatus,
    StateCapture,
    RetryConfig,
    PlatformAPIError,
)
from src.services.platform_executors.meta_executor import (
    MetaAdsExecutor,
    MetaCredentials,
)
from src.services.platform_executors.google_executor import (
    GoogleAdsExecutor,
    GoogleAdsCredentials,
)

__all__ = [
    # Base
    "BasePlatformExecutor",
    "ExecutionResult",
    "ExecutionResultStatus",
    "StateCapture",
    "RetryConfig",
    "PlatformAPIError",
    # Meta
    "MetaAdsExecutor",
    "MetaCredentials",
    # Google
    "GoogleAdsExecutor",
    "GoogleAdsCredentials",
]
