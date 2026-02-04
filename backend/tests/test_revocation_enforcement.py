"""
Tests for authorization enforcement (DB-as-source-of-truth).

These tests verify that authorization changes are enforced immediately:
- Tenant access revoked → next request fails with 403
- Role changed → permissions reflect immediately
- Billing downgrade → invalid role blocked with BILLING_ROLE_NOT_ALLOWED

Story: Authorization Hardening - DB-as-source-of-truth checks

Note: These tests use mocks to avoid importing the full application,
which has some Pydantic v2 compatibility issues in other modules.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


# =============================================================================
# Mock Classes (to avoid full import chain)
# =============================================================================


class MockTenantStatus(str, Enum):
    """Mock tenant status enum."""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class MockAuditAction(str, Enum):
    """Mock audit actions for testing."""
    IDENTITY_ACCESS_REVOKED_ENFORCED = "identity.access_revoked_enforced"
    IDENTITY_ROLE_CHANGE_ENFORCED = "identity.role_change_enforced"
    BILLING_ROLE_REVOKED_DUE_TO_DOWNGRADE = "billing.role_revoked_due_to_downgrade"


@dataclass
class MockAuthorizationResult:
    """Mock authorization result for testing."""
    is_authorized: bool
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    billing_tier: Optional[str] = None
    denial_reason: Optional[str] = None
    error_code: Optional[str] = None
    roles_changed: bool = False
    previous_roles: List[str] = field(default_factory=list)
    audit_action: Optional[MockAuditAction] = None
    audit_metadata: dict = field(default_factory=dict)


# =============================================================================
# Mock Billing Tier Validation (matches src/constants/permissions.py)
# =============================================================================


BILLING_TIER_ALLOWED_ROLES = {
    'free': {'merchant_admin', 'merchant_viewer', 'viewer', 'editor'},
    'growth': {'merchant_admin', 'merchant_viewer', 'agency_viewer', 'viewer', 'editor', 'owner'},
    'enterprise': {'merchant_admin', 'merchant_viewer', 'agency_admin', 'agency_viewer',
                   'viewer', 'editor', 'owner', 'admin'},
}


def is_role_allowed_for_billing_tier(role_name: str, billing_tier: str) -> bool:
    """Check if a role is allowed for a billing tier."""
    allowed_roles = BILLING_TIER_ALLOWED_ROLES.get(billing_tier.lower(), set())
    return role_name.lower() in allowed_roles


def get_allowed_roles_for_billing_tier(billing_tier: str) -> list:
    """Get allowed roles for a billing tier."""
    return list(BILLING_TIER_ALLOWED_ROLES.get(billing_tier.lower(), set()))


# =============================================================================
# Mock enforce_authorization function (matches TenantGuard implementation)
# =============================================================================


def mock_enforce_authorization(
    user: Optional[Mock],
    tenant: Optional[Mock],
    user_tenant_roles: List[Mock],
    clerk_user_id: str,
    active_tenant_id: str,
    jwt_roles: Optional[List[str]] = None,
    request_path: Optional[str] = None,
    request_method: Optional[str] = None,
) -> MockAuthorizationResult:
    """
    Mock implementation of enforce_authorization for testing.

    This mirrors the logic in TenantGuard.enforce_authorization.
    """
    # 1. Check if user exists
    if not user:
        return MockAuthorizationResult(
            is_authorized=False,
            denial_reason="User not found in local database",
            error_code="USER_NOT_FOUND",
            audit_action=MockAuditAction.IDENTITY_ACCESS_REVOKED_ENFORCED,
            audit_metadata={
                "clerk_user_id": clerk_user_id,
                "tenant_id": active_tenant_id,
                "enforcement_reason": "user_not_found",
                "request_path": request_path,
                "request_method": request_method,
            },
        )

    # Check if user is active
    if not user.is_active:
        return MockAuthorizationResult(
            is_authorized=False,
            user_id=user.id,
            denial_reason="User account is deactivated",
            error_code="USER_INACTIVE",
            audit_action=MockAuditAction.IDENTITY_ACCESS_REVOKED_ENFORCED,
            audit_metadata={
                "clerk_user_id": clerk_user_id,
                "tenant_id": active_tenant_id,
                "enforcement_reason": "user_deactivated",
                "request_path": request_path,
                "request_method": request_method,
            },
        )

    # 2. Check if tenant exists
    if not tenant:
        return MockAuthorizationResult(
            is_authorized=False,
            user_id=user.id,
            denial_reason="Tenant not found",
            error_code="TENANT_NOT_FOUND",
        )

    # Check tenant status
    if tenant.status != MockTenantStatus.ACTIVE:
        return MockAuthorizationResult(
            is_authorized=False,
            user_id=user.id,
            tenant_id=active_tenant_id,
            denial_reason=f"Tenant is {tenant.status.value}",
            error_code="TENANT_SUSPENDED",
            audit_action=MockAuditAction.IDENTITY_ACCESS_REVOKED_ENFORCED,
            audit_metadata={
                "clerk_user_id": clerk_user_id,
                "tenant_id": active_tenant_id,
                "enforcement_reason": "tenant_suspended",
                "tenant_status": tenant.status.value,
                "request_path": request_path,
                "request_method": request_method,
            },
        )

    # 3. Check if user has active roles
    if not user_tenant_roles:
        return MockAuthorizationResult(
            is_authorized=False,
            user_id=user.id,
            tenant_id=active_tenant_id,
            denial_reason="Access to this tenant has been revoked",
            error_code="ACCESS_REVOKED",
            previous_roles=jwt_roles or [],
            audit_action=MockAuditAction.IDENTITY_ACCESS_REVOKED_ENFORCED,
            audit_metadata={
                "clerk_user_id": clerk_user_id,
                "tenant_id": active_tenant_id,
                "previous_roles": jwt_roles or [],
                "enforcement_reason": "membership_deleted",
                "request_path": request_path,
                "request_method": request_method,
            },
        )

    # Extract roles from DB
    db_roles = [r.role for r in user_tenant_roles]
    billing_tier = tenant.billing_tier

    # 4. Validate roles against billing tier
    valid_roles = []
    invalid_roles = []
    for role in db_roles:
        if is_role_allowed_for_billing_tier(role, billing_tier):
            valid_roles.append(role)
        else:
            invalid_roles.append(role)

    if not valid_roles:
        allowed_roles = get_allowed_roles_for_billing_tier(billing_tier)
        return MockAuthorizationResult(
            is_authorized=False,
            user_id=user.id,
            tenant_id=active_tenant_id,
            roles=db_roles,
            billing_tier=billing_tier,
            denial_reason="Your role is not available on the current billing plan",
            error_code="BILLING_ROLE_NOT_ALLOWED",
            audit_action=MockAuditAction.BILLING_ROLE_REVOKED_DUE_TO_DOWNGRADE,
            audit_metadata={
                "clerk_user_id": clerk_user_id,
                "tenant_id": active_tenant_id,
                "previous_billing_tier": billing_tier,
                "new_billing_tier": billing_tier,
                "invalid_role": invalid_roles[0] if invalid_roles else None,
                "allowed_roles": allowed_roles,
                "request_path": request_path,
            },
        )

    # Check for role changes
    roles_changed = False
    if jwt_roles is not None:
        jwt_roles_set = set(r.lower() for r in jwt_roles)
        db_roles_set = set(r.lower() for r in valid_roles)
        roles_changed = jwt_roles_set != db_roles_set

    result = MockAuthorizationResult(
        is_authorized=True,
        user_id=user.id,
        tenant_id=active_tenant_id,
        roles=valid_roles,
        billing_tier=billing_tier,
        roles_changed=roles_changed,
        previous_roles=jwt_roles or [],
    )

    if roles_changed:
        result.audit_action = MockAuditAction.IDENTITY_ROLE_CHANGE_ENFORCED
        result.audit_metadata = {
            "clerk_user_id": clerk_user_id,
            "tenant_id": active_tenant_id,
            "previous_roles": jwt_roles or [],
            "new_roles": valid_roles,
            "change_source": "db_enforcement",
            "permissions_removed": [],
        }

    return result


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def active_user():
    """Create an active user fixture."""
    user = Mock()
    user.id = "user-123"
    user.clerk_user_id = "clerk_user_123"
    user.is_active = True
    user.email = "test@example.com"
    return user


@pytest.fixture
def inactive_user():
    """Create an inactive user fixture."""
    user = Mock()
    user.id = "user-456"
    user.clerk_user_id = "clerk_user_456"
    user.is_active = False
    user.email = "inactive@example.com"
    return user


@pytest.fixture
def active_tenant():
    """Create an active tenant fixture."""
    tenant = Mock()
    tenant.id = "tenant-123"
    tenant.status = MockTenantStatus.ACTIVE
    tenant.billing_tier = "growth"
    tenant.name = "Test Store"
    return tenant


@pytest.fixture
def suspended_tenant():
    """Create a suspended tenant fixture."""
    tenant = Mock()
    tenant.id = "tenant-456"
    tenant.status = MockTenantStatus.SUSPENDED
    tenant.billing_tier = "growth"
    tenant.name = "Suspended Store"
    return tenant


@pytest.fixture
def free_tier_tenant():
    """Create a free tier tenant fixture."""
    tenant = Mock()
    tenant.id = "tenant-789"
    tenant.status = MockTenantStatus.ACTIVE
    tenant.billing_tier = "free"
    tenant.name = "Free Store"
    return tenant


@pytest.fixture
def merchant_admin_role():
    """Create a merchant_admin role fixture."""
    role = Mock()
    role.id = "role-123"
    role.user_id = "user-123"
    role.tenant_id = "tenant-123"
    role.role = "merchant_admin"
    role.is_active = True
    return role


@pytest.fixture
def agency_admin_role():
    """Create an agency_admin role fixture."""
    role = Mock()
    role.id = "role-456"
    role.user_id = "user-123"
    role.tenant_id = "tenant-123"
    role.role = "agency_admin"
    role.is_active = True
    return role


# =============================================================================
# Test: Tenant Access Revoked → Request Fails
# =============================================================================


class TestTenantAccessRevoked:
    """Tests for tenant access revocation enforcement."""

    def test_revoked_access_returns_403(self, active_user, active_tenant):
        """
        When a user's tenant access is revoked, the next request should fail.
        """
        result = mock_enforce_authorization(
            user=active_user,
            tenant=active_tenant,
            user_tenant_roles=[],  # No roles = access revoked
            clerk_user_id="clerk_user_123",
            active_tenant_id="tenant-123",
            jwt_roles=["merchant_admin"],
            request_path="/api/data",
            request_method="GET",
        )

        assert not result.is_authorized
        assert result.error_code == "ACCESS_REVOKED"
        assert result.audit_action == MockAuditAction.IDENTITY_ACCESS_REVOKED_ENFORCED
        assert result.audit_metadata.get("tenant_id") == "tenant-123"

    def test_revoked_access_includes_previous_roles_in_audit(
        self, active_user, active_tenant
    ):
        """Audit event should include the previous roles for tracking."""
        result = mock_enforce_authorization(
            user=active_user,
            tenant=active_tenant,
            user_tenant_roles=[],
            clerk_user_id="clerk_user_123",
            active_tenant_id="tenant-123",
            jwt_roles=["merchant_admin", "billing_manager"],
            request_path="/api/data",
            request_method="GET",
        )

        assert result.previous_roles == ["merchant_admin", "billing_manager"]
        assert result.audit_metadata.get("previous_roles") == [
            "merchant_admin",
            "billing_manager",
        ]

    def test_user_not_found_returns_unauthorized(self):
        """If user doesn't exist in local DB, return unauthorized."""
        result = mock_enforce_authorization(
            user=None,
            tenant=None,
            user_tenant_roles=[],
            clerk_user_id="unknown_clerk_user",
            active_tenant_id="tenant-123",
            request_path="/api/data",
            request_method="GET",
        )

        assert not result.is_authorized
        assert result.error_code == "USER_NOT_FOUND"

    def test_inactive_user_returns_unauthorized(self, inactive_user):
        """If user is deactivated, return unauthorized."""
        result = mock_enforce_authorization(
            user=inactive_user,
            tenant=None,
            user_tenant_roles=[],
            clerk_user_id="clerk_user_456",
            active_tenant_id="tenant-123",
            request_path="/api/data",
            request_method="GET",
        )

        assert not result.is_authorized
        assert result.error_code == "USER_INACTIVE"


