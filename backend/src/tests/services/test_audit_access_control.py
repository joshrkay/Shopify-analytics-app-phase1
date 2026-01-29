"""
Unit tests for audit access control service.

Story 10.6 - Audit Log Access Controls
"""

import pytest
from unittest.mock import MagicMock, patch

from src.services.audit_access_control import (
    AuditAccessContext,
    AuditAccessControl,
    get_audit_access_context,
    get_audit_access_control,
)


class TestAuditAccessContext:
    """Test suite for AuditAccessContext dataclass."""

    def test_from_tenant_context_merchant(self):
        """Should create context for merchant user."""
        mock_tenant_ctx = MagicMock()
        mock_tenant_ctx.user_id = "user-123"
        mock_tenant_ctx.tenant_id = "tenant-abc"
        mock_tenant_ctx.roles = ["merchant_admin"]
        mock_tenant_ctx.allowed_tenants = ["tenant-abc"]

        ctx = AuditAccessContext.from_tenant_context(mock_tenant_ctx)

        assert ctx.user_id == "user-123"
        assert ctx.tenant_id == "tenant-abc"
        assert ctx.role == "merchant_admin"
        assert ctx.allowed_tenants == {"tenant-abc"}
        assert ctx.is_super_admin is False

    def test_from_tenant_context_agency(self):
        """Should create context for agency user with multiple tenants."""
        mock_tenant_ctx = MagicMock()
        mock_tenant_ctx.user_id = "user-456"
        mock_tenant_ctx.tenant_id = "tenant-abc"
        mock_tenant_ctx.roles = ["agency_admin"]
        mock_tenant_ctx.allowed_tenants = ["tenant-abc", "tenant-def", "tenant-ghi"]

        ctx = AuditAccessContext.from_tenant_context(mock_tenant_ctx)

        assert ctx.user_id == "user-456"
        assert ctx.tenant_id == "tenant-abc"
        assert ctx.role == "agency_admin"
        assert ctx.allowed_tenants == {"tenant-abc", "tenant-def", "tenant-ghi"}
        assert ctx.is_super_admin is False

    def test_from_tenant_context_super_admin(self):
        """Should detect super admin role."""
        mock_tenant_ctx = MagicMock()
        mock_tenant_ctx.user_id = "admin-999"
        mock_tenant_ctx.tenant_id = "platform"
        mock_tenant_ctx.roles = ["super_admin"]
        mock_tenant_ctx.allowed_tenants = []

        ctx = AuditAccessContext.from_tenant_context(mock_tenant_ctx)

        assert ctx.user_id == "admin-999"
        assert ctx.is_super_admin is True

    def test_from_tenant_context_super_admin_case_insensitive(self):
        """Should detect super admin role regardless of case."""
        mock_tenant_ctx = MagicMock()
        mock_tenant_ctx.user_id = "admin-999"
        mock_tenant_ctx.tenant_id = "platform"
        mock_tenant_ctx.roles = ["SUPER_ADMIN"]
        mock_tenant_ctx.allowed_tenants = []

        ctx = AuditAccessContext.from_tenant_context(mock_tenant_ctx)

        assert ctx.is_super_admin is True


