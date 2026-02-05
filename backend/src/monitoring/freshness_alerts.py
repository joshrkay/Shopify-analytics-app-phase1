"""
Freshness SLA violation alerting.

Monitors data availability state and dispatches alerts when SLAs are violated:
- STALE > 2 hours  → Slack #analytics-ops
- UNAVAILABLE       → PagerDuty (immediate)
- Multi-tenant      → escalate severity

Follows the same patterns as monitoring/alerts.py (AlertManager)
and api/dq/alerts/slack.py (SlackNotifier).

Configuration: config/alert_thresholds.yml
Environment variables:
- SLACK_FRESHNESS_WEBHOOK_URL: Slack webhook for #analytics-ops
- PAGERDUTY_FRESHNESS_ROUTING_KEY: PagerDuty routing key
"""

import os
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any

import httpx

from src.governance.base import load_yaml_config

logger = logging.getLogger(__name__)

# ─── Config loading ──────────────────────────────────────────────────────────

_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "alert_thresholds.yml"
)
_config_cache: Optional[dict] = None


def _load_config() -> dict:
    """Load and cache alert thresholds config."""
    global _config_cache
    if _config_cache is None:
        _config_cache = load_yaml_config(_CONFIG_PATH, logger=logger)
    return _config_cache


def _get_rule(rule_name: str) -> dict:
    """Get a specific alert rule from config."""
    config = _load_config()
    return config.get("rules", {}).get(rule_name, {})


def _get_escalation() -> dict:
    """Get escalation config."""
    config = _load_config()
    return config.get("escalation", {})


def _get_cooldown_minutes() -> int:
    """Get dedup cooldown in minutes."""
    config = _load_config()
    return config.get("dedup_cooldown_minutes", 30)


# ─── Types ───────────────────────────────────────────────────────────────────


class AlertSeverity(str, Enum):
    WARNING = "warning"
    CRITICAL = "critical"


class LikelyCause(str, Enum):
    INGESTION = "ingestion"
    DBT = "dbt_transformation"
    UNKNOWN = "unknown"


@dataclass
class FreshnessAlert:
    """A freshness SLA violation alert ready for dispatch."""

    source_type: str
    state: str
    severity: AlertSeverity
    tenant_ids: List[str]
    likely_cause: LikelyCause
    minutes_stale: Optional[int]
    reason: str
    message: str
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def tenant_count(self) -> int:
        return len(self.tenant_ids)

    @property
    def dedup_key(self) -> str:
        return f"freshness:{self.source_type}:{self.state}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "state": self.state,
            "severity": self.severity.value,
            "tenant_count": self.tenant_count,
            "likely_cause": self.likely_cause.value,
            "minutes_stale": self.minutes_stale,
            "reason": self.reason,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


# ─── Cause inference ─────────────────────────────────────────────────────────


def infer_likely_cause(reason: str) -> LikelyCause:
    """
    Infer whether the root cause is ingestion or transformation.

    Reason codes come from the DataAvailability state machine:
    - sync_failed, sla_exceeded, grace_window_exceeded → ingestion
    - dbt_failed → dbt transformation
    - never_synced → ingestion (no data ever arrived)
    """
    ingestion_reasons = {
        "sync_failed",
        "sla_exceeded",
        "grace_window_exceeded",
        "never_synced",
    }
    dbt_reasons = {"dbt_failed"}

    if reason in ingestion_reasons:
        return LikelyCause.INGESTION
    if reason in dbt_reasons:
        return LikelyCause.DBT
    return LikelyCause.UNKNOWN


# ─── Alert manager ───────────────────────────────────────────────────────────


