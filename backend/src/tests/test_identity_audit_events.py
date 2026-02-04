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


# =============================================================================
# Test Suite: End-to-End Integration Tests
# =============================================================================
# These tests verify the complete flow through ClerkSyncService with audit
# event emission for realistic identity lifecycle scenarios.

class TestEndToEndTenantLifecycle:
    """
    End-to-end tests for tenant lifecycle with audit events.

    Tests the complete flow:
    1. Tenant created from Clerk org
    2. Tenant deactivated
    """

    @pytest.fixture
    def mock_tenant(self):
        """Create a mock Tenant object."""
        tenant = MagicMock()
        tenant.id = "tenant_e2e_123"
        tenant.clerk_org_id = "org_clerk_e2e_456"
        tenant.name = "E2E Test Org"
        tenant.billing_tier = "free"
        return tenant

    @pytest.fixture
    def clerk_sync_service_mocked(self, mock_db_session, mock_tenant):
        """Create ClerkSyncService with mocked dependencies for e2e tests."""
        from src.services.clerk_sync_service import ClerkSyncService

        # Mock the query chain for tenant lookup
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = None  # No existing tenant (for creation)
        mock_query.filter.return_value = mock_filter
        mock_db_session.query.return_value = mock_query

        with patch('src.audit.identity_events.write_audit_log_sync') as mock_write:
            mock_write.return_value = MagicMock(spec=AuditLog)
            service = ClerkSyncService(
                session=mock_db_session,
                correlation_id="e2e-corr-tenant-lifecycle",
            )
            service._mock_write = mock_write
            service._mock_tenant = mock_tenant
            yield service

    def test_tenant_creation_emits_audit_event(self, clerk_sync_service_mocked, mock_tenant):
        """E2E: Tenant creation via Clerk org emits tenant_created event."""
        # Simulate tenant doesn't exist yet, then gets created
        mock_query = clerk_sync_service_mocked.session.query.return_value
        mock_query.filter.return_value.first.return_value = None

        # Mock the Tenant class to return our mock
        with patch('src.services.clerk_sync_service.Tenant') as MockTenant:
            MockTenant.return_value = mock_tenant

            tenant = clerk_sync_service_mocked.sync_tenant_from_org(
                clerk_org_id="org_clerk_e2e_456",
                name="E2E Test Org",
                billing_tier="free",
                source="clerk_webhook",
            )

        # Verify audit event was emitted
        assert clerk_sync_service_mocked._mock_write.called

        # Find the tenant_created event
        calls = clerk_sync_service_mocked._mock_write.call_args_list
        tenant_created_events = [
            c for c in calls
            if c[0][1].action == AuditAction.IDENTITY_TENANT_CREATED
        ]

        assert len(tenant_created_events) == 1
        event = tenant_created_events[0][0][1]
        assert event.metadata["clerk_org_id"] == "org_clerk_e2e_456"
        assert event.metadata["billing_tier"] == "free"
        assert event.metadata["source"] == "clerk_webhook"
        assert event.correlation_id == "e2e-corr-tenant-lifecycle"

    def test_tenant_deactivation_emits_audit_event(self, clerk_sync_service_mocked, mock_tenant):
        """E2E: Tenant deactivation emits tenant_deactivated event."""
        # Simulate tenant exists
        mock_query = clerk_sync_service_mocked.session.query.return_value
        mock_query.filter.return_value.first.return_value = mock_tenant

        result = clerk_sync_service_mocked.deactivate_tenant(
            clerk_org_id="org_clerk_e2e_456",
            reason="org_deleted",
        )

        assert result is True

        # Find the tenant_deactivated event
        calls = clerk_sync_service_mocked._mock_write.call_args_list
        deactivated_events = [
            c for c in calls
            if c[0][1].action == AuditAction.IDENTITY_TENANT_DEACTIVATED
        ]

        assert len(deactivated_events) == 1
        event = deactivated_events[0][0][1]
        assert event.metadata["tenant_id"] == "tenant_e2e_123"
        assert event.metadata["reason"] == "org_deleted"


