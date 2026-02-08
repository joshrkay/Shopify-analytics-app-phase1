"""
Tests for RBAC enforcement middleware and audit integration.

Story 5.5.5 — RBAC Enforcement Middleware

Test classes:
- TestRBACMiddlewareDefaultDeny: Unregistered endpoints blocked
- TestRBACMiddlewarePermissions: Registered endpoints check permissions
- TestRBACMiddlewarePublicEndpoints: Public endpoints allowed with auth
- TestSuperAdminTenantContext: Super admin must select active tenant
- TestRBACDeniedAuditEvent: rbac.denied audit events emitted
- TestDecoratorAuditIntegration: Decorators emit rbac.denied on denial
- TestPathMatching: Path pattern matching logic
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from src.platform.tenant_context import TenantContext
from src.constants.permissions import Permission, Role
from src.auth.rbac_middleware import (
    RBACMiddleware,
    register_endpoint_permissions,
    register_public_endpoint,
    clear_endpoint_registry,
    validate_super_admin_context,
    _match_path,
    _find_endpoint_permissions,
    _is_rbac_exempt,
)


# =============================================================================
# Fixtures
# =============================================================================


def _make_tenant_context(
    roles=None,
    tenant_id="tenant-123",
    user_id="user-1",
    resolved_permissions=None,
):
    """Create a TenantContext for testing."""
    return TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        roles=roles or ["viewer"],
        org_id=tenant_id,
        resolved_permissions=resolved_permissions,
    )


def _create_test_app(register_endpoints=True):
    """Create a FastAPI app with RBAC middleware for testing."""
    app = FastAPI()

    # Add RBAC middleware
    app.add_middleware(RBACMiddleware)

    # Define test routes
    @app.get("/api/analytics")
    async def get_analytics(request: Request):
        return JSONResponse({"data": "analytics"})

    @app.get("/api/stores/{store_id}")
    async def get_store(request: Request, store_id: str):
        return JSONResponse({"store": store_id})

    @app.post("/api/billing/plan")
    async def change_plan(request: Request):
        return JSONResponse({"plan": "pro"})

    @app.get("/api/public/status")
    async def public_status(request: Request):
        return JSONResponse({"status": "ok"})

    @app.get("/api/unregistered")
    async def unregistered(request: Request):
        return JSONResponse({"error": "should not reach"})

    @app.get("/health")
    async def health(request: Request):
        return JSONResponse({"health": "ok"})

    @app.get("/api/admin/config")
    async def admin_config(request: Request):
        return JSONResponse({"config": "value"})

    if register_endpoints:
        # Register permissions for test endpoints
        register_endpoint_permissions(
            "GET", "/api/analytics",
            [Permission.ANALYTICS_VIEW],
        )
        register_endpoint_permissions(
            "GET", "/api/stores/{store_id}",
            [Permission.STORE_VIEW],
        )
        register_endpoint_permissions(
            "POST", "/api/billing/plan",
            [Permission.BILLING_MANAGE],
        )
        register_endpoint_permissions(
            "GET", "/api/admin/config",
            [Permission.ADMIN_SYSTEM_CONFIG],
        )
        register_public_endpoint("GET", "/api/public/status")

    return app


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear the endpoint registry before and after each test."""
    clear_endpoint_registry()
    yield
    clear_endpoint_registry()


@pytest.fixture
def _mock_audit():
    """Mock audit emitter to prevent DB access in tests."""
    with patch(
        "src.auth.rbac_middleware._emit_rbac_denied_audit"
    ) as mock:
        yield mock


# =============================================================================
# TestRBACMiddlewareDefaultDeny
# =============================================================================


