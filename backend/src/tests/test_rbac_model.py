"""
Tests for data-driven RBAC: tenant-scoped roles, multi-tenant user, default deny.

Story 5.5.1 - Data Model: Custom Roles Per Tenant

Tests cover:
- Default deny (no permissions if no assignments)
- Data-driven permissions via Role -> RolePermission
- Legacy permissions via UserTenantRole -> ROLE_PERMISSIONS matrix
- Dual-source resolution (union of both)
- Tenant isolation (no cross-tenant leakage)
- Seed functions for tenant role templates
- has_permission / has_any_permission / has_all_permissions with resolved_permissions
"""

import uuid
import pytest
from unittest.mock import MagicMock, patch

from src.models.role import Role, RolePermission, ROLE_TEMPLATES, seed_roles_for_tenant, seed_global_super_admin_role
from src.models.user_role_assignment import UserRoleAssignment
from src.models.user import User
from src.models.tenant import Tenant
from src.models.user_tenant_roles import UserTenantRole
from src.services.rbac import (
    resolve_permissions_for_user,
    user_has_permission,
    user_has_any_permission,
)
from src.constants.permissions import Permission


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def tenant_a_id():
    return str(uuid.uuid4())


@pytest.fixture
def tenant_b_id():
    return str(uuid.uuid4())


@pytest.fixture
def user_a_id():
    return str(uuid.uuid4())


@pytest.fixture
def user_b_id():
    return str(uuid.uuid4())


@pytest.fixture
def sample_tenant_a(db_session, tenant_a_id):
    tenant = Tenant(id=tenant_a_id, name="Store A", billing_tier="enterprise")
    db_session.add(tenant)
    db_session.flush()
    return tenant


@pytest.fixture
def sample_tenant_b(db_session, tenant_b_id):
    tenant = Tenant(id=tenant_b_id, name="Store B", billing_tier="growth")
    db_session.add(tenant)
    db_session.flush()
    return tenant


@pytest.fixture
def sample_user_a(db_session, user_a_id):
    user = User(id=user_a_id, clerk_user_id=f"clerk_{user_a_id[:8]}", email="alice@test.com")
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def sample_user_b(db_session, user_b_id):
    user = User(id=user_b_id, clerk_user_id=f"clerk_{user_b_id[:8]}", email="bob@test.com")
    db_session.add(user)
    db_session.flush()
    return user


def _create_role(db_session, tenant_id, slug, permissions, is_system=False):
    """Helper to create a role with permissions."""
    role = Role(
        tenant_id=tenant_id,
        name=slug.replace("_", " ").title(),
        slug=slug,
        is_system=is_system,
    )
    db_session.add(role)
    db_session.flush()
    for perm in permissions:
        rp = RolePermission(role_id=role.id, permission=perm)
        db_session.add(rp)
    db_session.flush()
    return role


def _assign_role(db_session, user_id, role_id, tenant_id, source="admin_grant"):
    """Helper to assign a role to a user."""
    assignment = UserRoleAssignment(
        user_id=user_id,
        role_id=role_id,
        tenant_id=tenant_id,
        source=source,
    )
    db_session.add(assignment)
    db_session.flush()
    return assignment


# ============================================================================
# TestDefaultDeny
# ============================================================================