class TestAuditAccessControl:
    """Test suite for AuditAccessControl class."""

    # =========================================================================
    # Super Admin Tests
    # =========================================================================

    def test_super_admin_can_access_any_tenant(self):
        """Super admin should access all tenants."""
        ctx = AuditAccessContext(
            user_id="admin-1",
            role="super_admin",
            tenant_id="platform",
            allowed_tenants=set(),
            is_super_admin=True,
        )
        ac = AuditAccessControl(ctx)

        assert ac.can_access_tenant("tenant-1") is True
        assert ac.can_access_tenant("tenant-999") is True
        assert ac.can_access_tenant("any-random-tenant") is True

    def test_super_admin_get_accessible_tenants_returns_none(self):
        """Super admin should have unrestricted access (None)."""
        ctx = AuditAccessContext(
            user_id="admin-1",
            role="super_admin",
            tenant_id="platform",
            allowed_tenants=set(),
            is_super_admin=True,
        )
        ac = AuditAccessControl(ctx)

        assert ac.get_accessible_tenants() is None

    # =========================================================================
    # Merchant Tests
    # =========================================================================

    def test_merchant_can_access_own_tenant(self):
        """Merchant should access their own tenant."""
        ctx = AuditAccessContext(
            user_id="user-1",
            role="merchant_admin",
            tenant_id="tenant-1",
            allowed_tenants=set(),
            is_super_admin=False,
        )
        ac = AuditAccessControl(ctx)

        assert ac.can_access_tenant("tenant-1") is True

    def test_merchant_cannot_access_other_tenant(self):
        """Merchant should not access other tenants."""
        ctx = AuditAccessContext(
            user_id="user-1",
            role="merchant_admin",
            tenant_id="tenant-1",
            allowed_tenants=set(),
            is_super_admin=False,
        )
        ac = AuditAccessControl(ctx)

        assert ac.can_access_tenant("tenant-2") is False
        assert ac.can_access_tenant("tenant-other") is False

    def test_merchant_get_accessible_tenants(self):
        """Merchant should only have their tenant in accessible set."""
        ctx = AuditAccessContext(
            user_id="user-1",
            role="merchant_viewer",
            tenant_id="tenant-1",
            allowed_tenants=set(),
            is_super_admin=False,
        )
        ac = AuditAccessControl(ctx)

        accessible = ac.get_accessible_tenants()
        assert accessible == {"tenant-1"}

    # =========================================================================
    # Agency Tests
    # =========================================================================

    def test_agency_can_access_allowed_tenants(self):
        """Agency should access all allowed_tenants."""
        ctx = AuditAccessContext(
            user_id="user-1",
            role="agency_admin",
            tenant_id="agency-1",
            allowed_tenants={"tenant-1", "tenant-2", "tenant-3"},
            is_super_admin=False,
        )
        ac = AuditAccessControl(ctx)

        # Can access own tenant
        assert ac.can_access_tenant("agency-1") is True

        # Can access allowed tenants
        assert ac.can_access_tenant("tenant-1") is True
        assert ac.can_access_tenant("tenant-2") is True
        assert ac.can_access_tenant("tenant-3") is True

        # Cannot access non-allowed tenants
        assert ac.can_access_tenant("tenant-4") is False
        assert ac.can_access_tenant("other-tenant") is False

    def test_agency_get_accessible_tenants(self):
        """Agency should have all allowed tenants plus own tenant."""
        ctx = AuditAccessContext(
            user_id="user-1",
            role="agency_viewer",
            tenant_id="agency-1",
            allowed_tenants={"tenant-1", "tenant-2"},
            is_super_admin=False,
        )
        ac = AuditAccessControl(ctx)

        accessible = ac.get_accessible_tenants()
        assert accessible == {"agency-1", "tenant-1", "tenant-2"}

    # =========================================================================
    # validate_access Tests
    # =========================================================================

    def test_validate_access_passes_for_allowed_tenant(self):
        """validate_access should not raise for allowed tenant."""
        ctx = AuditAccessContext(
            user_id="user-1",
            role="merchant_admin",
            tenant_id="tenant-1",
            allowed_tenants=set(),
            is_super_admin=False,
        )
        ac = AuditAccessControl(ctx)

        # Should not raise
        ac.validate_access("tenant-1")

    def test_validate_access_raises_for_denied_tenant(self):
        """validate_access should raise HTTPException for denied tenant."""
        ctx = AuditAccessContext(
            user_id="user-1",
            role="merchant_admin",
            tenant_id="tenant-1",
            allowed_tenants=set(),
            is_super_admin=False,
        )
        ac = AuditAccessControl(ctx)

        with pytest.raises(Exception) as exc_info:
            ac.validate_access("tenant-2")

        assert exc_info.value.status_code == 403
        assert "Access denied" in str(exc_info.value.detail)

    def test_validate_access_super_admin_never_raises(self):
        """Super admin validate_access should never raise."""
        ctx = AuditAccessContext(
            user_id="admin-1",
            role="super_admin",
            tenant_id="platform",
            allowed_tenants=set(),
            is_super_admin=True,
        )
        ac = AuditAccessControl(ctx)

        # Should not raise for any tenant
        ac.validate_access("tenant-1")
        ac.validate_access("tenant-999")
        ac.validate_access("any-random-id")

    # =========================================================================
    # filter_query Tests
    # =========================================================================

    def test_filter_query_super_admin_no_filter(self):
        """Super admin query should not be filtered."""
        ctx = AuditAccessContext(
            user_id="admin-1",
            role="super_admin",
            tenant_id="platform",
            allowed_tenants=set(),
            is_super_admin=True,
        )
        ac = AuditAccessControl(ctx)

        mock_query = MagicMock()
        mock_column = MagicMock()

        result = ac.filter_query(mock_query, mock_column)

        # Query should be returned unchanged
        assert result == mock_query
        mock_query.filter.assert_not_called()

    def test_filter_query_single_tenant_uses_equality(self):
        """Single tenant should use equality filter."""
        ctx = AuditAccessContext(
            user_id="user-1",
            role="merchant_admin",
            tenant_id="tenant-1",
            allowed_tenants=set(),
            is_super_admin=False,
        )
        ac = AuditAccessControl(ctx)

        mock_query = MagicMock()
        mock_column = MagicMock()

        ac.filter_query(mock_query, mock_column)

        # Should use equality (==) not IN
        mock_query.filter.assert_called_once()
        # The filter was called with column == value
        mock_column.__eq__.assert_called_once_with("tenant-1")

    def test_filter_query_multiple_tenants_uses_in(self):
        """Multiple tenants should use IN filter."""
        ctx = AuditAccessContext(
            user_id="user-1",
            role="agency_admin",
            tenant_id="agency-1",
            allowed_tenants={"tenant-1", "tenant-2"},
            is_super_admin=False,
        )
        ac = AuditAccessControl(ctx)

        mock_query = MagicMock()
        mock_column = MagicMock()

        ac.filter_query(mock_query, mock_column)

        # Should use IN clause
        mock_query.filter.assert_called_once()
        mock_column.in_.assert_called_once()


