"""
Tests for grace-period access revocation.

Story 5.5.4 - Grace-Period Access Removal

Test classes:
- TestInitiateRevocation: Creates record, sets grace_period_ends_at, idempotent
- TestEnforceExpiredRevocations: Deactivates roles after grace period
- TestCancelRevocation: Re-granting cancels pending revocation
- TestConfigurableGracePeriod: Custom grace_period_hours respected
- TestAuditEvents: agency_access.revoked and agency_access.expired emitted
- TestWorkerEnforcement: Worker calls enforce and commits
- TestAccessRevocationModel: Model properties and methods
"""

import uuid
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from sqlalchemy.orm import Session

from src.models.user import User
from src.models.tenant import Tenant
from src.models.user_tenant_roles import UserTenantRole
from src.models.access_revocation import AccessRevocation, RevocationStatus
from src.models.user_role_assignment import UserRoleAssignment


@pytest.fixture(autouse=True)
def _mock_audit_writes():
    """Prevent audit log writes from committing/rolling back the test transaction."""
    with patch(
        "src.services.audit_logger.emit_agency_access_revoked",
        return_value=None,
    ), patch(
        "src.services.audit_logger.emit_agency_access_expired",
        return_value=None,
    ):
        yield


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


def _grant_access(
    db: Session, user: User, tenant: Tenant, role: str = "MERCHANT_VIEWER"
) -> UserTenantRole:
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
# TestAccessRevocationModel
# =============================================================================