class TestDefaultDeny:
    """Default deny: no permissions if no matching roles found."""

    def test_no_assignments_returns_empty(self, db_session, sample_user_a, sample_tenant_a):
        """User with no role assignments gets zero permissions."""
        perms = resolve_permissions_for_user(db_session, sample_user_a.id, sample_tenant_a.id)
        assert perms == set()

    def test_user_has_permission_returns_false_when_none(self, db_session, sample_user_a, sample_tenant_a):
        """user_has_permission returns False with no assignments."""
        assert user_has_permission(db_session, sample_user_a.id, sample_tenant_a.id, "analytics:view") is False

    def test_inactive_assignments_excluded(self, db_session, sample_user_a, sample_tenant_a):
        """Inactive assignments are not counted."""
        role = _create_role(db_session, sample_tenant_a.id, "test_role", ["analytics:view"])
        assignment = _assign_role(db_session, sample_user_a.id, role.id, sample_tenant_a.id)
        assignment.is_active = False
        db_session.flush()

        perms = resolve_permissions_for_user(db_session, sample_user_a.id, sample_tenant_a.id)
        assert perms == set()

    def test_inactive_role_excluded(self, db_session, sample_user_a, sample_tenant_a):
        """Inactive roles are not counted even if assignment is active."""
        role = _create_role(db_session, sample_tenant_a.id, "dead_role", ["analytics:view"])
        role.is_active = False
        db_session.flush()
        _assign_role(db_session, sample_user_a.id, role.id, sample_tenant_a.id)

        perms = resolve_permissions_for_user(db_session, sample_user_a.id, sample_tenant_a.id)
        assert perms == set()

    def test_inactive_permission_excluded(self, db_session, sample_user_a, sample_tenant_a):
        """Inactive permission rows are not counted."""
        role = _create_role(db_session, sample_tenant_a.id, "partial_role", ["analytics:view", "billing:view"])
        # Deactivate one permission
        for rp in role.permissions:
            if rp.permission == "billing:view":
                rp.is_active = False
        db_session.flush()
        _assign_role(db_session, sample_user_a.id, role.id, sample_tenant_a.id)

        perms = resolve_permissions_for_user(db_session, sample_user_a.id, sample_tenant_a.id)
        assert "analytics:view" in perms
        assert "billing:view" not in perms


# ============================================================================
# TestDataDrivenPermissions
# ============================================================================


class TestDataDrivenPermissions:
    """Permissions resolved from UserRoleAssignment -> Role -> RolePermission."""

    def test_single_role_permissions(self, db_session, sample_user_a, sample_tenant_a):
        """User with one role gets that role's permissions."""
        role = _create_role(db_session, sample_tenant_a.id, "viewer", ["analytics:view", "store:view"])
        _assign_role(db_session, sample_user_a.id, role.id, sample_tenant_a.id)

        perms = resolve_permissions_for_user(db_session, sample_user_a.id, sample_tenant_a.id)
        assert perms == {"analytics:view", "store:view"}

    def test_multiple_roles_union(self, db_session, sample_user_a, sample_tenant_a):
        """Multiple roles produce a union of permissions."""
        role1 = _create_role(db_session, sample_tenant_a.id, "analyst", ["analytics:view", "analytics:export"])
        role2 = _create_role(db_session, sample_tenant_a.id, "manager", ["team:manage", "billing:manage"])
        _assign_role(db_session, sample_user_a.id, role1.id, sample_tenant_a.id)
        _assign_role(db_session, sample_user_a.id, role2.id, sample_tenant_a.id)

        perms = resolve_permissions_for_user(db_session, sample_user_a.id, sample_tenant_a.id)
        assert perms == {"analytics:view", "analytics:export", "team:manage", "billing:manage"}

    def test_user_has_permission_true(self, db_session, sample_user_a, sample_tenant_a):
        """user_has_permission returns True when permission exists."""
        role = _create_role(db_session, sample_tenant_a.id, "viewer", ["analytics:view"])
        _assign_role(db_session, sample_user_a.id, role.id, sample_tenant_a.id)

        assert user_has_permission(db_session, sample_user_a.id, sample_tenant_a.id, "analytics:view") is True
        assert user_has_permission(db_session, sample_user_a.id, sample_tenant_a.id, "billing:manage") is False

    def test_user_has_any_permission(self, db_session, sample_user_a, sample_tenant_a):
        """user_has_any_permission returns True if any match."""
        role = _create_role(db_session, sample_tenant_a.id, "viewer", ["analytics:view"])
        _assign_role(db_session, sample_user_a.id, role.id, sample_tenant_a.id)

        assert user_has_any_permission(
            db_session, sample_user_a.id, sample_tenant_a.id,
            ["analytics:view", "billing:manage"]
        ) is True
        assert user_has_any_permission(
            db_session, sample_user_a.id, sample_tenant_a.id,
            ["billing:manage", "team:manage"]
        ) is False


