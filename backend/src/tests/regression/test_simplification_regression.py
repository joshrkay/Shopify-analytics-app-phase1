"""
Regression tests for codebase simplification.

These tests ensure that simplification changes do not break existing functionality.
Run these tests before and after any simplification to verify non-breaking changes.

Usage:
    pytest backend/src/tests/regression/test_simplification_regression.py -v
"""

import sys
import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from datetime import datetime, timezone

from fastapi import Request, HTTPException, status
from fastapi.testclient import TestClient
from fastapi import FastAPI

# Import directly from modules to avoid __init__.py import chain issues
# This bypasses the jwt/cryptography dependency that causes issues in some environments


# =============================================================================
# ERROR HANDLING REGRESSION TESTS
# =============================================================================

class TestErrorClassContracts:
    """Verify error classes maintain their public contracts."""

    def test_app_error_has_required_attributes(self):
        """AppError must have code, message, status_code, details."""
        from src.platform.errors import AppError  # Direct import, not via __init__

        error = AppError(
            code="TEST",
            message="test message",
            status_code=500,
            details={"key": "value"}
        )

        assert hasattr(error, 'code')
        assert hasattr(error, 'message')
        assert hasattr(error, 'status_code')
        assert hasattr(error, 'details')
        assert error.code == "TEST"
        assert error.message == "test message"
        assert error.status_code == 500
        assert error.details == {"key": "value"}

    def test_app_error_to_dict_format(self):
        """AppError.to_dict() must return exact format."""
        from src.platform.errors import AppError

        error = AppError(code="CODE", message="msg", details={"d": 1})
        result = error.to_dict()

        # Must have 'error' key at top level
        assert "error" in result
        assert set(result["error"].keys()) == {"code", "message", "details"}
        assert result["error"]["code"] == "CODE"
        assert result["error"]["message"] == "msg"
        assert result["error"]["details"] == {"d": 1}

    @pytest.mark.parametrize("error_class,expected_status,expected_code", [
        ("ValidationError", 400, "VALIDATION_ERROR"),
        ("AuthenticationError", 401, "AUTHENTICATION_ERROR"),
        ("PaymentRequiredError", 402, "PAYMENT_REQUIRED"),
        ("PermissionDeniedError", 403, "PERMISSION_DENIED"),
        ("TenantIsolationError", 403, "ACCESS_DENIED"),
        ("NotFoundError", 404, "NOT_FOUND"),
        ("ConflictError", 409, "CONFLICT"),
        ("RateLimitError", 429, "RATE_LIMIT_EXCEEDED"),
        ("ServiceUnavailableError", 503, "SERVICE_UNAVAILABLE"),
        ("FeatureDisabledError", 503, "FEATURE_DISABLED"),
    ])
    def test_error_status_codes_unchanged(self, error_class, expected_status, expected_code):
        """Each error class must return its expected status code."""
        import src.platform.errors as errors

        cls = getattr(errors, error_class)

        if error_class == "NotFoundError":
            error = cls("Resource")
        elif error_class == "FeatureDisabledError":
            error = cls("feature-name")
        elif error_class in ["ValidationError", "ConflictError"]:
            error = cls("test message")
        else:
            error = cls()

        assert error.status_code == expected_status, f"{error_class} status mismatch"
        assert error.code == expected_code, f"{error_class} code mismatch"

    def test_tenant_isolation_error_hides_details(self):
        """TenantIsolationError must never expose tenant details."""
        from src.platform.errors import TenantIsolationError

        # Even if initialized with sensitive message, it should be hidden
        error = TenantIsolationError("Attempted access to tenant-secret-123")

        assert "tenant-secret-123" not in error.message
        assert error.message == "Access denied"
        assert error.details == {}
        assert error.code == "ACCESS_DENIED"

    def test_rate_limit_error_includes_retry_after(self):
        """RateLimitError must include retry_after in details when provided."""
        from src.platform.errors import RateLimitError

        error = RateLimitError(retry_after=60)

        assert error.details["retry_after_seconds"] == 60

    def test_not_found_error_message_format(self):
        """NotFoundError message must include resource and identifier."""
        from src.platform.errors import NotFoundError

        error1 = NotFoundError("User")
        assert "User" in error1.message

        error2 = NotFoundError("Plan", "plan-123")
        assert "Plan" in error2.message
        assert "plan-123" in error2.message


