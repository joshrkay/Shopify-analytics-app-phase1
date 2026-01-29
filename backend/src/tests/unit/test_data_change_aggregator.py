"""
Unit tests for DataChangeAggregator service (Story 9.8).

Tests cover:
- Simplified recording methods for sync events
- Simplified recording methods for AI action events
- Error sanitization
- State diff computation

Story 9.8 - "What Changed?" Debug Panel
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

from src.services.data_change_aggregator import DataChangeAggregator
from src.models.data_change_event import DataChangeEvent, DataChangeEventType


@pytest.fixture
def tenant_id():
    """Test tenant ID."""
    return "test-tenant-123"


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = Mock()
    session.query = Mock(return_value=Mock())
    session.add = Mock()
    session.flush = Mock()
    session.commit = Mock()
    session.rollback = Mock()
    return session


@pytest.fixture
def aggregator(mock_db_session, tenant_id):
    """Create a DataChangeAggregator instance."""
    return DataChangeAggregator(mock_db_session, tenant_id)


class TestDataChangeAggregatorInit:
    """Tests for DataChangeAggregator initialization."""

    def test_requires_tenant_id(self, mock_db_session):
        """Should raise ValueError if tenant_id is empty."""
        with pytest.raises(ValueError, match="tenant_id is required"):
            DataChangeAggregator(mock_db_session, "")

        with pytest.raises(ValueError, match="tenant_id is required"):
            DataChangeAggregator(mock_db_session, None)

    def test_initializes_with_valid_tenant_id(self, mock_db_session, tenant_id):
        """Should initialize successfully with valid tenant_id."""
        aggregator = DataChangeAggregator(mock_db_session, tenant_id)
        assert aggregator.tenant_id == tenant_id
        assert aggregator.db == mock_db_session


class TestRecordSyncCompletedSimple:
    """Tests for record_sync_completed_simple method."""

    def test_creates_event_with_all_parameters(self, aggregator, mock_db_session):
        """Should create a DataChangeEvent with all parameters."""
        event = aggregator.record_sync_completed_simple(
            connection_id="conn-123",
            connector_name="Shopify Orders",
            rows_synced=1500,
            duration_seconds=45.5,
            job_id="job-456",
        )

        # Verify event was added to session
        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_called_once()

        # Verify the added object
        added_event = mock_db_session.add.call_args[0][0]
        assert added_event.tenant_id == aggregator.tenant_id
        assert added_event.event_type == DataChangeEventType.SYNC_COMPLETED.value
        assert "Shopify Orders" in added_event.title
        assert "1,500 rows" in added_event.description
        assert "45s" in added_event.description
        assert added_event.affected_connector_id == "conn-123"
        assert added_event.affected_connector_name == "Shopify Orders"
        assert added_event.source_entity_id == "job-456"

    def test_creates_event_with_minimal_parameters(self, aggregator, mock_db_session):
        """Should create event with only required parameters."""
        event = aggregator.record_sync_completed_simple(
            connection_id="conn-123",
            connector_name="GA4",
        )

        mock_db_session.add.assert_called_once()

        added_event = mock_db_session.add.call_args[0][0]
        assert "GA4" in added_event.title
        assert "data" in added_event.description  # Fallback when rows not provided

    def test_formats_large_row_counts(self, aggregator, mock_db_session):
        """Should format large row counts with comma separators."""
        aggregator.record_sync_completed_simple(
            connection_id="conn-123",
            connector_name="Test",
            rows_synced=1234567,
        )

        added_event = mock_db_session.add.call_args[0][0]
        assert "1,234,567 rows" in added_event.description

    def test_includes_affected_metrics(self, aggregator, mock_db_session):
        """Should include standard sync-affected metrics."""
        aggregator.record_sync_completed_simple(
            connection_id="conn-123",
            connector_name="Test",
        )

        added_event = mock_db_session.add.call_args[0][0]
        assert "revenue" in added_event.affected_metrics
        assert "orders" in added_event.affected_metrics


class TestRecordSyncFailedSimple:
    """Tests for record_sync_failed_simple method."""

    def test_creates_event_with_error_message(self, aggregator, mock_db_session):
        """Should create failure event with sanitized error message."""
        event = aggregator.record_sync_failed_simple(
            connection_id="conn-123",
            connector_name="Meta Ads",
            error_message="Connection timeout after 30s",
            job_id="job-456",
        )

        mock_db_session.add.assert_called_once()

        added_event = mock_db_session.add.call_args[0][0]
        assert added_event.event_type == DataChangeEventType.SYNC_FAILED.value
        assert "Meta Ads" in added_event.title
        assert "failed" in added_event.title.lower()
        assert "Connection timeout" in added_event.description
        assert "stale" in added_event.impact_summary.lower()

    def test_sanitizes_sensitive_error_message(self, aggregator, mock_db_session):
        """Should sanitize sensitive data from error messages."""
        sensitive_error = (
            "Connection failed: api_key=sk_live_12345 "
            "password=secret123 at 192.168.1.1"
        )

        aggregator.record_sync_failed_simple(
            connection_id="conn-123",
            connector_name="Test",
            error_message=sensitive_error,
        )

        added_event = mock_db_session.add.call_args[0][0]

        # Sensitive data should be redacted
        assert "sk_live_12345" not in added_event.description
        assert "secret123" not in added_event.description
        assert "192.168.1.1" not in added_event.description

    def test_handles_none_error_message(self, aggregator, mock_db_session):
        """Should handle None error message gracefully."""
        aggregator.record_sync_failed_simple(
            connection_id="conn-123",
            connector_name="Test",
            error_message=None,
        )

        added_event = mock_db_session.add.call_args[0][0]
        assert "Unknown error" in added_event.description


class TestRecordAIActionExecutedSimple:
    """Tests for record_ai_action_executed_simple method."""

    def test_creates_event_with_all_parameters(self, aggregator, mock_db_session):
        """Should create AI action event with all parameters."""
        before_state = {"status": "active", "budget": 100}
        after_state = {"status": "paused", "budget": 100}

        event = aggregator.record_ai_action_executed_simple(
            action_id="action-123",
            action_type="pause_campaign",
            target_name="Summer Sale Campaign",
            platform="meta_ads",
            before_state=before_state,
            after_state=after_state,
        )

        mock_db_session.add.assert_called_once()

        added_event = mock_db_session.add.call_args[0][0]
        assert added_event.event_type == DataChangeEventType.AI_ACTION_EXECUTED.value
        assert "pause_campaign" in added_event.title
        assert "Summer Sale Campaign" in added_event.description
        assert "meta_ads" in added_event.description
        assert added_event.source_entity_id == "action-123"

    def test_computes_state_diff(self, aggregator, mock_db_session):
        """Should compute and include state diff in impact summary."""
        before_state = {"status": "active", "budget": 100}
        after_state = {"status": "paused", "budget": 150}

        aggregator.record_ai_action_executed_simple(
            action_id="action-123",
            action_type="update_budget",
            target_name="Test",
            before_state=before_state,
            after_state=after_state,
        )

        added_event = mock_db_session.add.call_args[0][0]
        # Impact should mention the changes
        assert "Changed:" in added_event.impact_summary or "Metrics may be affected" in added_event.impact_summary

    def test_sanitizes_target_name(self, aggregator, mock_db_session):
        """Should sanitize target name to remove sensitive data."""
        aggregator.record_ai_action_executed_simple(
            action_id="action-123",
            action_type="pause_ad",
            target_name="user@email.com Campaign 1234567890123",
        )

        added_event = mock_db_session.add.call_args[0][0]

        # Email should be redacted
        assert "user@email.com" not in added_event.description

    def test_handles_no_state_change(self, aggregator, mock_db_session):
        """Should handle case when before and after states are identical."""
        state = {"status": "active", "budget": 100}

        aggregator.record_ai_action_executed_simple(
            action_id="action-123",
            action_type="refresh",
            target_name="Test",
            before_state=state,
            after_state=state.copy(),
        )

        added_event = mock_db_session.add.call_args[0][0]
        # Should still create event with default impact
        assert "Metrics may be affected" in added_event.impact_summary

    def test_handles_none_states(self, aggregator, mock_db_session):
        """Should handle None before/after states."""
        aggregator.record_ai_action_executed_simple(
            action_id="action-123",
            action_type="pause_campaign",
            target_name="Test Campaign",
            before_state=None,
            after_state=None,
        )

        mock_db_session.add.assert_called_once()
        added_event = mock_db_session.add.call_args[0][0]
        assert added_event is not None

    def test_includes_ai_affected_metrics(self, aggregator, mock_db_session):
        """Should include AI action affected metrics."""
        aggregator.record_ai_action_executed_simple(
            action_id="action-123",
            action_type="pause_campaign",
            target_name="Test",
        )

        added_event = mock_db_session.add.call_args[0][0]
        assert "ad_spend" in added_event.affected_metrics
        assert "roas" in added_event.affected_metrics


class TestComputeStateDiff:
    """Tests for _compute_state_diff helper method."""

    def test_detects_changed_values(self, aggregator):
        """Should detect changed values between states."""
        before = {"status": "active", "budget": 100}
        after = {"status": "paused", "budget": 100}

        diff = aggregator._compute_state_diff(before, after)

        assert diff is not None
        assert "Status" in diff
        assert "active" in diff
        assert "paused" in diff

    def test_detects_added_values(self, aggregator):
        """Should detect newly added values."""
        before = {"status": "active"}
        after = {"status": "active", "budget": 100}

        diff = aggregator._compute_state_diff(before, after)

        assert diff is not None
        assert "Budget" in diff
        assert "100" in diff

    def test_detects_removed_values(self, aggregator):
        """Should detect removed values."""
        before = {"status": "active", "budget": 100}
        after = {"status": "active"}

        diff = aggregator._compute_state_diff(before, after)

        assert diff is not None
        assert "Budget" in diff
        assert "removed" in diff.lower()

    def test_returns_none_for_identical_states(self, aggregator):
        """Should return None when states are identical."""
        state = {"status": "active", "budget": 100}

        diff = aggregator._compute_state_diff(state, state.copy())

        assert diff is None

    def test_limits_changes_to_three(self, aggregator):
        """Should limit diff to first 3 changes plus count."""
        before = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
        after = {"a": 10, "b": 20, "c": 30, "d": 40, "e": 50}

        diff = aggregator._compute_state_diff(before, after)

        assert diff is not None
        assert "(+2 more)" in diff

    def test_formats_keys_as_titles(self, aggregator):
        """Should format snake_case keys as Title Case."""
        before = {"daily_budget": 100}
        after = {"daily_budget": 200}

        diff = aggregator._compute_state_diff(before, after)

        assert "Daily Budget" in diff


class TestSanitizeErrorMessage:
    """Tests for _sanitize_error_message helper method."""

    def test_redacts_api_keys(self, aggregator):
        """Should redact API keys from error messages."""
        error = "Error: api_key=sk_live_12345abcdef"
        sanitized = aggregator._sanitize_error_message(error)

        assert "sk_live_12345abcdef" not in sanitized
        assert "api_key=***" in sanitized

    def test_redacts_bearer_tokens(self, aggregator):
        """Should redact Bearer tokens from error messages."""
        error = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        sanitized = aggregator._sanitize_error_message(error)

        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in sanitized
        assert "Bearer ***" in sanitized

    def test_redacts_passwords(self, aggregator):
        """Should redact passwords from error messages."""
        error = "Connection failed: password=mysecretpassword"
        sanitized = aggregator._sanitize_error_message(error)

        assert "mysecretpassword" not in sanitized
        assert "password=***" in sanitized

    def test_redacts_connection_strings(self, aggregator):
        """Should redact database connection strings."""
        error = "Failed to connect: postgresql://user:pass@host:5432/db"
        sanitized = aggregator._sanitize_error_message(error)

        assert "user:pass" not in sanitized
        assert "postgresql://***" in sanitized

    def test_redacts_internal_ips(self, aggregator):
        """Should redact internal IP addresses."""
        error = "Connection refused: 192.168.1.100:5432"
        sanitized = aggregator._sanitize_error_message(error)

        assert "192.168.1.100" not in sanitized
        assert "***" in sanitized

    def test_redacts_file_paths(self, aggregator):
        """Should redact file system paths."""
        error = "File not found: /home/user/credentials/secret.json"
        sanitized = aggregator._sanitize_error_message(error)

        assert "/home/user" not in sanitized

    def test_truncates_long_messages(self, aggregator):
        """Should truncate messages longer than 500 characters."""
        long_error = "x" * 1000
        sanitized = aggregator._sanitize_error_message(long_error)

        assert len(sanitized) <= 503  # 500 + "..."
        assert sanitized.endswith("...")

    def test_handles_none_input(self, aggregator):
        """Should handle None input gracefully."""
        sanitized = aggregator._sanitize_error_message(None)
        assert sanitized is None

    def test_handles_empty_string(self, aggregator):
        """Should handle empty string input."""
        sanitized = aggregator._sanitize_error_message("")
        assert sanitized == ""


class TestSanitizeTargetName:
    """Tests for _sanitize_target_name helper method."""

    def test_redacts_email_addresses(self, aggregator):
        """Should redact email addresses from target names."""
        target = "Campaign for user@example.com"
        sanitized = aggregator._sanitize_target_name(target)

        assert "user@example.com" not in sanitized
        assert "***" in sanitized

    def test_redacts_long_numbers(self, aggregator):
        """Should redact long numeric identifiers."""
        target = "Campaign 1234567890123456"
        sanitized = aggregator._sanitize_target_name(target)

        assert "1234567890123456" not in sanitized
        assert "***" in sanitized

    def test_handles_none_input(self, aggregator):
        """Should return default for None input."""
        sanitized = aggregator._sanitize_target_name(None)
        assert sanitized == "Unknown target"

    def test_handles_normal_names(self, aggregator):
        """Should preserve normal target names."""
        target = "Summer Sale 2024"
        sanitized = aggregator._sanitize_target_name(target)

        assert sanitized == "Summer Sale 2024"