class FreshnessAlertManager:
    """
    Evaluates freshness states and dispatches alerts.

    Features:
    - Deduplication via cooldown window
    - Severity escalation when multiple tenants are affected
    - Slack + PagerDuty dispatch based on config rules
    - Likely-cause inference from reason codes
    """

    def __init__(
        self,
        slack_webhook_url: Optional[str] = None,
        pagerduty_routing_key: Optional[str] = None,
    ):
        self.slack_webhook_url = (
            slack_webhook_url or os.getenv("SLACK_FRESHNESS_WEBHOOK_URL")
        )
        self.pagerduty_routing_key = (
            pagerduty_routing_key
            or os.getenv("PAGERDUTY_FRESHNESS_ROUTING_KEY")
        )
        self._recent_alerts: Dict[str, datetime] = {}

    def _should_send(self, dedup_key: str) -> bool:
        """Check cooldown for deduplication."""
        last_sent = self._recent_alerts.get(dedup_key)
        if last_sent:
            cooldown = timedelta(minutes=_get_cooldown_minutes())
            if datetime.now(timezone.utc) - last_sent < cooldown:
                logger.debug(
                    "Freshness alert suppressed (cooldown)",
                    extra={"dedup_key": dedup_key},
                )
                return False
        self._recent_alerts[dedup_key] = datetime.now(timezone.utc)
        return True

    def _apply_escalation(self, alert: FreshnessAlert) -> FreshnessAlert:
        """Escalate severity if multiple tenants are affected."""
        escalation = _get_escalation()
        threshold = escalation.get("multi_tenant_threshold", 3)

        if alert.tenant_count >= threshold:
            escalated = AlertSeverity(
                escalation.get("escalated_severity", "critical")
            )
            if escalated.value != alert.severity.value:
                logger.info(
                    "Escalating freshness alert severity",
                    extra={
                        "source_type": alert.source_type,
                        "tenant_count": alert.tenant_count,
                        "from_severity": alert.severity.value,
                        "to_severity": escalated.value,
                    },
                )
                alert.severity = escalated
        return alert

    def evaluate_and_alert(
        self,
        source_type: str,
        state: str,
        reason: str,
        tenant_ids: List[str],
        minutes_stale: Optional[int] = None,
    ) -> Optional[FreshnessAlert]:
        """
        Evaluate a source's availability state and fire alerts if needed.

        Args:
            source_type: SLA source key (e.g. "shopify_orders")
            state: Current state ("fresh", "stale", "unavailable")
            reason: Reason code from DataAvailability
            tenant_ids: List of affected tenant IDs
            minutes_stale: Minutes since last successful sync

        Returns:
            FreshnessAlert if an alert was dispatched, None otherwise.
        """
        if state == "fresh":
            return None

        likely_cause = infer_likely_cause(reason)

        if state == "stale":
            rule = _get_rule("stale_extended")
            delay = rule.get("stale_alert_delay_minutes", 120)
            if minutes_stale is not None and minutes_stale < delay:
                return None
            severity = AlertSeverity(rule.get("severity", "warning"))
        elif state == "unavailable":
            rule = _get_rule("unavailable_immediate")
            severity = AlertSeverity(rule.get("severity", "critical"))
        else:
            return None

        template = rule.get("message_template", "")
        message = template.format(
            source_type=source_type,
            minutes_stale=minutes_stale or 0,
            tenant_count=len(tenant_ids),
            likely_cause=likely_cause.value,
        )

        alert = FreshnessAlert(
            source_type=source_type,
            state=state,
            severity=severity,
            tenant_ids=tenant_ids,
            likely_cause=likely_cause,
            minutes_stale=minutes_stale,
            reason=reason,
            message=message,
        )

        alert = self._apply_escalation(alert)

        if not self._should_send(alert.dedup_key):
            return None

        self._dispatch(alert, rule)

        logger.warning(
            "Freshness SLA alert dispatched",
            extra={
                "source_type": source_type,
                "state": state,
                "severity": alert.severity.value,
                "tenant_count": alert.tenant_count,
                "likely_cause": likely_cause.value,
                "minutes_stale": minutes_stale,
            },
        )

        return alert

    def _dispatch(self, alert: FreshnessAlert, rule: dict) -> None:
        """Dispatch alert to configured channels."""
        channels = rule.get("channels", [])

        escalation = _get_escalation()
        threshold = escalation.get("multi_tenant_threshold", 3)
        if alert.tenant_count >= threshold:
            channels = list(
                set(channels)
                | set(escalation.get("escalated_channels", []))
            )

        for channel in channels:
            if channel == "slack_analytics_ops":
                self._send_slack(alert)
            elif channel == "pagerduty_analytics":
                self._send_pagerduty(alert)

    def _send_slack(self, alert: FreshnessAlert) -> bool:
        """Send alert to Slack #analytics-ops."""
        if not self.slack_webhook_url:
            logger.warning(
                "Slack freshness webhook not configured, skipping"
            )
            return False

        color = "#9c27b0" if alert.severity == AlertSeverity.CRITICAL else "#ff9800"
        emoji = (
            ":rotating_light:"
            if alert.severity == AlertSeverity.CRITICAL
            else ":warning:"
        )

        payload = {
            "attachments": [
                {
                    "color": color,
                    "title": f"{emoji} Freshness SLA Violation — {alert.source_type}",
                    "text": alert.message,
                    "fields": [
                        {"title": "State", "value": alert.state.upper(), "short": True},
                        {"title": "Severity", "value": alert.severity.value.upper(), "short": True},
                        {"title": "Affected Tenants", "value": str(alert.tenant_count), "short": True},
                        {"title": "Likely Cause", "value": alert.likely_cause.value.replace("_", " ").title(), "short": True},
                        {"title": "Minutes Stale", "value": str(alert.minutes_stale or "N/A"), "short": True},
                        {"title": "Reason", "value": alert.reason, "short": True},
                    ],
                    "footer": "Freshness Alert Monitor",
                    "ts": int(alert.timestamp.timestamp()),
                }
            ]
        }

        try:
            with httpx.Client() as client:
                response = client.post(
                    self.slack_webhook_url,
                    json=payload,
                    timeout=10.0,
                )
                if response.status_code != 200:
                    logger.error(
                        "Failed to send Slack freshness alert",
                        extra={"status_code": response.status_code},
                    )
                    return False
                return True
        except Exception as e:
            logger.error(
                "Error sending Slack freshness alert",
                extra={"error": str(e)},
            )
            return False

    def _send_pagerduty(self, alert: FreshnessAlert) -> bool:
        """Send critical alert to PagerDuty."""
        if not self.pagerduty_routing_key:
            logger.warning(
                "PagerDuty freshness routing key not configured, skipping"
            )
            return False

        payload = {
            "routing_key": self.pagerduty_routing_key,
            "event_action": "trigger",
            "dedup_key": alert.dedup_key,
            "payload": {
                "summary": (
                    f"[Freshness] {alert.source_type} is {alert.state.upper()} "
                    f"for {alert.tenant_count} tenant(s) — {alert.likely_cause.value}"
                ),
                "severity": "critical" if alert.severity == AlertSeverity.CRITICAL else "warning",
                "source": "freshness-monitor",
                "component": alert.source_type,
                "custom_details": alert.to_dict(),
            },
        }

        try:
            with httpx.Client() as client:
                response = client.post(
                    "https://events.pagerduty.com/v2/enqueue",
                    json=payload,
                    timeout=10.0,
                )
                if response.status_code not in [200, 201, 202]:
                    logger.error(
                        "Failed to send PagerDuty freshness alert",
                        extra={"status_code": response.status_code},
                    )
                    return False
                return True
        except Exception as e:
            logger.error(
                "Error sending PagerDuty freshness alert",
                extra={"error": str(e)},
            )
            return False


# ─── Singleton ───────────────────────────────────────────────────────────────

_manager: Optional[FreshnessAlertManager] = None


def get_freshness_alert_manager() -> FreshnessAlertManager:
    """Get the singleton FreshnessAlertManager instance."""
    global _manager
    if _manager is None:
        _manager = FreshnessAlertManager()
    return _manager
