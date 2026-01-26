"""
Superset Feature Flags for Production Analytics Environment.

This module defines production-hardened feature flags for Superset 3.x deployment.
These flags control audit logging, security monitoring, and observability features.

IMPORTANT:
- All experimental features are DISABLED by default
- Audit logging and security features are ENABLED by default
- Cross-tenant data access is DISABLED to prevent data leaks
- This file should be imported into superset_config.py

USAGE:
    # In superset_config.py
    from superset_feature_flags import FEATURE_FLAGS, EXTRA_CONFIGS

COMPATIBILITY:
- Superset 3.x (tested with 3.0, 3.1)
- Python 3.11+

SECURITY NOTES:
- No secrets are stored in this file
- Sensitive configurations should be injected via environment variables
- Review all flag changes before deployment
"""

from typing import Final

# =============================================================================
# RETENTION PERIOD CONSTANTS
# =============================================================================
# These constants define data retention periods for audit and logging data.
# Adjust based on compliance requirements (SOC2, GDPR, legal hold policies).

# Audit log retention in days
# SOC2 Type II requires minimum 90 days, legal holds may require longer
AUDIT_LOG_RETENTION_DAYS: Final[int] = 90

# Query log retention in days
# Balance between debugging capability and storage costs
QUERY_LOG_RETENTION_DAYS: Final[int] = 30

# Slow query log retention in days
# Keep longer for performance analysis trends
SLOW_QUERY_LOG_RETENTION_DAYS: Final[int] = 60

# Export audit retention in days
# Compliance requirement for tracking data exports
EXPORT_AUDIT_RETENTION_DAYS: Final[int] = 365

# Session log retention in days
SESSION_LOG_RETENTION_DAYS: Final[int] = 30


# =============================================================================
# SLOW QUERY THRESHOLDS
# =============================================================================
# Thresholds for identifying slow queries. Queries exceeding these thresholds
# will be logged for performance analysis.

# Threshold in milliseconds for logging slow queries
# Queries taking longer than this are logged to slow query log
SLOW_QUERY_THRESHOLD_MS: Final[int] = 5000

# Critical slow query threshold in milliseconds
# Queries exceeding this trigger alerts
CRITICAL_SLOW_QUERY_THRESHOLD_MS: Final[int] = 20000

# Query timeout in seconds
# Queries are terminated if they exceed this limit
QUERY_TIMEOUT_SECONDS: Final[int] = 300


# =============================================================================
# RATE LIMITING CONSTANTS
# =============================================================================
# Protect against abuse and ensure fair resource allocation.

# Maximum queries per user per minute
MAX_QUERIES_PER_USER_PER_MINUTE: Final[int] = 60

# Maximum export requests per user per hour
MAX_EXPORTS_PER_USER_PER_HOUR: Final[int] = 10

# Maximum dashboard refreshes per minute
MAX_DASHBOARD_REFRESH_PER_MINUTE: Final[int] = 30


# =============================================================================
# FEATURE FLAGS
# =============================================================================
# Production-hardened feature flag configuration for Superset 3.x
#
# CONVENTIONS:
# - True = Feature enabled
# - False = Feature disabled
# - All experimental features disabled by default
# - All audit/security features enabled by default