# ============================================================================
# TestLegacyFallback
# ============================================================================


class TestLegacyFallback:
    """Permissions resolved from UserTenantRole -> ROLE_PERMISSIONS matrix."""

    def test_legacy_role_resolves_via_matrix(self, db_session, sample_user_a, sample_tenant_a):
        """Legacy UserTenantRole roles resolve via hardcoded ROLE_PERMISSIONS."""
        legacy_role = UserTenantRole(
            user_id=sample_user_a.id,
            tenant_id=sample_tenant_a.id,
            role="MERCHANT_VIEWER",
            source="clerk_webhook",
            is_active=True,
        )
        db_session.add(legacy_role)
        db_session.flush()

        perms = resolve_permissions_for_user(db_session, sample_user_a.id, sample_tenant_a.id)
        # MERCHANT_VIEWER should have at least analytics:view
        assert "analytics:view" in perms
        assert "store:view" in perms
        # But not admin permissions
        assert "billing:manage" not in perms

    def test_inactive_legacy_role_excluded(self, db_session, sample_user_a, sample_tenant_a):
        """Inactive legacy roles are not counted."""
        legacy_role = UserTenantRole(
            user_id=sample_user_a.id,
            tenant_id=sample_tenant_a.id,
            role="MERCHANT_ADMIN",
            source="clerk_webhook",
            is_active=False,
        )
        db_session.add(legacy_role)
        db_session.flush()

        perms = resolve_permissions_for_user(db_session, sample_user_a.id, sample_tenant_a.id)
        assert perms == set()


# ============================================================================
# TestDualSourceResolution
# ============================================================================


class TestDualSourceResolution:
    """Union of data-driven + legacy permissions."""

    def test_union_of_both_sources(self, db_session, sample_user_a, sample_tenant_a):
        """Permissions from both sources are combined."""
        # Data-driven: custom role with billing:manage
        custom_role = _create_role(db_session, sample_tenant_a.id, "billing_manager", ["billing:manage"])
        _assign_role(db_session, sample_user_a.id, custom_role.id, sample_tenant_a.id)

        # Legacy: MERCHANT_VIEWER (has analytics:view, store:view, etc.)
        legacy_role = UserTenantRole(
            user_id=sample_user_a.id,
            tenant_id=sample_tenant_a.id,
            role="MERCHANT_VIEWER",
            source="clerk_webhook",
            is_active=True,
        )
        db_session.add(legacy_role)
        db_session.flush()

        perms = resolve_permissions_for_user(db_session, sample_user_a.id, sample_tenant_a.id)
        # Should have both custom and legacy permissions
        assert "billing:manage" in perms  # from custom role
        assert "analytics:view" in perms  # from legacy MERCHANT_VIEWER


# ============================================================================
# TestTenantIsolation
# ============================================================================


class TestTenantIsolation:
    """Multi-tenant user sees different permissions per tenant."""

    def test_user_different_roles_per_tenant(
        self, db_session, sample_user_a, sample_tenant_a, sample_tenant_b
    ):
        """Same user gets different permissions in different tenants."""
        # Admin in tenant A
        admin_role = _create_role(
            db_session, sample_tenant_a.id, "admin",
            ["analytics:view", "billing:manage", "team:manage"]
        )
        _assign_role(db_session, sample_user_a.id, admin_role.id, sample_tenant_a.id)

        # Viewer in tenant B
        viewer_role = _create_role(
            db_session, sample_tenant_b.id, "viewer",
            ["analytics:view"]
        )
        _assign_role(db_session, sample_user_a.id, viewer_role.id, sample_tenant_b.id)

        perms_a = resolve_permissions_for_user(db_session, sample_user_a.id, sample_tenant_a.id)
        perms_b = resolve_permissions_for_user(db_session, sample_user_a.id, sample_tenant_b.id)

        assert "billing:manage" in perms_a
        assert "billing:manage" not in perms_b
        assert "analytics:view" in perms_a
        assert "analytics:view" in perms_b

    def test_no_cross_tenant_leakage(
        self, db_session, sample_user_a, sample_tenant_a, sample_tenant_b
    ):
        """Permissions in tenant A do not leak to tenant B."""
        role = _create_role(
            db_session, sample_tenant_a.id, "secret_role",
            ["admin:system:config"]
        )
        _assign_role(db_session, sample_user_a.id, role.id, sample_tenant_a.id)

        perms_b = resolve_permissions_for_user(db_session, sample_user_a.id, sample_tenant_b.id)
        assert "admin:system:config" not in perms_b


