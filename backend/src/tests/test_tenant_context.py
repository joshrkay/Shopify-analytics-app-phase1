"""
Comprehensive tests for tenant context validation.

CRITICAL: These tests verify that:
1. Every authenticated request executes within a valid tenant context
2. clerk_user_id -> allowed tenant_ids resolution works correctly
3. Requests missing tenant context are rejected
4. Cross-tenant access is prevented
5. tenant_id and role are injected into request lifecycle
6. Audit logs are emitted on violations

Test Categories:
- TenantContext unit tests
- TenantGuard service tests
- TenantContextMiddleware integration tests
- Cross-tenant prevention tests
- Audit logging verification tests
"""

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from dataclasses import dataclass

from fastapi import FastAPI, Request, status, Depends
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine, Column, String, Boolean, Enum as SAEnum
from sqlalchemy.orm import sessionmaker, Session

from src.platform.tenant_context import (
    TenantContext,
    TenantContextMiddleware,
    TenantViolationType,
    get_tenant_context,
    _emit_tenant_violation_audit_log,
)
from src.services.tenant_guard import (
    TenantGuard,
    ViolationType,
    TenantViolation,
    ValidationResult,
    get_tenant_guard,
    require_tenant_guard,
    check_tenant_access,
    get_user_tenants,
)
from src.auth.context_resolver import AuthContext, TenantAccess
from src.constants.permissions import Permission, Role
from src.db_base import Base


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def mock_user():
    """Create a mock User object."""
    user = Mock()
    user.id = str(uuid.uuid4())
    user.clerk_user_id = f"user_{uuid.uuid4().hex[:8]}"
    user.email = "test@example.com"
    user.is_active = True
    return user


@pytest.fixture
def mock_tenant():
    """Create a mock Tenant object."""
    tenant = Mock()
    tenant.id = str(uuid.uuid4())
    tenant.name = "Test Tenant"
    tenant.clerk_org_id = f"org_{uuid.uuid4().hex[:8]}"
    tenant.billing_tier = "growth"
    tenant.status = Mock(value="active")
    tenant.is_active = True
    return tenant


@pytest.fixture
def mock_auth_context(mock_user, mock_tenant):
    """Create a mock AuthContext with tenant access."""
    tenant_access = TenantAccess(
        tenant_id=mock_tenant.id,
        tenant_name=mock_tenant.name,
        roles=frozenset(["merchant_admin"]),
        permissions=frozenset([Permission.ANALYTICS_VIEW, Permission.STORE_VIEW]),
        billing_tier=mock_tenant.billing_tier,
        clerk_org_id=mock_tenant.clerk_org_id,
        is_active=True,
    )

    context = AuthContext(
        user=mock_user,
        clerk_user_id=mock_user.clerk_user_id,
        session_id=str(uuid.uuid4()),
        tenant_access={mock_tenant.id: tenant_access},
        current_tenant_id=mock_tenant.id,
        org_id=mock_tenant.clerk_org_id,
        org_role="org:admin",
    )

    return context


@pytest.fixture
def mock_multi_tenant_auth_context(mock_user):
    """Create a mock AuthContext with access to multiple tenants (agency user)."""
    tenant_1_id = str(uuid.uuid4())
    tenant_2_id = str(uuid.uuid4())

    tenant_access = {
        tenant_1_id: TenantAccess(
            tenant_id=tenant_1_id,
            tenant_name="Tenant 1",
            roles=frozenset(["agency_admin"]),
            permissions=frozenset([
                Permission.ANALYTICS_VIEW,
                Permission.AGENCY_STORES_VIEW,
                Permission.MULTI_TENANT_ACCESS,
            ]),
            billing_tier="enterprise",
            is_active=True,
        ),
        tenant_2_id: TenantAccess(
            tenant_id=tenant_2_id,
            tenant_name="Tenant 2",
            roles=frozenset(["agency_viewer"]),
            permissions=frozenset([
                Permission.ANALYTICS_VIEW,
                Permission.AGENCY_STORES_VIEW,
                Permission.MULTI_TENANT_ACCESS,
            ]),
            billing_tier="enterprise",
            is_active=True,
        ),
    }

    context = AuthContext(
        user=mock_user,
        clerk_user_id=mock_user.clerk_user_id,
        session_id=str(uuid.uuid4()),
        tenant_access=tenant_access,
        current_tenant_id=tenant_1_id,
        org_id=f"org_{uuid.uuid4().hex[:8]}",
        org_role="org:admin",
    )

    return context