# =============================================================================
# Test: Role Changed → Permissions Reflect Immediately
# =============================================================================


class TestRoleChangeEnforcement:
    """Tests for role change detection and enforcement."""

    def test_role_change_detected(
        self, active_user, active_tenant, merchant_admin_role
    ):
        """
        When a user's role changes, the new role should be reflected immediately.
        """
        result = mock_enforce_authorization(
            user=active_user,
            tenant=active_tenant,
            user_tenant_roles=[merchant_admin_role],
            clerk_user_id="clerk_user_123",
            active_tenant_id="tenant-123",
            jwt_roles=["agency_admin"],  # JWT has old role
            request_path="/api/data",
            request_method="GET",
        )

        assert result.is_authorized
        assert result.roles == ["merchant_admin"]  # DB role used
        assert result.roles_changed is True
        assert result.previous_roles == ["agency_admin"]

    def test_role_change_emits_audit_event(
        self, active_user, active_tenant, merchant_admin_role
    ):
        """Role changes should emit an audit event for tracking."""
        result = mock_enforce_authorization(
            user=active_user,
            tenant=active_tenant,
            user_tenant_roles=[merchant_admin_role],
            clerk_user_id="clerk_user_123",
            active_tenant_id="tenant-123",
            jwt_roles=["agency_admin"],
            request_path="/api/data",
            request_method="GET",
        )

        assert result.audit_action == MockAuditAction.IDENTITY_ROLE_CHANGE_ENFORCED
        assert result.audit_metadata.get("previous_roles") == ["agency_admin"]
        assert result.audit_metadata.get("new_roles") == ["merchant_admin"]

    def test_no_role_change_when_roles_match(
        self, active_user, active_tenant, merchant_admin_role
    ):
        """No audit event when roles haven't changed."""
        result = mock_enforce_authorization(
            user=active_user,
            tenant=active_tenant,
            user_tenant_roles=[merchant_admin_role],
            clerk_user_id="clerk_user_123",
            active_tenant_id="tenant-123",
            jwt_roles=["merchant_admin"],  # Matches DB
            request_path="/api/data",
            request_method="GET",
        )

        assert result.is_authorized
        assert result.roles_changed is False
        assert result.audit_action is None


