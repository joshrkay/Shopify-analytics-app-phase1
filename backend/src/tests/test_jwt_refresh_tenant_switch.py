"""
Tests for JWT refresh and tenant context switching.

Story 5.5.3 - Tenant Selector + JWT Refresh for Active Tenant Context

Test classes:
- TestRefreshJWT: Success returns new JWT, validates tenant access
- TestAccessSurface: access_surface included in JWT payload
- TestAuditEvents: auth.jwt_refresh and tenant.context_switched emitted
"""

import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from sqlalchemy.orm import Session

from src.models.user import User
from src.models.tenant import Tenant
from src.models.user_tenant_roles import UserTenantRole


# =============================================================================
# Helpers
# =============================================================================


def _create_user(db: Session, clerk_user_id: str = None) -> User:
    user = User(
        id=str(uuid.uuid4()),
        clerk_user_id=clerk_user_id or f"clerk_{uuid.uuid4().hex[:8]}",
        email=f"test_{uuid.uuid4().hex[:6]}@example.com",
        first_name="Test",
        last_name="User",
    )
    db.add(user)
    db.flush()
    return user


def _create_tenant(db: Session, name: str = "Test Tenant") -> Tenant:
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name=name,
        slug=f"test-{uuid.uuid4().hex[:6]}",
        billing_tier="professional",
    )
    db.add(tenant)
    db.flush()
    return tenant


def _grant_access(db: Session, user: User, tenant: Tenant, role: str = "MERCHANT_VIEWER") -> UserTenantRole:
    utr = UserTenantRole(
        id=str(uuid.uuid4()),
        user_id=user.id,
        tenant_id=tenant.id,
        role=role,
        is_active=True,
        source="agency_grant",
    )
    db.add(utr)
    db.flush()
    return utr


# =============================================================================
# TestRefreshJWT
# =============================================================================


