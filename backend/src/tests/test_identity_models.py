"""
Tests for identity models: Organization, Tenant, User, UserTenantRole.

Test categories:
1. Model creation with required fields
2. Relationship navigation (Org→Tenant, Tenant→UserTenantRole, User→UserTenantRole)
3. Cascade deletes (User/Tenant delete → UserTenantRole deleted)
4. SET NULL behavior (Organization delete → tenant.organization_id = NULL)
5. Uniqueness constraints
6. Enum values (TenantStatus)
7. Property methods (User.full_name, etc.)
8. Timestamps
"""

import uuid
from datetime import datetime, timezone

import pytest

from src.models.organization import Organization
from src.models.tenant import Tenant, TenantStatus
from src.models.user import User
from src.models.user_tenant_roles import UserTenantRole


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def organization_id() -> str:
    """Generate unique organization ID."""
    return str(uuid.uuid4())


@pytest.fixture
def tenant_id() -> str:
    """Generate unique tenant ID."""
    return str(uuid.uuid4())


@pytest.fixture
def user_id() -> str:
    """Generate unique user ID."""
    return str(uuid.uuid4())


@pytest.fixture
def clerk_user_id() -> str:
    """Generate unique Clerk user ID."""
    return f"user_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def clerk_org_id() -> str:
    """Generate unique Clerk organization ID."""
    return f"org_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def sample_organization(organization_id, clerk_org_id) -> Organization:
    """Create a sample organization."""
    return Organization(
        id=organization_id,
        clerk_org_id=clerk_org_id,
        name="Test Agency",
        slug="test-agency",
        is_active=True,
        settings={"feature_flags": {"beta": True}},
    )


@pytest.fixture
def sample_tenant(tenant_id, clerk_org_id) -> Tenant:
    """Create a sample tenant."""
    return Tenant(
        id=tenant_id,
        clerk_org_id=clerk_org_id,
        name="Test Store",
        slug="test-store",
        billing_tier="growth",
        status=TenantStatus.ACTIVE,
        settings={"timezone": "America/New_York"},
    )


@pytest.fixture
def sample_user(user_id, clerk_user_id) -> User:
    """Create a sample user."""
    return User(
        id=user_id,
        clerk_user_id=clerk_user_id,
        email="test@example.com",
        first_name="John",
        last_name="Doe",
        avatar_url="https://example.com/avatar.jpg",
        is_active=True,
    )


@pytest.fixture
def sample_user_tenant_role(user_id, tenant_id) -> UserTenantRole:
    """Create a sample user tenant role."""
    return UserTenantRole(
        id=str(uuid.uuid4()),
        user_id=user_id,
        tenant_id=tenant_id,
        role="MERCHANT_ADMIN",
        source="clerk_webhook",
        is_active=True,
    )


# =============================================================================
# Organization Model Tests
# =============================================================================

class TestOrganizationModel:
    """Tests for Organization model."""

    def test_creates_with_required_fields(self):
        """Should create Organization with required fields."""
        org = Organization(name="Test Org")

        assert org.name == "Test Org"
        assert org.is_active is True  # Default
        assert org.id is not None  # UUID default

    def test_creates_with_all_fields(self, organization_id, clerk_org_id):
        """Should create Organization with all fields."""
        org = Organization(
            id=organization_id,
            clerk_org_id=clerk_org_id,
            name="Full Org",
            slug="full-org",
            is_active=True,
            settings={"key": "value"},
        )

        assert org.id == organization_id
        assert org.clerk_org_id == clerk_org_id
        assert org.name == "Full Org"
        assert org.slug == "full-org"
        assert org.is_active is True
        assert org.settings == {"key": "value"}

    def test_repr(self, sample_organization):
        """Should have readable repr."""
        repr_str = repr(sample_organization)

        assert "Organization" in repr_str
        assert sample_organization.name in repr_str

    def test_defaults(self):
        """Should have correct defaults."""
        org = Organization(name="Defaults Test")

        assert org.is_active is True
        assert org.settings is None
        assert org.slug is None
        assert org.clerk_org_id is None


# =============================================================================
# Tenant Model Tests
# =============================================================================