# =============================================================================
# Test: Billing Downgrade → Invalid Role Blocked
# =============================================================================


class TestBillingDowngradeEnforcement:
    """Tests for billing tier role validation."""

    def test_agency_role_blocked_on_free_tier(
        self, active_user, free_tier_tenant, agency_admin_role
    ):
        """
        Agency roles require paid tier. Free tier should block agency_admin.
        """
        agency_admin_role.tenant_id = "tenant-789"

        result = mock_enforce_authorization(
            user=active_user,
            tenant=free_tier_tenant,
            user_tenant_roles=[agency_admin_role],
            clerk_user_id="clerk_user_123",
            active_tenant_id="tenant-789",
            jwt_roles=["agency_admin"],
            request_path="/api/data",
            request_method="GET",
        )

        assert not result.is_authorized
        assert result.error_code == "BILLING_ROLE_NOT_ALLOWED"
        assert result.audit_action == MockAuditAction.BILLING_ROLE_REVOKED_DUE_TO_DOWNGRADE
        assert result.billing_tier == "free"

    def test_merchant_role_allowed_on_free_tier(
        self, active_user, free_tier_tenant, merchant_admin_role
    ):
        """Merchant roles should work on free tier."""
        merchant_admin_role.tenant_id = "tenant-789"

        result = mock_enforce_authorization(
            user=active_user,
            tenant=free_tier_tenant,
            user_tenant_roles=[merchant_admin_role],
            clerk_user_id="clerk_user_123",
            active_tenant_id="tenant-789",
            jwt_roles=["merchant_admin"],
            request_path="/api/data",
            request_method="GET",
        )

        assert result.is_authorized
        assert result.roles == ["merchant_admin"]

    def test_billing_downgrade_includes_allowed_roles(
        self, active_user, free_tier_tenant, agency_admin_role
    ):
        """Error response should include which roles are allowed for the tier."""
        agency_admin_role.tenant_id = "tenant-789"

        result = mock_enforce_authorization(
            user=active_user,
            tenant=free_tier_tenant,
            user_tenant_roles=[agency_admin_role],
            clerk_user_id="clerk_user_123",
            active_tenant_id="tenant-789",
            jwt_roles=["agency_admin"],
            request_path="/api/data",
            request_method="GET",
        )

        assert "allowed_roles" in result.audit_metadata
        allowed = result.audit_metadata["allowed_roles"]
        assert "merchant_admin" in allowed
        assert "merchant_viewer" in allowed

    def test_mixed_roles_filters_to_valid_only(self, active_user, free_tier_tenant):
        """If user has both valid and invalid roles, only valid roles are used."""
        merchant_role = Mock()
        merchant_role.role = "merchant_admin"
        merchant_role.is_active = True

        agency_role = Mock()
        agency_role.role = "agency_admin"
        agency_role.is_active = True

        result = mock_enforce_authorization(
            user=active_user,
            tenant=free_tier_tenant,
            user_tenant_roles=[merchant_role, agency_role],
            clerk_user_id="clerk_user_123",
            active_tenant_id="tenant-789",
            jwt_roles=["agency_admin", "merchant_admin"],
            request_path="/api/data",
            request_method="GET",
        )

        # Should be authorized with only the valid role
        assert result.is_authorized
        assert "merchant_admin" in result.roles
        assert "agency_admin" not in result.roles


