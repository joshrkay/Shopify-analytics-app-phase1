"""
API Contract Tests for Codebase Simplification.

These tests verify that external API contracts remain unchanged after simplification.
They test the exact shape and behavior of API responses.

Usage:
    pytest backend/src/tests/regression/test_api_contracts.py -v
"""

import pytest
import json
from unittest.mock import Mock, MagicMock, patch
from fastapi import FastAPI, Request, HTTPException
from fastapi.testclient import TestClient


# =============================================================================
# ERROR RESPONSE CONTRACT TESTS
# =============================================================================

class TestErrorResponseContracts:
    """Verify error responses match expected contracts exactly."""

    @pytest.fixture
    def app_with_errors(self):
        """Create app that raises various errors."""
        from src.platform.errors import (
            ValidationError, AuthenticationError, PaymentRequiredError,
            PermissionDeniedError, TenantIsolationError, NotFoundError,
            ConflictError, RateLimitError, ServiceUnavailableError,
            FeatureDisabledError, ErrorHandlerMiddleware
        )

        app = FastAPI()

        @app.middleware("http")
        async def error_handler(request: Request, call_next):
            middleware = ErrorHandlerMiddleware(app)
            return await middleware.dispatch(request, call_next)

        @app.get("/error/validation")
        async def validation_error():
            raise ValidationError("Invalid input", {"field": "email", "reason": "invalid format"})

        @app.get("/error/auth")
        async def auth_error():
            raise AuthenticationError("Token expired")

        @app.get("/error/payment")
        async def payment_error():
            raise PaymentRequiredError("Upgrade required")

        @app.get("/error/permission")
        async def permission_error():
            raise PermissionDeniedError("Admin only")

        @app.get("/error/tenant")
        async def tenant_error():
            raise TenantIsolationError("Cross-tenant access to tenant-secret-123")

        @app.get("/error/notfound")
        async def notfound_error():
            raise NotFoundError("User", "user-123")

        @app.get("/error/conflict")
        async def conflict_error():
            raise ConflictError("Resource already exists", {"existing_id": "abc"})

        @app.get("/error/ratelimit")
        async def ratelimit_error():
            raise RateLimitError("Too many requests", retry_after=60)

        @app.get("/error/unavailable")
        async def unavailable_error():
            raise ServiceUnavailableError("Database maintenance")

        @app.get("/error/feature")
        async def feature_error():
            raise FeatureDisabledError("ai-insights")

        return app

    def test_validation_error_contract(self, app_with_errors):
        """ValidationError returns exact expected format."""
        client = TestClient(app_with_errors)
        response = client.get("/error/validation")

        assert response.status_code == 400

        data = response.json()
        assert data == {
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid input",
                "details": {"field": "email", "reason": "invalid format"}
            }
        }

    def test_authentication_error_contract(self, app_with_errors):
        """AuthenticationError returns exact expected format."""
        client = TestClient(app_with_errors)
        response = client.get("/error/auth")

        assert response.status_code == 401

        data = response.json()
        assert data["error"]["code"] == "AUTHENTICATION_ERROR"
        assert data["error"]["message"] == "Token expired"

    def test_payment_required_error_contract(self, app_with_errors):
        """PaymentRequiredError returns exact expected format."""
        client = TestClient(app_with_errors)
        response = client.get("/error/payment")

        assert response.status_code == 402

        data = response.json()
        assert data["error"]["code"] == "PAYMENT_REQUIRED"

    def test_permission_denied_error_contract(self, app_with_errors):
        """PermissionDeniedError returns exact expected format."""
        client = TestClient(app_with_errors)
        response = client.get("/error/permission")

        assert response.status_code == 403

        data = response.json()
        assert data["error"]["code"] == "PERMISSION_DENIED"

    def test_tenant_isolation_error_hides_sensitive_data(self, app_with_errors):
        """TenantIsolationError must hide all sensitive information."""
        client = TestClient(app_with_errors)
        response = client.get("/error/tenant")

        assert response.status_code == 403

        data = response.json()
        # Must use generic code
        assert data["error"]["code"] == "ACCESS_DENIED"
        # Must use generic message
        assert data["error"]["message"] == "Access denied"
        # Must have empty details
        assert data["error"]["details"] == {}
        # Must NOT contain tenant ID
        assert "tenant-secret-123" not in json.dumps(data)

    def test_not_found_error_contract(self, app_with_errors):
        """NotFoundError returns exact expected format."""
        client = TestClient(app_with_errors)
        response = client.get("/error/notfound")

        assert response.status_code == 404

        data = response.json()
        assert data["error"]["code"] == "NOT_FOUND"
        assert "User" in data["error"]["message"]
        assert "user-123" in data["error"]["message"]

    def test_conflict_error_contract(self, app_with_errors):
        """ConflictError returns exact expected format."""
        client = TestClient(app_with_errors)
        response = client.get("/error/conflict")

        assert response.status_code == 409

        data = response.json()
        assert data["error"]["code"] == "CONFLICT"
        assert data["error"]["details"]["existing_id"] == "abc"

    def test_rate_limit_error_contract(self, app_with_errors):
        """RateLimitError returns exact expected format with retry_after."""
        client = TestClient(app_with_errors)
        response = client.get("/error/ratelimit")

        assert response.status_code == 429

        data = response.json()
        assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert data["error"]["details"]["retry_after_seconds"] == 60

    def test_service_unavailable_error_contract(self, app_with_errors):
        """ServiceUnavailableError returns exact expected format."""
        client = TestClient(app_with_errors)
        response = client.get("/error/unavailable")

        assert response.status_code == 503

        data = response.json()
        assert data["error"]["code"] == "SERVICE_UNAVAILABLE"

    def test_feature_disabled_error_contract(self, app_with_errors):
        """FeatureDisabledError returns exact expected format."""
        client = TestClient(app_with_errors)
        response = client.get("/error/feature")

        assert response.status_code == 503

        data = response.json()
        assert data["error"]["code"] == "FEATURE_DISABLED"
        assert "ai-insights" in data["error"]["message"]

    def test_correlation_id_in_response_headers(self, app_with_errors):
        """All error responses must include X-Correlation-ID header."""
        client = TestClient(app_with_errors)

        endpoints = [
            "/error/validation", "/error/auth", "/error/permission",
            "/error/notfound", "/error/conflict", "/error/ratelimit"
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert "X-Correlation-ID" in response.headers, f"Missing correlation ID for {endpoint}"


# =============================================================================
# RBAC ENDPOINT CONTRACT TESTS
# =============================================================================

class TestRBACEndpointContracts:
    """Verify RBAC-protected endpoints behave correctly."""

    @pytest.fixture
    def rbac_app(self):
        """Create app with RBAC-protected endpoints."""
        from src.platform.rbac import require_permission, require_role
        from src.platform.tenant_context import TenantContextMiddleware
        from src.constants.permissions import Permission, Role

        app = FastAPI()

        # Add tenant context middleware to parse JWT and populate request.state
        # Note: Custom middleware uses app.middleware("http") pattern
        try:
            middleware = TenantContextMiddleware()
            app.middleware("http")(middleware)
        except Exception:
            pass  # Middleware may fail if env vars not set, tests will mock

        @app.get("/api/admin")
        @require_permission(Permission.ADMIN_PLANS_VIEW)
        async def admin_endpoint(request: Request):
            return {"access": "granted"}

        @app.get("/api/analytics")
        @require_permission(Permission.ANALYTICS_VIEW)
        async def analytics_endpoint(request: Request):
            return {"data": "analytics"}

        @app.get("/api/superadmin")
        @require_role(Role.ADMIN)
        async def superadmin_endpoint(request: Request):
            return {"role": "admin"}

        return app

    @pytest.fixture(autouse=True)
    def setup_frontegg(self, monkeypatch):
        """Set up Frontegg mock."""
        monkeypatch.setenv("FRONTEGG_CLIENT_ID", "test-client")

    @patch('src.platform.tenant_context.jwt.decode')
    @patch('src.platform.tenant_context.FronteggJWKSClient.get_signing_key')
    def test_unauthorized_returns_403(
        self, mock_signing_key, mock_jwt_decode, rbac_app
    ):
        """Unauthorized access must return 403 Forbidden."""
        mock_key = MagicMock()
        mock_key.key = "mock-key"
        mock_signing_key.return_value = mock_key

        mock_jwt_decode.return_value = {
            "org_id": "tenant-1",
            "sub": "user-1",
            "roles": ["viewer"],  # Viewer cannot access admin
            "aud": "test-client",
            "iss": "https://api.frontegg.com",
            "exp": 9999999999,
        }

        client = TestClient(rbac_app)
        response = client.get(
            "/api/admin",
            headers={"Authorization": "Bearer test-token"}
        )

        assert response.status_code == 403

    @patch('src.platform.tenant_context.jwt.decode')
    @patch('src.platform.tenant_context.FronteggJWKSClient.get_signing_key')
    def test_authorized_returns_200(
        self, mock_signing_key, mock_jwt_decode, rbac_app
    ):
        """Authorized access must return 200 OK."""
        mock_key = MagicMock()
        mock_key.key = "mock-key"
        mock_signing_key.return_value = mock_key

        mock_jwt_decode.return_value = {
            "org_id": "tenant-1",
            "sub": "user-1",
            "roles": ["admin"],
            "aud": "test-client",
            "iss": "https://api.frontegg.com",
            "exp": 9999999999,
        }

        client = TestClient(rbac_app)
        response = client.get(
            "/api/admin",
            headers={"Authorization": "Bearer test-token"}
        )

        assert response.status_code == 200


# =============================================================================
# AUDIT EVENT CONTRACT TESTS
# =============================================================================

class TestAuditEventContracts:
    """Verify audit event structures unchanged."""

    def test_audit_action_values_unchanged(self):
        """AuditAction enum values must not change."""
        from src.platform.audit import AuditAction

        # These exact values are stored in database
        expected_values = {
            "AUTH_LOGIN": "auth.login",
            "AUTH_LOGOUT": "auth.logout",
            "AUTH_LOGIN_FAILED": "auth.login_failed",
            "BILLING_PLAN_CHANGED": "billing.plan_changed",
            "BILLING_SUBSCRIPTION_CREATED": "billing.subscription_created",
            "STORE_CONNECTED": "store.connected",
            "STORE_DISCONNECTED": "store.disconnected",
            "STORE_SYNC_STARTED": "store.sync_started",
            "STORE_SYNC_COMPLETED": "store.sync_completed",
            "AI_ACTION_EXECUTED": "ai.action_executed",
            "TEAM_MEMBER_INVITED": "team.member_invited",
            "TEAM_ROLE_CHANGED": "team.role_changed",
        }

        for name, expected_value in expected_values.items():
            action = getattr(AuditAction, name)
            assert action.value == expected_value, f"{name} value changed from {expected_value}"

    def test_audit_event_serialization(self):
        """AuditEvent.to_dict() format must not change."""
        from src.platform.audit import AuditEvent, AuditAction
        from datetime import datetime, timezone

        event = AuditEvent(
            tenant_id="t1",
            user_id="u1",
            action=AuditAction.AUTH_LOGIN,
            ip_address="1.2.3.4",
            user_agent="Mozilla/5.0",
            resource_type="session",
            resource_id="s1",
            metadata={"mfa": True},
            correlation_id="corr-123",
        )

        result = event.to_dict()

        # These keys must exist
        required_keys = [
            "tenant_id", "user_id", "action", "timestamp",
            "ip_address", "user_agent", "resource_type",
            "resource_id", "event_metadata", "correlation_id"
        ]

        for key in required_keys:
            assert key in result, f"Missing key: {key}"

        # Action must be string value
        assert result["action"] == "auth.login"

        # Metadata must use 'event_metadata' key (not 'metadata')
        assert result["event_metadata"] == {"mfa": True}


# =============================================================================
# SECRETS REDACTION CONTRACT TESTS
# =============================================================================

class TestSecretsRedactionContracts:
    """Verify secret redaction behavior unchanged."""

    def test_redaction_patterns_catch_all_sensitive_keys(self):
        """All known sensitive key patterns must be redacted."""
        from src.platform.secrets import redact_secrets

        sensitive_data = {
            "api_key": "sk-123",
            "API_KEY": "key-456",
            "apiKey": "key-789",
            "secret_key": "secret1",
            "SECRET_KEY": "secret2",
            "access_token": "token1",
            "refresh_token": "token2",
            "password": "pass123",
            "PASSWORD": "pass456",
            "client_secret": "client1",
            "auth_token": "auth1",
            "private_key": "priv1",
            "webhook_secret": "hook1",
            "database_url": "postgres://user:pass@host/db",
            "credentials": "cred1",
        }

        result = redact_secrets(sensitive_data)

        for key in sensitive_data:
            assert result[key] == "[REDACTED]", f"Key {key} was not redacted"

    def test_non_sensitive_keys_preserved(self):
        """Non-sensitive keys must not be redacted."""
        from src.platform.secrets import redact_secrets

        data = {
            "name": "John Doe",
            "email": "john@example.com",
            "tenant_id": "tenant-123",
            "user_id": "user-456",
            "status": "active",
            "count": 42,
        }

        result = redact_secrets(data)

        for key, value in data.items():
            assert result[key] == value, f"Key {key} was incorrectly modified"

    def test_nested_redaction(self):
        """Nested structures must be recursively redacted."""
        from src.platform.secrets import redact_secrets

        data = {
            "config": {
                "api_key": "secret",
                "settings": {
                    "password": "nested_secret"
                }
            },
            "items": [
                {"name": "item1", "token": "should_stay"}  # 'token' alone isn't matched
            ]
        }

        result = redact_secrets(data)

        assert result["config"]["api_key"] == "[REDACTED]"
        assert result["config"]["settings"]["password"] == "[REDACTED]"


# =============================================================================
# TENANT CONTEXT CONTRACT TESTS
# =============================================================================

class TestTenantContextContracts:
    """Verify TenantContext maintains its contract."""

    def test_tenant_context_required_attributes(self):
        """TenantContext must have all required attributes."""
        from src.platform.tenant_context import TenantContext

        ctx = TenantContext(
            tenant_id="t1",
            user_id="u1",
            roles=["admin"],
            org_id="o1"
        )

        assert ctx.tenant_id == "t1"
        assert ctx.user_id == "u1"
        assert ctx.roles == ["admin"]
        assert ctx.org_id == "o1"

    def test_tenant_context_from_request(self):
        """get_tenant_context must extract from request.state."""
        from src.platform.tenant_context import TenantContext, get_tenant_context

        ctx = TenantContext(
            tenant_id="t1",
            user_id="u1",
            roles=["viewer"],
            org_id="o1"
        )

        request = Mock(spec=Request)
        request.state.tenant_context = ctx

        result = get_tenant_context(request)

        assert result.tenant_id == "t1"
        assert result.user_id == "u1"


# =============================================================================
# GOVERNANCE MODULE CONTRACT TESTS (if module exists)
# =============================================================================

class TestGovernanceContracts:
    """Verify governance module contracts (skip if removed)."""

    @pytest.fixture
    def skip_if_no_governance(self):
        """Skip tests if governance module doesn't exist."""
        try:
            from src.governance import ai_guardrails
            return True
        except ImportError:
            pytest.skip("Governance module not present")

    def test_guardrail_refusal_format(self, skip_if_no_governance):
        """GuardrailRefusal must have expected format."""
        from src.governance.ai_guardrails import GuardrailRefusal, RefusalReason

        refusal = GuardrailRefusal(
            request_id="req-123",
            action_attempted="approve_metric",
            reason="AI cannot approve",
            reason_category=RefusalReason.PROHIBITED_ACTION,
            redirect_to="Product Manager",
        )

        result = refusal.to_dict()

        assert "request_id" in result
        assert "action_attempted" in result
        assert "reason" in result
        assert "redirect_to" in result

    def test_guardrail_check_format(self, skip_if_no_governance):
        """GuardrailCheck must have expected format."""
        from src.governance.ai_guardrails import GuardrailCheck

        check = GuardrailCheck(
            allowed=True,
            action_id="test_action",
        )

        result = check.to_dict()

        assert result["allowed"] == True
        assert result["action_id"] == "test_action"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