class TestEndToEndUserLifecycle:
    """
    End-to-end tests for user lifecycle with audit events.

    Tests the complete flow:
    1. User first seen (created from Clerk)
    2. User linked to tenant (membership created)
    3. Role assigned
    4. Role revoked (user removed from tenant)
    """

    @pytest.fixture
    def mock_user(self):
        """Create a mock User object."""
        user = MagicMock()
        user.id = "user_internal_123"
        user.clerk_user_id = "user_clerk_e2e_789"
        user.email = "test@example.com"
        user.is_active = True
        return user

    @pytest.fixture
    def mock_tenant(self):
        """Create a mock Tenant object."""
        tenant = MagicMock()
        tenant.id = "tenant_e2e_abc"
        tenant.clerk_org_id = "org_clerk_e2e_def"
        return tenant

    @pytest.fixture
    def mock_user_tenant_role(self, mock_user, mock_tenant):
        """Create a mock UserTenantRole object."""
        role = MagicMock()
        role.id = "role_123"
        role.user_id = mock_user.id
        role.tenant_id = mock_tenant.id
        role.role = "MERCHANT_ADMIN"
        role.is_active = True
        return role

    @pytest.fixture
    def clerk_sync_service_for_user(self, mock_db_session, mock_user, mock_tenant, mock_user_tenant_role):
        """Create ClerkSyncService with mocked dependencies for user e2e tests."""
        from src.services.clerk_sync_service import ClerkSyncService

        with patch('src.audit.identity_events.write_audit_log_sync') as mock_write:
            mock_write.return_value = MagicMock(spec=AuditLog)
            service = ClerkSyncService(
                session=mock_db_session,
                correlation_id="e2e-corr-user-lifecycle",
            )
            service._mock_write = mock_write
            service._mock_user = mock_user
            service._mock_tenant = mock_tenant
            service._mock_role = mock_user_tenant_role
            yield service

    def test_new_user_creation_emits_user_first_seen(self, clerk_sync_service_for_user, mock_user):
        """E2E: New user sync emits user_first_seen event."""
        # Simulate user doesn't exist (first time seen)
        mock_query = clerk_sync_service_for_user.session.query.return_value
        mock_query.filter.return_value.first.return_value = None

        with patch('src.services.clerk_sync_service.User') as MockUser:
            MockUser.return_value = mock_user

            user = clerk_sync_service_for_user.sync_user(
                clerk_user_id="user_clerk_e2e_789",
                email="test@example.com",
                first_name="Test",
                last_name="User",
                source="webhook",
            )

        # Find the user_first_seen event
        calls = clerk_sync_service_for_user._mock_write.call_args_list
        first_seen_events = [
            c for c in calls
            if c[0][1].action == AuditAction.IDENTITY_USER_FIRST_SEEN
        ]

        assert len(first_seen_events) == 1
        event = first_seen_events[0][0][1]
        assert event.metadata["clerk_user_id"] == "user_clerk_e2e_789"
        assert event.metadata["source"] == "webhook"
        # SECURITY: No email in metadata
        assert "email" not in event.metadata
        assert event.correlation_id == "e2e-corr-user-lifecycle"

    def test_existing_user_update_does_not_emit_first_seen(self, clerk_sync_service_for_user, mock_user):
        """E2E: Existing user update does NOT emit user_first_seen."""
        # Simulate user already exists
        mock_query = clerk_sync_service_for_user.session.query.return_value
        mock_query.filter.return_value.first.return_value = mock_user

        user = clerk_sync_service_for_user.sync_user(
            clerk_user_id="user_clerk_e2e_789",
            email="updated@example.com",
            source="webhook",
        )

        # Should NOT have any first_seen events
        calls = clerk_sync_service_for_user._mock_write.call_args_list
        first_seen_events = [
            c for c in calls
            if c[0][1].action == AuditAction.IDENTITY_USER_FIRST_SEEN
        ]

        assert len(first_seen_events) == 0

    def test_membership_creation_emits_linked_and_role_assigned(
        self, clerk_sync_service_for_user, mock_user, mock_tenant, mock_user_tenant_role
    ):
        """E2E: Membership creation emits user_linked_to_tenant AND role_assigned."""
        # Setup query mocks
        mock_query = clerk_sync_service_for_user.session.query.return_value

        # First call returns user, second returns tenant, third returns no existing role
        def side_effect_filter(*args, **kwargs):
            mock_filter = MagicMock()
            return mock_filter

        mock_query.filter.side_effect = side_effect_filter

        # Mock the service methods to return our mocks
        clerk_sync_service_for_user.get_user_by_clerk_id = MagicMock(return_value=mock_user)
        clerk_sync_service_for_user.get_tenant_by_clerk_org_id = MagicMock(return_value=mock_tenant)

        # No existing role
        mock_query.filter.return_value.first.return_value = None

        with patch('src.services.clerk_sync_service.UserTenantRole') as MockRole:
            MockRole.create_from_clerk.return_value = mock_user_tenant_role

            role = clerk_sync_service_for_user.sync_membership(
                clerk_user_id="user_clerk_e2e_789",
                clerk_org_id="org_clerk_e2e_def",
                role="org:admin",
                source="clerk_webhook",
                assigned_by="system",
            )

        calls = clerk_sync_service_for_user._mock_write.call_args_list

        # Should have user_linked_to_tenant event
        linked_events = [
            c for c in calls
            if c[0][1].action == AuditAction.IDENTITY_USER_LINKED_TO_TENANT
        ]
        assert len(linked_events) == 1
        linked_event = linked_events[0][0][1]
        assert linked_event.metadata["clerk_user_id"] == "user_clerk_e2e_789"
        assert linked_event.metadata["tenant_id"] == "tenant_e2e_abc"

        # Should have role_assigned event
        assigned_events = [
            c for c in calls
            if c[0][1].action == AuditAction.IDENTITY_ROLE_ASSIGNED
        ]
        assert len(assigned_events) == 1
        assigned_event = assigned_events[0][0][1]
        assert assigned_event.metadata["role"] == "MERCHANT_ADMIN"
        assert assigned_event.metadata["assigned_by"] == "system"

    def test_membership_removal_emits_role_revoked(
        self, clerk_sync_service_for_user, mock_user, mock_tenant, mock_user_tenant_role
    ):
        """E2E: Membership removal emits role_revoked for each role."""
        # Mock service methods
        clerk_sync_service_for_user.get_user_by_clerk_id = MagicMock(return_value=mock_user)
        clerk_sync_service_for_user.get_tenant_by_clerk_org_id = MagicMock(return_value=mock_tenant)

        # Mock query to return active roles
        mock_query = clerk_sync_service_for_user.session.query.return_value
        mock_query.filter.return_value.all.return_value = [mock_user_tenant_role]

        result = clerk_sync_service_for_user.remove_membership(
            clerk_user_id="user_clerk_e2e_789",
            clerk_org_id="org_clerk_e2e_def",
            reason="membership_deleted",
            revoked_by="system",
        )

        assert result is True

        calls = clerk_sync_service_for_user._mock_write.call_args_list

        # Should have role_revoked event
        revoked_events = [
            c for c in calls
            if c[0][1].action == AuditAction.IDENTITY_ROLE_REVOKED
        ]
        assert len(revoked_events) == 1
        event = revoked_events[0][0][1]
        assert event.metadata["clerk_user_id"] == "user_clerk_e2e_789"
        assert event.metadata["previous_role"] == "MERCHANT_ADMIN"
        assert event.metadata["reason"] == "membership_deleted"
        assert event.metadata["revoked_by"] == "system"