class TestRBACMiddlewareDefaultDeny:
    """Unregistered endpoints are denied by default."""

    def test_unregistered_endpoint_denied(self, _mock_audit):
        """Request to unregistered endpoint returns 403."""
        app = _create_test_app(register_endpoints=False)

        # Register only some endpoints, leave /api/unregistered out
        register_endpoint_permissions(
            "GET", "/api/analytics",
            [Permission.ANALYTICS_VIEW],
        )

        # Inject tenant context via middleware mock
        @app.middleware("http")
        async def inject_context(request: Request, call_next):
            request.state.tenant_context = _make_tenant_context(roles=["admin"])
            return await call_next(request)

        client = TestClient(app)
        response = client.get("/api/unregistered")
        assert response.status_code == 403
        body = response.json()
        assert body["error_code"] == "RBAC_DENIED"

    def test_exempt_paths_bypass_rbac(self, _mock_audit):
        """Health/webhook endpoints bypass RBAC entirely."""
        app = _create_test_app(register_endpoints=False)
        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code == 200

    def test_options_requests_bypass_rbac(self, _mock_audit):
        """OPTIONS requests bypass RBAC (CORS preflight)."""
        app = _create_test_app(register_endpoints=False)

        @app.middleware("http")
        async def inject_context(request: Request, call_next):
            request.state.tenant_context = _make_tenant_context()
            return await call_next(request)

        client = TestClient(app)
        response = client.options("/api/unregistered")
        # OPTIONS should pass through, not blocked by RBAC
        assert response.status_code != 403


# =============================================================================
# TestRBACMiddlewarePermissions
# =============================================================================


class TestRBACMiddlewarePermissions:
    """Registered endpoints check user permissions."""

    def test_user_with_permission_allowed(self, _mock_audit):
        """User with required permission can access endpoint."""
        app = _create_test_app()

        @app.middleware("http")
        async def inject_context(request: Request, call_next):
            ctx = _make_tenant_context(
                roles=["admin"],
                resolved_permissions={"analytics:view", "store:view"},
            )
            request.state.tenant_context = ctx
            return await call_next(request)

        client = TestClient(app)
        response = client.get("/api/analytics")
        assert response.status_code == 200
        assert response.json()["data"] == "analytics"

    def test_user_without_permission_denied(self, _mock_audit):
        """User without required permission gets 403."""
        app = _create_test_app()

        @app.middleware("http")
        async def inject_context(request: Request, call_next):
            ctx = _make_tenant_context(
                roles=["viewer"],
                resolved_permissions={"analytics:view"},
            )
            request.state.tenant_context = ctx
            return await call_next(request)

        client = TestClient(app)
        response = client.post("/api/billing/plan")
        assert response.status_code == 403

    def test_path_parameter_matching(self, _mock_audit):
        """Endpoint with path parameters correctly matched."""
        app = _create_test_app()

        @app.middleware("http")
        async def inject_context(request: Request, call_next):
            ctx = _make_tenant_context(
                roles=["admin"],
                resolved_permissions={"store:view"},
            )
            request.state.tenant_context = ctx
            return await call_next(request)

        client = TestClient(app)
        response = client.get("/api/stores/store-abc-123")
        assert response.status_code == 200
        assert response.json()["store"] == "store-abc-123"


# =============================================================================
# TestRBACMiddlewarePublicEndpoints
# =============================================================================


class TestRBACMiddlewarePublicEndpoints:
    """Public endpoints require auth but no specific permissions."""

    def test_public_endpoint_allowed_with_auth(self, _mock_audit):
        """Authenticated user can access public endpoint regardless of permissions."""
        app = _create_test_app()

        @app.middleware("http")
        async def inject_context(request: Request, call_next):
            ctx = _make_tenant_context(
                roles=["viewer"],
                resolved_permissions=set(),
            )
            request.state.tenant_context = ctx
            return await call_next(request)

        client = TestClient(app)
        response = client.get("/api/public/status")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


# =============================================================================
# TestSuperAdminTenantContext
# =============================================================================


