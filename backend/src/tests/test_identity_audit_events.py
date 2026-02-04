"""
Tests for identity audit events.

Tests cover:
- IdentityAuditEmitter service methods
- Event emission with correct metadata
- Correlation ID tracking
- No PII in metadata (clerk_user_id only, never email)
- Source and reason validation
- Integration with ClerkSyncService
"""

import uuid
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from src.audit.identity_events import IdentityAuditEmitter
from src.platform.audit import (
    AuditAction,
    AuditEvent,
    AuditLog,
    AuditOutcome,
)
from src.platform.audit_events import (
    AUDITABLE_EVENTS,
    EVENT_CATEGORIES,
    EVENT_SEVERITY,
    validate_event_metadata,
)
from src.db_base import Base


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock(spec=Session)
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.flush = MagicMock()
    return session


@pytest.fixture
def correlation_id():
    """Fixed correlation ID for testing."""
    return "test-corr-id-12345"


@pytest.fixture
def identity_emitter(mock_db_session, correlation_id):
    """Create an IdentityAuditEmitter with mocked dependencies."""
    with patch('src.audit.identity_events.write_audit_log_sync') as mock_write:
        mock_write.return_value = MagicMock(spec=AuditLog)
        emitter = IdentityAuditEmitter(
            db=mock_db_session,
            correlation_id=correlation_id,
        )
        emitter._mock_write = mock_write
        yield emitter


# =============================================================================
# Test Suite: Event Schema Registry
# =============================================================================

class TestIdentityEventSchemas:
    """Test that identity events are properly registered in the event schema."""

    def test_identity_events_in_auditable_events(self):
        """All identity events must be registered in AUDITABLE_EVENTS."""
        identity_events = [
            "identity.user_first_seen",
            "identity.user_linked_to_tenant",
            "identity.role_assigned",
            "identity.role_revoked",
            "identity.tenant_created",
            "identity.tenant_deactivated",
        ]

        for event in identity_events:
            assert event in AUDITABLE_EVENTS, f"Event {event} not registered"

    def test_identity_events_in_category(self):
        """All identity events must be in the identity category."""
        assert "identity" in EVENT_CATEGORIES
        expected_events = [
            "identity.user_first_seen",
            "identity.user_linked_to_tenant",
            "identity.role_assigned",
            "identity.role_revoked",
            "identity.tenant_created",
            "identity.tenant_deactivated",
        ]
        for event in expected_events:
            assert event in EVENT_CATEGORIES["identity"]

    def test_identity_events_have_severity(self):
        """All identity events must have severity levels."""
        identity_events = EVENT_CATEGORIES["identity"]
        for event in identity_events:
            assert event in EVENT_SEVERITY, f"Event {event} missing severity"

    def test_user_first_seen_required_fields(self):
        """user_first_seen must require clerk_user_id and source."""
        required = AUDITABLE_EVENTS["identity.user_first_seen"]
        assert "clerk_user_id" in required
        assert "source" in required

    def test_role_assigned_required_fields(self):
        """role_assigned must require proper audit trail fields."""
        required = AUDITABLE_EVENTS["identity.role_assigned"]
        assert "clerk_user_id" in required
        assert "tenant_id" in required
        assert "role" in required
        assert "assigned_by" in required
        assert "source" in required

    def test_role_revoked_required_fields(self):
        """role_revoked must require proper audit trail fields."""
        required = AUDITABLE_EVENTS["identity.role_revoked"]
        assert "clerk_user_id" in required
        assert "tenant_id" in required
        assert "previous_role" in required
        assert "revoked_by" in required
        assert "reason" in required

    def test_tenant_created_required_fields(self):
        """tenant_created must require proper fields."""
        required = AUDITABLE_EVENTS["identity.tenant_created"]
        assert "tenant_id" in required
        assert "clerk_org_id" in required
        assert "billing_tier" in required
        assert "source" in required

    def test_tenant_deactivated_required_fields(self):
        """tenant_deactivated must require proper fields."""
        required = AUDITABLE_EVENTS["identity.tenant_deactivated"]
        assert "tenant_id" in required
        assert "clerk_org_id" in required
        assert "reason" in required

    def test_no_email_in_required_fields(self):
        """SECURITY: No identity event should require email as a field."""
        for event_type in EVENT_CATEGORIES["identity"]:
            required_fields = AUDITABLE_EVENTS[event_type]
            assert "email" not in required_fields, f"Event {event_type} should not require email"