# ============================================================================
# TestSeedFunctions
# ============================================================================


class TestSeedFunctions:
    """Tests for role seeding."""

    def test_seed_roles_for_tenant(self, db_session, sample_tenant_a):
        """seed_roles_for_tenant creates roles with correct permissions."""
        roles = seed_roles_for_tenant(db_session, sample_tenant_a.id)
        db_session.flush()

        slugs = {r.slug for r in roles}
        # All non-super_admin templates should be created
        assert "merchant_admin" in slugs
        assert "merchant_viewer" in slugs
        assert "agency_admin" in slugs
        assert "agency_viewer" in slugs
        assert "analyst" in slugs
        # super_admin is global, not per-tenant
        assert "super_admin" not in slugs

        # Verify permissions were created
        for role in roles:
            template = ROLE_TEMPLATES[role.slug]
            assert len(role.permissions) == len(template["permissions"])
            assert role.is_system is True
            assert role.tenant_id == sample_tenant_a.id

    def test_seed_global_super_admin(self, db_session):
        """seed_global_super_admin_role creates a global role with NULL tenant_id."""
        role = seed_global_super_admin_role(db_session)
        db_session.flush()

        assert role.tenant_id is None
        assert role.slug == "super_admin"
        assert role.is_system is True
        assert len(role.permissions) > 0

    def test_seed_global_super_admin_idempotent(self, db_session):
        """Calling seed_global_super_admin_role twice returns the same role."""
        role1 = seed_global_super_admin_role(db_session)
        db_session.flush()
        role2 = seed_global_super_admin_role(db_session)
        db_session.flush()

        assert role1.id == role2.id

    def test_seed_specific_templates(self, db_session, sample_tenant_a):
        """Can seed only specific templates."""
        roles = seed_roles_for_tenant(
            db_session, sample_tenant_a.id,
            templates=["merchant_admin", "merchant_viewer"]
        )
        db_session.flush()

        slugs = {r.slug for r in roles}
        assert slugs == {"merchant_admin", "merchant_viewer"}


# ============================================================================
# TestResolvedPermissionsIntegration
# ============================================================================


