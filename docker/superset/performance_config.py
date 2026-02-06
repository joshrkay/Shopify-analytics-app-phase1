"""
Centralized Performance & Safety Configuration for Superset.

This module is the SINGLE SOURCE OF TRUTH for all performance limits.
All values are frozen and cannot be overridden by users.

Other modules MUST import from here rather than defining their own values:
- superset_config.py imports PERFORMANCE_LIMITS and derived constants
- explore_guardrails.py imports PERFORMANCE_LIMITS for guardrail defaults
- guards.py imports for validation

Story 5.1.6 - Performance & Safety Defaults
Story 5.2.6 - Performance Guardrails (Superset Layer): query timeout 20s, row limit 50k, max group-by 2, cache TTL 30min.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class PerformanceLimits:
    """
    Immutable performance limits. Frozen dataclass prevents runtime modification.

    These limits are enforced at multiple layers:
    1. Superset config (ROW_LIMIT, SQLLAB_TIMEOUT)
    2. Explore guardrails (ExplorePermissionValidator)
    3. Database query timeout (PostgreSQL statement_timeout)
    """

    # Query execution
    query_timeout_seconds: int = 20
    row_limit: int = 50_000
    samples_row_limit: int = 1_000

    # Date range
    max_date_range_days: int = 90

    # Complexity
    max_group_by_dimensions: int = 2
    max_filters: int = 10
    max_metrics_per_query: int = 5

    # Cache
    cache_ttl_seconds: int = 1800  # 30 minutes
    cache_key_prefix: str = "explore_data_"

    # Web server
    webserver_timeout_seconds: int = 30  # query timeout + 10s buffer

    # Rate limiting
    max_queries_per_user_per_minute: int = 60
    max_dashboard_refresh_per_minute: int = 30

    # Export controls
    allow_file_export: bool = False
    allow_csv_export: bool = False
    allow_pivot_export: bool = False

    @property
    def cache_ttl_minutes(self) -> int:
        """Cache TTL in minutes (derived from seconds)."""
        return self.cache_ttl_seconds // 60


# Singleton instance — the ONE source of truth
PERFORMANCE_LIMITS: Final[PerformanceLimits] = PerformanceLimits()


# ============================================================================
# Derived constants for direct import into superset_config.py
# ============================================================================

SQL_MAX_ROW: Final[int] = PERFORMANCE_LIMITS.row_limit
ROW_LIMIT: Final[int] = PERFORMANCE_LIMITS.row_limit
SAMPLES_ROW_LIMIT: Final[int] = PERFORMANCE_LIMITS.samples_row_limit
SQLLAB_TIMEOUT: Final[int] = PERFORMANCE_LIMITS.query_timeout_seconds
SQLLAB_ASYNC_TIME_LIMIT_SEC: Final[int] = PERFORMANCE_LIMITS.query_timeout_seconds
SUPERSET_WEBSERVER_TIMEOUT: Final[int] = PERFORMANCE_LIMITS.webserver_timeout_seconds
CACHE_DEFAULT_TIMEOUT: Final[int] = PERFORMANCE_LIMITS.cache_ttl_seconds
EXPLORE_CACHE_TTL: Final[int] = PERFORMANCE_LIMITS.cache_ttl_seconds


# ============================================================================
# Safety feature flags — dangerous features that must always be disabled
# ============================================================================

SAFETY_FEATURE_FLAGS: Final[dict[str, bool]] = {
    # Custom SQL / metrics — users must not write arbitrary SQL
    "ENABLE_CUSTOM_METRICS": False,
    "SQLLAB_BACKEND_PERSISTENCE": False,
    "ALLOW_USER_METRIC_EDIT": False,
    "SQL_QUERIES_ALLOWED": False,
    "EXPLORE_ALLOW_SUBQUERY": False,
    "ALLOW_ADHOC_SUBQUERY": False,
    "ENABLE_ADVANCED_DATA_TYPES": False,
    "ENABLE_TEMPLATE_PROCESSING": False,
    # Data export — all exports disabled for multi-tenant safety
    "ENABLE_PIVOT_TABLE_DATA_EXPORT": False,
    "CSV_EXPORT": False,
}