# =============================================================================
# Test Suite: IdentityAuditEmitter
# =============================================================================

class TestIdentityAuditEmitter:
    """Test the IdentityAuditEmitter service."""

    def test_emitter_creates_with_correlation_id(self, mock_db_session):
        """Emitter stores provided correlation_id."""
        emitter = IdentityAuditEmitter(
            db=mock_db_session,
            correlation_id="my-custom-corr-id",
        )
        assert emitter.correlation_id == "my-custom-corr-id"

    def test_emitter_generates_correlation_id_if_missing(self, mock_db_session):
        """Emitter generates correlation_id if not provided."""
        emitter = IdentityAuditEmitter(db=mock_db_session)
        assert emitter.correlation_id is not None
        assert len(emitter.correlation_id) == 36  # UUID format


class TestEmitUserFirstSeen:
    """Test emit_user_first_seen method."""

    def test_emit_user_first_seen_webhook(self, identity_emitter, correlation_id):
        """Test emitting user_first_seen from webhook."""
        result = identity_emitter.emit_user_first_seen(
            clerk_user_id="user_clerk_123",
            source="webhook",
        )

        assert result == correlation_id
        identity_emitter._mock_write.assert_called_once()

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]  # Second positional arg is the event

        assert event.action == AuditAction.IDENTITY_USER_FIRST_SEEN
        assert event.correlation_id == correlation_id
        assert event.metadata["clerk_user_id"] == "user_clerk_123"
        assert event.metadata["source"] == "webhook"
        assert "email" not in event.metadata

    def test_emit_user_first_seen_lazy_sync(self, identity_emitter, correlation_id):
        """Test emitting user_first_seen from lazy_sync."""
        result = identity_emitter.emit_user_first_seen(
            clerk_user_id="user_clerk_456",
            source="lazy_sync",
        )

        assert result == correlation_id
        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]

        assert event.metadata["source"] == "lazy_sync"
        assert event.source == "api"  # lazy_sync maps to api source

    def test_emit_user_first_seen_invalid_source(self, identity_emitter):
        """Test that invalid source raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            identity_emitter.emit_user_first_seen(
                clerk_user_id="user_123",
                source="invalid_source",
            )
        assert "Invalid source" in str(exc_info.value)

    def test_emit_user_first_seen_with_tenant_id(self, identity_emitter):
        """Test emitting user_first_seen with tenant context."""
        identity_emitter.emit_user_first_seen(
            clerk_user_id="user_123",
            source="webhook",
            tenant_id="tenant_abc",
        )

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]
        assert event.tenant_id == "tenant_abc"


class TestEmitUserLinkedToTenant:
    """Test emit_user_linked_to_tenant method."""

    def test_emit_user_linked_to_tenant(self, identity_emitter, correlation_id):
        """Test emitting user_linked_to_tenant event."""
        result = identity_emitter.emit_user_linked_to_tenant(
            clerk_user_id="user_clerk_123",
            tenant_id="tenant_abc",
            role="MERCHANT_ADMIN",
            source="clerk_webhook",
        )

        assert result == correlation_id

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]

        assert event.action == AuditAction.IDENTITY_USER_LINKED_TO_TENANT
        assert event.tenant_id == "tenant_abc"
        assert event.metadata["clerk_user_id"] == "user_clerk_123"
        assert event.metadata["tenant_id"] == "tenant_abc"
        assert event.metadata["role"] == "MERCHANT_ADMIN"
        assert event.metadata["source"] == "clerk_webhook"
        assert "email" not in event.metadata

    def test_emit_user_linked_to_tenant_invalid_source(self, identity_emitter):
        """Test that invalid source raises ValueError."""
        with pytest.raises(ValueError):
            identity_emitter.emit_user_linked_to_tenant(
                clerk_user_id="user_123",
                tenant_id="tenant_abc",
                role="MERCHANT_ADMIN",
                source="invalid_source",
            )


class TestEmitRoleAssigned:
    """Test emit_role_assigned method."""

    def test_emit_role_assigned_clerk_webhook(self, identity_emitter, correlation_id):
        """Test emitting role_assigned from Clerk webhook."""
        result = identity_emitter.emit_role_assigned(
            clerk_user_id="user_clerk_123",
            tenant_id="tenant_abc",
            role="MERCHANT_ADMIN",
            assigned_by="system",
            source="clerk_webhook",
        )

        assert result == correlation_id

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]

        assert event.action == AuditAction.IDENTITY_ROLE_ASSIGNED
        assert event.metadata["clerk_user_id"] == "user_clerk_123"
        assert event.metadata["role"] == "MERCHANT_ADMIN"
        assert event.metadata["assigned_by"] == "system"
        assert event.metadata["source"] == "clerk_webhook"
        assert event.source == "webhook"

    def test_emit_role_assigned_agency_grant(self, identity_emitter):
        """Test emitting role_assigned from agency grant."""
        identity_emitter.emit_role_assigned(
            clerk_user_id="user_clerk_456",
            tenant_id="tenant_xyz",
            role="MERCHANT_VIEWER",
            assigned_by="admin_user_789",
            source="agency_grant",
        )

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]

        assert event.metadata["assigned_by"] == "admin_user_789"
        assert event.metadata["source"] == "agency_grant"
        assert event.source == "api"

    def test_emit_role_assigned_invalid_source(self, identity_emitter):
        """Test that invalid source raises ValueError."""
        with pytest.raises(ValueError):
            identity_emitter.emit_role_assigned(
                clerk_user_id="user_123",
                tenant_id="tenant_abc",
                role="MERCHANT_ADMIN",
                assigned_by="system",
                source="invalid_source",
            )


class TestEmitRoleRevoked:
    """Test emit_role_revoked method."""

    def test_emit_role_revoked_membership_deleted(self, identity_emitter, correlation_id):
        """Test emitting role_revoked when membership is deleted."""
        result = identity_emitter.emit_role_revoked(
            clerk_user_id="user_clerk_123",
            tenant_id="tenant_abc",
            previous_role="MERCHANT_ADMIN",
            revoked_by="system",
            reason="membership_deleted",
        )

        assert result == correlation_id

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]

        assert event.action == AuditAction.IDENTITY_ROLE_REVOKED
        assert event.metadata["clerk_user_id"] == "user_clerk_123"
        assert event.metadata["previous_role"] == "MERCHANT_ADMIN"
        assert event.metadata["revoked_by"] == "system"
        assert event.metadata["reason"] == "membership_deleted"
        assert event.source == "webhook"

    def test_emit_role_revoked_admin_action(self, identity_emitter):
        """Test emitting role_revoked for admin action."""
        identity_emitter.emit_role_revoked(
            clerk_user_id="user_clerk_456",
            tenant_id="tenant_xyz",
            previous_role="MERCHANT_VIEWER",
            revoked_by="admin_user_789",
            reason="admin_action",
        )

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]

        assert event.metadata["reason"] == "admin_action"
        assert event.source == "api"

    def test_emit_role_revoked_invalid_reason(self, identity_emitter):
        """Test that invalid reason raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            identity_emitter.emit_role_revoked(
                clerk_user_id="user_123",
                tenant_id="tenant_abc",
                previous_role="MERCHANT_ADMIN",
                revoked_by="system",
                reason="invalid_reason",
            )
        assert "Invalid reason" in str(exc_info.value)


