"""
Platform-level modules for multi-tenant enforcement and security.

This package contains the Epic 0 platform foundations:
- tenant_context: Multi-tenant context enforcement
- rbac: Role-based access control
- audit: Audit logging
- feature_flags: Feature flag management (Frontegg)
- secrets: Secrets management and encryption
- errors: Consistent error handling
"""

from src.platform.tenant_context import (
    TenantContext,
    TenantContextMiddleware,
    get_tenant_context,
    require_tenant_context,
)

from src.platform.errors import (
    AppError,
    ValidationError,
    AuthenticationError,
    PaymentRequiredError,
    PermissionDeniedError,
    TenantIsolationError,
    NotFoundError,
    ConflictError,
    RateLimitError,
    ServiceUnavailableError,
    FeatureDisabledError,
    ErrorHandlerMiddleware,
    generate_correlation_id,
    get_correlation_id,
)

from src.platform.rbac import (
    has_permission,
    has_any_permission,
    has_all_permissions,
    has_role,
    require_permission,
    require_any_permission,
    require_all_permissions,
    require_role,
    require_admin,
    check_permission_or_raise,
)

from src.platform.audit import (
    AuditAction,
    AuditEvent,
    AuditLog,
    AuditBase,
    write_audit_log,
    log_audit_event,
    log_system_audit_event,
    create_audit_decorator,
    extract_client_info,
)

from src.platform.feature_flags import (
    FeatureFlag,
    get_feature_flag_client,
    is_feature_enabled,
    is_kill_switch_active,
    require_feature_flag,
    require_kill_switch_inactive,
    check_feature_or_raise,
)

from src.platform.secrets import (
    encrypt_secret,
    decrypt_secret,
    redact_secrets,
    mask_secret,
    is_secret_key,
    SecretRedactingFilter,
    get_env_secret,
    validate_encryption_configured,
)

__all__ = [
    # Tenant context
    "TenantContext",
    "TenantContextMiddleware",
    "get_tenant_context",
    "require_tenant_context",
    # Errors
    "AppError",
    "ValidationError",
    "AuthenticationError",
    "PaymentRequiredError",
    "PermissionDeniedError",
    "TenantIsolationError",
    "NotFoundError",
    "ConflictError",
    "RateLimitError",
    "ServiceUnavailableError",
    "FeatureDisabledError",
    "ErrorHandlerMiddleware",
    "generate_correlation_id",
    "get_correlation_id",
    # RBAC
    "has_permission",
    "has_any_permission",
    "has_all_permissions",
    "has_role",
    "require_permission",
    "require_any_permission",
    "require_all_permissions",
    "require_role",
    "require_admin",
    "check_permission_or_raise",
    # Audit
    "AuditAction",
    "AuditEvent",
    "AuditLog",
    "AuditBase",
    "write_audit_log",
    "log_audit_event",
    "log_system_audit_event",
    "create_audit_decorator",
    "extract_client_info",
    # Feature flags
    "FeatureFlag",
    "get_feature_flag_client",
    "is_feature_enabled",
    "is_kill_switch_active",
    "require_feature_flag",
    "require_kill_switch_inactive",
    "check_feature_or_raise",
    # Secrets
    "encrypt_secret",
    "decrypt_secret",
    "redact_secrets",
    "mask_secret",
    "is_secret_key",
    "SecretRedactingFilter",
    "get_env_secret",
    "validate_encryption_configured",
]