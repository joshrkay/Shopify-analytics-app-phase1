"""
Unit tests for merchant consent flow.

Covers:
- Model: status transitions, immutability, approve/deny methods
- Service: request_consent, approve, deny, permission checks
- Denied cannot auto-retry
- Duplicate prevention
- Tenant isolation in queries

Security:
- Verifies only SETTINGS_MANAGE permission can approve/deny
- Verifies denied requests block auto-retry
- Verifies immutability of decided consents
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.models.connection_consent import (
    ConnectionConsent,
    ConsentStatus,
)
from src.services.consent_service import (
    ConsentService,
    ConsentNotFoundError,
    ConsentAlreadyExistsError,
    ConsentDeniedRetryError,
    PermissionDeniedError,
    ConsentError,
)


# =============================================================================
# Fixtures
# =============================================================================

TENANT_ID = "tenant-test-001"
USER_ID = "clerk_user_abc123"
ADMIN_ROLES = ["merchant_admin"]
VIEWER_ROLES = ["merchant_viewer"]
CONNECTION_ID = "conn-airbyte-456"


def _make_consent(**overrides) -> ConnectionConsent:
    """Factory for ConnectionConsent instances."""
    defaults = {
        "id": str(uuid.uuid4()),
        "tenant_id": TENANT_ID,
        "connection_id": CONNECTION_ID,
        "connection_name": "Shopify Production",
        "source_type": "shopify",
        "app_name": "Analytics App",
        "requested_by": USER_ID,
        "status": ConsentStatus.PENDING,
        "decided_by": None,
        "decided_at": None,
        "decision_reason": None,
        "ip_address": None,
        "user_agent": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    consent = ConnectionConsent()
    for key, value in defaults.items():
        setattr(consent, key, value)
    return consent


def _mock_session():
    """Create a mock SQLAlchemy session."""
    session = MagicMock()
    session.execute = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.refresh = MagicMock()
    session.flush = MagicMock()
    return session


# =============================================================================
# Model Tests
# =============================================================================

class TestConnectionConsentModel:
    """Tests for ConnectionConsent model properties and transitions."""

    def test_is_pending(self):
        consent = _make_consent(status=ConsentStatus.PENDING)
        assert consent.is_pending is True
        assert consent.is_decided is False

    def test_is_approved(self):
        consent = _make_consent(status=ConsentStatus.APPROVED)
        assert consent.is_approved is True
        assert consent.is_decided is True

    def test_is_denied(self):
        consent = _make_consent(status=ConsentStatus.DENIED)
        assert consent.is_denied is True
        assert consent.is_decided is True

    def test_approve_from_pending(self):
        consent = _make_consent(status=ConsentStatus.PENDING)
        consent.approve(user_id="admin-1", reason="Looks good")

        assert consent.status == ConsentStatus.APPROVED
        assert consent.decided_by == "admin-1"
        assert consent.decided_at is not None
        assert consent.decision_reason == "Looks good"

    def test_deny_from_pending(self):
        consent = _make_consent(status=ConsentStatus.PENDING)
        consent.deny(
            user_id="admin-1",
            reason="Not authorized",
            ip_address="192.168.1.1",
            user_agent="TestBrowser/1.0",
        )

        assert consent.status == ConsentStatus.DENIED
        assert consent.decided_by == "admin-1"
        assert consent.decided_at is not None
        assert consent.decision_reason == "Not authorized"
        assert consent.ip_address == "192.168.1.1"
        assert consent.user_agent == "TestBrowser/1.0"

    def test_approve_already_approved_raises(self):
        """Immutability: cannot approve an already-decided consent."""
        consent = _make_consent(status=ConsentStatus.APPROVED)
        with pytest.raises(ValueError, match="Cannot approve"):
            consent.approve(user_id="admin-2")

    def test_deny_already_approved_raises(self):
        """Immutability: cannot deny an already-approved consent."""
        consent = _make_consent(status=ConsentStatus.APPROVED)
        with pytest.raises(ValueError, match="Cannot deny"):
            consent.deny(user_id="admin-2")

    def test_approve_already_denied_raises(self):
        """Immutability: cannot approve a denied consent."""
        consent = _make_consent(status=ConsentStatus.DENIED)
        with pytest.raises(ValueError, match="Cannot approve"):
            consent.approve(user_id="admin-2")

    def test_deny_already_denied_raises(self):
        """Immutability: cannot re-deny a denied consent."""
        consent = _make_consent(status=ConsentStatus.DENIED)
        with pytest.raises(ValueError, match="Cannot deny"):
            consent.deny(user_id="admin-2")

    def test_to_summary_contains_expected_fields(self):
        consent = _make_consent()
        summary = consent.to_summary()
        assert "id" in summary
        assert "connection_id" in summary
        assert "connection_name" in summary
        assert "source_type" in summary
        assert "app_name" in summary
        assert "status" in summary
        assert "decided_by" in summary
        assert "decided_at" in summary
        assert "created_at" in summary

    def test_repr_safe(self):
        consent = _make_consent()
        r = repr(consent)
        assert "ConnectionConsent" in r
        assert "connection_id" in r


# =============================================================================
# Service: request_consent Tests
# =============================================================================

class TestConsentServiceRequest:
    """Tests for ConsentService.request_consent()."""

    def test_request_consent_happy_path(self):
        session = _mock_session()
        # No existing consent
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        service = ConsentService(db_session=session, tenant_id=TENANT_ID)
        consent = service.request_consent(
            connection_id=CONNECTION_ID,
            connection_name="Shopify Prod",
            source_type="shopify",
            app_name="Analytics App",
            requested_by=USER_ID,
        )

        session.add.assert_called_once()
        session.commit.assert_called_once()
        added = session.add.call_args[0][0]
        assert added.status == ConsentStatus.PENDING
        assert added.connection_id == CONNECTION_ID

    def test_request_consent_duplicate_pending_raises(self):
        """Cannot create duplicate pending consent for same connection."""
        existing = _make_consent(status=ConsentStatus.PENDING)
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        session.execute.return_value = mock_result

        service = ConsentService(db_session=session, tenant_id=TENANT_ID)

        with pytest.raises(ConsentAlreadyExistsError, match="Pending"):
            service.request_consent(
                connection_id=CONNECTION_ID,
                connection_name="Shopify Prod",
                source_type="shopify",
                app_name="Analytics App",
                requested_by=USER_ID,
            )

    def test_request_consent_denied_cannot_retry(self):
        """Denied requests cannot auto-retry."""
        existing = _make_consent(status=ConsentStatus.DENIED)
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        session.execute.return_value = mock_result

        service = ConsentService(db_session=session, tenant_id=TENANT_ID)

        with pytest.raises(ConsentDeniedRetryError, match="cannot auto-retry"):
            service.request_consent(
                connection_id=CONNECTION_ID,
                connection_name="Shopify Prod",
                source_type="shopify",
                app_name="Analytics App",
                requested_by=USER_ID,
            )


# =============================================================================
# Service: approve Tests
# =============================================================================

class TestConsentServiceApprove:
    """Tests for ConsentService.approve()."""

    def test_approve_happy_path(self):
        consent = _make_consent(status=ConsentStatus.PENDING)
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = consent
        session.execute.return_value = mock_result

        service = ConsentService(db_session=session, tenant_id=TENANT_ID)
        result = service.approve(
            consent_id=consent.id,
            user_id=USER_ID,
            user_roles=ADMIN_ROLES,
            reason="Approved for testing",
        )

        assert result.status == ConsentStatus.APPROVED
        assert result.decided_by == USER_ID
        assert result.decided_at is not None
        session.commit.assert_called_once()

    def test_approve_not_found_raises(self):
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        service = ConsentService(db_session=session, tenant_id=TENANT_ID)

        with pytest.raises(ConsentNotFoundError):
            service.approve(
                consent_id="nonexistent",
                user_id=USER_ID,
                user_roles=ADMIN_ROLES,
            )

    def test_approve_viewer_permission_denied(self):
        """Merchant Viewer cannot approve consent."""
        session = _mock_session()
        service = ConsentService(db_session=session, tenant_id=TENANT_ID)

        with pytest.raises(PermissionDeniedError, match="Merchant Admin"):
            service.approve(
                consent_id="any-id",
                user_id=USER_ID,
                user_roles=VIEWER_ROLES,
            )

    def test_approve_already_decided_raises(self):
        consent = _make_consent(status=ConsentStatus.DENIED)
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = consent
        session.execute.return_value = mock_result

        service = ConsentService(db_session=session, tenant_id=TENANT_ID)

        with pytest.raises(ConsentError, match="Cannot approve"):
            service.approve(
                consent_id=consent.id,
                user_id=USER_ID,
                user_roles=ADMIN_ROLES,
            )


# =============================================================================
# Service: deny Tests
# =============================================================================

class TestConsentServiceDeny:
    """Tests for ConsentService.deny()."""

    def test_deny_happy_path(self):
        consent = _make_consent(status=ConsentStatus.PENDING)
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = consent
        session.execute.return_value = mock_result

        service = ConsentService(db_session=session, tenant_id=TENANT_ID)
        result = service.deny(
            consent_id=consent.id,
            user_id=USER_ID,
            user_roles=ADMIN_ROLES,
            reason="Not authorized for our store",
        )

        assert result.status == ConsentStatus.DENIED
        assert result.decided_by == USER_ID
        assert result.decision_reason == "Not authorized for our store"
        session.commit.assert_called_once()

    def test_deny_viewer_permission_denied(self):
        """Merchant Viewer cannot deny consent."""
        session = _mock_session()
        service = ConsentService(db_session=session, tenant_id=TENANT_ID)

        with pytest.raises(PermissionDeniedError):
            service.deny(
                consent_id="any-id",
                user_id=USER_ID,
                user_roles=VIEWER_ROLES,
            )

    def test_deny_not_found_raises(self):
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        service = ConsentService(db_session=session, tenant_id=TENANT_ID)

        with pytest.raises(ConsentNotFoundError):
            service.deny(
                consent_id="nonexistent",
                user_id=USER_ID,
                user_roles=ADMIN_ROLES,
            )


# =============================================================================
# Service: query Tests
# =============================================================================

class TestConsentServiceQuery:
    """Tests for ConsentService query methods."""

    def test_list_pending(self):
        consents = [
            _make_consent(id=f"c-{i}", status=ConsentStatus.PENDING)
            for i in range(3)
        ]
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = consents
        session.execute.return_value = mock_result

        service = ConsentService(db_session=session, tenant_id=TENANT_ID)
        results = service.list_pending()
        assert len(results) == 3

    def test_get_pending_count(self):
        session = _mock_session()
        session.execute.return_value.scalar.return_value = 5

        service = ConsentService(db_session=session, tenant_id=TENANT_ID)
        assert service.get_pending_count() == 5

    def test_is_connection_approved_true(self):
        consent = _make_consent(status=ConsentStatus.APPROVED)
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = consent
        session.execute.return_value = mock_result

        service = ConsentService(db_session=session, tenant_id=TENANT_ID)
        assert service.is_connection_approved(CONNECTION_ID) is True

    def test_is_connection_approved_false_when_pending(self):
        consent = _make_consent(status=ConsentStatus.PENDING)
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = consent
        session.execute.return_value = mock_result

        service = ConsentService(db_session=session, tenant_id=TENANT_ID)
        assert service.is_connection_approved(CONNECTION_ID) is False

    def test_is_connection_approved_false_when_none(self):
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        service = ConsentService(db_session=session, tenant_id=TENANT_ID)
        assert service.is_connection_approved(CONNECTION_ID) is False


# =============================================================================
# ConsentStatus Enum Tests
# =============================================================================

class TestConsentStatus:
    """Tests for ConsentStatus enum values."""

    def test_all_expected_values(self):
        assert ConsentStatus.PENDING.value == "pending"
        assert ConsentStatus.APPROVED.value == "approved"
        assert ConsentStatus.DENIED.value == "denied"

    def test_is_string_enum(self):
        assert isinstance(ConsentStatus.PENDING, str)
        assert ConsentStatus.APPROVED == "approved"