class TestEmitTenantCreated:
    """Test emit_tenant_created method."""

    def test_emit_tenant_created_webhook(self, identity_emitter, correlation_id):
        """Test emitting tenant_created from Clerk webhook."""
        result = identity_emitter.emit_tenant_created(
            tenant_id="tenant_new_123",
            clerk_org_id="org_clerk_456",
            billing_tier="free",
            source="clerk_webhook",
        )

        assert result == correlation_id

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]

        assert event.action == AuditAction.IDENTITY_TENANT_CREATED
        assert event.tenant_id == "tenant_new_123"
        assert event.user_id is None  # System-level event
        assert event.metadata["tenant_id"] == "tenant_new_123"
        assert event.metadata["clerk_org_id"] == "org_clerk_456"
        assert event.metadata["billing_tier"] == "free"
        assert event.metadata["source"] == "clerk_webhook"
        assert event.source == "webhook"

    def test_emit_tenant_created_admin_action(self, identity_emitter):
        """Test emitting tenant_created from admin action."""
        identity_emitter.emit_tenant_created(
            tenant_id="tenant_789",
            clerk_org_id="org_xyz",
            billing_tier="growth",
            source="admin_action",
        )

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]

        assert event.metadata["billing_tier"] == "growth"
        assert event.source == "system"

    def test_emit_tenant_created_invalid_source(self, identity_emitter):
        """Test that invalid source raises ValueError."""
        with pytest.raises(ValueError):
            identity_emitter.emit_tenant_created(
                tenant_id="tenant_123",
                clerk_org_id="org_456",
                billing_tier="free",
                source="invalid_source",
            )


