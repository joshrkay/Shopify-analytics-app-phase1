"""
Canonical Audit Event Registry for AI Growth Analytics.

This module defines the single source of truth for all auditable events in the
analytics platform. It is designed to be imported by other modules for event
validation, ensuring consistency across logging, alerting, and compliance systems.

ARCHITECTURE:
- Superset-based analytics with embedded dashboards
- JWT authentication with tenant isolation
- Row-Level Security (RLS) enforcement
- Multi-tenant data access patterns

COMPLIANCE CONSIDERATIONS:
- SOC2 Type II: 90-day minimum retention, change tracking
- GDPR: Right to deletion, PII handling
- Data governance: Metric versioning, approval workflows

USAGE:
    from src.platform.audit_events import AUDITABLE_EVENTS, validate_event_metadata

    # Validate before logging
    if validate_event_metadata("auth.jwt_issued", metadata):
        logger.log_event("auth.jwt_issued", user_id, tenant_id, metadata)

NOTE: This module defines the EVENT SCHEMA only. It does NOT implement:
- Logging logic (see audit_logger.py)
- Database persistence (see audit.py)
- Alert routing (see alert_rules.yaml)
"""

from typing import Final

# =============================================================================
# CANONICAL AUDITABLE EVENTS REGISTRY
# =============================================================================
# Keys: Event type identifiers (dot-notation for category grouping)
# Values: Ordered list of required metadata fields for each event
#
# Field naming conventions:
# - Use snake_case for all field names
# - Use _id suffix for identifiers (user_id, tenant_id, dashboard_id)
# - Use _at suffix for timestamps (created_at, expires_at)
# - Use _ms suffix for millisecond durations (duration_ms, latency_ms)
# - Use _count suffix for counts (row_count, query_count)
# - NEVER include raw PII (emails stored as user_id references only)
# =============================================================================