FEATURE_FLAGS: Final[dict[str, bool]] = {
    # =========================================================================
    # AUDIT LOGGING & OBSERVABILITY
    # =========================================================================

    # Enable query execution logging
    # REQUIRED for audit trail and performance monitoring
    # Logs: query text, user, dataset, duration, row count
    "ENABLE_QUERY_LOGGING": True,

    # Enable slow query logging
    # Queries exceeding SLOW_QUERY_THRESHOLD_MS are logged separately
    # Critical for identifying performance bottlenecks
    "ENABLE_SLOW_QUERY_LOG": True,

    # Enable audit log export functionality
    # Allows authorized users to export audit logs for compliance
    # Required for SOC2 Type II audit requirements
    "ENABLE_AUDIT_LOG_EXPORT": True,

    # Enable access request logging
    # Tracks all resource access attempts (granted and denied)
    # Critical for security investigation
    "ENABLE_ACCESS_REQUEST_LOGGING": True,

    # Enable dashboard access logging
    # Tracks who views which dashboards and when
    # Required for usage analytics and security
    "ENABLE_DASHBOARD_ACCESS_LOGGING": True,

    # Enable chart/explore query logging
    # Logs all ad-hoc queries from Explore interface
    "ENABLE_EXPLORE_QUERY_LOGGING": True,

    # =========================================================================
    # SECURITY ALERTING
    # =========================================================================

    # Alert on permission escalation events
    # Triggers when user gains elevated permissions
    # Critical for detecting unauthorized privilege changes
    "ALERT_ON_PERMISSION_ESCALATION": True,

    # Alert on bulk data export
    # Triggers when large data volumes are exported
    # Helps detect potential data exfiltration
    "ALERT_ON_BULK_EXPORT": True,

    # Alert on cross-tenant access attempts
    # Triggers on any attempt to access another tenant's data
    # Critical for multi-tenant security
    "ALERT_ON_CROSS_TENANT_ACCESS": True,

    # Alert on RLS bypass attempts
    # Triggers when row-level security is circumvented
    # Highest priority security alert
    "ALERT_ON_RLS_BYPASS_ATTEMPT": True,

    # Alert on unusual access patterns
    # Triggers on anomalous user behavior
    # Helps detect compromised accounts
    "ALERT_ON_UNUSUAL_ACCESS_PATTERN": True,

    # Alert on failed authentication spikes
    # Triggers on multiple auth failures
    # Helps detect brute force attacks
    "ALERT_ON_AUTH_FAILURE_SPIKE": True,

    # =========================================================================
    # DATA ISOLATION & TENANT SECURITY
    # =========================================================================

    # CRITICAL: Disable cross-tenant metrics
    # Prevents accidental data leaks between tenants
    # Must remain FALSE in multi-tenant deployments
    "ENABLE_CROSS_TENANT_METRICS": False,

    # Enable strict RLS enforcement
    # Ensures row-level security cannot be bypassed
    # Required for multi-tenant data isolation
    "ENABLE_STRICT_RLS_ENFORCEMENT": True,

    # Enable tenant context validation
    # Validates tenant context on every request
    # Prevents tenant spoofing attacks
    "ENABLE_TENANT_CONTEXT_VALIDATION": True,

    # Enable query result isolation
    # Ensures query results are filtered by tenant
    # Defense-in-depth for data isolation
    "ENABLE_QUERY_RESULT_ISOLATION": True,

    # =========================================================================
    # CACHING & PERFORMANCE
    # =========================================================================

    # Enable query caching
    # Caches query results for performance
    # Cache keys include tenant ID for isolation
    "ENABLE_QUERY_CACHING": True,

    # Enable dashboard caching
    # Caches rendered dashboard data
    # Significantly improves load times
    "ENABLE_DASHBOARD_CACHING": True,

    # Enable cache logging
    # Logs cache hits/misses for debugging
    # Helps identify caching inefficiencies
    "ENABLE_CACHE_LOGGING": True,

    # Enable tenant-scoped caching
    # Ensures cache entries are isolated by tenant
    # Required for multi-tenant deployments
    "ENABLE_TENANT_SCOPED_CACHE": True,

    # =========================================================================
    # EMBEDDED ANALYTICS
    # =========================================================================

    # Enable embedded dashboards
    # Allows dashboards to be embedded in external applications
    # Required for Shopify Admin integration
    "ENABLE_EMBEDDED_SUPERSET": True,

    # Enable JWT authentication for embedded dashboards
    # Required for secure embedded authentication
    "ENABLE_JWT_EMBEDDED_AUTH": True,

    # Enable CSP enforcement for embedded content
    # Restricts where dashboards can be embedded
    # Prevents clickjacking and XSS attacks
    "ENABLE_CSP_ENFORCEMENT": True,

    # Log embedded access separately
    # Tracks embedded dashboard usage
    # Helps monitor third-party integrations
    "ENABLE_EMBEDDED_ACCESS_LOGGING": True,

    # =========================================================================
    # USER INTERFACE FEATURES
    # =========================================================================

    # Enable scheduled reports
    # Allows users to schedule dashboard exports
    # Controlled by plan entitlements
    "ENABLE_SCHEDULED_REPORTS": True,

    # Enable alerts
    # Allows users to create data-driven alerts
    # Controlled by plan entitlements
    "ENABLE_ALERTS": True,

    # Disable public sharing
    # Prevents sharing dashboards publicly
    # Required for data security
    "ENABLE_PUBLIC_SHARING": False,

    # =========================================================================
    # EXPERIMENTAL FEATURES (ALL DISABLED)
    # =========================================================================
    # These features are experimental or in development.
    # Do NOT enable in production without thorough testing.

    # Experimental async query execution
    # May cause stability issues, keep disabled
    "ENABLE_ASYNC_QUERY_EXECUTION_EXPERIMENTAL": False,

    # Experimental chart templates
    # UI feature in development
    "ENABLE_CHART_TEMPLATES_EXPERIMENTAL": False,

    # Experimental SQL Lab features
    # Includes untested autocomplete features
    "ENABLE_SQLLAB_EXPERIMENTAL": False,

    # Experimental explore features
    # New visualization types in testing
    "ENABLE_EXPLORE_EXPERIMENTAL": False,

    # Experimental dashboard filters
    # Cross-filter features in development
    "ENABLE_DASHBOARD_CROSS_FILTERS_EXPERIMENTAL": False,

    # Experimental natural language queries
    # AI-powered query generation (not production ready)
    "ENABLE_NL_QUERY_EXPERIMENTAL": False,

    # =========================================================================
    # DEPRECATED FEATURES (ALL DISABLED)
    # =========================================================================
    # These features are deprecated and should not be used.

    # Legacy access request system
    # Replaced by new RBAC system
    "ENABLE_ACCESS_REQUEST": False,

    # Legacy dataset creation
    # Replaced by governance-controlled creation
    "ENABLE_LEGACY_DATASET_CREATION": False,
}


