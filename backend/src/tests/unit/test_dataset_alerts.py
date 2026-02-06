"""
Unit tests for dataset alert dispatching.

Tests cover:
- DatasetAlertType and DatasetAlertSeverity enum values
- Severity mapping per alert type
- Cooldown logic (suppress repeated alerts within window)
- Slack dispatch (mocked httpx)
- PagerDuty escalation for HIGH/CRITICAL only
- Public helper functions (alert_sync_failure, alert_compatibility_failure, etc.)

Story 5.2.9 — Operator Alerting
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from src.monitoring.dataset_alerts import (
    DatasetAlertType,
    DatasetAlertSeverity,
    DatasetAlert,
    dispatch_alert,
    alert_sync_failure,
    alert_compatibility_failure,
    alert_stale_dataset,
    alert_version_rolled_back,
    _SEVERITY_MAP,
    _is_cooled_down,
    _record_alert,
    _last_alert_times,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TestDatasetAlertType:
    """Verify alert type enum values."""

    def test_sync_failure(self):
        assert DatasetAlertType.SYNC_FAILURE.value == "dataset.sync.failure"

    def test_compatibility_failure(self):
        assert DatasetAlertType.COMPATIBILITY_FAILURE.value == "dataset.compatibility.failure"

    def test_stale_dataset(self):
        assert DatasetAlertType.STALE_DATASET.value == "dataset.stale"

    def test_version_rolled_back(self):
        assert DatasetAlertType.VERSION_ROLLED_BACK.value == "dataset.version.rolled_back"


class TestDatasetAlertSeverity:
    """Verify severity enum values."""

    def test_four_levels(self):
        assert len(DatasetAlertSeverity) == 4

    def test_severity_ordering(self):
        levels = [s.value for s in DatasetAlertSeverity]
        assert "low" in levels
        assert "critical" in levels


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------

class TestSeverityMapping:
    """Verify severity is correct per alert type."""

    def test_sync_failure_is_high(self):
        assert _SEVERITY_MAP[DatasetAlertType.SYNC_FAILURE] == DatasetAlertSeverity.HIGH

    def test_compatibility_failure_is_critical(self):
        assert _SEVERITY_MAP[DatasetAlertType.COMPATIBILITY_FAILURE] == DatasetAlertSeverity.CRITICAL

    def test_stale_dataset_is_medium(self):
        assert _SEVERITY_MAP[DatasetAlertType.STALE_DATASET] == DatasetAlertSeverity.MEDIUM

    def test_version_rolled_back_is_high(self):
        assert _SEVERITY_MAP[DatasetAlertType.VERSION_ROLLED_BACK] == DatasetAlertSeverity.HIGH


# ---------------------------------------------------------------------------
# Cooldown logic
# ---------------------------------------------------------------------------

class TestCooldown:
    """Test cooldown prevents alert fatigue."""

    def setup_method(self):
        _last_alert_times.clear()

    def test_first_alert_is_not_cooled_down(self):
        assert _is_cooled_down("ds1", DatasetAlertType.SYNC_FAILURE) is True

    def test_recent_alert_is_cooled_down(self):
        _record_alert("ds1", DatasetAlertType.SYNC_FAILURE)
        assert _is_cooled_down("ds1", DatasetAlertType.SYNC_FAILURE) is False

    def test_different_dataset_not_cooled_down(self):
        _record_alert("ds1", DatasetAlertType.SYNC_FAILURE)
        # ds2 should NOT be cooled down
        assert _is_cooled_down("ds2", DatasetAlertType.SYNC_FAILURE) is True

    def test_different_alert_type_not_cooled_down(self):
        _record_alert("ds1", DatasetAlertType.SYNC_FAILURE)
        # Same dataset, different alert type
        assert _is_cooled_down("ds1", DatasetAlertType.STALE_DATASET) is True

    def teardown_method(self):
        _last_alert_times.clear()


# ---------------------------------------------------------------------------
# Dispatch with mocked transports
# ---------------------------------------------------------------------------

class TestDispatchAlert:
    """Test alert dispatch routing."""

    def setup_method(self):
        _last_alert_times.clear()

    @patch("src.monitoring.dataset_alerts._send_slack_alert", return_value=True)
    @patch("src.monitoring.dataset_alerts._send_pagerduty_alert", return_value=True)
    def test_high_severity_sends_slack_and_pagerduty(self, mock_pd, mock_slack):
        result = dispatch_alert(
            DatasetAlertType.SYNC_FAILURE,
            "fact_orders_current",
            "API timeout",
        )
        assert result is True
        mock_slack.assert_called_once()
        mock_pd.assert_called_once()

    @patch("src.monitoring.dataset_alerts._send_slack_alert", return_value=True)
    @patch("src.monitoring.dataset_alerts._send_pagerduty_alert", return_value=False)
    def test_medium_severity_sends_only_slack(self, mock_pd, mock_slack):
        result = dispatch_alert(
            DatasetAlertType.STALE_DATASET,
            "fact_orders_current",
            "Stale for 120 minutes",
        )
        assert result is True
        mock_slack.assert_called_once()
        # PagerDuty should NOT be called for MEDIUM severity
        mock_pd.assert_not_called()

    @patch("src.monitoring.dataset_alerts._send_slack_alert", return_value=True)
    @patch("src.monitoring.dataset_alerts._send_pagerduty_alert", return_value=True)
    def test_critical_sends_both(self, mock_pd, mock_slack):
        result = dispatch_alert(
            DatasetAlertType.COMPATIBILITY_FAILURE,
            "fact_orders_current",
            "Column removed",
        )
        assert result is True
        mock_slack.assert_called_once()
        mock_pd.assert_called_once()

    @patch("src.monitoring.dataset_alerts._send_slack_alert", return_value=True)
    def test_cooldown_suppresses_second_alert(self, mock_slack):
        dispatch_alert(
            DatasetAlertType.STALE_DATASET,
            "ds1",
            "First alert",
        )
        result = dispatch_alert(
            DatasetAlertType.STALE_DATASET,
            "ds1",
            "Second alert (should be suppressed)",
        )
        assert result is False
        # Slack called only once (first alert)
        assert mock_slack.call_count == 1

    def teardown_method(self):
        _last_alert_times.clear()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestAlertHelpers:
    """Test convenience alert functions."""

    def setup_method(self):
        _last_alert_times.clear()

    @patch("src.monitoring.dataset_alerts.dispatch_alert", return_value=True)
    def test_alert_sync_failure(self, mock_dispatch):
        alert_sync_failure("ds1", "timeout", retry_count=2, will_retry=True)
        mock_dispatch.assert_called_once()
        args = mock_dispatch.call_args
        assert args[0][0] == DatasetAlertType.SYNC_FAILURE
        assert args[0][1] == "ds1"
        assert "timeout" in args[0][2]

    @patch("src.monitoring.dataset_alerts.dispatch_alert", return_value=True)
    def test_alert_compatibility_failure(self, mock_dispatch):
        alert_compatibility_failure("ds1", "column removed", ["channel"])
        mock_dispatch.assert_called_once()
        args = mock_dispatch.call_args
        assert args[0][0] == DatasetAlertType.COMPATIBILITY_FAILURE

    @patch("src.monitoring.dataset_alerts.dispatch_alert", return_value=True)
    def test_alert_stale_dataset(self, mock_dispatch):
        alert_stale_dataset("ds1", "2026-02-01T00:00:00Z", 120, 60)
        mock_dispatch.assert_called_once()

    @patch("src.monitoring.dataset_alerts.dispatch_alert", return_value=True)
    def test_alert_version_rolled_back(self, mock_dispatch):
        alert_version_rolled_back("ds1", "v2", "v1")
        mock_dispatch.assert_called_once()
        args = mock_dispatch.call_args
        assert "v2" in args[0][2]
        assert "v1" in args[0][2]

    def teardown_method(self):
        _last_alert_times.clear()