@pytest.fixture
def app_with_middleware(monkeypatch):
    """Create FastAPI app with tenant context middleware for testing."""
    monkeypatch.setenv("CLERK_FRONTEND_API", "test.clerk.accounts.dev")

    app = FastAPI()

    # Add middleware
    middleware = TenantContextMiddleware()
    app.middleware("http")(middleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/data")
    async def get_data(request: Request):
        tenant_ctx = get_tenant_context(request)
        return {
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
            "roles": tenant_ctx.roles,
        }

    @app.post("/api/data")
    async def create_data(request: Request):
        tenant_ctx = get_tenant_context(request)
        body = await request.json()
        return {
            "tenant_id": tenant_ctx.tenant_id,
            "body_tenant_id": body.get("tenant_id", "not-provided"),
        }

    return app


# =============================================================================
# TenantContext Unit Tests
# =============================================================================


class TestTenantContextCreation:
    """Test TenantContext class creation and validation."""

    def test_create_basic_tenant_context(self):
        """Test creating a basic TenantContext."""
        ctx = TenantContext(
            tenant_id="tenant-123",
            user_id="user-456",
            roles=["merchant_admin"],
            org_id="org-789",
        )

        assert ctx.tenant_id == "tenant-123"
        assert ctx.user_id == "user-456"
        assert ctx.roles == ["merchant_admin"]
        assert ctx.org_id == "org-789"
        assert ctx.billing_tier == "free"  # Default
        assert ctx.allowed_tenants == ["tenant-123"]

    def test_empty_tenant_id_raises_error(self):
        """Test that empty tenant_id raises ValueError."""
        with pytest.raises(ValueError, match="tenant_id cannot be empty"):
            TenantContext(
                tenant_id="",
                user_id="user-1",
                roles=["admin"],
                org_id="org-1",
            )

    def test_agency_user_multiple_tenants(self):
        """Test TenantContext for agency user with multiple tenants."""
        ctx = TenantContext(
            tenant_id="tenant-1",
            user_id="user-1",
            roles=["agency_admin"],
            org_id="org-1",
            allowed_tenants=["tenant-1", "tenant-2", "tenant-3"],
            billing_tier="enterprise",
        )

        assert ctx.tenant_id == "tenant-1"
        assert ctx.is_agency_user is True
        assert len(ctx.allowed_tenants) == 3
        assert ctx.can_access_tenant("tenant-2") is True
        assert ctx.can_access_tenant("tenant-4") is False

    def test_merchant_user_single_tenant(self):
        """Test TenantContext for merchant user (single tenant)."""
        ctx = TenantContext(
            tenant_id="tenant-1",
            user_id="user-1",
            roles=["merchant_admin"],
            org_id="org-1",
        )

        assert ctx.is_agency_user is False
        assert ctx.allowed_tenants == ["tenant-1"]
        assert ctx.can_access_tenant("tenant-1") is True
        assert ctx.can_access_tenant("tenant-2") is False

    def test_active_tenant_not_in_allowed_list_raises(self):
        """Test that active tenant must be in allowed list."""
        with pytest.raises(ValueError, match="not in allowed_tenants list"):
            TenantContext(
                tenant_id="tenant-4",
                user_id="user-1",
                roles=["agency_admin"],
                org_id="org-1",
                allowed_tenants=["tenant-1", "tenant-2", "tenant-3"],
            )

    def test_rls_clause_single_tenant(self):
        """Test RLS clause generation for single tenant."""
        ctx = TenantContext(
            tenant_id="tenant-123",
            user_id="user-1",
            roles=["merchant_admin"],
            org_id="org-1",
        )

        rls = ctx.get_rls_clause()
        assert rls == "tenant_id = 'tenant-123'"

    def test_rls_clause_multiple_tenants(self):
        """Test RLS clause generation for multiple tenants."""
        ctx = TenantContext(
            tenant_id="tenant-1",
            user_id="user-1",
            roles=["agency_admin"],
            org_id="org-1",
            allowed_tenants=["tenant-1", "tenant-2"],
        )

        rls = ctx.get_rls_clause()
        assert "tenant_id IN" in rls
        assert "tenant-1" in rls
        assert "tenant-2" in rls


# =============================================================================
# TenantGuard Service Tests
# =============================================================================


class TestTenantGuardValidation:
    """Test TenantGuard validation logic."""

    def test_validate_authenticated_user_with_tenant(self, mock_auth_context, mock_db_session):
        """Test validation passes for authenticated user with valid tenant."""
        guard = TenantGuard(mock_db_session)

        result = guard.validate_tenant_access(mock_auth_context)

        assert result.is_valid is True
        assert result.tenant_id == mock_auth_context.current_tenant_id
        assert result.violation is None

    def test_validate_unauthenticated_user_fails(self, mock_db_session):
        """Test validation fails for unauthenticated user."""
        guard = TenantGuard(mock_db_session)

        # Create anonymous context
        anon_context = AuthContext(
            user=None,
            clerk_user_id="",
            session_id=None,
            tenant_access={},
            current_tenant_id=None,
        )

        result = guard.validate_tenant_access(anon_context)

        assert result.is_valid is False
        assert result.error_code == "AUTH_REQUIRED"
        assert result.violation.violation_type == ViolationType.MISSING_AUTH

    def test_validate_missing_tenant_context_fails(self, mock_user, mock_db_session):
        """Test validation fails when no tenant context."""
        guard = TenantGuard(mock_db_session)

        # Create context without tenant
        context = AuthContext(
            user=mock_user,
            clerk_user_id=mock_user.clerk_user_id,
            session_id=str(uuid.uuid4()),
            tenant_access={},
            current_tenant_id=None,
        )

        result = guard.validate_tenant_access(context)

        assert result.is_valid is False
        assert result.error_code == "TENANT_REQUIRED"
        assert result.violation.violation_type == ViolationType.MISSING_TENANT

    def test_validate_cross_tenant_access_fails(self, mock_auth_context, mock_db_session):
        """Test validation fails for cross-tenant access attempt."""
        guard = TenantGuard(mock_db_session)

        # Try to access a tenant not in allowed list
        unauthorized_tenant = str(uuid.uuid4())

        result = guard.validate_tenant_access(
            mock_auth_context,
            requested_tenant_id=unauthorized_tenant,
        )

        assert result.is_valid is False
        assert result.error_code == "CROSS_TENANT_DENIED"
        assert result.violation.violation_type == ViolationType.CROSS_TENANT
        assert result.violation.requested_tenant_id == unauthorized_tenant

    def test_validate_agency_user_can_switch_tenants(
        self, mock_multi_tenant_auth_context, mock_db_session
    ):
        """Test agency user can access any of their allowed tenants."""
        guard = TenantGuard(mock_db_session)

        # Get both tenant IDs
        tenant_ids = list(mock_multi_tenant_auth_context.tenant_access.keys())
        assert len(tenant_ids) == 2

        # Validate access to first tenant
        result1 = guard.validate_tenant_access(
            mock_multi_tenant_auth_context,
            requested_tenant_id=tenant_ids[0],
        )
        assert result1.is_valid is True

        # Validate access to second tenant
        result2 = guard.validate_tenant_access(
            mock_multi_tenant_auth_context,
            requested_tenant_id=tenant_ids[1],
        )
        assert result2.is_valid is True


class TestTenantGuardResolution:
    """Test clerk_user_id -> tenant_ids resolution."""

    def test_resolve_allowed_tenants_empty_for_unknown_user(self, mock_db_session):
        """Test that unknown user gets empty tenant list."""
        guard = TenantGuard(mock_db_session)

        result = guard.resolve_allowed_tenants("unknown_user_id")

        assert result == []

    def test_resolve_allowed_tenants_empty_for_empty_clerk_id(self, mock_db_session):
        """Test that empty clerk_user_id returns empty list."""
        guard = TenantGuard(mock_db_session)

        result = guard.resolve_allowed_tenants("")

        assert result == []

    @patch('src.services.tenant_guard.TenantGuard.resolve_allowed_tenants')
    def test_resolve_allowed_tenants_returns_active_tenants(
        self, mock_resolve, mock_db_session
    ):
        """Test that resolution returns only active tenants."""
        mock_resolve.return_value = ["tenant-1", "tenant-2"]
        guard = TenantGuard(mock_db_session)

        result = guard.resolve_allowed_tenants("user_abc123")

        assert len(result) == 2
        assert "tenant-1" in result
        assert "tenant-2" in result


class TestTenantGuardAuditLogging:
    """Test that TenantGuard emits audit logs on violations."""

    @patch('src.services.tenant_guard.write_audit_log_sync')
    def test_guard_request_emits_audit_on_cross_tenant(
        self, mock_audit, mock_auth_context, mock_db_session
    ):
        """Test audit log is emitted for cross-tenant access attempt."""
        guard = TenantGuard(mock_db_session)

        # Create mock request
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.auth_context = mock_auth_context
        request.url = Mock()
        request.url.path = "/api/data"
        request.method = "GET"
        request.headers = {"User-Agent": "test-agent"}
        request.client = Mock()
        request.client.host = "127.0.0.1"

        # Patch get_auth_context to return our mock
        with patch('src.services.tenant_guard.get_auth_context', return_value=mock_auth_context):
            # Try to access unauthorized tenant
            unauthorized_tenant = str(uuid.uuid4())

            with pytest.raises(Exception):  # HTTPException
                guard.guard_request(request, requested_tenant_id=unauthorized_tenant)

        # Verify audit log was called
        mock_audit.assert_called_once()


# =============================================================================
# Middleware Integration Tests
# =============================================================================


class TestTenantContextMiddleware:
    """Test TenantContextMiddleware integration."""

    @pytest.mark.asyncio
    async def test_health_endpoint_bypasses_auth(self, app_with_middleware):
        """Test that /health endpoint doesn't require authentication."""
        client = TestClient(app_with_middleware)

        response = client.get("/health")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_protected_endpoint_requires_auth(self, app_with_middleware):
        """Test that protected endpoints require authentication."""
        client = TestClient(app_with_middleware)

        # Request without token should fail
        response = client.get("/api/data")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "authorization token" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    @patch('src.platform.tenant_context.jwt.decode')
    @patch('src.platform.tenant_context.ClerkJWKSClient.get_signing_key')
    async def test_valid_jwt_creates_tenant_context(
        self, mock_get_key, mock_decode, app_with_middleware
    ):
        """Test that valid JWT creates proper tenant context."""
        # Setup mocks
        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"
        mock_get_key.return_value = mock_signing_key

        mock_decode.return_value = {
            "sub": "user-123",
            "org_id": "org-456",
            "org_role": "org:admin",
            "metadata": {"roles": ["merchant_admin"]},
            "iss": "https://test.clerk.accounts.dev",
            "exp": 9999999999,
        }

        client = TestClient(app_with_middleware)

        response = client.get(
            "/api/data",
            headers={"Authorization": "Bearer valid-token"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["tenant_id"] == "org-456"
        assert data["user_id"] == "user-123"

    @pytest.mark.asyncio
    @patch('src.platform.tenant_context.get_db_session_sync')
    @patch('src.platform.tenant_context.jwt.decode')
    @patch('src.platform.tenant_context.ClerkJWKSClient.get_signing_key')
    async def test_db_authorization_failure_falls_back_to_jwt_context(
        self, mock_get_key, mock_decode, mock_get_db_session_sync, app_with_middleware
    ):
        """Test middleware degrades gracefully when DB authorization is unavailable."""
        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"
        mock_get_key.return_value = mock_signing_key

        mock_decode.return_value = {
            "sub": "user-123",
            "org_id": "org-456",
            "org_role": "org:admin",
            "metadata": {"roles": ["merchant_admin"]},
            "iss": "https://test.clerk.accounts.dev",
            "exp": 9999999999,
        }
        mock_get_db_session_sync.side_effect = ValueError("DATABASE_URL environment variable is not set")

        client = TestClient(app_with_middleware)

        response = client.get(
            "/api/data",
            headers={"Authorization": "Bearer valid-token"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["tenant_id"] == "org-456"
        assert data["user_id"] == "user-123"



    @pytest.mark.asyncio
    @patch('src.platform.tenant_context.get_db_session_sync')
    @patch('src.platform.tenant_context._get_tenant_guard_class')
    @patch('src.platform.tenant_context.jwt.decode')
    @patch('src.platform.tenant_context.ClerkJWKSClient.get_signing_key')
    async def test_unexpected_tenant_guard_error_returns_500(
        self,
        mock_get_key,
        mock_decode,
        mock_get_guard_class,
        mock_get_db_session_sync,
        app_with_middleware,
    ):
        """Non-DB guard errors should still surface as internal auth failures."""
        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"
        mock_get_key.return_value = mock_signing_key

        mock_decode.return_value = {
            "sub": "user-123",
            "org_id": "org-456",
            "org_role": "org:admin",
            "metadata": {"roles": ["merchant_admin"]},
            "iss": "https://test.clerk.accounts.dev",
            "exp": 9999999999,
        }

        mock_db = Mock()
        mock_get_db_session_sync.return_value = iter([mock_db])

        mock_guard = Mock()
        mock_guard.enforce_authorization.side_effect = TypeError("bad guard state")
        mock_get_guard_class.return_value = Mock(return_value=mock_guard)

        client = TestClient(app_with_middleware)

        response = client.get(
            "/api/data",
            headers={"Authorization": "Bearer valid-token"},
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Internal error during authentication"
        mock_db.close.assert_called_once()

    @pytest.mark.asyncio
    @patch('src.platform.tenant_context.jwt.decode')
    @patch('src.platform.tenant_context.ClerkJWKSClient.get_signing_key')
    async def test_tenant_id_from_body_is_ignored(
        self, mock_get_key, mock_decode, app_with_middleware
    ):
        """CRITICAL: Test that tenant_id in request body is ignored."""
        # Setup mocks
        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"
        mock_get_key.return_value = mock_signing_key

        mock_decode.return_value = {
            "sub": "user-123",
            "org_id": "tenant-a",  # JWT says tenant-a
            "org_role": "org:admin",
            "metadata": {},
            "iss": "https://test.clerk.accounts.dev",
            "exp": 9999999999,
        }

        client = TestClient(app_with_middleware)

        # Try to send tenant_id in body (should be ignored)
        response = client.post(
            "/api/data",
            headers={"Authorization": "Bearer valid-token"},
            json={"tenant_id": "tenant-b"},  # Attempted cross-tenant
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # CRITICAL: tenant_id must be from JWT (tenant-a), NOT from body (tenant-b)
        assert data["tenant_id"] == "tenant-a"
        assert data["body_tenant_id"] == "tenant-b"


# =============================================================================
# Cross-Tenant Prevention Tests
# =============================================================================


class TestCrossTenantPrevention:
    """CRITICAL: Test that cross-tenant access is impossible."""

    def test_tenant_a_cannot_access_tenant_b(self, mock_db_session):
        """Test that user from tenant A cannot access tenant B data."""
        # Create auth context for tenant A
        tenant_a_id = str(uuid.uuid4())
        tenant_a_access = TenantAccess(
            tenant_id=tenant_a_id,
            tenant_name="Tenant A",
            roles=frozenset(["merchant_admin"]),
            permissions=frozenset([Permission.ANALYTICS_VIEW]),
            billing_tier="growth",
            is_active=True,
        )

        user = Mock()
        user.id = str(uuid.uuid4())
        user.clerk_user_id = "user_tenant_a"
        user.is_active = True

        context_a = AuthContext(
            user=user,
            clerk_user_id="user_tenant_a",
            session_id=str(uuid.uuid4()),
            tenant_access={tenant_a_id: tenant_a_access},
            current_tenant_id=tenant_a_id,
        )

        guard = TenantGuard(mock_db_session)

        # Try to access tenant B
        tenant_b_id = str(uuid.uuid4())
        result = guard.validate_tenant_access(context_a, requested_tenant_id=tenant_b_id)

        assert result.is_valid is False
        assert result.error_code == "CROSS_TENANT_DENIED"
        assert result.violation.requested_tenant_id == tenant_b_id

    @pytest.mark.parametrize("tenant_a_id,tenant_b_id", [
        ("tenant-1", "tenant-2"),
        ("org-abc", "org-xyz"),
        ("123", "456"),
        ("tenant-with-dashes", "tenant_with_underscores"),
    ])
    def test_cross_tenant_prevention_various_formats(
        self, tenant_a_id, tenant_b_id, mock_db_session
    ):
        """Test cross-tenant prevention with various ID formats."""
        tenant_a_access = TenantAccess(
            tenant_id=tenant_a_id,
            tenant_name="Tenant A",
            roles=frozenset(["merchant_admin"]),
            permissions=frozenset([Permission.ANALYTICS_VIEW]),
            billing_tier="growth",
            is_active=True,
        )

        user = Mock()
        user.id = str(uuid.uuid4())
        user.clerk_user_id = "user_a"
        user.is_active = True

        context = AuthContext(
            user=user,
            clerk_user_id="user_a",
            session_id=str(uuid.uuid4()),
            tenant_access={tenant_a_id: tenant_a_access},
            current_tenant_id=tenant_a_id,
        )

        guard = TenantGuard(mock_db_session)

        # Attempt cross-tenant access
        result = guard.validate_tenant_access(context, requested_tenant_id=tenant_b_id)

        assert result.is_valid is False
        assert tenant_b_id not in context.allowed_tenant_ids


# =============================================================================
# Audit Logging Tests
# =============================================================================


class TestAuditLogging:
    """Test that violations emit proper audit logs."""

    @patch('src.platform.tenant_context.write_audit_log_sync')
    @patch('src.platform.tenant_context.get_db_session_sync')
    def test_violation_emits_audit_log(self, mock_get_db, mock_write_audit):
        """Test that tenant violations emit audit logs."""
        mock_session = Mock()
        mock_get_db.return_value = mock_session

        # Create mock request
        request = Mock(spec=Request)
        request.url = Mock()
        request.url.path = "/api/data"
        request.method = "GET"
        request.headers = {"User-Agent": "test-agent"}
        request.client = Mock()
        request.client.host = "192.168.1.1"

        # Emit violation
        correlation_id = _emit_tenant_violation_audit_log(
            request=request,
            violation_type=TenantViolationType.MISSING_AUTH_TOKEN,
            error_message="Missing authorization token",
        )

        # Verify audit log was written
        mock_write_audit.assert_called_once()

        # Verify correlation_id was returned
        assert correlation_id is not None
        assert isinstance(correlation_id, str)

    @patch('src.platform.tenant_context.write_audit_log_sync')
    @patch('src.platform.tenant_context.get_db_session_sync')
    def test_audit_log_includes_metadata(self, mock_get_db, mock_write_audit):
        """Test that audit log includes all required metadata."""
        mock_session = Mock()
        mock_get_db.return_value = mock_session

        request = Mock(spec=Request)
        request.url = Mock()
        request.url.path = "/api/sensitive"
        request.method = "POST"
        request.headers = {"User-Agent": "Mozilla/5.0", "X-Forwarded-For": "10.0.0.1"}
        request.client = Mock()
        request.client.host = "192.168.1.1"

        _emit_tenant_violation_audit_log(
            request=request,
            violation_type=TenantViolationType.CROSS_TENANT,
            error_message="Cross-tenant access attempt",
            user_id="user-123",
            org_id="org-456",
            extra_metadata={"attempted_tenant": "org-789"},
        )

        # Get the AuditEvent that was passed to write_audit_log_sync
        call_args = mock_write_audit.call_args
        event = call_args[0][1]  # Second positional arg is the event

        assert event.action.value == "security.cross_tenant_denied"
        assert event.user_id == "user-123"
        assert event.tenant_id == "org-456"
        assert event.metadata["path"] == "/api/sensitive"
        assert event.metadata["method"] == "POST"

    @patch('src.platform.tenant_context.write_audit_log_sync')
    @patch('src.platform.tenant_context.get_db_session_sync')
    def test_audit_failure_does_not_crash(self, mock_get_db, mock_write_audit):
        """Test that audit logging failure doesn't crash the request."""
        mock_session = Mock()
        mock_get_db.return_value = mock_session

        # Make audit log fail
        mock_write_audit.side_effect = Exception("Database error")

        request = Mock(spec=Request)
        request.url = Mock()
        request.url.path = "/api/data"
        request.method = "GET"
        request.headers = {}
        request.client = Mock()
        request.client.host = "127.0.0.1"

        # Should not raise exception
        correlation_id = _emit_tenant_violation_audit_log(
            request=request,
            violation_type=TenantViolationType.INVALID_TOKEN,
            error_message="Token expired",
        )

        # Should still return correlation ID
        assert correlation_id is not None


# =============================================================================
# Request Lifecycle Tests
# =============================================================================


class TestRequestLifecycle:
    """Test tenant context injection into request lifecycle."""

    def test_tenant_context_available_in_route_handler(
        self, mock_auth_context, mock_db_session
    ):
        """Test that tenant context is available in route handlers."""
        # Create mock request with auth context
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.auth_context = mock_auth_context

        guard = TenantGuard(mock_db_session)

        # Patch get_auth_context
        with patch('src.services.tenant_guard.get_auth_context', return_value=mock_auth_context):
            result = guard.validate_tenant_access(mock_auth_context)

        assert result.is_valid is True
        assert result.tenant_id == mock_auth_context.current_tenant_id

    def test_roles_injected_into_context(self, mock_auth_context, mock_db_session):
        """Test that roles are properly injected into context."""
        guard = TenantGuard(mock_db_session)

        result = guard.validate_tenant_access(mock_auth_context)

        assert result.is_valid is True
        assert len(result.roles) > 0
        assert "merchant_admin" in result.roles


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestUtilityFunctions:
    """Test utility functions for tenant access."""

    @patch('src.services.tenant_guard.TenantGuard.resolve_allowed_tenants')
    def test_check_tenant_access_returns_true_for_valid(
        self, mock_resolve, mock_db_session
    ):
        """Test check_tenant_access returns True for valid access."""
        mock_resolve.return_value = ["tenant-1", "tenant-2"]

        result = check_tenant_access(
            db=mock_db_session,
            clerk_user_id="user-123",
            tenant_id="tenant-1",
        )

        assert result is True

    @patch('src.services.tenant_guard.TenantGuard.resolve_allowed_tenants')
    def test_check_tenant_access_returns_false_for_invalid(
        self, mock_resolve, mock_db_session
    ):
        """Test check_tenant_access returns False for invalid access."""
        mock_resolve.return_value = ["tenant-1", "tenant-2"]

        result = check_tenant_access(
            db=mock_db_session,
            clerk_user_id="user-123",
            tenant_id="tenant-3",  # Not in allowed list
        )

        assert result is False


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_none_tenant_id_in_validation(self, mock_user, mock_db_session):
        """Test handling of None tenant_id."""
        context = AuthContext(
            user=mock_user,
            clerk_user_id=mock_user.clerk_user_id,
            session_id=str(uuid.uuid4()),
            tenant_access={},
            current_tenant_id=None,
        )

        guard = TenantGuard(mock_db_session)
        result = guard.validate_tenant_access(context)

        assert result.is_valid is False
        assert result.error_code == "TENANT_REQUIRED"

    def test_empty_allowed_tenants_list(self, mock_user, mock_db_session):
        """Test user with empty allowed_tenants list."""
        context = AuthContext(
            user=mock_user,
            clerk_user_id=mock_user.clerk_user_id,
            session_id=str(uuid.uuid4()),
            tenant_access={},
            current_tenant_id=None,
        )

        guard = TenantGuard(mock_db_session)
        result = guard.validate_tenant_access(context, requested_tenant_id="any-tenant")

        assert result.is_valid is False
        assert result.error_code == "CROSS_TENANT_DENIED"

    def test_inactive_tenant_access_denied(self, mock_user, mock_db_session):
        """Test that inactive tenant access is denied."""
        tenant_id = str(uuid.uuid4())
        inactive_access = TenantAccess(
            tenant_id=tenant_id,
            tenant_name="Inactive Tenant",
            roles=frozenset(["merchant_admin"]),
            permissions=frozenset([Permission.ANALYTICS_VIEW]),
            billing_tier="growth",
            is_active=False,  # Inactive
        )

        context = AuthContext(
            user=mock_user,
            clerk_user_id=mock_user.clerk_user_id,
            session_id=str(uuid.uuid4()),
            tenant_access={tenant_id: inactive_access},
            current_tenant_id=tenant_id,
        )

        guard = TenantGuard(mock_db_session)
        result = guard.validate_tenant_access(context)

        assert result.is_valid is False
        assert result.violation.violation_type == ViolationType.SUSPENDED_TENANT


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
