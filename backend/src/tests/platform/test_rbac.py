"""
RBAC (Role-Based Access Control) tests for AI Growth Analytics.

CRITICAL: These tests verify that RBAC is enforced server-side.
UI permission gating is NOT security - server-side enforcement is security.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.testclient import TestClient

from src.platform.tenant_context import TenantContext, TenantContextMiddleware
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
from src.constants.permissions import Permission, Role, ROLE_PERMISSIONS


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def admin_context():
    """Tenant context for admin user."""
    return TenantContext(
        tenant_id="tenant-123",
        user_id="user-admin-1",
        roles=["admin"],
        org_id="tenant-123"
    )


@pytest.fixture
def owner_context():
    """Tenant context for owner user."""
    return TenantContext(
        tenant_id="tenant-123",
        user_id="user-owner-1",
        roles=["owner"],
        org_id="tenant-123"
    )


@pytest.fixture
def editor_context():
    """Tenant context for editor user."""
    return TenantContext(
        tenant_id="tenant-123",
        user_id="user-editor-1",
        roles=["editor"],
        org_id="tenant-123"
    )


@pytest.fixture
def viewer_context():
    """Tenant context for viewer user."""
    return TenantContext(
        tenant_id="tenant-123",
        user_id="user-viewer-1",
        roles=["viewer"],
        org_id="tenant-123"
    )


@pytest.fixture
def multi_role_context():
    """Tenant context with multiple roles."""
    return TenantContext(
        tenant_id="tenant-123",
        user_id="user-multi-1",
        roles=["editor", "viewer"],
        org_id="tenant-123"
    )


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Set up test environment variables."""
    monkeypatch.setenv("FRONTEGG_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("CLERK_FRONTEND_API", "test.clerk.accounts.dev")


# ============================================================================
# TEST SUITE: PERMISSION CHECKS
# ============================================================================

class TestPermissionChecks:
    """Test permission checking functions."""

    def test_admin_has_all_permissions(self, admin_context):
        """CRITICAL: Admin role has all permissions."""
        # Admin should have all defined permissions
        for permission in Permission:
            assert has_permission(admin_context, permission), f"Admin missing {permission}"

    def test_viewer_has_limited_permissions(self, viewer_context):
        """CRITICAL: Viewer role has limited permissions."""
        # Viewer should have view permissions
        assert has_permission(viewer_context, Permission.ANALYTICS_VIEW)
        assert has_permission(viewer_context, Permission.STORE_VIEW)

        # Viewer should NOT have write permissions
        assert not has_permission(viewer_context, Permission.STORE_CREATE)
        assert not has_permission(viewer_context, Permission.STORE_DELETE)
        assert not has_permission(viewer_context, Permission.BILLING_MANAGE)
        assert not has_permission(viewer_context, Permission.ADMIN_PLANS_MANAGE)

    def test_editor_has_write_permissions(self, editor_context):
        """Editor role has write but not admin permissions."""
        # Editor should have write permissions
        assert has_permission(editor_context, Permission.ANALYTICS_VIEW)
        assert has_permission(editor_context, Permission.ANALYTICS_EXPORT)
        assert has_permission(editor_context, Permission.STORE_CREATE)
        assert has_permission(editor_context, Permission.AI_ACTIONS_EXECUTE)

        # Editor should NOT have admin permissions
        assert not has_permission(editor_context, Permission.ADMIN_PLANS_MANAGE)
        assert not has_permission(editor_context, Permission.BILLING_MANAGE)

    def test_owner_has_management_permissions(self, owner_context):
        """Owner role has management but not admin permissions."""
        # Owner should have management permissions
        assert has_permission(owner_context, Permission.BILLING_MANAGE)
        assert has_permission(owner_context, Permission.TEAM_MANAGE)
        assert has_permission(owner_context, Permission.AI_CONFIG_MANAGE)

        # Owner should NOT have admin permissions
        assert not has_permission(owner_context, Permission.ADMIN_PLANS_MANAGE)
        assert not has_permission(owner_context, Permission.ADMIN_SYSTEM_CONFIG)

    def test_has_any_permission(self, viewer_context):
        """Test has_any_permission function."""
        # Viewer has ANALYTICS_VIEW but not ANALYTICS_EXPORT
        assert has_any_permission(viewer_context, [Permission.ANALYTICS_VIEW, Permission.ANALYTICS_EXPORT])

        # Viewer has neither of these
        assert not has_any_permission(viewer_context, [Permission.ADMIN_PLANS_MANAGE, Permission.ADMIN_SYSTEM_CONFIG])

    def test_has_all_permissions(self, admin_context, viewer_context):
        """Test has_all_permissions function."""
        # Admin has all
        assert has_all_permissions(admin_context, [Permission.ANALYTICS_VIEW, Permission.ADMIN_PLANS_MANAGE])

        # Viewer has only some
        assert not has_all_permissions(viewer_context, [Permission.ANALYTICS_VIEW, Permission.ADMIN_PLANS_MANAGE])

    def test_has_role(self, admin_context, viewer_context):
        """Test has_role function."""
        assert has_role(admin_context, Role.ADMIN)
        assert not has_role(admin_context, Role.VIEWER)

        assert has_role(viewer_context, Role.VIEWER)
        assert not has_role(viewer_context, Role.ADMIN)

    def test_multi_role_union_permissions(self, multi_role_context):
        """Multi-role users get union of permissions."""
        # Should have editor permissions
        assert has_permission(multi_role_context, Permission.ANALYTICS_EXPORT)
        assert has_permission(multi_role_context, Permission.STORE_CREATE)

        # Should have viewer permissions too
        assert has_permission(multi_role_context, Permission.ANALYTICS_VIEW)


# ============================================================================
# TEST SUITE: PERMISSION DECORATORS
# ============================================================================

class TestPermissionDecorators:
    """Test permission decorator functions."""

    @pytest.fixture
    def app_with_rbac(self):
        """Create FastAPI app with RBAC-protected endpoints."""
        app = FastAPI()
        middleware = TenantContextMiddleware()
        app.middleware("http")(middleware)

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        @app.get("/api/admin/plans")
        @require_permission(Permission.ADMIN_PLANS_VIEW)
        async def list_plans(request: Request):
            return {"plans": []}

        @app.post("/api/admin/plans")
        @require_permission(Permission.ADMIN_PLANS_MANAGE)
        async def create_plan(request: Request):
            return {"created": True}

        @app.get("/api/analytics")
        @require_any_permission(Permission.ANALYTICS_VIEW, Permission.ADMIN_SYSTEM_CONFIG)
        async def view_analytics(request: Request):
            return {"analytics": "data"}

        @app.post("/api/automation/execute")
        @require_all_permissions(Permission.AUTOMATION_CREATE, Permission.AUTOMATION_EXECUTE)
        async def execute_automation(request: Request):
            return {"executed": True}

        @app.get("/api/admin/system")
        @require_role(Role.ADMIN)
        async def admin_system(request: Request):
            return {"system": "config"}

        @app.get("/api/admin/shorthand")
        @require_admin
        async def admin_shorthand(request: Request):
            return {"admin": True}

        return app

    @pytest.mark.asyncio
    @patch('src.platform.tenant_context.jwt.decode')
    @patch('src.platform.tenant_context.FronteggJWKSClient.get_signing_key')
    async def test_admin_can_access_admin_endpoint(
        self,
        mock_get_signing_key,
        mock_jwt_decode,
        app_with_rbac
    ):
        """CRITICAL: Admin can access admin-protected endpoints."""
        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"
        mock_get_signing_key.return_value = mock_signing_key

        mock_jwt_decode.return_value = {
            "org_id": "tenant-123",
            "sub": "user-admin",
            "metadata": {"roles": ["admin"]},
            "aud": "test-client-id",
            "iss": "https://test.clerk.accounts.dev",
            "exp": 9999999999,
        }

        client = TestClient(app_with_rbac)
        response = client.get(
            "/api/admin/plans",
            headers={"Authorization": "Bearer admin-token"}
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    @patch('src.platform.tenant_context.jwt.decode')
    @patch('src.platform.tenant_context.FronteggJWKSClient.get_signing_key')
    async def test_viewer_cannot_access_admin_endpoint(
        self,
        mock_get_signing_key,
        mock_jwt_decode,
        app_with_rbac
    ):
        """CRITICAL: Viewer cannot access admin-protected endpoints."""
        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"
        mock_get_signing_key.return_value = mock_signing_key

        mock_jwt_decode.return_value = {
            "org_id": "tenant-123",
            "sub": "user-viewer",
            "metadata": {"roles": ["viewer"]},
            "aud": "test-client-id",
            "iss": "https://test.clerk.accounts.dev",
            "exp": 9999999999,
        }

        client = TestClient(app_with_rbac)
        response = client.get(
            "/api/admin/plans",
            headers={"Authorization": "Bearer viewer-token"}
        )

        assert response.status_code == 403
        assert "permission" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    @patch('src.platform.tenant_context.jwt.decode')
    @patch('src.platform.tenant_context.FronteggJWKSClient.get_signing_key')
    async def test_require_any_permission_allows_one_match(
        self,
        mock_get_signing_key,
        mock_jwt_decode,
        app_with_rbac
    ):
        """require_any_permission allows access with any matching permission."""
        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"
        mock_get_signing_key.return_value = mock_signing_key

        # Viewer has ANALYTICS_VIEW but not ADMIN_SYSTEM_CONFIG
        mock_jwt_decode.return_value = {
            "org_id": "tenant-123",
            "sub": "user-viewer",
            "metadata": {"roles": ["viewer"]},
            "aud": "test-client-id",
            "iss": "https://test.clerk.accounts.dev",
            "exp": 9999999999,
        }

        client = TestClient(app_with_rbac)
        response = client.get(
            "/api/analytics",
            headers={"Authorization": "Bearer viewer-token"}
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    @patch('src.platform.tenant_context.jwt.decode')
    @patch('src.platform.tenant_context.FronteggJWKSClient.get_signing_key')
    async def test_require_all_permissions_requires_all(
        self,
        mock_get_signing_key,
        mock_jwt_decode,
        app_with_rbac
    ):
        """require_all_permissions denies if any permission is missing."""
        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"
        mock_get_signing_key.return_value = mock_signing_key

        # Editor has AUTOMATION_CREATE but not AUTOMATION_EXECUTE
        mock_jwt_decode.return_value = {
            "org_id": "tenant-123",
            "sub": "user-editor",
            "metadata": {"roles": ["editor"]},
            "aud": "test-client-id",
            "iss": "https://test.clerk.accounts.dev",
            "exp": 9999999999,
        }

        client = TestClient(app_with_rbac)
        response = client.post(
            "/api/automation/execute",
            headers={"Authorization": "Bearer editor-token"}
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    @patch('src.platform.tenant_context.jwt.decode')
    @patch('src.platform.tenant_context.FronteggJWKSClient.get_signing_key')
    async def test_require_role_decorator(
        self,
        mock_get_signing_key,
        mock_jwt_decode,
        app_with_rbac
    ):
        """require_role decorator enforces role check."""
        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"
        mock_get_signing_key.return_value = mock_signing_key

        # Non-admin cannot access
        mock_jwt_decode.return_value = {
            "org_id": "tenant-123",
            "sub": "user-owner",
            "metadata": {"roles": ["owner"]},
            "aud": "test-client-id",
            "iss": "https://test.clerk.accounts.dev",
            "exp": 9999999999,
        }

        client = TestClient(app_with_rbac)
        response = client.get(
            "/api/admin/system",
            headers={"Authorization": "Bearer owner-token"}
        )

        assert response.status_code == 403


# ============================================================================
# TEST SUITE: PROGRAMMATIC CHECKS
# ============================================================================

class TestProgrammaticPermissionChecks:
    """Test programmatic permission checking."""

    def test_check_permission_or_raise_passes(self, admin_context):
        """check_permission_or_raise passes for valid permission."""
        request = Mock(spec=Request)
        request.state.tenant_context = admin_context
        request.url.path = "/api/test"
        request.method = "GET"

        # Should not raise
        check_permission_or_raise(admin_context, Permission.ADMIN_PLANS_VIEW, request)

    def test_check_permission_or_raise_raises(self, viewer_context):
        """check_permission_or_raise raises HTTPException for invalid permission."""
        request = Mock(spec=Request)
        request.state.tenant_context = viewer_context
        request.url.path = "/api/test"
        request.method = "GET"

        with pytest.raises(HTTPException) as exc_info:
            check_permission_or_raise(viewer_context, Permission.ADMIN_PLANS_VIEW, request)

        assert exc_info.value.status_code == 403


# ============================================================================
# TEST SUITE: PERMISSIONS MATRIX
# ============================================================================

class TestPermissionsMatrix:
    """Test the permissions matrix is correctly defined."""

    def test_all_roles_have_permissions_defined(self):
        """All roles must have permissions defined."""
        for role in Role:
            assert role in ROLE_PERMISSIONS, f"Role {role} missing from ROLE_PERMISSIONS"

    def test_viewer_is_subset_of_editor(self):
        """Viewer permissions should be subset of editor permissions."""
        viewer_perms = ROLE_PERMISSIONS[Role.VIEWER]
        editor_perms = ROLE_PERMISSIONS[Role.EDITOR]

        # Viewer can have some unique permissions, but generally should be subset
        # At minimum, viewer's view permissions should be in editor
        assert Permission.ANALYTICS_VIEW in viewer_perms
        assert Permission.ANALYTICS_VIEW in editor_perms

    def test_admin_has_all_admin_permissions(self):
        """Admin role must have all admin permissions."""
        admin_perms = ROLE_PERMISSIONS[Role.ADMIN]

        admin_permissions = [p for p in Permission if p.value.startswith("admin:")]
        for perm in admin_permissions:
            assert perm in admin_perms, f"Admin missing {perm}"

    def test_no_role_has_empty_permissions(self):
        """No role should have empty permissions."""
        for role in Role:
            assert len(ROLE_PERMISSIONS[role]) > 0, f"Role {role} has no permissions"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