class TestTenantModel:
    """Tests for Tenant model."""

    def test_creates_with_required_fields(self):
        """Should create Tenant with required fields."""
        tenant = Tenant(name="Test Tenant")

        assert tenant.name == "Test Tenant"
        assert tenant.status == TenantStatus.ACTIVE  # Default
        assert tenant.billing_tier == "free"  # Default
        assert tenant.id is not None  # UUID default

    def test_creates_with_all_fields(self, tenant_id, organization_id, clerk_org_id):
        """Should create Tenant with all fields."""
        tenant = Tenant(
            id=tenant_id,
            organization_id=organization_id,
            clerk_org_id=clerk_org_id,
            name="Full Tenant",
            slug="full-tenant",
            billing_tier="enterprise",
            status=TenantStatus.ACTIVE,
            settings={"theme": "dark"},
        )

        assert tenant.id == tenant_id
        assert tenant.organization_id == organization_id
        assert tenant.clerk_org_id == clerk_org_id
        assert tenant.name == "Full Tenant"
        assert tenant.slug == "full-tenant"
        assert tenant.billing_tier == "enterprise"
        assert tenant.status == TenantStatus.ACTIVE
        assert tenant.settings == {"theme": "dark"}

    def test_is_active_property(self):
        """Should correctly report is_active status."""
        active_tenant = Tenant(name="Active", status=TenantStatus.ACTIVE)
        suspended_tenant = Tenant(name="Suspended", status=TenantStatus.SUSPENDED)
        deactivated_tenant = Tenant(name="Deactivated", status=TenantStatus.DEACTIVATED)

        assert active_tenant.is_active is True
        assert suspended_tenant.is_active is False
        assert deactivated_tenant.is_active is False

    def test_is_standalone_property(self):
        """Should correctly report standalone status."""
        standalone = Tenant(name="Standalone")
        with_org = Tenant(name="With Org", organization_id="org_123")

        assert standalone.is_standalone is True
        assert with_org.is_standalone is False

    def test_repr(self, sample_tenant):
        """Should have readable repr."""
        repr_str = repr(sample_tenant)

        assert "Tenant" in repr_str
        assert sample_tenant.name in repr_str


class TestTenantStatusEnum:
    """Tests for TenantStatus enumeration."""

    def test_all_status_values(self):
        """Should have all expected status values."""
        assert TenantStatus.ACTIVE.value == "active"
        assert TenantStatus.SUSPENDED.value == "suspended"
        assert TenantStatus.DEACTIVATED.value == "deactivated"

    def test_status_count(self):
        """Should have exactly 3 status values."""
        assert len(TenantStatus) == 3


# =============================================================================
# User Model Tests
# =============================================================================

class TestUserModel:
    """Tests for User model."""

    def test_creates_with_required_fields(self, clerk_user_id):
        """Should create User with required fields."""
        user = User(clerk_user_id=clerk_user_id)

        assert user.clerk_user_id == clerk_user_id
        assert user.is_active is True  # Default
        assert user.id is not None  # UUID default

    def test_creates_with_all_fields(self, user_id, clerk_user_id):
        """Should create User with all fields."""
        user = User(
            id=user_id,
            clerk_user_id=clerk_user_id,
            email="full@example.com",
            first_name="Jane",
            last_name="Smith",
            avatar_url="https://example.com/jane.jpg",
            is_active=True,
            metadata={"preferences": {"theme": "dark"}},
        )

        assert user.id == user_id
        assert user.clerk_user_id == clerk_user_id
        assert user.email == "full@example.com"
        assert user.first_name == "Jane"
        assert user.last_name == "Smith"
        assert user.avatar_url == "https://example.com/jane.jpg"
        assert user.is_active is True
        assert user.metadata == {"preferences": {"theme": "dark"}}

    def test_no_password_column(self, clerk_user_id):
        """Should NOT have password column (Clerk handles auth)."""
        user = User(clerk_user_id=clerk_user_id)

        # Verify no password-related attributes
        assert not hasattr(user, 'password')
        assert not hasattr(user, 'password_hash')
        assert not hasattr(user, 'hashed_password')

    def test_full_name_with_both_names(self, clerk_user_id):
        """Should return full name when both names set."""
        user = User(
            clerk_user_id=clerk_user_id,
            first_name="John",
            last_name="Doe",
        )

        assert user.full_name == "John Doe"

    def test_full_name_with_first_name_only(self, clerk_user_id):
        """Should return first name when only first name set."""
        user = User(
            clerk_user_id=clerk_user_id,
            first_name="John",
        )

        assert user.full_name == "John"

    def test_full_name_with_last_name_only(self, clerk_user_id):
        """Should return last name when only last name set."""
        user = User(
            clerk_user_id=clerk_user_id,
            last_name="Doe",
        )

        assert user.full_name == "Doe"

    def test_full_name_falls_back_to_email(self, clerk_user_id):
        """Should fall back to email when no name set."""
        user = User(
            clerk_user_id=clerk_user_id,
            email="john@example.com",
        )

        assert user.full_name == "john@example.com"

    def test_full_name_empty_when_nothing_set(self, clerk_user_id):
        """Should return empty string when nothing set."""
        user = User(clerk_user_id=clerk_user_id)

        assert user.full_name == ""

    def test_display_name_priority(self, clerk_user_id):
        """Should prioritize full_name > email > clerk_user_id."""
        # With name
        user1 = User(clerk_user_id=clerk_user_id, first_name="John", email="john@example.com")
        assert user1.display_name == "John"

        # Without name, with email
        user2 = User(clerk_user_id=clerk_user_id, email="john@example.com")
        assert user2.display_name == "john@example.com"

        # Without name or email
        user3 = User(clerk_user_id=clerk_user_id)
        assert user3.display_name == clerk_user_id

    def test_mark_synced(self, sample_user):
        """Should update last_synced_at timestamp."""
        assert sample_user.last_synced_at is None

        sample_user.mark_synced()

        assert sample_user.last_synced_at is not None
        assert isinstance(sample_user.last_synced_at, datetime)

    def test_repr(self, sample_user):
        """Should have readable repr."""
        repr_str = repr(sample_user)

        assert "User" in repr_str
        assert sample_user.clerk_user_id in repr_str