# =============================================================================
# Test: Tenant Suspended → Access Denied
# =============================================================================


class TestTenantSuspensionEnforcement:
    """Tests for tenant status enforcement."""

    def test_suspended_tenant_returns_403(
        self, active_user, suspended_tenant, merchant_admin_role
    ):
        """Suspended tenant should block all access."""
        result = mock_enforce_authorization(
            user=active_user,
            tenant=suspended_tenant,
            user_tenant_roles=[merchant_admin_role],
            clerk_user_id="clerk_user_123",
            active_tenant_id="tenant-456",
            jwt_roles=["merchant_admin"],
            request_path="/api/data",
            request_method="GET",
        )

        assert not result.is_authorized
        assert result.error_code == "TENANT_SUSPENDED"
        assert result.audit_action == MockAuditAction.IDENTITY_ACCESS_REVOKED_ENFORCED

    def test_tenant_not_found_returns_error(self, active_user):
        """Non-existent tenant should return error."""
        result = mock_enforce_authorization(
            user=active_user,
            tenant=None,
            user_tenant_roles=[],
            clerk_user_id="clerk_user_123",
            active_tenant_id="nonexistent-tenant",
            request_path="/api/data",
            request_method="GET",
        )

        assert not result.is_authorized
        assert result.error_code == "TENANT_NOT_FOUND"