class TestSuperAdminTenantContext:
    """Super admin must select an active tenant context."""

    def test_super_admin_with_tenant_context_allowed(self, _mock_audit):
        """Super admin with active tenant context can proceed."""
        ctx = _make_tenant_context(
            roles=["super_admin"],
            tenant_id="tenant-123",
        )
        error = validate_super_admin_context(ctx)
        assert error is None

    def test_non_super_admin_skips_validation(self, _mock_audit):
        """Non-super-admin users skip super admin validation."""
        ctx = _make_tenant_context(roles=["admin"])
        error = validate_super_admin_context(ctx)
        assert error is None

    def test_super_admin_without_tenant_context_denied(self, _mock_audit):
        """Super admin without tenant context gets error."""
        # TenantContext requires non-empty tenant_id in __init__,
        # so we test with validate function using a mock
        mock_ctx = MagicMock()
        mock_ctx.roles = ["super_admin"]
        mock_ctx.tenant_id = ""  # Empty tenant

        error = validate_super_admin_context(mock_ctx)
        assert error is not None
        assert "active tenant context" in error

    def test_super_admin_none_tenant_denied(self, _mock_audit):
        """Super admin with None tenant_id gets error."""
        mock_ctx = MagicMock()
        mock_ctx.roles = ["super_admin"]
        mock_ctx.tenant_id = None

        error = validate_super_admin_context(mock_ctx)
        assert error is not None


# =============================================================================
# TestRBACDeniedAuditEvent
# =============================================================================


class TestRBACDeniedAuditEvent:
    """rbac.denied audit events are emitted on denials."""

    def test_audit_event_on_unregistered_endpoint(self):
        """Audit event emitted when unregistered endpoint is accessed."""
        with patch(
            "src.auth.rbac_middleware._emit_rbac_denied_audit"
        ) as mock_audit:
            app = _create_test_app(register_endpoints=False)

            @app.middleware("http")
            async def inject_context(request: Request, call_next):
                request.state.tenant_context = _make_tenant_context(
                    roles=["viewer"],
                    user_id="user-audit-1",
                    tenant_id="tenant-audit",
                )
                return await call_next(request)

            client = TestClient(app)
            response = client.get("/api/unregistered")
            assert response.status_code == 403

            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args
            assert call_kwargs[1]["user_id"] == "user-audit-1" or call_kwargs[0][1] == "user-audit-1"

    def test_audit_event_on_permission_denied(self):
        """Audit event emitted when user lacks required permission."""
        with patch(
            "src.auth.rbac_middleware._emit_rbac_denied_audit"
        ) as mock_audit:
            app = _create_test_app()

            @app.middleware("http")
            async def inject_context(request: Request, call_next):
                request.state.tenant_context = _make_tenant_context(
                    roles=["viewer"],
                    resolved_permissions=set(),
                )
                return await call_next(request)

            client = TestClient(app)
            response = client.get("/api/analytics")
            assert response.status_code == 403

            mock_audit.assert_called_once()

    def test_no_audit_event_on_allowed_request(self):
        """No audit event when request is allowed."""
        with patch(
            "src.auth.rbac_middleware._emit_rbac_denied_audit"
        ) as mock_audit:
            app = _create_test_app()

            @app.middleware("http")
            async def inject_context(request: Request, call_next):
                request.state.tenant_context = _make_tenant_context(
                    roles=["admin"],
                    resolved_permissions={"analytics:view"},
                )
                return await call_next(request)

            client = TestClient(app)
            response = client.get("/api/analytics")
            assert response.status_code == 200

            mock_audit.assert_not_called()

    def test_audit_action_enum_value(self):
        """Verify RBAC_DENIED audit action enum value is correct."""
        from src.platform.audit import AuditAction

        assert hasattr(AuditAction, "RBAC_DENIED")
        assert AuditAction.RBAC_DENIED.value == "rbac.denied"


# =============================================================================
# TestDecoratorAuditIntegration
# =============================================================================