class TestEmitTenantDeactivated:
    """Test emit_tenant_deactivated method."""

    def test_emit_tenant_deactivated_org_deleted(self, identity_emitter, correlation_id):
        """Test emitting tenant_deactivated when org is deleted."""
        result = identity_emitter.emit_tenant_deactivated(
            tenant_id="tenant_123",
            clerk_org_id="org_456",
            reason="org_deleted",
        )

        assert result == correlation_id

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]

        assert event.action == AuditAction.IDENTITY_TENANT_DEACTIVATED
        assert event.tenant_id == "tenant_123"
        assert event.user_id is None  # System-level event
        assert event.metadata["tenant_id"] == "tenant_123"
        assert event.metadata["clerk_org_id"] == "org_456"
        assert event.metadata["reason"] == "org_deleted"
        assert event.source == "webhook"

    def test_emit_tenant_deactivated_admin_action(self, identity_emitter):
        """Test emitting tenant_deactivated for admin action."""
        identity_emitter.emit_tenant_deactivated(
            tenant_id="tenant_789",
            clerk_org_id="org_xyz",
            reason="admin_action",
        )

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]

        assert event.metadata["reason"] == "admin_action"
        assert event.source == "system"

    def test_emit_tenant_deactivated_billing(self, identity_emitter):
        """Test emitting tenant_deactivated for billing issues."""
        identity_emitter.emit_tenant_deactivated(
            tenant_id="tenant_abc",
            clerk_org_id="org_def",
            reason="billing",
        )

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]

        assert event.metadata["reason"] == "billing"

    def test_emit_tenant_deactivated_invalid_reason(self, identity_emitter):
        """Test that invalid reason raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            identity_emitter.emit_tenant_deactivated(
                tenant_id="tenant_123",
                clerk_org_id="org_456",
                reason="invalid_reason",
            )
        assert "Invalid reason" in str(exc_info.value)


# =============================================================================
# Test Suite: Metadata Compliance
# =============================================================================

class TestMetadataCompliance:
    """Test that event metadata complies with security requirements."""

    def test_no_pii_in_user_first_seen(self, identity_emitter):
        """SECURITY: user_first_seen must not contain PII."""
        identity_emitter.emit_user_first_seen(
            clerk_user_id="user_123",
            source="webhook",
        )

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]
        metadata = event.metadata

        # Check no PII fields
        pii_fields = ["email", "phone", "name", "first_name", "last_name", "address"]
        for field in pii_fields:
            assert field not in metadata, f"PII field {field} found in metadata"

        # Ensure we use clerk_user_id
        assert "clerk_user_id" in metadata

    def test_no_pii_in_role_assigned(self, identity_emitter):
        """SECURITY: role_assigned must not contain PII."""
        identity_emitter.emit_role_assigned(
            clerk_user_id="user_123",
            tenant_id="tenant_abc",
            role="MERCHANT_ADMIN",
            assigned_by="admin_456",
            source="clerk_webhook",
        )

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]
        metadata = event.metadata

        pii_fields = ["email", "phone", "name", "first_name", "last_name", "address"]
        for field in pii_fields:
            assert field not in metadata, f"PII field {field} found in metadata"

    def test_correlation_id_always_present(self, identity_emitter, correlation_id):
        """All events must include correlation_id."""
        # Test all event types
        identity_emitter.emit_user_first_seen("user_1", "webhook")
        identity_emitter.emit_user_linked_to_tenant("user_1", "tenant_1", "ADMIN", "clerk_webhook")
        identity_emitter.emit_role_assigned("user_1", "tenant_1", "ADMIN", "system", "clerk_webhook")
        identity_emitter.emit_role_revoked("user_1", "tenant_1", "ADMIN", "system", "membership_deleted")
        identity_emitter.emit_tenant_created("tenant_1", "org_1", "free", "clerk_webhook")
        identity_emitter.emit_tenant_deactivated("tenant_1", "org_1", "org_deleted")

        # All 6 calls should have correlation_id
        assert identity_emitter._mock_write.call_count == 6

        for call in identity_emitter._mock_write.call_args_list:
            event = call[0][1]
            assert event.correlation_id == correlation_id

    def test_metadata_validates_against_schema(self, identity_emitter):
        """Event metadata should pass schema validation."""
        identity_emitter.emit_role_assigned(
            clerk_user_id="user_123",
            tenant_id="tenant_abc",
            role="MERCHANT_ADMIN",
            assigned_by="system",
            source="clerk_webhook",
        )

        call_args = identity_emitter._mock_write.call_args
        event = call_args[0][1]
        metadata = event.metadata

        # Validate against schema
        is_valid, missing = validate_event_metadata(
            "identity.role_assigned",
            metadata,
        )
        assert is_valid, f"Missing fields: {missing}"


# =============================================================================
# Test Suite: AuditAction Enum
# =============================================================================

class TestAuditActionEnum:
    """Test that identity AuditActions are properly defined."""

    def test_identity_audit_actions_exist(self):
        """All identity audit actions must exist in the enum."""
        assert hasattr(AuditAction, 'IDENTITY_USER_FIRST_SEEN')
        assert hasattr(AuditAction, 'IDENTITY_USER_LINKED_TO_TENANT')
        assert hasattr(AuditAction, 'IDENTITY_ROLE_ASSIGNED')
        assert hasattr(AuditAction, 'IDENTITY_ROLE_REVOKED')
        assert hasattr(AuditAction, 'IDENTITY_TENANT_CREATED')
        assert hasattr(AuditAction, 'IDENTITY_TENANT_DEACTIVATED')

    def test_identity_audit_action_values(self):
        """Identity audit action values follow naming convention."""
        assert AuditAction.IDENTITY_USER_FIRST_SEEN.value == "identity.user_first_seen"
        assert AuditAction.IDENTITY_USER_LINKED_TO_TENANT.value == "identity.user_linked_to_tenant"
        assert AuditAction.IDENTITY_ROLE_ASSIGNED.value == "identity.role_assigned"
        assert AuditAction.IDENTITY_ROLE_REVOKED.value == "identity.role_revoked"
        assert AuditAction.IDENTITY_TENANT_CREATED.value == "identity.tenant_created"
        assert AuditAction.IDENTITY_TENANT_DEACTIVATED.value == "identity.tenant_deactivated"