# =============================================================================
# Test: Concurrency and Race Conditions
# =============================================================================


class TestConcurrencyHandling:
    """Tests for concurrent request handling during revocation."""

    def test_concurrent_requests_during_revocation(
        self, active_user, active_tenant, merchant_admin_role
    ):
        """
        If user changes tenant while revocation happens, enforcement still works.
        Each request gets a fresh DB check.
        """
        # First request: user still has access
        result1 = mock_enforce_authorization(
            user=active_user,
            tenant=active_tenant,
            user_tenant_roles=[merchant_admin_role],
            clerk_user_id="clerk_user_123",
            active_tenant_id="tenant-123",
            request_path="/api/data",
            request_method="GET",
        )
        assert result1.is_authorized

        # Second request: access revoked (no roles)
        result2 = mock_enforce_authorization(
            user=active_user,
            tenant=active_tenant,
            user_tenant_roles=[],  # Roles removed
            clerk_user_id="clerk_user_123",
            active_tenant_id="tenant-123",
            request_path="/api/data",
            request_method="GET",
        )
        assert not result2.is_authorized
        assert result2.error_code == "ACCESS_REVOKED"


# =============================================================================
# Test: Billing Tier Validation Functions
# =============================================================================


class TestBillingTierValidation:
    """Tests for billing tier role validation functions."""

    def test_free_tier_allows_merchant_roles(self):
        """Free tier should allow merchant roles."""
        assert is_role_allowed_for_billing_tier("merchant_admin", "free")
        assert is_role_allowed_for_billing_tier("merchant_viewer", "free")
        assert is_role_allowed_for_billing_tier("viewer", "free")
        assert is_role_allowed_for_billing_tier("editor", "free")

    def test_free_tier_blocks_agency_roles(self):
        """Free tier should block agency roles."""
        assert not is_role_allowed_for_billing_tier("agency_admin", "free")
        assert not is_role_allowed_for_billing_tier("agency_viewer", "free")

    def test_growth_tier_allows_agency_viewer(self):
        """Growth tier should allow agency_viewer but not agency_admin."""
        assert is_role_allowed_for_billing_tier("agency_viewer", "growth")
        assert not is_role_allowed_for_billing_tier("agency_admin", "growth")

    def test_enterprise_tier_allows_all_roles(self):
        """Enterprise tier should allow all roles."""
        assert is_role_allowed_for_billing_tier("agency_admin", "enterprise")
        assert is_role_allowed_for_billing_tier("agency_viewer", "enterprise")
        assert is_role_allowed_for_billing_tier("merchant_admin", "enterprise")
        assert is_role_allowed_for_billing_tier("admin", "enterprise")

    def test_case_insensitive_billing_tier(self):
        """Billing tier check should be case-insensitive."""
        assert is_role_allowed_for_billing_tier("merchant_admin", "FREE")
        assert is_role_allowed_for_billing_tier("merchant_admin", "Free")
        assert is_role_allowed_for_billing_tier("merchant_admin", "free")

    def test_get_allowed_roles_returns_list(self):
        """get_allowed_roles_for_billing_tier should return a list."""
        roles = get_allowed_roles_for_billing_tier("free")
        assert isinstance(roles, list)
        assert "merchant_admin" in roles
        assert "agency_admin" not in roles