class TestDecoratorAuditIntegration:
    """Existing RBAC decorators emit rbac.denied audit events."""

    def test_require_permission_emits_audit(self):
        """require_permission decorator emits audit on denial."""
        from src.platform.rbac import require_permission

        app = FastAPI()

        @app.get("/test-perm")
        @require_permission(Permission.BILLING_MANAGE)
        async def test_endpoint(request: Request):
            return JSONResponse({"ok": True})

        with patch(
            "src.platform.rbac._try_emit_rbac_denied"
        ) as mock_audit:
            # Set up tenant context as viewer (no billing perms)
            @app.middleware("http")
            async def inject_context(request: Request, call_next):
                request.state.tenant_context = _make_tenant_context(
                    roles=["viewer"],
                )
                return await call_next(request)

            client = TestClient(app)
            response = client.get("/test-perm")
            assert response.status_code == 403
            mock_audit.assert_called_once()

    def test_require_role_emits_audit(self):
        """require_role decorator emits audit on denial."""
        from src.platform.rbac import require_role
        from src.constants.permissions import Role

        app = FastAPI()

        @app.get("/test-role")
        @require_role(Role.ADMIN)
        async def test_endpoint(request: Request):
            return JSONResponse({"ok": True})

        with patch(
            "src.platform.rbac._try_emit_rbac_denied"
        ) as mock_audit:
            @app.middleware("http")
            async def inject_context(request: Request, call_next):
                request.state.tenant_context = _make_tenant_context(
                    roles=["viewer"],
                )
                return await call_next(request)

            client = TestClient(app)
            response = client.get("/test-role")
            assert response.status_code == 403
            mock_audit.assert_called_once()
            # Check that the permission string contains role info
            args = mock_audit.call_args
            assert "role:admin" in args[1].get("permission_str", "") or "role:admin" in str(args)


# =============================================================================
# TestPathMatching
# =============================================================================


class TestPathMatching:
    """Test path pattern matching logic."""

    def test_exact_match(self):
        """Exact path matches."""
        assert _match_path("/api/analytics", "/api/analytics") is True

    def test_no_match_different_path(self):
        """Different paths don't match."""
        assert _match_path("/api/billing", "/api/analytics") is False

    def test_path_parameter_match(self):
        """Path with parameters matches."""
        assert _match_path(
            "/api/stores/abc-123", "/api/stores/{store_id}"
        ) is True

    def test_multiple_path_parameters(self):
        """Multiple path parameters match."""
        assert _match_path(
            "/api/tenants/t-1/users/u-2",
            "/api/tenants/{tenant_id}/users/{user_id}",
        ) is True

    def test_different_segment_count(self):
        """Paths with different segment counts don't match."""
        assert _match_path("/api/stores", "/api/stores/{store_id}") is False

    def test_trailing_slash_normalized(self):
        """Trailing slashes are stripped for matching."""
        assert _match_path("/api/analytics/", "/api/analytics") is True

    def test_is_rbac_exempt_health(self):
        """Health endpoint is exempt."""
        assert _is_rbac_exempt("/health") is True

    def test_is_rbac_exempt_webhook_prefix(self):
        """Webhook endpoints are exempt."""
        assert _is_rbac_exempt("/api/webhooks/clerk") is True
        assert _is_rbac_exempt("/api/webhooks/shopify/orders") is True

    def test_non_exempt_path(self):
        """Regular API paths are not exempt."""
        assert _is_rbac_exempt("/api/analytics") is False


# =============================================================================
# TestEndpointRegistry
# =============================================================================