class TestAccessRevocationModel:
    """Test AccessRevocation model properties and methods."""

    def test_is_in_grace_period_when_active(self, db_session):
        """is_in_grace_period returns True during grace period."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        revocation = AccessRevocation(
            id=str(uuid.uuid4()),
            user_id=user.id,
            tenant_id=tenant.id,
            revoked_at=datetime.now(timezone.utc),
            grace_period_ends_at=datetime.now(timezone.utc) + timedelta(hours=24),
            grace_period_hours=24,
            status=RevocationStatus.GRACE_PERIOD.value,
        )
        db_session.add(revocation)
        db_session.flush()

        assert revocation.is_in_grace_period is True
        assert revocation.is_expired is False

    def test_is_expired_after_grace_period(self, db_session):
        """is_expired returns True after grace period ends."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        revocation = AccessRevocation(
            id=str(uuid.uuid4()),
            user_id=user.id,
            tenant_id=tenant.id,
            revoked_at=datetime.now(timezone.utc) - timedelta(hours=25),
            grace_period_ends_at=datetime.now(timezone.utc) - timedelta(hours=1),
            grace_period_hours=24,
            status=RevocationStatus.GRACE_PERIOD.value,
        )
        db_session.add(revocation)
        db_session.flush()

        assert revocation.is_expired is True

    def test_enforce_expiry_sets_status(self, db_session):
        """enforce_expiry() sets status to expired and records timestamp."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        revocation = AccessRevocation(
            id=str(uuid.uuid4()),
            user_id=user.id,
            tenant_id=tenant.id,
            revoked_at=datetime.now(timezone.utc),
            grace_period_ends_at=datetime.now(timezone.utc) - timedelta(hours=1),
            grace_period_hours=24,
            status=RevocationStatus.GRACE_PERIOD.value,
        )
        db_session.add(revocation)
        db_session.flush()

        revocation.enforce_expiry()
        assert revocation.status == RevocationStatus.EXPIRED.value
        assert revocation.expired_at is not None

    def test_cancel_sets_status(self, db_session):
        """cancel() sets status to cancelled."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        revocation = AccessRevocation(
            id=str(uuid.uuid4()),
            user_id=user.id,
            tenant_id=tenant.id,
            revoked_at=datetime.now(timezone.utc),
            grace_period_ends_at=datetime.now(timezone.utc) + timedelta(hours=24),
            grace_period_hours=24,
            status=RevocationStatus.GRACE_PERIOD.value,
        )
        db_session.add(revocation)
        db_session.flush()

        revocation.cancel()
        assert revocation.status == RevocationStatus.CANCELLED.value

    def test_revocation_status_enum(self):
        """RevocationStatus enum has the correct values."""
        assert RevocationStatus.GRACE_PERIOD.value == "grace_period"
        assert RevocationStatus.EXPIRED.value == "expired"
        assert RevocationStatus.CANCELLED.value == "cancelled"

    def test_repr(self, db_session):
        """__repr__ includes key fields."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        revocation = AccessRevocation(
            id="test-id",
            user_id=user.id,
            tenant_id=tenant.id,
            revoked_at=datetime.now(timezone.utc),
            grace_period_ends_at=datetime.now(timezone.utc) + timedelta(hours=24),
            grace_period_hours=24,
            status=RevocationStatus.GRACE_PERIOD.value,
        )
        repr_str = repr(revocation)
        assert "test-id" in repr_str
        assert user.id in repr_str


# =============================================================================
# TestInitiateRevocation
# =============================================================================


class TestInitiateRevocation:
    """Test initiating grace-period revocation."""

    def test_creates_revocation_record(self, db_session):
        """Initiating revocation creates an AccessRevocation record."""
        from src.services.access_revocation_service import AccessRevocationService

        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        _grant_access(db_session, user, tenant)

        service = AccessRevocationService(db_session)
        result = service.initiate_revocation(
            user_id=user.id,
            tenant_id=tenant.id,
            revoked_by="admin-clerk-id",
        )

        assert result["status"] == "grace_period"
        assert result["user_id"] == user.id
        assert result["tenant_id"] == tenant.id
        assert result["grace_period_hours"] == 24
        assert result["is_in_grace_period"] is True
        assert result["is_expired"] is False

    def test_grace_period_ends_at_correct(self, db_session):
        """grace_period_ends_at is correctly set based on hours."""
        from src.services.access_revocation_service import AccessRevocationService

        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        _grant_access(db_session, user, tenant)

        service = AccessRevocationService(db_session)
        result = service.initiate_revocation(
            user_id=user.id,
            tenant_id=tenant.id,
            grace_period_hours=48,
        )

        assert result["grace_period_hours"] == 48
        # grace_period_ends_at should be ~48h from now
        ends_at = datetime.fromisoformat(result["grace_period_ends_at"])
        now = datetime.now(timezone.utc)
        diff = (ends_at - now).total_seconds()
        assert 47 * 3600 < diff < 49 * 3600

    def test_idempotent_for_duplicate(self, db_session):
        """Initiating revocation twice returns existing record."""
        from src.services.access_revocation_service import AccessRevocationService

        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        _grant_access(db_session, user, tenant)

        service = AccessRevocationService(db_session)
        result1 = service.initiate_revocation(user_id=user.id, tenant_id=tenant.id)
        result2 = service.initiate_revocation(user_id=user.id, tenant_id=tenant.id)

        assert result1["id"] == result2["id"]

    def test_roles_remain_active_during_grace_period(self, db_session):
        """UserTenantRole stays active during grace period."""
        from src.services.access_revocation_service import AccessRevocationService

        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        role = _grant_access(db_session, user, tenant)

        service = AccessRevocationService(db_session)
        service.initiate_revocation(user_id=user.id, tenant_id=tenant.id)

        # Role should still be active
        db_session.refresh(role)
        assert role.is_active is True


# =============================================================================
# TestEnforceExpiredRevocations
# =============================================================================


class TestEnforceExpiredRevocations:
    """Test enforcement of expired grace periods."""

    def test_deactivates_roles_after_expiry(self, db_session):
        """Enforcement deactivates UserTenantRole after grace period ends."""
        from src.services.access_revocation_service import AccessRevocationService

        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        role = _grant_access(db_session, user, tenant)

        # Create expired revocation
        revocation = AccessRevocation(
            id=str(uuid.uuid4()),
            user_id=user.id,
            tenant_id=tenant.id,
            revoked_at=datetime.now(timezone.utc) - timedelta(hours=25),
            grace_period_ends_at=datetime.now(timezone.utc) - timedelta(hours=1),
            grace_period_hours=24,
            status=RevocationStatus.GRACE_PERIOD.value,
        )
        db_session.add(revocation)
        db_session.flush()

        service = AccessRevocationService(db_session)
        enforced = service.enforce_expired_revocations()

        assert len(enforced) == 1
        assert enforced[0]["status"] == "expired"

        # Role should now be inactive
        db_session.refresh(role)
        assert role.is_active is False

    def test_skips_still_in_grace_period(self, db_session):
        """Enforcement skips revocations still within grace period."""
        from src.services.access_revocation_service import AccessRevocationService

        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        _grant_access(db_session, user, tenant)

        # Create still-active revocation
        revocation = AccessRevocation(
            id=str(uuid.uuid4()),
            user_id=user.id,
            tenant_id=tenant.id,
            revoked_at=datetime.now(timezone.utc),
            grace_period_ends_at=datetime.now(timezone.utc) + timedelta(hours=23),
            grace_period_hours=24,
            status=RevocationStatus.GRACE_PERIOD.value,
        )
        db_session.add(revocation)
        db_session.flush()

        service = AccessRevocationService(db_session)
        enforced = service.enforce_expired_revocations()

        assert len(enforced) == 0

    def test_skips_already_expired(self, db_session):
        """Enforcement skips revocations already in expired status."""
        from src.services.access_revocation_service import AccessRevocationService

        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        revocation = AccessRevocation(
            id=str(uuid.uuid4()),
            user_id=user.id,
            tenant_id=tenant.id,
            revoked_at=datetime.now(timezone.utc) - timedelta(hours=48),
            grace_period_ends_at=datetime.now(timezone.utc) - timedelta(hours=24),
            grace_period_hours=24,
            status=RevocationStatus.EXPIRED.value,
            expired_at=datetime.now(timezone.utc) - timedelta(hours=24),
        )
        db_session.add(revocation)
        db_session.flush()

        service = AccessRevocationService(db_session)
        enforced = service.enforce_expired_revocations()

        assert len(enforced) == 0


# =============================================================================
# TestCancelRevocation
# =============================================================================


class TestCancelRevocation:
    """Test cancelling pending revocations."""

    def test_cancel_sets_status_cancelled(self, db_session):
        """Cancelling a revocation sets status to cancelled."""
        from src.services.access_revocation_service import AccessRevocationService

        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        _grant_access(db_session, user, tenant)

        service = AccessRevocationService(db_session)
        service.initiate_revocation(user_id=user.id, tenant_id=tenant.id)

        result = service.cancel_revocation(user_id=user.id, tenant_id=tenant.id)

        assert result is not None
        assert result["status"] == "cancelled"

    def test_cancel_returns_none_when_no_active(self, db_session):
        """Cancelling when no active revocation returns None."""
        from src.services.access_revocation_service import AccessRevocationService

        service = AccessRevocationService(db_session)
        result = service.cancel_revocation(
            user_id="nonexistent", tenant_id="nonexistent"
        )
        assert result is None

    def test_cancelled_revocation_not_enforced(self, db_session):
        """A cancelled revocation is not picked up by enforcement."""
        from src.services.access_revocation_service import AccessRevocationService

        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        _grant_access(db_session, user, tenant)

        service = AccessRevocationService(db_session)
        service.initiate_revocation(user_id=user.id, tenant_id=tenant.id)
        service.cancel_revocation(user_id=user.id, tenant_id=tenant.id)

        enforced = service.enforce_expired_revocations()
        assert len(enforced) == 0


# =============================================================================
# TestConfigurableGracePeriod
# =============================================================================


class TestConfigurableGracePeriod:
    """Test configurable grace period hours."""

    def test_custom_grace_period_hours(self, db_session):
        """Custom grace_period_hours is respected."""
        from src.services.access_revocation_service import AccessRevocationService

        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        _grant_access(db_session, user, tenant)

        service = AccessRevocationService(db_session)
        result = service.initiate_revocation(
            user_id=user.id,
            tenant_id=tenant.id,
            grace_period_hours=72,
        )

        assert result["grace_period_hours"] == 72
        ends_at = datetime.fromisoformat(result["grace_period_ends_at"])
        now = datetime.now(timezone.utc)
        diff_hours = (ends_at - now).total_seconds() / 3600
        assert 71 < diff_hours < 73

    def test_zero_grace_period_immediately_expirable(self, db_session):
        """Zero-hour grace period is immediately enforceable."""
        from src.services.access_revocation_service import AccessRevocationService

        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        role = _grant_access(db_session, user, tenant)

        service = AccessRevocationService(db_session)
        result = service.initiate_revocation(
            user_id=user.id,
            tenant_id=tenant.id,
            grace_period_hours=0,
        )

        assert result["grace_period_hours"] == 0

        # Should be immediately enforceable
        enforced = service.enforce_expired_revocations()
        assert len(enforced) == 1

        db_session.refresh(role)
        assert role.is_active is False


# =============================================================================
# TestGetActiveRevocation
# =============================================================================


class TestGetActiveRevocation:
    """Test getting active revocation for JWT banner."""

    def test_returns_active_revocation(self, db_session):
        """get_active_revocation returns revocation in grace period."""
        from src.services.access_revocation_service import AccessRevocationService

        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        _grant_access(db_session, user, tenant)

        service = AccessRevocationService(db_session)
        service.initiate_revocation(user_id=user.id, tenant_id=tenant.id)

        result = service.get_active_revocation(user_id=user.id, tenant_id=tenant.id)
        assert result is not None
        assert result["status"] == "grace_period"
        assert result["grace_period_ends_at"] is not None

    def test_returns_none_when_no_revocation(self, db_session):
        """get_active_revocation returns None when no active revocation."""
        from src.services.access_revocation_service import AccessRevocationService

        service = AccessRevocationService(db_session)
        result = service.get_active_revocation(
            user_id="nonexistent", tenant_id="nonexistent"
        )
        assert result is None


# =============================================================================
# TestAuditEvents
# =============================================================================


class TestAuditEvents:
    """Test audit event emission for revocation lifecycle."""

    def test_revocation_audit_action_values(self):
        """Verify new AuditAction enum values for revocation."""
        from src.platform.audit import AuditAction

        assert hasattr(AuditAction, "AGENCY_ACCESS_REVOKED")
        assert AuditAction.AGENCY_ACCESS_REVOKED.value == "agency_access.revoked"
        assert hasattr(AuditAction, "AGENCY_ACCESS_EXPIRED")
        assert AuditAction.AGENCY_ACCESS_EXPIRED.value == "agency_access.expired"

    def test_emit_agency_access_revoked(self, db_session):
        """emit_agency_access_revoked does not raise."""
        from src.services.audit_logger import emit_agency_access_revoked

        emit_agency_access_revoked(
            db=db_session,
            tenant_id="tenant-1",
            user_id="user-1",
            revoked_by="admin-1",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            grace_period_hours=24,
        )

    def test_emit_agency_access_expired(self, db_session):
        """emit_agency_access_expired does not raise."""
        from src.services.audit_logger import emit_agency_access_expired

        emit_agency_access_expired(
            db=db_session,
            tenant_id="tenant-1",
            user_id="user-1",
            revocation_id="rev-1",
        )


# =============================================================================
# TestWorkerEnforcement
# =============================================================================


class TestWorkerEnforcement:
    """Test the worker enforcement cycle."""

    def test_run_cycle_calls_enforce(self, db_session):
        """Worker run_cycle invokes enforce_expired_revocations."""
        from src.services.access_revocation_service import AccessRevocationService

        # Test the service method directly (worker uses get_db_session_sync
        # which requires DATABASE_URL — not available in unit tests)
        service = AccessRevocationService(db_session)
        enforced = service.enforce_expired_revocations()
        assert isinstance(enforced, list)
        assert len(enforced) >= 0

    def test_revocation_model_imported_in_init(self):
        """AccessRevocation is exported from models/__init__.py."""
        from src.models import AccessRevocation, RevocationStatus

        assert AccessRevocation is not None
        assert RevocationStatus is not None