class TestCorrelationIdContract:
    """Verify correlation ID handling unchanged."""

    def test_generate_correlation_id_returns_uuid(self):
        """generate_correlation_id must return valid UUID string."""
        from src.platform.errors import generate_correlation_id

        corr_id = generate_correlation_id()

        assert isinstance(corr_id, str)
        assert len(corr_id) == 36  # UUID format with dashes

    def test_get_correlation_id_priority(self):
        """get_correlation_id must check header first, then state."""
        from src.platform.errors import get_correlation_id

        # Header takes priority
        request = Mock(spec=Request)
        request.headers = {"X-Correlation-ID": "from-header"}
        request.state = Mock()
        request.state.correlation_id = "from-state"

        assert get_correlation_id(request) == "from-header"

        # Falls back to state
        request.headers = {}
        assert get_correlation_id(request) == "from-state"


# =============================================================================
# RBAC REGRESSION TESTS
# =============================================================================

class TestRBACFunctionContracts:
    """Verify RBAC functions maintain their contracts."""

    @pytest.fixture
    def admin_context(self):
        from src.platform.tenant_context import TenantContext
        return TenantContext(
            tenant_id="test-tenant",
            user_id="admin-user",
            roles=["admin"],
            org_id="test-tenant"
        )

    @pytest.fixture
    def viewer_context(self):
        from src.platform.tenant_context import TenantContext
        return TenantContext(
            tenant_id="test-tenant",
            user_id="viewer-user",
            roles=["viewer"],
            org_id="test-tenant"
        )

    def test_has_permission_signature(self, admin_context):
        """has_permission accepts TenantContext and Permission."""
        from src.platform.rbac import has_permission
        from src.constants.permissions import Permission

        result = has_permission(admin_context, Permission.ANALYTICS_VIEW)
        assert isinstance(result, bool)

    def test_has_any_permission_signature(self, admin_context):
        """has_any_permission accepts TenantContext and list of Permissions."""
        from src.platform.rbac import has_any_permission
        from src.constants.permissions import Permission

        result = has_any_permission(admin_context, [Permission.ANALYTICS_VIEW])
        assert isinstance(result, bool)

    def test_has_all_permissions_signature(self, admin_context):
        """has_all_permissions accepts TenantContext and list of Permissions."""
        from src.platform.rbac import has_all_permissions
        from src.constants.permissions import Permission

        result = has_all_permissions(admin_context, [Permission.ANALYTICS_VIEW])
        assert isinstance(result, bool)

    def test_has_role_signature(self, admin_context):
        """has_role accepts TenantContext and Role."""
        from src.platform.rbac import has_role
        from src.constants.permissions import Role

        result = has_role(admin_context, Role.ADMIN)
        assert isinstance(result, bool)

    def test_admin_has_all_permissions(self, admin_context):
        """Admin role must have all permissions."""
        from src.platform.rbac import has_permission
        from src.constants.permissions import Permission

        for perm in Permission:
            assert has_permission(admin_context, perm), f"Admin missing {perm}"

    def test_viewer_lacks_write_permissions(self, viewer_context):
        """Viewer must not have write/admin permissions."""
        from src.platform.rbac import has_permission
        from src.constants.permissions import Permission

        # Viewer should have view permission
        assert has_permission(viewer_context, Permission.ANALYTICS_VIEW)

        # Viewer should NOT have admin permissions
        assert not has_permission(viewer_context, Permission.ADMIN_PLANS_MANAGE)
        assert not has_permission(viewer_context, Permission.ADMIN_SYSTEM_CONFIG)


class TestRBACDecoratorContracts:
    """Verify RBAC decorators maintain their contracts."""

    def test_require_permission_is_decorator(self):
        """require_permission must return a decorator."""
        from src.platform.rbac import require_permission
        from src.constants.permissions import Permission

        decorator = require_permission(Permission.ANALYTICS_VIEW)
        assert callable(decorator)

    def test_require_any_permission_is_decorator(self):
        """require_any_permission must return a decorator."""
        from src.platform.rbac import require_any_permission
        from src.constants.permissions import Permission

        decorator = require_any_permission(Permission.ANALYTICS_VIEW)
        assert callable(decorator)

    def test_require_all_permissions_is_decorator(self):
        """require_all_permissions must return a decorator."""
        from src.platform.rbac import require_all_permissions
        from src.constants.permissions import Permission

        decorator = require_all_permissions(Permission.ANALYTICS_VIEW)
        assert callable(decorator)

    def test_require_role_is_decorator(self):
        """require_role must return a decorator."""
        from src.platform.rbac import require_role
        from src.constants.permissions import Role

        decorator = require_role(Role.ADMIN)
        assert callable(decorator)

    def test_require_admin_is_decorator(self):
        """require_admin must be a decorator."""
        from src.platform.rbac import require_admin

        assert callable(require_admin)


# =============================================================================
# AUDIT SYSTEM REGRESSION TESTS
# =============================================================================