AUDITABLE_EVENTS: Final[dict[str, list[str]]] = {
    # =========================================================================
    # AUTHENTICATION & JWT LIFECYCLE
    # =========================================================================
    # Track all authentication events for security monitoring and compliance.
    # JWT tokens are the primary authentication mechanism for embedded dashboards.

    "auth.jwt_issued": [
        "user_id",           # User receiving the token
        "tenant_id",         # Tenant context for the token
        "lifetime_minutes",  # Token validity period
        "scopes",            # Permissions granted in token
        "embed_context",     # Whether issued for embedded dashboard
    ],

    "auth.jwt_refresh": [
        "user_id",
        "tenant_id",
        "token_age_minutes",   # Age of token being refreshed
        "refresh_count",       # Number of times this session refreshed
        "new_lifetime_minutes",
    ],

    "auth.jwt_revoked": [
        "user_id",
        "tenant_id",
        "reason",              # Enum: logout, security, expired, admin_action
        "revoked_by",          # user_id of revoker (may be self or admin)
        "remaining_lifetime",  # Minutes left when revoked
    ],

    "auth.jwt_validation_failed": [
        "token_fingerprint",   # Hash of token for correlation (not the token itself)
        "failure_reason",      # Enum: expired, invalid_signature, malformed, revoked
        "client_ip",
        "user_agent_hash",     # Hashed user agent for fingerprinting
    ],

    "auth.login_success": [
        "user_id",
        "tenant_id",
        "auth_method",         # Enum: shopify_oauth, api_key, sso
        "client_ip",
        "user_agent_hash",
        "mfa_used",            # Boolean: whether MFA was required
    ],

    "auth.login_failed": [
        "attempted_user_id",   # May be null if unknown
        "failure_reason",      # Enum: invalid_credentials, account_locked, mfa_failed
        "client_ip",
        "user_agent_hash",
        "attempt_count",       # Number of recent failed attempts
    ],

    "auth.session_expired": [
        "user_id",
        "tenant_id",
        "session_duration_minutes",
        "last_activity_minutes_ago",
    ],

    "auth.api_token_created": [
        "user_id",
        "tenant_id",
        "token_id",            # Identifier for the token (not the secret)
        "scopes",
        "expires_at",
        "created_for",         # Purpose/label for the token
    ],

    "auth.api_token_revoked": [
        "user_id",
        "tenant_id",
        "token_id",
        "revoked_by",
        "reason",
    ],

    # =========================================================================
    # ROLE & PERMISSION CHANGES
    # =========================================================================
    # All permission changes must be audited for SOC2 compliance and
    # security investigation capabilities.

    "role.assigned": [
        "user_id",             # User receiving the role
        "tenant_id",
        "role",                # Role identifier
        "assigned_by",         # user_id of assigner
        "previous_roles",      # List of roles before change
        "effective_permissions",  # Computed permissions after assignment
    ],

    "role.revoked": [
        "user_id",
        "tenant_id",
        "role",
        "revoked_by",
        "reason",
        "remaining_roles",
    ],

    "role.modified": [
        "role_id",
        "tenant_id",
        "modified_by",
        "changes",             # Dict of changed permissions
        "affected_user_count", # Number of users affected
    ],

    "permission.escalation_detected": [
        "user_id",
        "tenant_id",
        "escalation_type",     # Enum: role_change, direct_grant, inheritance
        "previous_level",
        "new_level",
        "triggered_by",        # What caused the escalation
    ],

    # =========================================================================
    # ROW-LEVEL SECURITY (RLS) ENFORCEMENT
    # =========================================================================
    # RLS is critical for tenant isolation. All enforcement events must be
    # logged for security monitoring and debugging.

    "rls.applied": [
        "user_id",
        "tenant_id",
        "dataset_id",
        "dataset_name",
        "rls_clause",          # The WHERE clause applied (sanitized)
        "injection_time_ms",   # Time to apply RLS
    ],

    "rls.denied": [
        "user_id",
        "tenant_id",
        "dataset_id",
        "dataset_name",
        "attempted_tenant_ids",  # Tenants user tried to access
        "denial_reason",       # Enum: no_permission, filter_violation, policy_block
        "query_fingerprint",   # Hash of query for analysis
    ],

    "rls.modified": [
        "rule_id",
        "dataset_id",
        "tenant_id",
        "modified_by",
        "previous_clause",
        "new_clause",
        "change_reason",
    ],

    "rls.created": [
        "rule_id",
        "dataset_id",
        "tenant_id",
        "created_by",
        "clause",
        "applies_to_roles",
    ],

    "rls.deleted": [
        "rule_id",
        "dataset_id",
        "tenant_id",
        "deleted_by",
        "reason",
    ],

    "rls.bypass_attempted": [
        "user_id",
        "tenant_id",
        "dataset_id",
        "bypass_method",       # How bypass was attempted
        "blocked",             # Boolean: whether attempt was blocked
        "client_ip",
    ],

    # =========================================================================
    # DASHBOARD ACCESS & LIFECYCLE
    # =========================================================================
    # Track all dashboard interactions for usage analytics and security.

    "dashboard.viewed": [
        "user_id",
        "tenant_id",
        "dashboard_id",
        "dashboard_name",
        "embed_context",       # Whether viewed in embedded mode
        "view_duration_ms",    # How long dashboard was viewed (if available)
        "filters_applied",     # List of filter names used
    ],

    "dashboard.created": [
        "user_id",
        "tenant_id",
        "dashboard_id",
        "dashboard_name",
        "chart_count",
        "dataset_ids",         # Datasets used
        "is_template",         # Whether created from template
    ],

    "dashboard.edited": [
        "user_id",
        "tenant_id",
        "dashboard_id",
        "dashboard_name",
        "changes",             # Dict of what changed
        "previous_version",
        "new_version",
    ],

    "dashboard.deleted": [
        "user_id",
        "tenant_id",
        "dashboard_id",
        "dashboard_name",
        "deleted_by",
        "reason",
        "recoverable",         # Whether soft-deleted
    ],

    "dashboard.shared": [
        "user_id",
        "tenant_id",
        "dashboard_id",
        "shared_with",         # List of user_ids or role_ids
        "permissions_granted", # Enum: view, edit, admin
        "expiration",          # When sharing expires (if applicable)
    ],

    "dashboard.access_revoked": [
        "user_id",
        "tenant_id",
        "dashboard_id",
        "revoked_from",        # List of user_ids or role_ids
        "revoked_by",
        "reason",
    ],

    "dashboard.exported": [
        "user_id",
        "tenant_id",
        "dashboard_id",
        "export_format",       # Enum: pdf, png, csv
        "include_data",        # Whether raw data was included
        "row_count",           # If data included
    ],

    "dashboard.embed_token_generated": [
        "user_id",
        "tenant_id",
        "dashboard_id",
        "token_lifetime_minutes",
        "allowed_domains",     # CSP domains for embedding
        "rls_filters",         # RLS applied to embed token
    ],

    # =========================================================================
    # EXPLORE / AD-HOC QUERY EXECUTION
    # =========================================================================
    # Track all query execution for performance monitoring and security.

    "explore.query_executed": [
        "user_id",
        "tenant_id",
        "dataset_id",
        "dataset_name",
        "dimensions",          # List of dimension columns
        "measures",            # List of measure columns
        "filters",             # List of filter definitions
        "row_count",
        "query_duration_ms",
        "cache_hit",
        "rls_applied",
    ],

    "explore.query_denied": [
        "user_id",
        "tenant_id",
        "dataset_id",
        "dataset_name",
        "denial_reason",       # Enum: no_permission, rls_block, rate_limit
        "requested_columns",
    ],

    "explore.query_timeout": [
        "user_id",
        "tenant_id",
        "dataset_id",
        "dataset_name",
        "timeout_seconds",
        "query_complexity_score",
        "estimated_row_count",
        "suggested_optimization",
    ],

    "explore.query_cancelled": [
        "user_id",
        "tenant_id",
        "dataset_id",
        "cancelled_by",        # user_id or "system"
        "cancel_reason",       # Enum: user_request, timeout, resource_limit
        "runtime_before_cancel_ms",
    ],

    "explore.bulk_query_detected": [
        "user_id",
        "tenant_id",
        "query_count",
        "time_window_minutes",
        "datasets_accessed",
        "total_rows_accessed",
        "alert_triggered",
    ],

    # =========================================================================
    # METRIC DEFINITION GOVERNANCE
    # =========================================================================
    # Track all metric definition changes for data governance and audit.

    "metric.created": [
        "user_id",
        "tenant_id",
        "metric_id",
        "metric_name",
        "definition",          # SQL or expression
        "dataset_id",
        "certified",           # Boolean: whether metric is certified
    ],

    "metric.definition_changed": [
        "user_id",
        "tenant_id",
        "metric_id",
        "metric_name",
        "previous_version",
        "new_version",
        "previous_definition",
        "new_definition",
        "breaking_changes",    # Boolean: whether change breaks existing usage
        "approved_by",         # user_id of approver (if approval required)
        "change_reason",
    ],

    "metric.certified": [
        "metric_id",
        "metric_name",
        "tenant_id",
        "certified_by",
        "certification_level", # Enum: team, org, enterprise
        "documentation_url",
    ],

    "metric.deprecated": [
        "metric_id",
        "metric_name",
        "tenant_id",
        "deprecated_by",
        "replacement_metric_id",
        "sunset_date",
        "affected_dashboard_count",
    ],

    "metric.deleted": [
        "metric_id",
        "metric_name",
        "tenant_id",
        "deleted_by",
        "reason",
        "affected_dashboards",
    ],

    # =========================================================================
    # DATASET SYNC & CACHE OPERATIONS
    # =========================================================================
    # Track data pipeline operations for debugging and monitoring.

    "dataset.synced": [
        "dataset_id",
        "dataset_name",
        "tenant_id",
        "sync_type",           # Enum: full, incremental, schema_only
        "row_count",
        "sync_duration_ms",
        "triggered_by",        # Enum: schedule, manual, webhook
        "source_freshness",    # How fresh the source data was
    ],

    "dataset.sync_failed": [
        "dataset_id",
        "dataset_name",
        "tenant_id",
        "failure_reason",
        "error_message",
        "retry_count",
        "will_retry",
    ],

    "dataset.schema_changed": [
        "dataset_id",
        "dataset_name",
        "tenant_id",
        "columns_added",
        "columns_removed",
        "columns_modified",
        "detected_by",         # Enum: sync, manual, schema_scan
    ],

    "cache.cleared": [
        "tenant_id",
        "scope",               # Enum: dataset, dashboard, query, all
        "scope_id",            # ID of specific resource if applicable
        "cleared_by",
        "reason",
        "cache_size_mb",       # Size of cleared cache
    ],

    "cache.warmed": [
        "tenant_id",
        "scope",
        "scope_id",
        "queries_warmed",
        "warm_duration_ms",
        "triggered_by",
    ],

    "cache.evicted": [
        "tenant_id",
        "cache_key",
        "eviction_reason",     # Enum: ttl, memory_pressure, invalidation
        "age_minutes",
    ],

    # =========================================================================
    # QUERY TIMEOUTS & ANOMALIES
    # =========================================================================
    # Track performance issues and anomalous behavior patterns.

    "anomaly.slow_query": [
        "user_id",
        "tenant_id",
        "dataset_id",
        "query_duration_ms",
        "threshold_ms",        # What threshold was exceeded
        "query_fingerprint",
        "optimization_suggestions",
    ],

    "anomaly.high_row_count": [
        "user_id",
        "tenant_id",
        "dataset_id",
        "row_count",
        "threshold",
        "query_fingerprint",
    ],

    "anomaly.unusual_access_pattern": [
        "user_id",
        "tenant_id",
        "pattern_type",        # Enum: time_of_day, frequency, data_volume
        "deviation_score",     # How far from normal
        "baseline_description",
        "alert_triggered",
    ],

    "anomaly.resource_exhaustion": [
        "tenant_id",
        "resource_type",       # Enum: cpu, memory, connections, queries
        "current_usage",
        "limit",
        "affected_users",
    ],

    # =========================================================================
    # CROSS-TENANT ACCESS ATTEMPTS
    # =========================================================================
    # Critical security events - any cross-tenant access must be logged.

    "cross_tenant.access_attempted": [
        "user_id",
        "from_tenant_id",      # User's actual tenant
        "to_tenant_id",        # Tenant user tried to access
        "resource_type",       # Enum: dashboard, dataset, metric
        "resource_id",
        "success",             # Boolean: whether access was granted
        "access_method",       # How access was attempted
        "client_ip",
        "grant_reason",        # Why access was granted (if successful)
    ],

    "cross_tenant.access_granted": [
        "user_id",
        "from_tenant_id",
        "to_tenant_id",
        "resource_type",
        "resource_id",
        "granted_by",          # user_id or policy that granted access
        "grant_reason",        # Enum: agency_role, explicit_share, admin_override
        "expiration",
    ],

    "cross_tenant.access_revoked": [
        "user_id",
        "from_tenant_id",
        "to_tenant_id",
        "resource_type",
        "resource_id",
        "revoked_by",
        "reason",
    ],

    "cross_tenant.data_leak_detected": [
        "user_id",
        "from_tenant_id",
        "to_tenant_id",
        "leak_type",           # Enum: query_result, export, cache_leak
        "data_volume",
        "detection_method",
        "remediation_action",
    ],

    # =========================================================================
    # ADMINISTRATIVE OPERATIONS
    # =========================================================================
    # Track all admin actions for audit and compliance.

    "admin.config_changed": [
        "admin_user_id",
        "config_key",
        "previous_value",      # Sanitized if sensitive
        "new_value",           # Sanitized if sensitive
        "change_reason",
        "requires_restart",
    ],

    "admin.user_impersonated": [
        "admin_user_id",
        "impersonated_user_id",
        "tenant_id",
        "reason",
        "duration_minutes",
    ],

    "admin.tenant_suspended": [
        "admin_user_id",
        "tenant_id",
        "reason",
        "suspension_type",     # Enum: billing, security, compliance
        "auto_reactivate_at",
    ],

    "admin.data_export_requested": [
        "admin_user_id",
        "tenant_id",
        "export_scope",        # Enum: all, audit_logs, analytics_data
        "reason",
        "approved_by",
    ],

    "admin.audit_log_exported": [
        "admin_user_id",
        "tenant_id",
        "date_range_start",
        "date_range_end",
        "event_count",
        "export_format",
        "destination",
    ],
}