class TestEndToEndCompleteLifecycle:
    """
    Full end-to-end test simulating complete identity lifecycle.

    Scenario:
    1. New tenant created (org webhook)
    2. New user created (user webhook)
    3. User added to tenant with role (membership webhook)
    4. User role updated (membership.updated webhook)
    5. User removed from tenant (membership.deleted webhook)
    6. Tenant deactivated (org.deleted webhook)
    """

    @pytest.fixture
    def audit_event_collector(self):
        """Collector to track all emitted audit events."""
        class EventCollector:
            def __init__(self):
                self.events = []

            def collect(self, db, event):
                self.events.append(event)
                return MagicMock(spec=AuditLog)

            def get_events_by_action(self, action):
                return [e for e in self.events if e.action == action]

            def get_all_actions(self):
                return [e.action for e in self.events]

        return EventCollector()

    def test_complete_lifecycle_audit_trail(self, mock_db_session, audit_event_collector):
        """E2E: Complete lifecycle produces correct audit trail."""
        from src.services.clerk_sync_service import ClerkSyncService

        # Create mocks
        mock_tenant = MagicMock()
        mock_tenant.id = "tenant_complete_123"
        mock_tenant.clerk_org_id = "org_complete_456"
        mock_tenant.billing_tier = "growth"

        mock_user = MagicMock()
        mock_user.id = "user_complete_789"
        mock_user.clerk_user_id = "clerk_user_complete_abc"
        mock_user.is_active = True

        mock_role = MagicMock()
        mock_role.role = "MERCHANT_ADMIN"
        mock_role.is_active = True

        with patch('src.audit.identity_events.write_audit_log_sync', side_effect=audit_event_collector.collect):
            # Use same correlation_id for entire lifecycle
            correlation_id = "complete-lifecycle-corr-123"

            # Step 1: Create tenant
            service = ClerkSyncService(mock_db_session, correlation_id)
            mock_db_session.query.return_value.filter.return_value.first.return_value = None

            with patch('src.services.clerk_sync_service.Tenant', return_value=mock_tenant):
                service.sync_tenant_from_org(
                    clerk_org_id="org_complete_456",
                    name="Complete Test Org",
                    billing_tier="growth",
                    source="clerk_webhook",
                )

            # Step 2: Create user
            with patch('src.services.clerk_sync_service.User', return_value=mock_user):
                service.sync_user(
                    clerk_user_id="clerk_user_complete_abc",
                    source="webhook",
                )

            # Step 3: Add user to tenant with role
            service.get_user_by_clerk_id = MagicMock(return_value=mock_user)
            service.get_tenant_by_clerk_org_id = MagicMock(return_value=mock_tenant)
            mock_db_session.query.return_value.filter.return_value.first.return_value = None

            with patch('src.services.clerk_sync_service.UserTenantRole') as MockRole:
                MockRole.create_from_clerk.return_value = mock_role
                service.sync_membership(
                    clerk_user_id="clerk_user_complete_abc",
                    clerk_org_id="org_complete_456",
                    role="org:admin",
                    source="clerk_webhook",
                )

            # Step 4: Remove membership
            mock_db_session.query.return_value.filter.return_value.all.return_value = [mock_role]
            service.remove_membership(
                clerk_user_id="clerk_user_complete_abc",
                clerk_org_id="org_complete_456",
                reason="membership_deleted",
            )

            # Step 5: Deactivate tenant
            mock_db_session.query.return_value.filter.return_value.first.return_value = mock_tenant
            service.deactivate_tenant(
                clerk_org_id="org_complete_456",
                reason="org_deleted",
            )

        # Verify complete audit trail
        all_actions = audit_event_collector.get_all_actions()

        # Expected sequence of events
        assert AuditAction.IDENTITY_TENANT_CREATED in all_actions
        assert AuditAction.IDENTITY_USER_FIRST_SEEN in all_actions
        assert AuditAction.IDENTITY_USER_LINKED_TO_TENANT in all_actions
        assert AuditAction.IDENTITY_ROLE_ASSIGNED in all_actions
        assert AuditAction.IDENTITY_ROLE_REVOKED in all_actions
        assert AuditAction.IDENTITY_TENANT_DEACTIVATED in all_actions

        # Verify all events have same correlation_id
        for event in audit_event_collector.events:
            assert event.correlation_id == correlation_id

        # Verify no PII in any event
        for event in audit_event_collector.events:
            assert "email" not in event.metadata
            assert "phone" not in event.metadata
            assert "first_name" not in event.metadata
            assert "last_name" not in event.metadata

        # Verify clerk_user_id used (not email) in user events
        user_events = [
            e for e in audit_event_collector.events
            if "clerk_user_id" in e.metadata
        ]
        for event in user_events:
            assert event.metadata["clerk_user_id"] == "clerk_user_complete_abc"

    def test_lifecycle_event_ordering(self, mock_db_session, audit_event_collector):
        """E2E: Audit events are emitted in correct chronological order."""
        from src.services.clerk_sync_service import ClerkSyncService

        mock_tenant = MagicMock()
        mock_tenant.id = "tenant_order_123"
        mock_tenant.clerk_org_id = "org_order_456"
        mock_tenant.billing_tier = "free"

        mock_user = MagicMock()
        mock_user.id = "user_order_789"
        mock_user.clerk_user_id = "clerk_user_order_abc"

        mock_role = MagicMock()
        mock_role.role = "MERCHANT_VIEWER"
        mock_role.is_active = True

        with patch('src.audit.identity_events.write_audit_log_sync', side_effect=audit_event_collector.collect):
            service = ClerkSyncService(mock_db_session, "order-test-corr")

            # Create tenant first
            mock_db_session.query.return_value.filter.return_value.first.return_value = None
            with patch('src.services.clerk_sync_service.Tenant', return_value=mock_tenant):
                service.sync_tenant_from_org("org_order_456", "Order Test", source="clerk_webhook")

            # Create user
            with patch('src.services.clerk_sync_service.User', return_value=mock_user):
                service.sync_user("clerk_user_order_abc", source="webhook")

            # Add membership
            service.get_user_by_clerk_id = MagicMock(return_value=mock_user)
            service.get_tenant_by_clerk_org_id = MagicMock(return_value=mock_tenant)
            with patch('src.services.clerk_sync_service.UserTenantRole') as MockRole:
                MockRole.create_from_clerk.return_value = mock_role
                service.sync_membership("clerk_user_order_abc", "org_order_456", "org:member")

        # Verify order: tenant_created -> user_first_seen -> user_linked -> role_assigned
        actions = audit_event_collector.get_all_actions()

        tenant_idx = actions.index(AuditAction.IDENTITY_TENANT_CREATED)
        user_idx = actions.index(AuditAction.IDENTITY_USER_FIRST_SEEN)
        linked_idx = actions.index(AuditAction.IDENTITY_USER_LINKED_TO_TENANT)
        role_idx = actions.index(AuditAction.IDENTITY_ROLE_ASSIGNED)

        # Tenant created before user
        assert tenant_idx < user_idx
        # User created before linked to tenant
        assert user_idx < linked_idx
        # Linked and role assigned happen together (linked first)
        assert linked_idx < role_idx