# =============================================================================
# EXTRA CONFIGURATIONS
# =============================================================================
# Additional configuration values used alongside feature flags.
# These are not boolean flags but related settings.

EXTRA_CONFIGS: Final[dict[str, int | str | list]] = {
    # Query logging configuration
    "QUERY_LOG_RETENTION_DAYS": QUERY_LOG_RETENTION_DAYS,
    "SLOW_QUERY_LOG_RETENTION_DAYS": SLOW_QUERY_LOG_RETENTION_DAYS,
    "SLOW_QUERY_THRESHOLD_MS": SLOW_QUERY_THRESHOLD_MS,
    "CRITICAL_SLOW_QUERY_THRESHOLD_MS": CRITICAL_SLOW_QUERY_THRESHOLD_MS,
    "QUERY_TIMEOUT_SECONDS": QUERY_TIMEOUT_SECONDS,

    # Audit configuration
    "AUDIT_LOG_RETENTION_DAYS": AUDIT_LOG_RETENTION_DAYS,
    "EXPORT_AUDIT_RETENTION_DAYS": EXPORT_AUDIT_RETENTION_DAYS,
    "AUDIT_LOG_BACKUP_FREQUENCY": "daily",

    # Session configuration
    "SESSION_LOG_RETENTION_DAYS": SESSION_LOG_RETENTION_DAYS,

    # Rate limiting
    "MAX_QUERIES_PER_USER_PER_MINUTE": MAX_QUERIES_PER_USER_PER_MINUTE,
    "MAX_EXPORTS_PER_USER_PER_HOUR": MAX_EXPORTS_PER_USER_PER_HOUR,
    "MAX_DASHBOARD_REFRESH_PER_MINUTE": MAX_DASHBOARD_REFRESH_PER_MINUTE,

    # Bulk export thresholds (trigger alerts)
    "BULK_EXPORT_ROW_THRESHOLD": 100000,
    "BULK_EXPORT_TIME_WINDOW_HOURS": 1,

    # Cache TTL settings (seconds)
    "QUERY_CACHE_TTL_SECONDS": 300,
    "DASHBOARD_CACHE_TTL_SECONDS": 600,
    "METADATA_CACHE_TTL_SECONDS": 3600,

    # Embedded dashboard settings
    "EMBEDDED_TOKEN_MAX_LIFETIME_MINUTES": 60,
    "EMBEDDED_ALLOWED_DOMAINS": [],  # Populated from environment
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_feature_flag(flag_name: str, default: bool = False) -> bool:
    """
    Get a feature flag value with a default fallback.

    Args:
        flag_name: Name of the feature flag
        default: Default value if flag not found

    Returns:
        Boolean value of the flag
    """
    return FEATURE_FLAGS.get(flag_name, default)


def get_config_value(config_name: str, default: int | str | list | None = None):
    """
    Get an extra configuration value with a default fallback.

    Args:
        config_name: Name of the configuration
        default: Default value if not found

    Returns:
        Configuration value
    """
    return EXTRA_CONFIGS.get(config_name, default)


def is_audit_enabled() -> bool:
    """Check if audit logging is fully enabled."""
    return all([
        FEATURE_FLAGS.get("ENABLE_QUERY_LOGGING", False),
        FEATURE_FLAGS.get("ENABLE_ACCESS_REQUEST_LOGGING", False),
        FEATURE_FLAGS.get("ENABLE_DASHBOARD_ACCESS_LOGGING", False),
    ])


def is_security_alerting_enabled() -> bool:
    """Check if security alerting is fully enabled."""
    return all([
        FEATURE_FLAGS.get("ALERT_ON_PERMISSION_ESCALATION", False),
        FEATURE_FLAGS.get("ALERT_ON_CROSS_TENANT_ACCESS", False),
        FEATURE_FLAGS.get("ALERT_ON_RLS_BYPASS_ATTEMPT", False),
    ])


def get_disabled_experimental_features() -> list[str]:
    """Get list of all disabled experimental features."""
    return [
        flag for flag, enabled in FEATURE_FLAGS.items()
        if "EXPERIMENTAL" in flag and not enabled
    ]


def validate_production_config() -> tuple[bool, list[str]]:
    """
    Validate that configuration is production-ready.

    Returns:
        Tuple of (is_valid, list_of_issues)

    Usage:
        is_valid, issues = validate_production_config()
        if not is_valid:
            raise ConfigurationError(f"Invalid config: {issues}")
    """
    issues = []

    # Check critical security flags
    if FEATURE_FLAGS.get("ENABLE_CROSS_TENANT_METRICS", True):
        issues.append("CRITICAL: ENABLE_CROSS_TENANT_METRICS must be False")

    if FEATURE_FLAGS.get("ENABLE_PUBLIC_SHARING", True):
        issues.append("WARNING: ENABLE_PUBLIC_SHARING should be False")

    if not FEATURE_FLAGS.get("ENABLE_STRICT_RLS_ENFORCEMENT", False):
        issues.append("CRITICAL: ENABLE_STRICT_RLS_ENFORCEMENT must be True")

    if not FEATURE_FLAGS.get("ENABLE_TENANT_CONTEXT_VALIDATION", False):
        issues.append("CRITICAL: ENABLE_TENANT_CONTEXT_VALIDATION must be True")

    # Check audit logging
    if not is_audit_enabled():
        issues.append("WARNING: Audit logging is not fully enabled")

    # Check security alerting
    if not is_security_alerting_enabled():
        issues.append("WARNING: Security alerting is not fully enabled")

    # Check experimental features
    experimental_enabled = [
        flag for flag, enabled in FEATURE_FLAGS.items()
        if "EXPERIMENTAL" in flag and enabled
    ]
    if experimental_enabled:
        issues.append(
            f"WARNING: Experimental features enabled: {experimental_enabled}"
        )

    # Check retention periods meet compliance
    if AUDIT_LOG_RETENTION_DAYS < 90:
        issues.append(
            f"WARNING: AUDIT_LOG_RETENTION_DAYS ({AUDIT_LOG_RETENTION_DAYS}) "
            "may not meet SOC2 Type II requirements (90 days minimum)"
        )

    return len(issues) == 0 or all("WARNING" in i for i in issues), issues