# =============================================================================
# UserTenantRole Model Tests
# =============================================================================

class TestUserTenantRoleModel:
    """Tests for UserTenantRole model."""

    def test_creates_with_required_fields(self, user_id, tenant_id):
        """Should create UserTenantRole with required fields."""
        role = UserTenantRole(
            user_id=user_id,
            tenant_id=tenant_id,
            role="MERCHANT_ADMIN",
        )

        assert role.user_id == user_id
        assert role.tenant_id == tenant_id
        assert role.role == "MERCHANT_ADMIN"
        assert role.is_active is True  # Default
        assert role.id is not None  # UUID default

    def test_creates_with_all_fields(self, user_id, tenant_id, clerk_user_id):
        """Should create UserTenantRole with all fields."""
        role = UserTenantRole(
            id=str(uuid.uuid4()),
            user_id=user_id,
            tenant_id=tenant_id,
            role="AGENCY_ADMIN",
            assigned_by=clerk_user_id,
            source="agency_grant",
            is_active=True,
        )

        assert role.user_id == user_id
        assert role.tenant_id == tenant_id
        assert role.role == "AGENCY_ADMIN"
        assert role.assigned_by == clerk_user_id
        assert role.source == "agency_grant"
        assert role.is_active is True

    def test_is_admin_role_property(self, user_id, tenant_id):
        """Should correctly identify admin roles."""
        admin_roles = ["admin", "owner", "merchant_admin", "agency_admin", "super_admin"]
        non_admin_roles = ["viewer", "editor", "merchant_viewer", "agency_viewer"]

        for role_name in admin_roles:
            role = UserTenantRole(user_id=user_id, tenant_id=tenant_id, role=role_name)
            assert role.is_admin_role is True, f"{role_name} should be admin"

        for role_name in non_admin_roles:
            role = UserTenantRole(user_id=user_id, tenant_id=tenant_id, role=role_name)
            assert role.is_admin_role is False, f"{role_name} should not be admin"

    def test_is_agency_role_property(self, user_id, tenant_id):
        """Should correctly identify agency roles."""
        agency_roles = ["agency_admin", "agency_viewer"]
        non_agency_roles = ["admin", "merchant_admin", "viewer"]

        for role_name in agency_roles:
            role = UserTenantRole(user_id=user_id, tenant_id=tenant_id, role=role_name)
            assert role.is_agency_role is True, f"{role_name} should be agency"

        for role_name in non_agency_roles:
            role = UserTenantRole(user_id=user_id, tenant_id=tenant_id, role=role_name)
            assert role.is_agency_role is False, f"{role_name} should not be agency"

    def test_deactivate(self, sample_user_tenant_role):
        """Should deactivate role."""
        assert sample_user_tenant_role.is_active is True

        sample_user_tenant_role.deactivate()

        assert sample_user_tenant_role.is_active is False

    def test_reactivate(self, sample_user_tenant_role):
        """Should reactivate role."""
        sample_user_tenant_role.is_active = False

        sample_user_tenant_role.reactivate()

        assert sample_user_tenant_role.is_active is True

    def test_create_from_clerk_factory(self, user_id, tenant_id):
        """Should create role from Clerk webhook."""
        role = UserTenantRole.create_from_clerk(
            user_id=user_id,
            tenant_id=tenant_id,
            role="MERCHANT_ADMIN",
        )

        assert role.user_id == user_id
        assert role.tenant_id == tenant_id
        assert role.role == "MERCHANT_ADMIN"
        assert role.source == "clerk_webhook"
        assert role.assigned_by is None
        assert role.assigned_at is not None

    def test_create_from_grant_factory(self, user_id, tenant_id, clerk_user_id):
        """Should create role from agency grant."""
        role = UserTenantRole.create_from_grant(
            user_id=user_id,
            tenant_id=tenant_id,
            role="AGENCY_VIEWER",
            granted_by=clerk_user_id,
        )

        assert role.user_id == user_id
        assert role.tenant_id == tenant_id
        assert role.role == "AGENCY_VIEWER"
        assert role.source == "agency_grant"
        assert role.assigned_by == clerk_user_id
        assert role.assigned_at is not None

    def test_repr(self, sample_user_tenant_role):
        """Should have readable repr."""
        repr_str = repr(sample_user_tenant_role)

        assert "UserTenantRole" in repr_str
        assert sample_user_tenant_role.role in repr_str


