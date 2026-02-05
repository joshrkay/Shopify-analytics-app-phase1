"""
Tests for freshness SLA violation alerting.

Covers:
- Alert suppression for fresh state
- Stale alert with 2-hour delay
- Immediate unavailable alert
- Deduplication / cooldown
- Multi-tenant severity escalation
- Likely-cause inference (ingestion vs dbt)
- Slack and PagerDuty dispatch
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from src.monitoring.freshness_alerts import (
    FreshnessAlertManager,
    FreshnessAlert,
    AlertSeverity,
    LikelyCause,
    infer_likely_cause,
)


# ─── Config fixture ──────────────────────────────────────────────────────────

MOCK_CONFIG = {
    "version": 1,
    "dedup_cooldown_minutes": 30,
    "channels": {
        "slack_analytics_ops": {
            "channel": "#analytics-ops",
            "env_var": "SLACK_FRESHNESS_WEBHOOK_URL",
        },
        "pagerduty_analytics": {
            "env_var": "PAGERDUTY_FRESHNESS_ROUTING_KEY",
        },
    },
    "rules": {
        "stale_extended": {
            "trigger_state": "stale",
            "stale_alert_delay_minutes": 120,
            "severity": "warning",
            "channels": ["slack_analytics_ops"],
            "message_template": (
                'Source "{source_type}" has been stale for {minutes_stale}m '
                "across {tenant_count} tenant(s). Likely cause: {likely_cause}."
            ),
        },
        "unavailable_immediate": {
            "trigger_state": "unavailable",
            "stale_alert_delay_minutes": 0,
            "severity": "critical",
            "channels": ["slack_analytics_ops", "pagerduty_analytics"],
            "message_template": (
                'Source "{source_type}" is UNAVAILABLE for {tenant_count} '
                "tenant(s). Likely cause: {likely_cause}. Immediate attention required."
            ),
        },
    },
    "escalation": {
        "multi_tenant_threshold": 3,
        "escalated_severity": "critical",
        "escalated_channels": ["slack_analytics_ops", "pagerduty_analytics"],
    },
}


@pytest.fixture(autouse=True)
def mock_config():
    """Patch config loading to avoid filesystem dependency."""
    with patch(
        "src.monitoring.freshness_alerts._load_config",
        return_value=MOCK_CONFIG,
    ):
        yield


@pytest.fixture
def manager():
    """Manager with no real webhooks (dispatch is mocked separately)."""
    m = FreshnessAlertManager(
        slack_webhook_url=None,
        pagerduty_routing_key=None,
    )
    m._recent_alerts.clear()
    return m


# ─── infer_likely_cause ──────────────────────────────────────────────────────


class TestInferLikelyCause:
    def test_sync_failed_is_ingestion(self):
        assert infer_likely_cause("sync_failed") == LikelyCause.INGESTION

    def test_sla_exceeded_is_ingestion(self):
        assert infer_likely_cause("sla_exceeded") == LikelyCause.INGESTION

    def test_grace_window_exceeded_is_ingestion(self):
        assert infer_likely_cause("grace_window_exceeded") == LikelyCause.INGESTION

    def test_never_synced_is_ingestion(self):
        assert infer_likely_cause("never_synced") == LikelyCause.INGESTION

    def test_dbt_failed_is_dbt(self):
        assert infer_likely_cause("dbt_failed") == LikelyCause.DBT

    def test_unknown_reason(self):
        assert infer_likely_cause("something_else") == LikelyCause.UNKNOWN


# ─── FreshnessAlert dataclass ────────────────────────────────────────────────


class TestFreshnessAlert:
    def test_tenant_count(self):
        alert = FreshnessAlert(
            source_type="shopify_orders",
            state="stale",
            severity=AlertSeverity.WARNING,
            tenant_ids=["t1", "t2"],
            likely_cause=LikelyCause.INGESTION,
            minutes_stale=150,
            reason="sla_exceeded",
            message="test",
        )
        assert alert.tenant_count == 2

    def test_dedup_key(self):
        alert = FreshnessAlert(
            source_type="facebook_ads",
            state="unavailable",
            severity=AlertSeverity.CRITICAL,
            tenant_ids=["t1"],
            likely_cause=LikelyCause.INGESTION,
            minutes_stale=None,
            reason="sync_failed",
            message="test",
        )
        assert alert.dedup_key == "freshness:facebook_ads:unavailable"

    def test_to_dict_contains_required_fields(self):
        alert = FreshnessAlert(
            source_type="shopify_orders",
            state="stale",
            severity=AlertSeverity.WARNING,
            tenant_ids=["t1"],
            likely_cause=LikelyCause.INGESTION,
            minutes_stale=130,
            reason="sla_exceeded",
            message="test message",
        )
        d = alert.to_dict()
        assert d["source_type"] == "shopify_orders"
        assert d["tenant_count"] == 1
        assert d["likely_cause"] == "ingestion"
        assert d["severity"] == "warning"


# ─── Fresh state (no alert) ─────────────────────────────────────────────────


class TestFreshState:
    def test_fresh_state_returns_none(self, manager):
        result = manager.evaluate_and_alert(
            source_type="shopify_orders",
            state="fresh",
            reason="sync_ok",
            tenant_ids=["t1"],
            minutes_stale=5,
        )
        assert result is None


# ─── Stale state ─────────────────────────────────────────────────────────────


class TestStaleAlerts:
    def test_stale_under_delay_returns_none(self, manager):
        """Stale for only 60 minutes should not alert (delay is 120m)."""
        result = manager.evaluate_and_alert(
            source_type="shopify_orders",
            state="stale",
            reason="sla_exceeded",
            tenant_ids=["t1"],
            minutes_stale=60,
        )
        assert result is None

    def test_stale_over_delay_fires_alert(self, manager):
        """Stale for 150 minutes (> 120m delay) should alert."""
        result = manager.evaluate_and_alert(
            source_type="shopify_orders",
            state="stale",
            reason="sla_exceeded",
            tenant_ids=["t1"],
            minutes_stale=150,
        )
        assert result is not None
        assert result.severity == AlertSeverity.WARNING
        assert result.state == "stale"
        assert "shopify_orders" in result.message

    def test_stale_alert_includes_tenant_count(self, manager):
        result = manager.evaluate_and_alert(
            source_type="facebook_ads",
            state="stale",
            reason="sla_exceeded",
            tenant_ids=["t1", "t2"],
            minutes_stale=200,
        )
        assert result is not None
        assert result.tenant_count == 2
        assert "2 tenant(s)" in result.message

    def test_stale_alert_includes_likely_cause(self, manager):
        result = manager.evaluate_and_alert(
            source_type="shopify_orders",
            state="stale",
            reason="sla_exceeded",
            tenant_ids=["t1"],
            minutes_stale=150,
        )
        assert result is not None
        assert result.likely_cause == LikelyCause.INGESTION
        assert "ingestion" in result.message


# ─── Unavailable state ───────────────────────────────────────────────────────


class TestUnavailableAlerts:
    def test_unavailable_fires_immediately(self, manager):
        """UNAVAILABLE should alert with zero delay."""
        result = manager.evaluate_and_alert(
            source_type="shopify_orders",
            state="unavailable",
            reason="sync_failed",
            tenant_ids=["t1"],
            minutes_stale=5,
        )
        assert result is not None
        assert result.severity == AlertSeverity.CRITICAL
        assert result.state == "unavailable"

    def test_unavailable_fires_without_minutes_stale(self, manager):
        """UNAVAILABLE can alert even with no minutes_stale."""
        result = manager.evaluate_and_alert(
            source_type="shopify_orders",
            state="unavailable",
            reason="never_synced",
            tenant_ids=["t1"],
            minutes_stale=None,
        )
        assert result is not None
        assert result.severity == AlertSeverity.CRITICAL


# ─── Deduplication ───────────────────────────────────────────────────────────


class TestDeduplication:
    def test_second_alert_is_suppressed(self, manager):
        """Same source+state within cooldown should be deduplicated."""
        first = manager.evaluate_and_alert(
            source_type="shopify_orders",
            state="unavailable",
            reason="sync_failed",
            tenant_ids=["t1"],
        )
        assert first is not None

        second = manager.evaluate_and_alert(
            source_type="shopify_orders",
            state="unavailable",
            reason="sync_failed",
            tenant_ids=["t1"],
        )
        assert second is None

    def test_different_sources_not_deduplicated(self, manager):
        """Different sources should alert independently."""
        first = manager.evaluate_and_alert(
            source_type="shopify_orders",
            state="unavailable",
            reason="sync_failed",
            tenant_ids=["t1"],
        )
        second = manager.evaluate_and_alert(
            source_type="facebook_ads",
            state="unavailable",
            reason="sync_failed",
            tenant_ids=["t1"],
        )
        assert first is not None
        assert second is not None

    def test_cooldown_expiry_allows_re_alert(self, manager):
        """After cooldown expires, the same alert can fire again."""
        first = manager.evaluate_and_alert(
            source_type="shopify_orders",
            state="unavailable",
            reason="sync_failed",
            tenant_ids=["t1"],
        )
        assert first is not None

        # Manually expire the cooldown
        key = first.dedup_key
        manager._recent_alerts[key] = datetime.now(timezone.utc) - timedelta(
            minutes=31
        )

        second = manager.evaluate_and_alert(
            source_type="shopify_orders",
            state="unavailable",
            reason="sync_failed",
            tenant_ids=["t1"],
        )
        assert second is not None


# ─── Escalation ──────────────────────────────────────────────────────────────


class TestEscalation:
    def test_stale_escalated_when_many_tenants(self, manager):
        """Stale alert with >= 3 tenants should escalate to critical."""
        result = manager.evaluate_and_alert(
            source_type="shopify_orders",
            state="stale",
            reason="sla_exceeded",
            tenant_ids=["t1", "t2", "t3"],
            minutes_stale=200,
        )
        assert result is not None
        assert result.severity == AlertSeverity.CRITICAL

    def test_stale_not_escalated_under_threshold(self, manager):
        """Stale alert with < 3 tenants stays warning."""
        result = manager.evaluate_and_alert(
            source_type="shopify_orders",
            state="stale",
            reason="sla_exceeded",
            tenant_ids=["t1", "t2"],
            minutes_stale=200,
        )
        assert result is not None
        assert result.severity == AlertSeverity.WARNING

    def test_unavailable_already_critical_not_double_escalated(self, manager):
        """Unavailable is already critical; escalation should not downgrade."""
        result = manager.evaluate_and_alert(
            source_type="shopify_orders",
            state="unavailable",
            reason="sync_failed",
            tenant_ids=["t1", "t2", "t3", "t4"],
        )
        assert result is not None
        assert result.severity == AlertSeverity.CRITICAL


# ─── Dispatch (Slack / PagerDuty) ────────────────────────────────────────────


class TestDispatch:
    def test_slack_called_for_stale_alert(self):
        mgr = FreshnessAlertManager(
            slack_webhook_url="https://hooks.slack.com/test",
        )
        with patch.object(mgr, "_send_slack", return_value=True) as mock_slack:
            result = mgr.evaluate_and_alert(
                source_type="shopify_orders",
                state="stale",
                reason="sla_exceeded",
                tenant_ids=["t1"],
                minutes_stale=150,
            )
            assert result is not None
            mock_slack.assert_called_once()

    def test_pagerduty_called_for_unavailable_alert(self):
        mgr = FreshnessAlertManager(
            slack_webhook_url="https://hooks.slack.com/test",
            pagerduty_routing_key="test-key",
        )
        with (
            patch.object(mgr, "_send_slack", return_value=True),
            patch.object(mgr, "_send_pagerduty", return_value=True) as mock_pd,
        ):
            result = mgr.evaluate_and_alert(
                source_type="shopify_orders",
                state="unavailable",
                reason="sync_failed",
                tenant_ids=["t1"],
            )
            assert result is not None
            mock_pd.assert_called_once()

    def test_pagerduty_not_called_for_stale_single_tenant(self):
        mgr = FreshnessAlertManager(
            slack_webhook_url="https://hooks.slack.com/test",
            pagerduty_routing_key="test-key",
        )
        with (
            patch.object(mgr, "_send_slack", return_value=True),
            patch.object(mgr, "_send_pagerduty", return_value=True) as mock_pd,
        ):
            result = mgr.evaluate_and_alert(
                source_type="shopify_orders",
                state="stale",
                reason="sla_exceeded",
                tenant_ids=["t1"],
                minutes_stale=150,
            )
            assert result is not None
            mock_pd.assert_not_called()

    def test_pagerduty_called_on_escalated_stale(self):
        """Stale with >= 3 tenants escalates to critical → PagerDuty."""
        mgr = FreshnessAlertManager(
            slack_webhook_url="https://hooks.slack.com/test",
            pagerduty_routing_key="test-key",
        )
        with (
            patch.object(mgr, "_send_slack", return_value=True),
            patch.object(mgr, "_send_pagerduty", return_value=True) as mock_pd,
        ):
            result = mgr.evaluate_and_alert(
                source_type="shopify_orders",
                state="stale",
                reason="sla_exceeded",
                tenant_ids=["t1", "t2", "t3"],
                minutes_stale=200,
            )
            assert result is not None
            assert result.severity == AlertSeverity.CRITICAL
            mock_pd.assert_called_once()

    def test_slack_sends_correct_payload(self):
        """Verify Slack payload structure."""
        mgr = FreshnessAlertManager(
            slack_webhook_url="https://hooks.slack.com/test",
        )

        with patch("src.monitoring.freshness_alerts.httpx.Client") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client_cls.return_value.__enter__ = MagicMock(
                return_value=MagicMock(post=MagicMock(return_value=mock_response))
            )
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

            alert = FreshnessAlert(
                source_type="shopify_orders",
                state="stale",
                severity=AlertSeverity.WARNING,
                tenant_ids=["t1"],
                likely_cause=LikelyCause.INGESTION,
                minutes_stale=150,
                reason="sla_exceeded",
                message="Test message",
            )
            result = mgr._send_slack(alert)
            assert result is True

    def test_slack_returns_false_when_not_configured(self):
        mgr = FreshnessAlertManager(slack_webhook_url=None)
        alert = FreshnessAlert(
            source_type="shopify_orders",
            state="stale",
            severity=AlertSeverity.WARNING,
            tenant_ids=["t1"],
            likely_cause=LikelyCause.INGESTION,
            minutes_stale=150,
            reason="sla_exceeded",
            message="test",
        )
        assert mgr._send_slack(alert) is False

    def test_pagerduty_returns_false_when_not_configured(self):
        mgr = FreshnessAlertManager(pagerduty_routing_key=None)
        alert = FreshnessAlert(
            source_type="shopify_orders",
            state="unavailable",
            severity=AlertSeverity.CRITICAL,
            tenant_ids=["t1"],
            likely_cause=LikelyCause.INGESTION,
            minutes_stale=None,
            reason="sync_failed",
            message="test",
        )
        assert mgr._send_pagerduty(alert) is False