# =============================================================================
# EVENT CATEGORIES FOR GROUPING AND FILTERING
# =============================================================================

EVENT_CATEGORIES: Final[dict[str, list[str]]] = {
    "authentication": [
        "auth.jwt_issued",
        "auth.jwt_refresh",
        "auth.jwt_revoked",
        "auth.jwt_validation_failed",
        "auth.login_success",
        "auth.login_failed",
        "auth.session_expired",
        "auth.api_token_created",
        "auth.api_token_revoked",
    ],
    "authorization": [
        "role.assigned",
        "role.revoked",
        "role.modified",
        "permission.escalation_detected",
    ],
    "rls": [
        "rls.applied",
        "rls.denied",
        "rls.modified",
        "rls.created",
        "rls.deleted",
        "rls.bypass_attempted",
    ],
    "dashboard": [
        "dashboard.viewed",
        "dashboard.created",
        "dashboard.edited",
        "dashboard.deleted",
        "dashboard.shared",
        "dashboard.access_revoked",
        "dashboard.exported",
        "dashboard.embed_token_generated",
    ],
    "explore": [
        "explore.query_executed",
        "explore.query_denied",
        "explore.query_timeout",
        "explore.query_cancelled",
        "explore.bulk_query_detected",
    ],
    "governance": [
        "metric.created",
        "metric.definition_changed",
        "metric.certified",
        "metric.deprecated",
        "metric.deleted",
    ],
    "operations": [
        "dataset.synced",
        "dataset.sync_failed",
        "dataset.schema_changed",
        "cache.cleared",
        "cache.warmed",
        "cache.evicted",
    ],
    "anomaly": [
        "anomaly.slow_query",
        "anomaly.high_row_count",
        "anomaly.unusual_access_pattern",
        "anomaly.resource_exhaustion",
    ],
    "cross_tenant": [
        "cross_tenant.access_attempted",
        "cross_tenant.access_granted",
        "cross_tenant.access_revoked",
        "cross_tenant.data_leak_detected",
    ],
    "admin": [
        "admin.config_changed",
        "admin.user_impersonated",
        "admin.tenant_suspended",
        "admin.data_export_requested",
        "admin.audit_log_exported",
    ],
}