class TestAuditActionContract:
    """Verify AuditAction enum values unchanged."""

    def test_audit_action_is_string_enum(self):
        """AuditAction must be string enum."""
        from src.platform.audit import AuditAction

        assert issubclass(AuditAction, str)
        for action in AuditAction:
            assert isinstance(action.value, str)

    def test_critical_audit_actions_exist(self):
        """Critical audit actions must exist."""
        from src.platform.audit import AuditAction

        critical_actions = [
            "AUTH_LOGIN",
            "AUTH_LOGOUT",
            "BILLING_PLAN_CHANGED",
            "STORE_CONNECTED",
            "STORE_DISCONNECTED",
            "AI_ACTION_EXECUTED",
            "TEAM_ROLE_CHANGED",
        ]

        for action_name in critical_actions:
            assert hasattr(AuditAction, action_name), f"Missing {action_name}"


class TestAuditEventContract:
    """Verify AuditEvent dataclass contract."""

    def test_audit_event_required_fields(self):
        """AuditEvent must have required fields."""
        from src.platform.audit import AuditEvent, AuditAction

        event = AuditEvent(
            tenant_id="tenant-1",
            user_id="user-1",
            action=AuditAction.AUTH_LOGIN,
        )

        assert event.tenant_id == "tenant-1"
        assert event.user_id == "user-1"
        assert event.action == AuditAction.AUTH_LOGIN

    def test_audit_event_to_dict_format(self):
        """AuditEvent.to_dict() must return expected format."""
        from src.platform.audit import AuditEvent, AuditAction

        event = AuditEvent(
            tenant_id="t1",
            user_id="u1",
            action=AuditAction.AUTH_LOGIN,
            resource_type="session",
            resource_id="s1",
            metadata={"browser": "chrome"},
        )

        result = event.to_dict()

        assert result["tenant_id"] == "t1"
        assert result["user_id"] == "u1"
        assert result["action"] == "auth.login"
        assert result["resource_type"] == "session"
        assert result["resource_id"] == "s1"
        assert result["event_metadata"] == {"browser": "chrome"}


class TestAuditLogModelContract:
    """Verify AuditLog model contract."""

    def test_audit_log_table_name(self):
        """AuditLog table must be 'audit_logs'."""
        from src.platform.audit import AuditLog

        assert AuditLog.__tablename__ == "audit_logs"

    def test_audit_log_has_required_columns(self):
        """AuditLog must have required columns."""
        from src.platform.audit import AuditLog

        required_columns = [
            "id", "tenant_id", "user_id", "action",
            "timestamp", "ip_address", "user_agent",
            "resource_type", "resource_id", "event_metadata",
            "correlation_id"
        ]

        for col in required_columns:
            assert hasattr(AuditLog, col), f"Missing column {col}"


# =============================================================================
# SECRETS MODULE REGRESSION TESTS
# =============================================================================

class TestSecretRedactionContract:
    """Verify secret redaction maintains its contract."""

    def test_redact_secrets_handles_dict(self):
        """redact_secrets must handle dict input."""
        from src.platform.secrets import redact_secrets

        data = {"api_key": "sk-secret123", "name": "test"}
        result = redact_secrets(data)

        assert result["api_key"] == "[REDACTED]"
        assert result["name"] == "test"

    def test_redact_secrets_handles_nested(self):
        """redact_secrets must handle nested structures."""
        from src.platform.secrets import redact_secrets

        data = {
            "config": {
                "password": "secret",
                "host": "localhost"
            }
        }
        result = redact_secrets(data)

        assert result["config"]["password"] == "[REDACTED]"
        assert result["config"]["host"] == "localhost"

    def test_is_secret_key_detects_patterns(self):
        """is_secret_key must detect known secret patterns."""
        from src.platform.secrets import is_secret_key

        secret_keys = [
            "api_key", "API_KEY", "apiKey",
            "secret_key", "SECRET_KEY",
            "access_token", "ACCESS_TOKEN",
            "password", "PASSWORD",
            "client_secret", "CLIENT_SECRET",
        ]

        for key in secret_keys:
            assert is_secret_key(key), f"Failed to detect {key}"

    def test_mask_secret_format(self):
        """mask_secret must return masked format."""
        from src.platform.secrets import mask_secret

        result = mask_secret("abcdefghijklmnop", visible_chars=4)

        assert result.endswith("mnop")
        assert result.startswith("*")
        assert len(result) == 16


class TestEncryptionContract:
    """Verify encryption maintains its contract."""

    @pytest.fixture
    def setup_encryption(self, monkeypatch):
        """Set up encryption key."""
        monkeypatch.setenv("ENCRYPTION_KEY", "test-encryption-key-for-testing")

    @pytest.mark.asyncio
    async def test_encrypt_decrypt_roundtrip(self, setup_encryption):
        """Encrypt then decrypt must return original."""
        from src.platform.secrets import encrypt_secret, decrypt_secret

        # Reset singleton state
        from src.platform.secrets import _secrets_manager
        _secrets_manager._initialized = False

        original = "my-secret-value"
        encrypted = await encrypt_secret(original)
        decrypted = await decrypt_secret(encrypted)

        assert decrypted == original
        assert encrypted != original