class TestResolvedPermissionsIntegration:
    """Test has_permission/has_any_permission with resolved_permissions on TenantContext."""

    def test_resolved_permissions_used_when_present(self):
        """RBAC decorators use resolved_permissions when available."""
        from src.platform.rbac import has_permission, has_any_permission, has_all_permissions
        from src.platform.tenant_context import TenantContext

        ctx = TenantContext(
            tenant_id="t1",
            user_id="u1",
            roles=["merchant_viewer"],
            org_id="org1",
            resolved_permissions={"analytics:view", "store:view"},
        )

        # These should use resolved_permissions, not the hardcoded matrix
        assert has_permission(ctx, Permission.ANALYTICS_VIEW) is True
        assert has_permission(ctx, Permission.BILLING_MANAGE) is False
        assert has_any_permission(ctx, [Permission.ANALYTICS_VIEW, Permission.BILLING_MANAGE]) is True
        assert has_any_permission(ctx, [Permission.BILLING_MANAGE]) is False
        assert has_all_permissions(ctx, [Permission.ANALYTICS_VIEW, Permission.STORE_VIEW]) is True
        assert has_all_permissions(ctx, [Permission.ANALYTICS_VIEW, Permission.BILLING_MANAGE]) is False

    def test_falls_back_to_hardcoded_when_none(self):
        """RBAC decorators fall back to hardcoded matrix when resolved_permissions is None."""
        from src.platform.rbac import has_permission
        from src.platform.tenant_context import TenantContext

        ctx = TenantContext(
            tenant_id="t1",
            user_id="u1",
            roles=["merchant_viewer"],
            org_id="org1",
            resolved_permissions=None,
        )

        # merchant_viewer has analytics:view in hardcoded matrix
        assert has_permission(ctx, Permission.ANALYTICS_VIEW) is True
        # merchant_viewer does NOT have billing:manage
        assert has_permission(ctx, Permission.BILLING_MANAGE) is False

    def test_empty_resolved_permissions_denies_all(self):
        """Empty set means default deny for all permissions."""
        from src.platform.rbac import has_permission
        from src.platform.tenant_context import TenantContext

        ctx = TenantContext(
            tenant_id="t1",
            user_id="u1",
            roles=["merchant_admin"],  # Would have perms via hardcoded matrix
            org_id="org1",
            resolved_permissions=set(),  # But empty resolved_permissions takes precedence
        )

        # Even though merchant_admin has analytics:view in hardcoded matrix,
        # empty resolved_permissions means default deny
        assert has_permission(ctx, Permission.ANALYTICS_VIEW) is False


# ============================================================================
# TestRoleModel
# ============================================================================


class TestRoleModel:
    """Tests for Role model properties."""

    def test_permission_strings(self, db_session, sample_tenant_a):
        """Role.permission_strings returns active permission strings."""
        role = _create_role(db_session, sample_tenant_a.id, "test_role", ["analytics:view", "billing:view"])
        assert set(role.permission_strings) == {"analytics:view", "billing:view"}

    def test_has_permission(self, db_session, sample_tenant_a):
        """Role.has_permission checks against permission_strings."""
        role = _create_role(db_session, sample_tenant_a.id, "test_role", ["analytics:view"])
        assert role.has_permission("analytics:view") is True
        assert role.has_permission("billing:manage") is False

    def test_repr(self, db_session, sample_tenant_a):
        """Role repr includes scope info."""
        role = _create_role(db_session, sample_tenant_a.id, "test_role", [])
        assert "tenant=" in repr(role)

    def test_global_role_repr(self, db_session):
        """Global role repr shows 'global'."""
        role = Role(name="Global", slug="global_test", tenant_id=None)
        assert "global" in repr(role)


# ============================================================================
# TestUserRoleAssignment
# ============================================================================


class TestUserRoleAssignment:
    """Tests for UserRoleAssignment model."""

    def test_create_from_approval(self):
        """Factory method sets correct source."""
        assignment = UserRoleAssignment.create_from_approval(
            user_id="u1", role_id="r1", tenant_id="t1", assigned_by="admin1"
        )
        assert assignment.source == "agency_approval"
        assert assignment.assigned_by == "admin1"

    def test_create_from_admin(self):
        """Factory method sets correct source."""
        assignment = UserRoleAssignment.create_from_admin(
            user_id="u1", role_id="r1", tenant_id="t1", assigned_by="admin1"
        )
        assert assignment.source == "admin_grant"

    def test_deactivate_reactivate(self, db_session, sample_user_a, sample_tenant_a):
        """Deactivate and reactivate work correctly."""
        role = _create_role(db_session, sample_tenant_a.id, "test", ["analytics:view"])
        assignment = _assign_role(db_session, sample_user_a.id, role.id, sample_tenant_a.id)

        assert assignment.is_active is True
        assignment.deactivate()
        assert assignment.is_active is False
        assignment.reactivate(reactivated_by="admin2")
        assert assignment.is_active is True
        assert assignment.assigned_by == "admin2"