class TestGetAuditAccessContext:
    """Test suite for get_audit_access_context helper."""

    def test_extracts_context_from_request(self):
        """Should extract context from request's tenant context."""
        mock_request = MagicMock()
        mock_tenant_ctx = MagicMock()
        mock_tenant_ctx.user_id = "user-123"
        mock_tenant_ctx.tenant_id = "tenant-abc"
        mock_tenant_ctx.roles = ["merchant_admin"]
        mock_tenant_ctx.allowed_tenants = ["tenant-abc"]

        with patch(
            "src.services.audit_access_control.get_tenant_context",
            return_value=mock_tenant_ctx
        ):
            ctx = get_audit_access_context(mock_request)

        assert ctx.user_id == "user-123"
        assert ctx.tenant_id == "tenant-abc"


class TestGetAuditAccessControl:
    """Test suite for get_audit_access_control helper."""

    def test_returns_access_control_instance(self):
        """Should return AuditAccessControl with context from request."""
        mock_request = MagicMock()
        mock_tenant_ctx = MagicMock()
        mock_tenant_ctx.user_id = "user-123"
        mock_tenant_ctx.tenant_id = "tenant-abc"
        mock_tenant_ctx.roles = ["agency_admin"]
        mock_tenant_ctx.allowed_tenants = ["tenant-abc", "tenant-def"]

        with patch(
            "src.services.audit_access_control.get_tenant_context",
            return_value=mock_tenant_ctx
        ):
            ac = get_audit_access_control(mock_request)

        assert isinstance(ac, AuditAccessControl)
        assert ac.context.user_id == "user-123"
        assert ac.can_access_tenant("tenant-abc") is True
        assert ac.can_access_tenant("tenant-def") is True
        assert ac.can_access_tenant("other") is False