# =============================================================================
# SEVERITY LEVELS FOR EVENTS
# =============================================================================
# Used by alerting systems to determine escalation paths.

EVENT_SEVERITY: Final[dict[str, str]] = {
    # Critical - Immediate response required
    "auth.login_failed": "high",
    "auth.jwt_validation_failed": "medium",
    "rls.denied": "high",
    "rls.bypass_attempted": "critical",
    "cross_tenant.access_attempted": "critical",
    "cross_tenant.data_leak_detected": "critical",
    "permission.escalation_detected": "critical",
    "anomaly.resource_exhaustion": "critical",

    # High - Response within 15 minutes
    "explore.query_denied": "high",
    "dataset.sync_failed": "high",
    "admin.user_impersonated": "high",
    "admin.tenant_suspended": "high",

    # Medium - Response within 1 hour
    "explore.query_timeout": "medium",
    "anomaly.slow_query": "medium",
    "anomaly.unusual_access_pattern": "medium",
    "explore.bulk_query_detected": "medium",

    # Low - Informational, review daily
    "dashboard.viewed": "low",
    "dashboard.exported": "low",
    "explore.query_executed": "low",
    "cache.cleared": "low",
}


# =============================================================================
# VALIDATION UTILITIES
# =============================================================================

def validate_event_metadata(event_type: str, metadata: dict) -> tuple[bool, list[str]]:
    """
    Validate that metadata contains all required fields for an event type.

    Args:
        event_type: The event type identifier (e.g., "auth.jwt_issued")
        metadata: The metadata dictionary to validate

    Returns:
        Tuple of (is_valid, missing_fields)

    Example:
        >>> valid, missing = validate_event_metadata("auth.jwt_issued", {"user_id": "123"})
        >>> valid
        False
        >>> missing
        ['tenant_id', 'lifetime_minutes', 'scopes', 'embed_context']
    """
    if event_type not in AUDITABLE_EVENTS:
        return False, [f"Unknown event type: {event_type}"]

    required_fields = AUDITABLE_EVENTS[event_type]
    missing_fields = [field for field in required_fields if field not in metadata]

    return len(missing_fields) == 0, missing_fields