class TestEndpointRegistry:
    """Test endpoint permission registry."""

    def test_register_and_find_endpoint(self):
        """Registered endpoint is found with correct permissions."""
        register_endpoint_permissions(
            "GET", "/api/test", [Permission.ANALYTICS_VIEW]
        )
        found, perms = _find_endpoint_permissions("GET", "/api/test")
        assert found is True
        assert perms == [Permission.ANALYTICS_VIEW]

    def test_unregistered_endpoint_not_found(self):
        """Unregistered endpoint returns not found."""
        found, perms = _find_endpoint_permissions("GET", "/api/missing")
        assert found is False
        assert perms is None

    def test_public_endpoint_found_no_perms(self):
        """Public endpoint returns found with empty permissions."""
        register_public_endpoint("GET", "/api/public")
        found, perms = _find_endpoint_permissions("GET", "/api/public")
        assert found is True
        assert perms == []

    def test_method_mismatch(self):
        """Different HTTP method doesn't match."""
        register_endpoint_permissions(
            "POST", "/api/test", [Permission.ANALYTICS_VIEW]
        )
        found, perms = _find_endpoint_permissions("GET", "/api/test")
        assert found is False

    def test_clear_registry(self):
        """clear_endpoint_registry removes all registrations."""
        register_endpoint_permissions(
            "GET", "/api/test", [Permission.ANALYTICS_VIEW]
        )
        register_public_endpoint("GET", "/api/public")

        clear_endpoint_registry()

        found1, _ = _find_endpoint_permissions("GET", "/api/test")
        found2, _ = _find_endpoint_permissions("GET", "/api/public")
        assert found1 is False
        assert found2 is False

    def test_path_parameter_in_registry(self):
        """Endpoint with path parameter matches actual paths."""
        register_endpoint_permissions(
            "GET", "/api/items/{item_id}",
            [Permission.STORE_VIEW],
        )
        found, perms = _find_endpoint_permissions("GET", "/api/items/abc-123")
        assert found is True
        assert perms == [Permission.STORE_VIEW]


# =============================================================================
# TestEmitRBACDeniedFunction
# =============================================================================


class TestEmitRBACDeniedFunction:
    """Test the emit_rbac_denied audit emitter function."""

    def test_emit_rbac_denied_creates_event(self, db_session):
        """emit_rbac_denied creates an audit log entry."""
        from src.services.audit_logger import emit_rbac_denied

        # Should not raise
        emit_rbac_denied(
            db=db_session,
            tenant_id="tenant-1",
            user_id="user-1",
            permission="analytics:view",
            endpoint="/api/analytics",
            method="GET",
            roles=["viewer"],
        )

    def test_emit_rbac_denied_with_missing_fields(self, db_session):
        """emit_rbac_denied handles missing optional fields."""
        from src.services.audit_logger import emit_rbac_denied

        # Should not raise with minimal args
        emit_rbac_denied(
            db=db_session,
            tenant_id="tenant-1",
            user_id="user-1",
            permission="billing:manage",
            endpoint="/api/billing",
        )


# =============================================================================
# TestAuditableEventsRegistry
# =============================================================================


class TestAuditableEventsRegistry:
    """Test that RBAC_DENIED is properly registered in AUDITABLE_EVENTS."""

    def test_rbac_denied_in_registry(self):
        """RBAC_DENIED action is in the AUDITABLE_EVENTS registry."""
        from src.platform.audit import AuditAction, AUDITABLE_EVENTS

        assert AuditAction.RBAC_DENIED in AUDITABLE_EVENTS

    def test_rbac_denied_required_fields(self):
        """RBAC_DENIED has the correct required fields."""
        from src.platform.audit import AuditAction, AUDITABLE_EVENTS

        meta = AUDITABLE_EVENTS[AuditAction.RBAC_DENIED]
        assert "user_id" in meta.required_fields
        assert "tenant_id" in meta.required_fields
        assert "permission" in meta.required_fields
        assert "endpoint" in meta.required_fields

    def test_rbac_denied_is_high_risk(self):
        """RBAC_DENIED is classified as high risk."""
        from src.platform.audit import AuditAction, AUDITABLE_EVENTS

        meta = AUDITABLE_EVENTS[AuditAction.RBAC_DENIED]
        assert meta.risk_level == "high"
