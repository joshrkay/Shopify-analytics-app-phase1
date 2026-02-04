"""
Tests for Tenant Members Service and API.

Tests cover:
- Listing tenant members
- Granting access (by clerk_user_id and email)
- Revoking access
- Updating roles
- Permission checks
- Edge cases (duplicate roles, last admin, self-actions)
"""

import pytest
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.models.organization import Organization
from src.models.tenant import Tenant, TenantStatus
from src.models.user import User
from src.models.user_tenant_roles import UserTenantRole
from src.services.tenant_members_service import (
    TenantMembersService,
    TenantNotFoundError,
    UserNotFoundError,
    DuplicateRoleError,
    LastAdminError,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def db_session(test_db_session):
    """Use the test database session."""
    return test_db_session


@pytest.fixture
def service(db_session):
    """Create a TenantMembersService instance."""
    return TenantMembersService(db_session)


@pytest.fixture
def sample_tenant(db_session):
    """Create a sample tenant for testing."""
    tenant = Tenant(
        name="Test Tenant",
        slug="test-tenant",
        clerk_org_id="org_test_123",
        billing_tier="growth",
        status=TenantStatus.ACTIVE,
    )
    db_session.add(tenant)
    db_session.flush()
    return tenant


@pytest.fixture
def sample_user(db_session):
    """Create a sample user for testing."""
    user = User(
        clerk_user_id="user_test_123",
        email="testuser@example.com",
        first_name="Test",
        last_name="User",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def admin_user(db_session):
    """Create an admin user for testing."""
    user = User(
        clerk_user_id="user_admin_123",
        email="admin@example.com",
        first_name="Admin",
        last_name="User",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def tenant_with_admin(db_session, sample_tenant, admin_user):
    """Create a tenant with an admin user."""
    role = UserTenantRole.create_from_clerk(
        user_id=admin_user.id,
        tenant_id=sample_tenant.id,
        role="MERCHANT_ADMIN",
    )
    db_session.add(role)
    db_session.flush()
    return sample_tenant


# =============================================================================
# List Members Tests
# =============================================================================

class TestListMembers:
    """Tests for listing tenant members."""

    def test_list_members_empty(self, service, sample_tenant):
        """Test listing members of a tenant with no members."""
        members = service.list_members(sample_tenant.id)
        assert len(members) == 0

    def test_list_members_with_users(self, service, tenant_with_admin, admin_user):
        """Test listing members with users."""
        members = service.list_members(tenant_with_admin.id)

        assert len(members) == 1
        assert members[0]["clerk_user_id"] == admin_user.clerk_user_id
        assert members[0]["role"] == "MERCHANT_ADMIN"
        assert members[0]["is_active"] is True

    def test_list_members_excludes_inactive(
        self, service, db_session, tenant_with_admin, sample_user
    ):
        """Test that inactive members are excluded by default."""
        # Add an inactive member
        role = UserTenantRole.create_from_clerk(
            user_id=sample_user.id,
            tenant_id=tenant_with_admin.id,
            role="MERCHANT_VIEWER",
        )
        role.is_active = False
        db_session.add(role)
        db_session.flush()

        members = service.list_members(tenant_with_admin.id)
        assert len(members) == 1  # Only admin

    def test_list_members_include_inactive(
        self, service, db_session, tenant_with_admin, sample_user
    ):
        """Test including inactive members."""
        # Add an inactive member
        role = UserTenantRole.create_from_clerk(
            user_id=sample_user.id,
            tenant_id=tenant_with_admin.id,
            role="MERCHANT_VIEWER",
        )
        role.is_active = False
        db_session.add(role)
        db_session.flush()

        members = service.list_members(tenant_with_admin.id, include_inactive=True)
        assert len(members) == 2

    def test_list_members_tenant_not_found(self, service):
        """Test listing members of non-existent tenant."""
        with pytest.raises(TenantNotFoundError):
            service.list_members("nonexistent_tenant_id")


# =============================================================================
# Grant Access Tests
# =============================================================================

class TestGrantAccess:
    """Tests for granting access to tenants."""

    def test_grant_access_by_clerk_id(
        self, service, db_session, sample_tenant, sample_user
    ):
        """Test granting access by clerk_user_id."""
        result = service.grant_access(
            tenant_id=sample_tenant.id,
            clerk_user_id=sample_user.clerk_user_id,
            role="MERCHANT_VIEWER",
            granted_by="user_granter_123",
        )
        db_session.flush()

        assert result["role"] == "MERCHANT_VIEWER"
        assert result["user_id"] == sample_user.id
        assert result["tenant_id"] == sample_tenant.id
        assert result["assigned_by"] == "user_granter_123"
        assert result["source"] == "agency_grant"

    def test_grant_access_by_email(
        self, service, db_session, sample_tenant, sample_user
    ):
        """Test granting access by email."""
        result = service.grant_access(
            tenant_id=sample_tenant.id,
            email=sample_user.email,
            role="MERCHANT_VIEWER",
        )
        db_session.flush()

        assert result["role"] == "MERCHANT_VIEWER"
        assert result["user_id"] == sample_user.id

    def test_grant_access_creates_user_if_needed(
        self, service, db_session, sample_tenant
    ):
        """Test that granting access creates user if not exists."""
        result = service.grant_access(
            tenant_id=sample_tenant.id,
            clerk_user_id="user_new_grant_123",
            role="MERCHANT_VIEWER",
        )
        db_session.flush()

        # User should be created
        user = db_session.query(User).filter(
            User.clerk_user_id == "user_new_grant_123"
        ).first()
        assert user is not None
        assert result["user_id"] == user.id

    def test_grant_access_duplicate_role(
        self, service, db_session, tenant_with_admin, admin_user
    ):
        """Test that duplicate role grants are rejected."""
        with pytest.raises(DuplicateRoleError):
            service.grant_access(
                tenant_id=tenant_with_admin.id,
                clerk_user_id=admin_user.clerk_user_id,
                role="MERCHANT_ADMIN",
            )

    def test_grant_access_reactivates_inactive_role(
        self, service, db_session, sample_tenant, sample_user
    ):
        """Test that granting reactivates an inactive role."""
        # Create and deactivate a role
        role = UserTenantRole.create_from_clerk(
            user_id=sample_user.id,
            tenant_id=sample_tenant.id,
            role="MERCHANT_VIEWER",
        )
        role.is_active = False
        db_session.add(role)
        db_session.flush()
        original_id = role.id

        # Grant same role again
        result = service.grant_access(
            tenant_id=sample_tenant.id,
            clerk_user_id=sample_user.clerk_user_id,
            role="MERCHANT_VIEWER",
        )
        db_session.flush()

        # Should reactivate existing role
        assert result["id"] == original_id
        assert result["is_active"] is True

    def test_grant_access_tenant_not_found(self, service, sample_user):
        """Test granting access to non-existent tenant."""
        with pytest.raises(TenantNotFoundError):
            service.grant_access(
                tenant_id="nonexistent_tenant",
                clerk_user_id=sample_user.clerk_user_id,
                role="MERCHANT_VIEWER",
            )

    def test_grant_access_user_not_found_by_email(self, service, sample_tenant):
        """Test granting access with non-existent email (no clerk_id)."""
        with pytest.raises(UserNotFoundError):
            service.grant_access(
                tenant_id=sample_tenant.id,
                email="nonexistent@example.com",
                role="MERCHANT_VIEWER",
            )

    def test_grant_access_invalid_role(self, service, sample_tenant, sample_user):
        """Test granting access with invalid role."""
        with pytest.raises(ValueError, match="Invalid role"):
            service.grant_access(
                tenant_id=sample_tenant.id,
                clerk_user_id=sample_user.clerk_user_id,
                role="INVALID_ROLE",
            )

    def test_grant_access_missing_identifier(self, service, sample_tenant):
        """Test that grant requires either clerk_user_id or email."""
        with pytest.raises(ValueError, match="Either clerk_user_id or email"):
            service.grant_access(
                tenant_id=sample_tenant.id,
                role="MERCHANT_VIEWER",
            )


# =============================================================================
# Revoke Access Tests
# =============================================================================

class TestRevokeAccess:
    """Tests for revoking access to tenants."""

    def test_revoke_access_success(
        self, service, db_session, tenant_with_admin, sample_user, admin_user
    ):
        """Test revoking access successfully."""
        # Add a non-admin member
        role = UserTenantRole.create_from_clerk(
            user_id=sample_user.id,
            tenant_id=tenant_with_admin.id,
            role="MERCHANT_VIEWER",
        )
        db_session.add(role)
        db_session.flush()

        # Revoke their access
        result = service.revoke_access(
            tenant_id=tenant_with_admin.id,
            user_id=sample_user.id,
        )

        assert result is True

        # Verify role is deactivated
        updated_role = db_session.query(UserTenantRole).filter(
            UserTenantRole.id == role.id
        ).first()
        assert updated_role.is_active is False

    def test_revoke_access_user_not_member(self, service, tenant_with_admin, sample_user):
        """Test revoking access for user who is not a member."""
        result = service.revoke_access(
            tenant_id=tenant_with_admin.id,
            user_id=sample_user.id,
        )

        assert result is False

    def test_revoke_access_last_admin(self, service, tenant_with_admin, admin_user):
        """Test that revoking last admin's access is prevented."""
        with pytest.raises(LastAdminError):
            service.revoke_access(
                tenant_id=tenant_with_admin.id,
                user_id=admin_user.id,
            )

    def test_revoke_access_not_last_admin(
        self, service, db_session, tenant_with_admin, sample_user, admin_user
    ):
        """Test revoking admin access when another admin exists."""
        # Add another admin
        role = UserTenantRole.create_from_clerk(
            user_id=sample_user.id,
            tenant_id=tenant_with_admin.id,
            role="MERCHANT_ADMIN",
        )
        db_session.add(role)
        db_session.flush()

        # Now we can revoke the original admin
        result = service.revoke_access(
            tenant_id=tenant_with_admin.id,
            user_id=admin_user.id,
        )

        assert result is True

    def test_revoke_access_tenant_not_found(self, service, sample_user):
        """Test revoking access from non-existent tenant."""
        with pytest.raises(TenantNotFoundError):
            service.revoke_access(
                tenant_id="nonexistent_tenant",
                user_id=sample_user.id,
            )


# =============================================================================
# Update Role Tests
# =============================================================================

class TestUpdateRole:
    """Tests for updating user roles."""

    def test_update_role_success(
        self, service, db_session, tenant_with_admin, sample_user
    ):
        """Test updating a role successfully."""
        # Add a viewer
        role = UserTenantRole.create_from_clerk(
            user_id=sample_user.id,
            tenant_id=tenant_with_admin.id,
            role="MERCHANT_VIEWER",
        )
        db_session.add(role)
        db_session.flush()

        # Update to admin
        result = service.update_role(
            tenant_id=tenant_with_admin.id,
            user_id=sample_user.id,
            new_role="MERCHANT_ADMIN",
        )
        db_session.flush()

        assert result["role"] == "MERCHANT_ADMIN"

        # Old role should be deactivated
        old_role = db_session.query(UserTenantRole).filter(
            UserTenantRole.id == role.id
        ).first()
        assert old_role.is_active is False

    def test_update_role_downgrade_last_admin(
        self, service, tenant_with_admin, admin_user
    ):
        """Test that downgrading the last admin is prevented."""
        with pytest.raises(LastAdminError):
            service.update_role(
                tenant_id=tenant_with_admin.id,
                user_id=admin_user.id,
                new_role="MERCHANT_VIEWER",
            )

    def test_update_role_user_not_found(self, service, tenant_with_admin):
        """Test updating role for non-existent user."""
        with pytest.raises(UserNotFoundError):
            service.update_role(
                tenant_id=tenant_with_admin.id,
                user_id="nonexistent_user_id",
                new_role="MERCHANT_ADMIN",
            )


# =============================================================================
# Get User Tenants Tests
# =============================================================================

class TestGetUserTenants:
    """Tests for getting tenants a user has access to."""

    def test_get_user_tenants(self, service, db_session, tenant_with_admin, admin_user):
        """Test getting tenants for a user."""
        tenants = service.get_user_tenants(admin_user.clerk_user_id)

        assert len(tenants) == 1
        assert tenants[0]["id"] == tenant_with_admin.id
        assert tenants[0]["name"] == tenant_with_admin.name
        assert "MERCHANT_ADMIN" in tenants[0]["roles"]
        assert tenants[0]["is_admin"] is True

    def test_get_user_tenants_multiple(
        self, service, db_session, admin_user
    ):
        """Test getting multiple tenants for a user."""
        # Create two tenants
        tenant1 = Tenant(
            name="Tenant 1",
            slug="tenant-1",
            clerk_org_id="org_multi_1",
            status=TenantStatus.ACTIVE,
        )
        tenant2 = Tenant(
            name="Tenant 2",
            slug="tenant-2",
            clerk_org_id="org_multi_2",
            status=TenantStatus.ACTIVE,
        )
        db_session.add_all([tenant1, tenant2])
        db_session.flush()

        # Add user to both tenants
        role1 = UserTenantRole.create_from_clerk(
            user_id=admin_user.id,
            tenant_id=tenant1.id,
            role="MERCHANT_ADMIN",
        )
        role2 = UserTenantRole.create_from_clerk(
            user_id=admin_user.id,
            tenant_id=tenant2.id,
            role="MERCHANT_VIEWER",
        )
        db_session.add_all([role1, role2])
        db_session.flush()

        tenants = service.get_user_tenants(admin_user.clerk_user_id)

        assert len(tenants) == 2
        tenant_ids = [t["id"] for t in tenants]
        assert tenant1.id in tenant_ids
        assert tenant2.id in tenant_ids

    def test_get_user_tenants_excludes_inactive_tenants(
        self, service, db_session, admin_user
    ):
        """Test that inactive tenants are excluded."""
        # Create an inactive tenant
        tenant = Tenant(
            name="Inactive Tenant",
            slug="inactive-tenant",
            clerk_org_id="org_inactive",
            status=TenantStatus.DEACTIVATED,
        )
        db_session.add(tenant)
        db_session.flush()

        # Add user to tenant
        role = UserTenantRole.create_from_clerk(
            user_id=admin_user.id,
            tenant_id=tenant.id,
            role="MERCHANT_ADMIN",
        )
        db_session.add(role)
        db_session.flush()

        tenants = service.get_user_tenants(admin_user.clerk_user_id)

        # Should not include inactive tenant
        tenant_ids = [t["id"] for t in tenants]
        assert tenant.id not in tenant_ids

    def test_get_user_tenants_user_not_found(self, service):
        """Test getting tenants for non-existent user."""
        tenants = service.get_user_tenants("nonexistent_clerk_id")
        assert len(tenants) == 0


# =============================================================================
# Access Check Tests
# =============================================================================

class TestAccessChecks:
    """Tests for access check methods."""

    def test_check_user_has_access_true(
        self, service, tenant_with_admin, admin_user
    ):
        """Test checking user has access."""
        has_access = service.check_user_has_access(
            clerk_user_id=admin_user.clerk_user_id,
            tenant_id=tenant_with_admin.id,
        )
        assert has_access is True

    def test_check_user_has_access_false(self, service, tenant_with_admin, sample_user):
        """Test checking user does not have access."""
        has_access = service.check_user_has_access(
            clerk_user_id=sample_user.clerk_user_id,
            tenant_id=tenant_with_admin.id,
        )
        assert has_access is False

    def test_check_user_has_access_with_role(
        self, service, tenant_with_admin, admin_user
    ):
        """Test checking user has access with specific role."""
        # Admin has MERCHANT_ADMIN
        has_admin = service.check_user_has_access(
            clerk_user_id=admin_user.clerk_user_id,
            tenant_id=tenant_with_admin.id,
            required_role="MERCHANT_ADMIN",
        )
        assert has_admin is True

        # Admin does not have MERCHANT_VIEWER
        has_viewer = service.check_user_has_access(
            clerk_user_id=admin_user.clerk_user_id,
            tenant_id=tenant_with_admin.id,
            required_role="MERCHANT_VIEWER",
        )
        assert has_viewer is False

    def test_check_user_is_admin(self, service, tenant_with_admin, admin_user):
        """Test checking if user is admin."""
        is_admin = service.check_user_is_admin(
            clerk_user_id=admin_user.clerk_user_id,
            tenant_id=tenant_with_admin.id,
        )
        assert is_admin is True

    def test_check_user_is_admin_false(
        self, service, db_session, tenant_with_admin, sample_user
    ):
        """Test checking non-admin user."""
        # Add as viewer
        role = UserTenantRole.create_from_clerk(
            user_id=sample_user.id,
            tenant_id=tenant_with_admin.id,
            role="MERCHANT_VIEWER",
        )
        db_session.add(role)
        db_session.flush()

        is_admin = service.check_user_is_admin(
            clerk_user_id=sample_user.clerk_user_id,
            tenant_id=tenant_with_admin.id,
        )
        assert is_admin is False