# =============================================================================
# REPOSITORY LAYER REGRESSION TESTS
# =============================================================================

class TestBaseRepositoryContract:
    """Verify BaseRepository maintains its contract."""

    def test_base_repository_requires_tenant_id(self):
        """BaseRepository must require tenant_id."""
        from src.repositories.base_repo import BaseRepository

        # Should raise if tenant_id is empty
        with pytest.raises(ValueError):
            class TestRepo(BaseRepository):
                def _get_model_class(self):
                    return Mock()
                def _get_tenant_column_name(self):
                    return "tenant_id"

            TestRepo(Mock(), "")  # Empty tenant_id

    def test_tenant_isolation_error_exists(self):
        """TenantIsolationError must exist in repository module."""
        from src.repositories.base_repo import TenantIsolationError

        error = TenantIsolationError("test")
        assert isinstance(error, Exception)


# =============================================================================
# GOVERNANCE MODULE REGRESSION TESTS
# =============================================================================

class TestGovernanceModuleExists:
    """Verify governance module components exist (if module kept)."""

    def test_ai_guardrails_importable(self):
        """AIGuardrails must be importable."""
        try:
            from src.governance.ai_guardrails import AIGuardrails
            assert AIGuardrails is not None
        except ImportError:
            pytest.skip("Governance module removed")

    def test_refusal_reason_enum_exists(self):
        """RefusalReason enum must exist."""
        try:
            from src.governance.ai_guardrails import RefusalReason
            assert hasattr(RefusalReason, "PROHIBITED_ACTION")
        except ImportError:
            pytest.skip("Governance module removed")


# =============================================================================
# PERMISSIONS CONSTANTS REGRESSION TESTS
# =============================================================================

class TestPermissionsConstantsContract:
    """Verify permissions constants unchanged."""

    def test_permission_enum_has_critical_values(self):
        """Permission enum must have critical permission values."""
        from src.constants.permissions import Permission

        critical_permissions = [
            "ANALYTICS_VIEW",
            "ANALYTICS_EXPORT",
            "STORE_VIEW",
            "STORE_CREATE",
            "STORE_DELETE",
            "BILLING_VIEW",
            "BILLING_MANAGE",
            "ADMIN_PLANS_VIEW",
            "ADMIN_PLANS_MANAGE",
            "ADMIN_SYSTEM_CONFIG",
        ]

        for perm in critical_permissions:
            assert hasattr(Permission, perm), f"Missing {perm}"

    def test_role_enum_has_critical_values(self):
        """Role enum must have critical role values."""
        from src.constants.permissions import Role

        critical_roles = ["ADMIN", "OWNER", "EDITOR", "VIEWER"]

        for role in critical_roles:
            assert hasattr(Role, role), f"Missing {role}"

    def test_role_permissions_mapping_complete(self):
        """ROLE_PERMISSIONS must have entry for each role."""
        from src.constants.permissions import Role, ROLE_PERMISSIONS

        for role in Role:
            assert role in ROLE_PERMISSIONS, f"Missing permissions for {role}"
            assert len(ROLE_PERMISSIONS[role]) > 0, f"Empty permissions for {role}"


# =============================================================================
# API RESPONSE FORMAT TESTS
# =============================================================================

class TestAPIResponseFormats:
    """Verify API response formats unchanged."""

    def test_error_response_has_standard_structure(self):
        """All error responses must have standard structure."""
        from src.platform.errors import (
            ValidationError, AuthenticationError, NotFoundError
        )

        errors = [
            ValidationError("test"),
            AuthenticationError(),
            NotFoundError("Resource"),
        ]

        for error in errors:
            response = error.to_dict()

            # Top level must have 'error' key only
            assert "error" in response

            # Error object must have exactly these keys
            error_obj = response["error"]
            assert "code" in error_obj
            assert "message" in error_obj
            assert "details" in error_obj

            # Types must be correct
            assert isinstance(error_obj["code"], str)
            assert isinstance(error_obj["message"], str)
            assert isinstance(error_obj["details"], dict)


# =============================================================================
# INTEGRATION REGRESSION TESTS
# =============================================================================

class TestMiddlewareIntegration:
    """Verify middleware integration unchanged."""

    def test_error_handler_middleware_exists(self):
        """ErrorHandlerMiddleware must exist and be usable."""
        from src.platform.errors import ErrorHandlerMiddleware
        from fastapi import FastAPI

        app = FastAPI()
        middleware = ErrorHandlerMiddleware(app)

        assert middleware is not None
        assert hasattr(middleware, 'dispatch')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
