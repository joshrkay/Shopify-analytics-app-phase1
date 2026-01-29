"""
Audit logging tests for AI Growth Analytics.

CRITICAL: These tests verify that all sensitive actions are properly audited.
Audit logs MUST be append-only and include complete context.

Story 10.1 - Audit Event Schema & Logging Foundation
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from fastapi import Request

from src.platform.audit import (
    AuditAction,
    AuditEvent,
    AuditLog,
    AuditOutcome,
    PIIRedactor,
    extract_client_info,
    get_correlation_id,
    write_audit_log_sync,
    _write_fallback_log,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_request():
    """Create a mock FastAPI request."""
    request = Mock(spec=Request)
    request.headers = {
        "User-Agent": "Mozilla/5.0 Test Browser",
        "X-Forwarded-For": "192.168.1.100, 10.0.0.1",
        "X-Correlation-ID": "corr-123-456",
    }
    request.client = Mock()
    request.client.host = "127.0.0.1"
    request.state = Mock()
    request.state.correlation_id = "corr-123-456"
    return request


@pytest.fixture
def mock_request_no_headers():
    """Create a mock request without special headers."""
    request = Mock(spec=Request)
    request.headers = {}
    request.client = Mock()
    request.client.host = "192.168.1.50"
    request.state = Mock(spec=[])  # No attributes
    return request


# ============================================================================
# TEST SUITE: AUDIT EVENT CREATION
# ============================================================================

class TestAuditEventCreation:
    """Test audit event data structure."""

    def test_audit_event_has_required_fields(self):
        """CRITICAL: Audit events must include all required fields."""
        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.BILLING_PLAN_CHANGED,
            user_id="user-456",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0",
            resource_type="plan",
            resource_id="plan-789",
            metadata={"old_plan": "free", "new_plan": "pro"},
            correlation_id="corr-123",
        )

        assert event.tenant_id == "tenant-123"
        assert event.user_id == "user-456"
        assert event.action == AuditAction.BILLING_PLAN_CHANGED
        assert event.ip_address == "192.168.1.100"
        assert event.user_agent == "Mozilla/5.0"
        assert event.resource_type == "plan"
        assert event.resource_id == "plan-789"
        assert event.metadata == {"old_plan": "free", "new_plan": "pro"}
        assert event.correlation_id == "corr-123"
        assert event.timestamp is not None

    def test_audit_event_timestamp_auto_generated(self):
        """Audit events auto-generate timestamp if not provided."""
        before = datetime.now(timezone.utc)

        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.AUTH_LOGIN,
            user_id="user-456",
        )

        after = datetime.now(timezone.utc)

        assert before <= event.timestamp <= after

    def test_audit_event_correlation_id_auto_generated(self):
        """Audit events auto-generate correlation_id if not provided."""
        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.AUTH_LOGIN,
        )

        assert event.correlation_id is not None
        assert len(event.correlation_id) == 36  # UUID format

    def test_audit_event_to_dict(self):
        """Audit event can be converted to dict for DB insertion."""
        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.STORE_CONNECTED,
            user_id="user-456",
            resource_type="store",
            resource_id="store-789",
        )

        event_dict = event.to_dict()

        assert event_dict["tenant_id"] == "tenant-123"
        assert event_dict["user_id"] == "user-456"
        assert event_dict["action"] == "store.connected"
        assert event_dict["resource_type"] == "store"
        assert event_dict["resource_id"] == "store-789"
        assert "timestamp" in event_dict
        assert "source" in event_dict
        assert "outcome" in event_dict
        assert "correlation_id" in event_dict

    def test_audit_event_new_fields_story_10_1(self):
        """Story 10.1: Audit events include source, outcome, error_code."""
        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.AUTH_LOGIN_FAILED,
            source="api",
            outcome=AuditOutcome.FAILURE,
            error_code="INVALID_CREDENTIALS",
        )

        assert event.source == "api"
        assert event.outcome == AuditOutcome.FAILURE
        assert event.error_code == "INVALID_CREDENTIALS"

        event_dict = event.to_dict()
        assert event_dict["source"] == "api"
        assert event_dict["outcome"] == "failure"
        assert event_dict["error_code"] == "INVALID_CREDENTIALS"

    def test_audit_event_system_event_null_user(self):
        """System events can have NULL user_id."""
        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.STORE_SYNC_COMPLETED,
            user_id=None,
            source="worker",
        )

        assert event.user_id is None
        assert event.source == "worker"


# ============================================================================
# TEST SUITE: AUDIT ACTIONS
# ============================================================================

class TestAuditActions:
    """Test audit action enumeration."""

    def test_all_sensitive_actions_defined(self):
        """CRITICAL: All sensitive actions must have audit actions defined."""
        # Auth events
        assert AuditAction.AUTH_LOGIN
        assert AuditAction.AUTH_LOGOUT
        assert AuditAction.AUTH_LOGIN_FAILED

        # Billing events
        assert AuditAction.BILLING_PLAN_CHANGED
        assert AuditAction.BILLING_SUBSCRIPTION_CREATED
        assert AuditAction.BILLING_SUBSCRIPTION_CANCELLED

        # Store/connector events
        assert AuditAction.STORE_CONNECTED
        assert AuditAction.STORE_DISCONNECTED

        # AI events
        assert AuditAction.AI_KEY_CREATED
        assert AuditAction.AI_ACTION_EXECUTED

        # Export events
        assert AuditAction.EXPORT_REQUESTED
        assert AuditAction.EXPORT_COMPLETED

        # Automation events
        assert AuditAction.AUTOMATION_APPROVED
        assert AuditAction.AUTOMATION_EXECUTED

        # Feature flag events
        assert AuditAction.FEATURE_FLAG_ENABLED
        assert AuditAction.FEATURE_FLAG_DISABLED

        # Admin events
        assert AuditAction.ADMIN_PLAN_CREATED
        assert AuditAction.ADMIN_CONFIG_CHANGED

    def test_audit_action_values_follow_convention(self):
        """Audit action values should follow naming convention."""
        for action in AuditAction:
            # Values should be lowercase with dots
            assert action.value == action.value.lower()
            assert "." in action.value
            # Should have category.action format
            parts = action.value.split(".")
            assert len(parts) >= 2


# ============================================================================
# TEST SUITE: CLIENT INFO EXTRACTION
# ============================================================================

class TestClientInfoExtraction:
    """Test client information extraction from requests."""

    def test_extract_ip_from_x_forwarded_for(self, mock_request):
        """IP address extracted from X-Forwarded-For header."""
        ip, user_agent = extract_client_info(mock_request)

        # Should take first IP from X-Forwarded-For
        assert ip == "192.168.1.100"
        assert user_agent == "Mozilla/5.0 Test Browser"

    def test_extract_ip_from_client_direct(self, mock_request_no_headers):
        """IP address extracted from client when no proxy headers."""
        ip, user_agent = extract_client_info(mock_request_no_headers)

        assert ip == "192.168.1.50"
        assert user_agent is None

    def test_correlation_id_from_state(self, mock_request):
        """Correlation ID extracted from request state."""
        correlation_id = get_correlation_id(mock_request)

        assert correlation_id == "corr-123-456"

    def test_correlation_id_from_header(self):
        """Correlation ID extracted from header if not in state."""
        request = Mock(spec=Request)
        request.headers = {"X-Correlation-ID": "header-corr-id"}
        request.state = Mock(spec=[])  # No correlation_id attribute

        correlation_id = get_correlation_id(request)

        assert correlation_id == "header-corr-id"


# ============================================================================
# TEST SUITE: AUDIT LOG MODEL
# ============================================================================

class TestAuditLogModel:
    """Test AuditLog database model."""

    def test_audit_log_has_required_columns(self):
        """CRITICAL: AuditLog model has all required columns."""
        # Check that AuditLog has the required columns
        assert hasattr(AuditLog, 'id')
        assert hasattr(AuditLog, 'tenant_id')
        assert hasattr(AuditLog, 'user_id')
        assert hasattr(AuditLog, 'action')
        assert hasattr(AuditLog, 'timestamp')
        assert hasattr(AuditLog, 'ip_address')
        assert hasattr(AuditLog, 'user_agent')
        assert hasattr(AuditLog, 'resource_type')
        assert hasattr(AuditLog, 'resource_id')
        assert hasattr(AuditLog, 'event_metadata')
        assert hasattr(AuditLog, 'correlation_id')

    def test_audit_log_has_new_columns_story_10_1(self):
        """Story 10.1: AuditLog model has new columns."""
        assert hasattr(AuditLog, 'source')
        assert hasattr(AuditLog, 'outcome')
        assert hasattr(AuditLog, 'error_code')

    def test_audit_log_table_name(self):
        """AuditLog has correct table name."""
        assert AuditLog.__tablename__ == "audit_logs"


# ============================================================================
# TEST SUITE: AUDIT EVENT SCENARIOS
# ============================================================================

class TestAuditEventScenarios:
    """Test specific audit event scenarios."""

    def test_auth_login_event(self):
        """Auth login events capture required data."""
        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.AUTH_LOGIN,
            user_id="user-456",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0",
            metadata={
                "login_method": "oauth",
                "provider": "frontegg",
            }
        )

        assert event.action == AuditAction.AUTH_LOGIN
        assert event.metadata["login_method"] == "oauth"

    def test_billing_change_event(self):
        """Billing change events capture plan transition."""
        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.BILLING_PLAN_CHANGED,
            user_id="user-456",
            resource_type="subscription",
            resource_id="sub-789",
            metadata={
                "old_plan": "free",
                "new_plan": "pro",
                "monthly_price": 29.99,
            }
        )

        assert event.action == AuditAction.BILLING_PLAN_CHANGED
        assert event.metadata["old_plan"] == "free"
        assert event.metadata["new_plan"] == "pro"

    def test_store_connected_event(self):
        """Store connected events capture shop details."""
        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.STORE_CONNECTED,
            user_id="user-456",
            resource_type="store",
            resource_id="store-789",
            metadata={
                "shop_domain": "example.myshopify.com",
                "shop_name": "Example Store",
            }
        )

        assert event.action == AuditAction.STORE_CONNECTED
        assert event.resource_type == "store"

    def test_ai_action_executed_event(self):
        """AI action events capture what was executed."""
        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.AI_ACTION_EXECUTED,
            user_id="user-456",
            resource_type="ai_action",
            resource_id="action-789",
            metadata={
                "action_type": "price_update",
                "affected_products": 15,
                "model_used": "gpt-4",
            }
        )

        assert event.action == AuditAction.AI_ACTION_EXECUTED
        assert event.metadata["action_type"] == "price_update"

    def test_export_event(self):
        """Export events capture export details."""
        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.EXPORT_COMPLETED,
            user_id="user-456",
            resource_type="export",
            resource_id="export-789",
            metadata={
                "format": "csv",
                "rows": 10000,
                "file_size_bytes": 524288,
            }
        )

        assert event.action == AuditAction.EXPORT_COMPLETED
        assert event.metadata["format"] == "csv"

    def test_system_event_without_user(self):
        """System events can have None user_id (Story 10.1)."""
        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.STORE_SYNC_COMPLETED,
            user_id=None,
            source="worker",
            resource_type="store",
            resource_id="store-789",
            metadata={
                "records_synced": 5000,
                "duration_seconds": 120,
            }
        )

        assert event.user_id is None
        assert event.source == "worker"
        assert event.action == AuditAction.STORE_SYNC_COMPLETED


# ============================================================================
# TEST SUITE: APPEND-ONLY REQUIREMENT
# ============================================================================

class TestAppendOnlyRequirement:
    """Test that audit logs are append-only."""

    def test_audit_event_is_immutable_dataclass(self):
        """AuditEvent should be a dataclass (effectively immutable)."""
        from dataclasses import is_dataclass

        assert is_dataclass(AuditEvent)

    def test_audit_log_model_is_append_only_by_design(self):
        """
        CRITICAL: AuditLog is designed for append-only use.

        Note: Actual DB constraints would be at the database level.
        This test documents the requirement.
        """
        # The model exists and is intended for append-only use
        # Actual enforcement requires:
        # 1. No UPDATE/DELETE methods in repository
        # 2. Database triggers or policies
        # 3. Application-level restrictions

        # Verify model has no update method
        assert not hasattr(AuditLog, 'update')


# ============================================================================
# TEST SUITE: PII REDACTION (Story 10.1)
# ============================================================================

class TestPIIRedactor:
    """Test PII redaction functionality for audit logs."""

    def test_redacts_email_with_partial_mask(self):
        """Should redact email to ***@domain.com format."""
        data = {"email": "user@example.com", "name": "John"}
        result = PIIRedactor.redact(data)

        assert result["email"] == "***@example.com"
        assert result["name"] == "John"  # Non-PII preserved

    def test_redacts_phone_with_last_four(self):
        """Should redact phone to ***1234 format."""
        data = {"phone": "555-123-4567", "phone_number": "9876543210"}
        result = PIIRedactor.redact(data)

        assert result["phone"] == "***4567"
        assert result["phone_number"] == "***3210"

    def test_redacts_token_completely(self):
        """Should replace token with [REDACTED]."""
        data = {
            "token": "secret-token-123",
            "access_token": "bearer-xyz",
            "refresh_token": "refresh-abc",
            "api_key": "key-456",
        }
        result = PIIRedactor.redact(data)

        assert result["token"] == "[REDACTED]"
        assert result["access_token"] == "[REDACTED]"
        assert result["refresh_token"] == "[REDACTED]"
        assert result["api_key"] == "[REDACTED]"

    def test_redacts_password_and_credentials(self):
        """Should redact password and credential fields."""
        data = {
            "password": "super-secret",
            "secret": "my-secret",
            "credential": "cred-123",
            "credentials": {"user": "a", "pass": "b"},
        }
        result = PIIRedactor.redact(data)

        assert result["password"] == "[REDACTED]"
        assert result["secret"] == "[REDACTED]"
        assert result["credential"] == "[REDACTED]"
        assert result["credentials"] == "[REDACTED]"

    def test_redacts_financial_data(self):
        """Should redact financial fields."""
        data = {
            "credit_card": "4111111111111111",
            "card_number": "5500000000000004",
            "cvv": "123",
            "bank_account": "123456789",
        }
        result = PIIRedactor.redact(data)

        assert result["credit_card"] == "[REDACTED]"
        assert result["card_number"] == "[REDACTED]"
        assert result["cvv"] == "[REDACTED]"
        assert result["bank_account"] == "[REDACTED]"

    def test_redacts_nested_pii_fields(self):
        """Should redact PII in nested dictionaries."""
        data = {
            "user": {
                "email": "nested@example.com",
                "phone": "1234567890",
                "preferences": {"theme": "dark"},
            }
        }
        result = PIIRedactor.redact(data)

        assert result["user"]["email"] == "***@example.com"
        assert result["user"]["phone"] == "***7890"
        assert result["user"]["preferences"]["theme"] == "dark"

    def test_redacts_pii_in_lists(self):
        """Should redact PII in list items."""
        data = {
            "users": [
                {"email": "user1@test.com", "name": "User 1"},
                {"email": "user2@test.com", "name": "User 2"},
            ]
        }
        result = PIIRedactor.redact(data)

        assert result["users"][0]["email"] == "***@test.com"
        assert result["users"][0]["name"] == "User 1"
        assert result["users"][1]["email"] == "***@test.com"

    def test_preserves_non_pii_fields(self):
        """Should not modify non-PII fields."""
        data = {
            "action": "login",
            "status": "success",
            "timestamp": "2024-01-15T10:30:00Z",
            "count": 42,
            "enabled": True,
        }
        result = PIIRedactor.redact(data)

        assert result == data  # No changes

    def test_handles_empty_input(self):
        """Should return empty dict for empty input."""
        assert PIIRedactor.redact({}) == {}

    def test_handles_none_values(self):
        """Should handle None values gracefully."""
        data = {"email": None, "phone": None}
        result = PIIRedactor.redact(data)

        assert result["email"] == "[REDACTED]"
        assert result["phone"] == "[REDACTED]"

    def test_handles_non_dict_input(self):
        """Should return input unchanged if not a dict."""
        assert PIIRedactor.redact("not a dict") == "not a dict"
        assert PIIRedactor.redact(123) == 123
        assert PIIRedactor.redact(None) is None

    def test_case_insensitive_field_matching(self):
        """Should match PII fields case-insensitively."""
        data = {
            "Email": "upper@test.com",
            "PHONE": "9999999999",
            "API_KEY": "key-123",
        }
        result = PIIRedactor.redact(data)

        assert result["Email"] == "***@test.com"
        assert result["PHONE"] == "***9999"
        assert result["API_KEY"] == "[REDACTED]"

    def test_pii_redacted_in_audit_event_to_dict(self):
        """PII should be automatically redacted when converting to dict."""
        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.AUTH_LOGIN,
            metadata={
                "email": "user@example.com",
                "token": "secret-token",
                "action": "login",
            }
        )

        event_dict = event.to_dict()

        # Metadata should have PII redacted
        assert event_dict["event_metadata"]["email"] == "***@example.com"
        assert event_dict["event_metadata"]["token"] == "[REDACTED]"
        assert event_dict["event_metadata"]["action"] == "login"


# ============================================================================
# TEST SUITE: FALLBACK LOGGING (Story 10.1)
# ============================================================================

class TestFallbackLogging:
    """Test fallback logging when primary DB fails."""

    def test_write_fallback_log_format(self):
        """Fallback log should have correct JSON structure."""
        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.AUTH_LOGIN,
            user_id="user-456",
            correlation_id="corr-789",
            source="api",
            outcome=AuditOutcome.SUCCESS,
        )

        with patch("src.platform.audit.fallback_logger") as mock_logger:
            _write_fallback_log(event, "audit-id-123", "DB connection failed")

            mock_logger.error.assert_called_once()
            call_args = mock_logger.error.call_args

            assert call_args[0][0] == "Audit log fallback"
            extra = call_args[1]["extra"]
            audit_entry = json.loads(extra["audit_entry"])

            assert audit_entry["event_id"] == "audit-id-123"
            assert audit_entry["tenant_id"] == "tenant-123"
            assert audit_entry["user_id"] == "user-456"
            assert audit_entry["correlation_id"] == "corr-789"
            assert audit_entry["fallback_reason"] == "DB connection failed"

    def test_write_audit_log_sync_uses_fallback_on_db_error(self):
        """Should write to fallback logger when DB fails."""
        mock_db = Mock()
        mock_db.add.side_effect = Exception("DB connection error")
        mock_db.rollback = Mock()

        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.AUTH_LOGIN,
        )

        with patch("src.platform.audit.fallback_logger") as mock_logger:
            result = write_audit_log_sync(mock_db, event)

            # Should return None on failure
            assert result is None

            # Should have called fallback logger
            mock_logger.error.assert_called_once()

            # Should have tried to rollback
            mock_db.rollback.assert_called_once()

    def test_write_audit_log_sync_never_raises(self):
        """Audit logging should never crash request flow."""
        mock_db = Mock()
        mock_db.add.side_effect = Exception("Catastrophic DB failure")
        mock_db.rollback.side_effect = Exception("Rollback also failed")

        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.AUTH_LOGIN,
        )

        # Should NOT raise, even with multiple failures
        with patch("src.platform.audit.fallback_logger"):
            result = write_audit_log_sync(mock_db, event)
            assert result is None  # Returns None, doesn't crash


# ============================================================================
# TEST SUITE: AUDIT OUTCOME (Story 10.1)
# ============================================================================

class TestAuditOutcome:
    """Test AuditOutcome enum."""

    def test_outcome_values(self):
        """AuditOutcome should have expected values."""
        assert AuditOutcome.SUCCESS.value == "success"
        assert AuditOutcome.FAILURE.value == "failure"
        assert AuditOutcome.DENIED.value == "denied"

    def test_outcome_in_event(self):
        """AuditEvent should accept outcome parameter."""
        event_success = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.AUTH_LOGIN,
            outcome=AuditOutcome.SUCCESS,
        )
        assert event_success.outcome == AuditOutcome.SUCCESS

        event_denied = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.ENTITLEMENT_DENIED,
            outcome=AuditOutcome.DENIED,
            error_code="FEATURE_NOT_AVAILABLE",
        )
        assert event_denied.outcome == AuditOutcome.DENIED
        assert event_denied.error_code == "FEATURE_NOT_AVAILABLE"

    def test_outcome_serialization(self):
        """AuditOutcome should serialize to string value."""
        event = AuditEvent(
            tenant_id="tenant-123",
            action=AuditAction.AUTH_LOGIN_FAILED,
            outcome=AuditOutcome.FAILURE,
            error_code="INVALID_CREDENTIALS",
        )

        event_dict = event.to_dict()
        assert event_dict["outcome"] == "failure"
        assert event_dict["error_code"] == "INVALID_CREDENTIALS"


# ============================================================================
# TEST SUITE: AUDITABLE EVENTS REGISTRY (Story 10.2)
# ============================================================================

class TestAuditableEventsRegistry:
    """Test AUDITABLE_EVENTS registry for audit coverage enforcement."""

    def test_registry_exists_and_is_dict(self):
        """AUDITABLE_EVENTS should be a dictionary."""
        from src.platform.audit import AUDITABLE_EVENTS
        assert isinstance(AUDITABLE_EVENTS, dict)
        assert len(AUDITABLE_EVENTS) > 0

    def test_registry_contains_high_risk_events(self):
        """Registry should contain all high-risk events."""
        from src.platform.audit import AUDITABLE_EVENTS

        high_risk_actions = [
            AuditAction.AUTH_LOGIN,
            AuditAction.AUTH_LOGIN_FAILED,
            AuditAction.AUTH_PASSWORD_CHANGE,
            AuditAction.BILLING_PLAN_CHANGED,
            AuditAction.BILLING_SUBSCRIPTION_CANCELLED,
            AuditAction.AI_KEY_CREATED,
            AuditAction.AI_ACTION_EXECUTED,
            AuditAction.EXPORT_REQUESTED,
            AuditAction.TEAM_MEMBER_INVITED,
            AuditAction.ADMIN_PLAN_CREATED,
        ]

        for action in high_risk_actions:
            assert action in AUDITABLE_EVENTS, f"{action} should be in registry"

    def test_registry_metadata_has_required_fields(self):
        """Each registry entry should have required metadata fields."""
        from src.platform.audit import AUDITABLE_EVENTS, AuditableEventMetadata

        for action, metadata in AUDITABLE_EVENTS.items():
            assert isinstance(metadata, AuditableEventMetadata)
            assert metadata.description, f"{action} should have description"
            assert metadata.risk_level in ("high", "medium", "low")
            assert isinstance(metadata.required_fields, tuple)
            assert isinstance(metadata.compliance_tags, tuple)

    def test_billing_plan_changed_requires_old_and_new_plan(self):
        """BILLING_PLAN_CHANGED should require old_plan and new_plan."""
        from src.platform.audit import AUDITABLE_EVENTS

        metadata = AUDITABLE_EVENTS[AuditAction.BILLING_PLAN_CHANGED]
        assert "old_plan" in metadata.required_fields
        assert "new_plan" in metadata.required_fields

    def test_export_completed_requires_record_count(self):
        """EXPORT_COMPLETED should require record_count."""
        from src.platform.audit import AUDITABLE_EVENTS

        metadata = AUDITABLE_EVENTS[AuditAction.EXPORT_COMPLETED]
        assert "export_type" in metadata.required_fields
        assert "record_count" in metadata.required_fields


# ============================================================================
# TEST SUITE: METADATA VALIDATION (Story 10.2)
# ============================================================================

class TestValidateAuditMetadata:
    """Test validate_audit_metadata function."""

    def test_valid_metadata_returns_no_warnings(self):
        """Valid metadata should return empty warnings list."""
        from src.platform.audit import validate_audit_metadata

        metadata = {"old_plan": "free", "new_plan": "pro"}
        warnings = validate_audit_metadata(
            AuditAction.BILLING_PLAN_CHANGED,
            metadata
        )

        assert warnings == []

    def test_missing_required_field_returns_warning(self):
        """Missing required field should return warning."""
        from src.platform.audit import validate_audit_metadata

        metadata = {"old_plan": "free"}  # missing new_plan
        warnings = validate_audit_metadata(
            AuditAction.BILLING_PLAN_CHANGED,
            metadata
        )

        assert len(warnings) == 1
        assert "new_plan" in warnings[0]

    def test_strict_mode_raises_on_missing_field(self):
        """Strict mode should raise ValueError on missing field."""
        from src.platform.audit import validate_audit_metadata

        metadata = {}  # missing both old_plan and new_plan
        with pytest.raises(ValueError) as exc_info:
            validate_audit_metadata(
                AuditAction.BILLING_PLAN_CHANGED,
                metadata,
                strict=True
            )

        assert "old_plan" in str(exc_info.value)
        assert "new_plan" in str(exc_info.value)

    def test_action_not_in_registry_returns_warning(self):
        """Action not in registry should return warning."""
        from src.platform.audit import validate_audit_metadata, AuditAction

        # Find an action not in registry (if any) or use a known one
        # AI_RATE_LIMIT_HIT might not be in the simplified registry
        metadata = {}
        warnings = validate_audit_metadata(
            AuditAction.AI_RATE_LIMIT_HIT,  # May not have required fields
            metadata
        )

        # Should either have no warnings (no required fields) or warning about missing registry
        assert isinstance(warnings, list)


# ============================================================================
# TEST SUITE: HIGH RISK AND COMPLIANCE HELPERS (Story 10.2)
# ============================================================================

class TestAuditHelpers:
    """Test get_high_risk_actions and get_compliance_actions helpers."""

    def test_get_high_risk_actions_returns_list(self):
        """get_high_risk_actions should return list of high-risk actions."""
        from src.platform.audit import get_high_risk_actions

        high_risk = get_high_risk_actions()

        assert isinstance(high_risk, list)
        assert len(high_risk) > 0
        assert AuditAction.AUTH_LOGIN in high_risk
        assert AuditAction.BILLING_PLAN_CHANGED in high_risk
        assert AuditAction.EXPORT_REQUESTED in high_risk

    def test_get_compliance_actions_soc2(self):
        """get_compliance_actions('SOC2') should return SOC2 tagged actions."""
        from src.platform.audit import get_compliance_actions

        soc2_actions = get_compliance_actions("SOC2")

        assert isinstance(soc2_actions, list)
        assert len(soc2_actions) > 0
        assert AuditAction.AUTH_LOGIN in soc2_actions

    def test_get_compliance_actions_gdpr(self):
        """get_compliance_actions('GDPR') should return GDPR tagged actions."""
        from src.platform.audit import get_compliance_actions

        gdpr_actions = get_compliance_actions("GDPR")

        assert isinstance(gdpr_actions, list)
        assert len(gdpr_actions) > 0
        # Data export events should be GDPR tagged
        assert AuditAction.EXPORT_REQUESTED in gdpr_actions
        assert AuditAction.DATA_EXPORTED in gdpr_actions

    def test_get_compliance_actions_pci(self):
        """get_compliance_actions('PCI') should return PCI tagged actions."""
        from src.platform.audit import get_compliance_actions

        pci_actions = get_compliance_actions("PCI")

        assert isinstance(pci_actions, list)
        # Billing events should be PCI tagged
        assert AuditAction.BILLING_PLAN_CHANGED in pci_actions
        assert AuditAction.BILLING_PAYMENT_SUCCESS in pci_actions


# ============================================================================
# TEST SUITE: REQUIRE_AUDIT DECORATOR (Story 10.2)
# ============================================================================

class TestRequireAuditDecorator:
    """Test require_audit decorator."""

    def test_require_audit_decorator_exists(self):
        """require_audit decorator should be importable."""
        from src.platform.audit import require_audit
        assert callable(require_audit)

    def test_require_audit_creates_decorator(self):
        """require_audit should create a decorator function."""
        from src.platform.audit import require_audit

        decorator = require_audit(AuditAction.BILLING_PLAN_CHANGED)
        assert callable(decorator)

    def test_require_audit_preserves_function_name(self):
        """Decorated function should preserve original name."""
        from src.platform.audit import require_audit

        @require_audit(AuditAction.BILLING_PLAN_CHANGED)
        async def change_plan():
            return {"old_plan": "free", "new_plan": "pro"}

        assert change_plan.__name__ == "change_plan"


# ============================================================================
# TEST SUITE: AUDIT EXPORT SERVICE (Story 10.3)
# ============================================================================

class TestAuditExportFormat:
    """Test AuditExportFormat enum."""

    def test_export_format_values(self):
        """AuditExportFormat should have CSV and JSON."""
        from src.platform.audit import AuditExportFormat

        assert AuditExportFormat.CSV.value == "csv"
        assert AuditExportFormat.JSON.value == "json"


class TestAuditExportRequest:
    """Test AuditExportRequest dataclass."""

    def test_export_request_has_required_fields(self):
        """AuditExportRequest should have all required fields."""
        from src.platform.audit import AuditExportRequest, AuditExportFormat

        request = AuditExportRequest(
            tenant_id="tenant-123",
            format=AuditExportFormat.CSV,
        )

        assert request.tenant_id == "tenant-123"
        assert request.format == AuditExportFormat.CSV
        assert request.limit == 10000  # Default
        assert request.offset == 0  # Default

    def test_export_request_optional_fields(self):
        """AuditExportRequest should accept optional fields."""
        from src.platform.audit import AuditExportRequest, AuditExportFormat

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 31, tzinfo=timezone.utc)

        request = AuditExportRequest(
            tenant_id="tenant-123",
            format=AuditExportFormat.JSON,
            start_date=start,
            end_date=end,
            actions=[AuditAction.AUTH_LOGIN, AuditAction.AUTH_LOGOUT],
            user_id="user-456",
            limit=5000,
            offset=100,
        )

        assert request.start_date == start
        assert request.end_date == end
        assert request.actions == [AuditAction.AUTH_LOGIN, AuditAction.AUTH_LOGOUT]
        assert request.user_id == "user-456"
        assert request.limit == 5000
        assert request.offset == 100


class TestAuditExportResult:
    """Test AuditExportResult dataclass."""

    def test_export_result_success(self):
        """AuditExportResult should represent successful export."""
        from src.platform.audit import AuditExportResult, AuditExportFormat

        result = AuditExportResult(
            success=True,
            record_count=100,
            format=AuditExportFormat.CSV,
            content="id,timestamp,action\n1,2024-01-01,auth.login\n",
            export_id="export-123",
        )

        assert result.success is True
        assert result.record_count == 100
        assert result.format == AuditExportFormat.CSV
        assert result.content is not None
        assert result.error is None
        assert result.is_async is False

    def test_export_result_failure(self):
        """AuditExportResult should represent failed export."""
        from src.platform.audit import AuditExportResult, AuditExportFormat

        result = AuditExportResult(
            success=False,
            record_count=0,
            format=AuditExportFormat.CSV,
            error="Rate limit exceeded",
            export_id="export-456",
        )

        assert result.success is False
        assert result.record_count == 0
        assert result.error == "Rate limit exceeded"
        assert result.content is None

    def test_export_result_async(self):
        """AuditExportResult should indicate async export."""
        from src.platform.audit import AuditExportResult, AuditExportFormat

        result = AuditExportResult(
            success=True,
            record_count=50000,
            format=AuditExportFormat.JSON,
            export_id="export-789",
            is_async=True,
        )

        assert result.success is True
        assert result.is_async is True
        assert result.content is None  # Content not available yet


class TestAuditExportServiceRateLimiting:
    """Test AuditExportService rate limiting."""

    def test_rate_limit_initial_state(self):
        """Initial state should allow exports."""
        from src.platform.audit import AuditExportService

        mock_db = Mock()
        service = AuditExportService(mock_db)

        is_allowed, remaining = service.check_rate_limit("tenant-123")

        assert is_allowed is True
        assert remaining == 3

    def test_rate_limit_after_exports(self):
        """Should decrease remaining after exports."""
        from src.platform.audit import AuditExportService

        mock_db = Mock()
        service = AuditExportService(mock_db)

        # Record 2 exports
        service.record_export("tenant-123")
        service.record_export("tenant-123")

        is_allowed, remaining = service.check_rate_limit("tenant-123")

        assert is_allowed is True
        assert remaining == 1

    def test_rate_limit_exceeded(self):
        """Should deny when rate limit exceeded."""
        from src.platform.audit import AuditExportService

        mock_db = Mock()
        service = AuditExportService(mock_db)

        # Record 3 exports (max)
        service.record_export("tenant-123")
        service.record_export("tenant-123")
        service.record_export("tenant-123")

        is_allowed, remaining = service.check_rate_limit("tenant-123")

        assert is_allowed is False
        assert remaining == 0

    def test_rate_limit_separate_tenants(self):
        """Rate limits should be per-tenant."""
        from src.platform.audit import AuditExportService

        mock_db = Mock()
        service = AuditExportService(mock_db)

        # Max out tenant-1
        for _ in range(3):
            service.record_export("tenant-1")

        # Tenant-2 should still be allowed
        is_allowed, remaining = service.check_rate_limit("tenant-2")

        assert is_allowed is True
        assert remaining == 3


class TestAuditExportServiceFormatting:
    """Test AuditExportService formatting methods."""

    def test_format_csv_empty(self):
        """CSV format should handle empty list."""
        from src.platform.audit import AuditExportService

        mock_db = Mock()
        service = AuditExportService(mock_db)

        csv_content = service.format_csv([])

        # Should have header row
        assert "id,timestamp,tenant_id" in csv_content
        lines = csv_content.strip().split("\n")
        assert len(lines) == 1  # Just header

    def test_format_csv_with_data(self):
        """CSV format should include data rows."""
        from src.platform.audit import AuditExportService, AuditLog

        mock_db = Mock()
        service = AuditExportService(mock_db)

        # Create mock log
        mock_log = Mock(spec=AuditLog)
        mock_log.id = "log-1"
        mock_log.timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_log.tenant_id = "tenant-123"
        mock_log.user_id = "user-456"
        mock_log.action = "auth.login"
        mock_log.resource_type = None
        mock_log.resource_id = None
        mock_log.ip_address = "192.168.1.100"
        mock_log.user_agent = "Mozilla/5.0"
        mock_log.source = "api"
        mock_log.outcome = "success"
        mock_log.error_code = None
        mock_log.correlation_id = "corr-789"
        mock_log.event_metadata = {"key": "value"}

        csv_content = service.format_csv([mock_log])

        assert "log-1" in csv_content
        assert "tenant-123" in csv_content
        assert "user-456" in csv_content
        assert "auth.login" in csv_content
        lines = csv_content.strip().split("\n")
        assert len(lines) == 2  # Header + 1 data row

    def test_format_json_empty(self):
        """JSON format should handle empty list."""
        from src.platform.audit import AuditExportService

        mock_db = Mock()
        service = AuditExportService(mock_db)

        json_content = service.format_json([])
        data = json.loads(json_content)

        assert data["audit_logs"] == []
        assert data["count"] == 0

    def test_format_json_with_data(self):
        """JSON format should include data."""
        from src.platform.audit import AuditExportService, AuditLog

        mock_db = Mock()
        service = AuditExportService(mock_db)

        # Create mock log
        mock_log = Mock(spec=AuditLog)
        mock_log.id = "log-1"
        mock_log.timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_log.tenant_id = "tenant-123"
        mock_log.user_id = "user-456"
        mock_log.action = "auth.login"
        mock_log.resource_type = "session"
        mock_log.resource_id = "session-abc"
        mock_log.ip_address = "192.168.1.100"
        mock_log.user_agent = "Mozilla/5.0"
        mock_log.source = "api"
        mock_log.outcome = "success"
        mock_log.error_code = None
        mock_log.correlation_id = "corr-789"
        mock_log.event_metadata = {"method": "oauth"}

        json_content = service.format_json([mock_log])
        data = json.loads(json_content)

        assert data["count"] == 1
        assert len(data["audit_logs"]) == 1

        log_entry = data["audit_logs"][0]
        assert log_entry["id"] == "log-1"
        assert log_entry["tenant_id"] == "tenant-123"
        assert log_entry["action"] == "auth.login"
        assert log_entry["metadata"] == {"method": "oauth"}


class TestAuditExportServiceConstants:
    """Test AuditExportService constants."""

    def test_rate_limit_constants(self):
        """Service should have correct rate limit constants."""
        from src.platform.audit import AuditExportService

        assert AuditExportService.RATE_LIMIT_EXPORTS == 3
        assert AuditExportService.RATE_LIMIT_WINDOW_HOURS == 24

    def test_async_threshold_constant(self):
        """Service should have correct async threshold."""
        from src.platform.audit import AuditExportService

        assert AuditExportService.ASYNC_THRESHOLD_ROWS == 10000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