def get_event_category(event_type: str) -> str | None:
    """
    Get the category for an event type.

    Args:
        event_type: The event type identifier

    Returns:
        Category name or None if event type not found
    """
    for category, events in EVENT_CATEGORIES.items():
        if event_type in events:
            return category
    return None


def get_event_severity(event_type: str) -> str:
    """
    Get the severity level for an event type.

    Args:
        event_type: The event type identifier

    Returns:
        Severity level (defaults to "low" if not explicitly defined)
    """
    return EVENT_SEVERITY.get(event_type, "low")


def get_all_event_types() -> list[str]:
    """
    Get a list of all registered event types.

    Returns:
        Sorted list of all event type identifiers
    """
    return sorted(AUDITABLE_EVENTS.keys())


def get_events_by_category(category: str) -> list[str]:
    """
    Get all event types in a category.

    Args:
        category: Category name (e.g., "authentication", "rls")

    Returns:
        List of event types in the category, or empty list if category not found
    """
    return EVENT_CATEGORIES.get(category, [])


def get_required_fields(event_type: str) -> list[str]:
    """
    Get the required metadata fields for an event type.

    Args:
        event_type: The event type identifier

    Returns:
        List of required field names, or empty list if event type not found
    """
    return AUDITABLE_EVENTS.get(event_type, [])