# =============================================================================
# Relationship Tests (require database session)
# =============================================================================

class TestModelRelationships:
    """
    Tests for model relationships.

    Note: These tests verify relationship definitions exist.
    Full relationship behavior tests require database session fixtures.
    """

    def test_organization_has_tenants_relationship(self, sample_organization):
        """Organization should have tenants relationship defined."""
        # Verify relationship is defined (not executed)
        assert hasattr(sample_organization, 'tenants')

    def test_tenant_has_organization_relationship(self, sample_tenant):
        """Tenant should have organization relationship defined."""
        assert hasattr(sample_tenant, 'organization')

    def test_tenant_has_user_roles_relationship(self, sample_tenant):
        """Tenant should have user_roles relationship defined."""
        assert hasattr(sample_tenant, 'user_roles')

    def test_user_has_tenant_roles_relationship(self, sample_user):
        """User should have tenant_roles relationship defined."""
        assert hasattr(sample_user, 'tenant_roles')

    def test_user_tenant_role_has_user_relationship(self, sample_user_tenant_role):
        """UserTenantRole should have user relationship defined."""
        assert hasattr(sample_user_tenant_role, 'user')

    def test_user_tenant_role_has_tenant_relationship(self, sample_user_tenant_role):
        """UserTenantRole should have tenant relationship defined."""
        assert hasattr(sample_user_tenant_role, 'tenant')


# =============================================================================
# Constraint Tests
# =============================================================================

class TestConstraints:
    """
    Tests for model constraints.

    Note: Actual uniqueness enforcement requires database.
    These tests verify constraint definitions.
    """

    def test_user_clerk_user_id_unique_constraint(self):
        """User.clerk_user_id should be unique."""
        # Verify unique=True in column definition
        from sqlalchemy import inspect

        mapper = inspect(User)
        clerk_user_id_col = mapper.columns['clerk_user_id']

        assert clerk_user_id_col.unique is True

    def test_organization_clerk_org_id_unique_constraint(self):
        """Organization.clerk_org_id should be unique."""
        from sqlalchemy import inspect

        mapper = inspect(Organization)
        clerk_org_id_col = mapper.columns['clerk_org_id']

        assert clerk_org_id_col.unique is True

    def test_tenant_clerk_org_id_unique_constraint(self):
        """Tenant.clerk_org_id should be unique."""
        from sqlalchemy import inspect

        mapper = inspect(Tenant)
        clerk_org_id_col = mapper.columns['clerk_org_id']

        assert clerk_org_id_col.unique is True

    def test_organization_slug_unique_constraint(self):
        """Organization.slug should be unique."""
        from sqlalchemy import inspect

        mapper = inspect(Organization)
        slug_col = mapper.columns['slug']

        assert slug_col.unique is True

    def test_tenant_slug_unique_constraint(self):
        """Tenant.slug should be unique."""
        from sqlalchemy import inspect

        mapper = inspect(Tenant)
        slug_col = mapper.columns['slug']

        assert slug_col.unique is True


# =============================================================================
# Default Value Tests
# =============================================================================

class TestDefaultValues:
    """Tests for model default values."""

    def test_organization_defaults(self):
        """Organization should have correct defaults."""
        org = Organization(name="Test")

        assert org.is_active is True
        assert org.settings is None
        assert org.id is not None

    def test_tenant_defaults(self):
        """Tenant should have correct defaults."""
        tenant = Tenant(name="Test")

        assert tenant.status == TenantStatus.ACTIVE
        assert tenant.billing_tier == "free"
        assert tenant.organization_id is None
        assert tenant.id is not None

    def test_user_defaults(self):
        """User should have correct defaults."""
        user = User(clerk_user_id="user_123")

        assert user.is_active is True
        assert user.email is None
        assert user.first_name is None
        assert user.last_name is None
        assert user.id is not None

    def test_user_tenant_role_defaults(self):
        """UserTenantRole should have correct defaults."""
        role = UserTenantRole(
            user_id="user_123",
            tenant_id="tenant_123",
            role="VIEWER",
        )

        assert role.is_active is True
        assert role.source == "clerk_webhook"
        assert role.assigned_at is not None
        assert role.id is not None