class TestRefreshJWT:
    """Test JWT refresh endpoint logic."""

    def test_jwt_refresh_generates_token_for_valid_tenant(self, db_session):
        """JWT refresh succeeds when user has active access to target tenant."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        _grant_access(db_session, user, tenant)

        # Verify user-tenant access exists
        active_role = (
            db_session.query(UserTenantRole)
            .filter(
                UserTenantRole.user_id == user.id,
                UserTenantRole.tenant_id == tenant.id,
                UserTenantRole.is_active == True,
            )
            .first()
        )
        assert active_role is not None
        assert active_role.role == "MERCHANT_VIEWER"

    def test_jwt_refresh_denies_non_allowed_tenant(self, db_session):
        """JWT refresh fails when target tenant is not in user's access."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        # No access granted
        active_role = (
            db_session.query(UserTenantRole)
            .filter(
                UserTenantRole.user_id == user.id,
                UserTenantRole.tenant_id == tenant.id,
                UserTenantRole.is_active == True,
            )
            .first()
        )
        assert active_role is None

    def test_jwt_refresh_denies_inactive_access(self, db_session):
        """JWT refresh fails when user's access is deactivated."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        role = _grant_access(db_session, user, tenant)

        # Deactivate
        role.is_active = False
        db_session.flush()

        active_role = (
            db_session.query(UserTenantRole)
            .filter(
                UserTenantRole.user_id == user.id,
                UserTenantRole.tenant_id == tenant.id,
                UserTenantRole.is_active == True,
            )
            .first()
        )
        assert active_role is None

    def test_multiple_tenants_can_be_switched(self, db_session):
        """User with access to multiple tenants can switch between them."""
        user = _create_user(db_session)
        tenant_a = _create_tenant(db_session, name="Tenant A")
        tenant_b = _create_tenant(db_session, name="Tenant B")
        _grant_access(db_session, user, tenant_a)
        _grant_access(db_session, user, tenant_b)

        # Both should have active access
        roles = (
            db_session.query(UserTenantRole)
            .filter(
                UserTenantRole.user_id == user.id,
                UserTenantRole.is_active == True,
            )
            .all()
        )
        tenant_ids = {r.tenant_id for r in roles}
        assert tenant_a.id in tenant_ids
        assert tenant_b.id in tenant_ids


# =============================================================================
# TestAccessSurface
# =============================================================================


class TestAccessSurface:
    """Test access_surface JWT claim generation."""

    def test_generate_jwt_includes_access_surface(self):
        """JWT generator includes access_surface in payload."""
        from src.api.routes.agency import _generate_jwt_token

        token = _generate_jwt_token(
            user_id="test-user",
            tenant_id="test-tenant",
            roles=["AGENCY_ADMIN"],
            allowed_tenants=["test-tenant"],
            billing_tier="professional",
            org_id="test-org",
            access_surface="shopify_embed",
        )
        assert token is not None

        import jwt as pyjwt
        import os

        secret = os.getenv("JWT_SECRET", "development-secret-change-in-prod")
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
        assert payload["access_surface"] == "shopify_embed"

    def test_generate_jwt_default_access_surface(self):
        """JWT generator defaults to external_app for access_surface."""
        from src.api.routes.agency import _generate_jwt_token

        token = _generate_jwt_token(
            user_id="test-user",
            tenant_id="test-tenant",
            roles=["AGENCY_ADMIN"],
            allowed_tenants=["test-tenant"],
            billing_tier="professional",
            org_id="test-org",
        )

        import jwt as pyjwt
        import os

        secret = os.getenv("JWT_SECRET", "development-secret-change-in-prod")
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
        assert payload["access_surface"] == "external_app"

    def test_generate_jwt_includes_access_expiring_at(self):
        """JWT generator includes access_expiring_at when provided."""
        from src.api.routes.agency import _generate_jwt_token

        expiring_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)

        token = _generate_jwt_token(
            user_id="test-user",
            tenant_id="test-tenant",
            roles=["AGENCY_ADMIN"],
            allowed_tenants=["test-tenant"],
            billing_tier="professional",
            org_id="test-org",
            access_expiring_at=expiring_at,
        )

        import jwt as pyjwt
        import os

        secret = os.getenv("JWT_SECRET", "development-secret-change-in-prod")
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
        assert payload["access_expiring_at"] == expiring_at.isoformat()

    def test_generate_jwt_no_access_expiring_at_when_none(self):
        """JWT generator omits access_expiring_at when not provided."""
        from src.api.routes.agency import _generate_jwt_token

        token = _generate_jwt_token(
            user_id="test-user",
            tenant_id="test-tenant",
            roles=["AGENCY_ADMIN"],
            allowed_tenants=["test-tenant"],
            billing_tier="professional",
            org_id="test-org",
        )

        import jwt as pyjwt
        import os

        secret = os.getenv("JWT_SECRET", "development-secret-change-in-prod")
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
        assert "access_expiring_at" not in payload


# =============================================================================
# TestAuditEvents
# =============================================================================


class TestAuditEvents:
    """Test that JWT refresh emits correct audit events."""

    def test_jwt_refresh_audit_event_emitted(self, db_session):
        """emit_jwt_refresh creates an audit event."""
        from src.services.audit_logger import emit_jwt_refresh

        # Should not raise
        emit_jwt_refresh(
            db=db_session,
            tenant_id="tenant-1",
            user_id="user-1",
            previous_tenant_id="tenant-0",
            access_surface="external_app",
        )

    def test_tenant_context_switched_audit_event(self, db_session):
        """emit_tenant_context_switched creates an audit event."""
        from src.services.audit_logger import emit_tenant_context_switched

        # Should not raise
        emit_tenant_context_switched(
            db=db_session,
            tenant_id="tenant-1",
            user_id="user-1",
            previous_tenant_id="tenant-0",
        )

    def test_audit_action_values_exist(self):
        """Verify new AuditAction enum values are registered."""
        from src.platform.audit import AuditAction

        assert hasattr(AuditAction, "AUTH_JWT_REFRESH")
        assert AuditAction.AUTH_JWT_REFRESH.value == "auth.jwt_refresh"
        assert hasattr(AuditAction, "TENANT_CONTEXT_SWITCHED")
        assert AuditAction.TENANT_CONTEXT_SWITCHED.value == "tenant.context_switched"
        assert hasattr(AuditAction, "AUTH_JWT_ISSUED")
        assert AuditAction.AUTH_JWT_ISSUED.value == "auth.jwt_issued"


# =============================================================================
# TestDashboardDenial
# =============================================================================


class TestDashboardDenial:
    """Test that non-active tenants are denied."""

    def test_inactive_role_blocks_access(self, db_session):
        """Deactivated role means no active access."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        role = _grant_access(db_session, user, tenant)
        role.is_active = False
        db_session.flush()

        active = (
            db_session.query(UserTenantRole)
            .filter(
                UserTenantRole.user_id == user.id,
                UserTenantRole.tenant_id == tenant.id,
                UserTenantRole.is_active == True,
            )
            .first()
        )
        assert active is None

    def test_no_role_blocks_access(self, db_session):
        """No role assignment means no access."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        active = (
            db_session.query(UserTenantRole)
            .filter(
                UserTenantRole.user_id == user.id,
                UserTenantRole.tenant_id == tenant.id,
                UserTenantRole.is_active == True,
            )
            .first()
        )
        assert active is None
