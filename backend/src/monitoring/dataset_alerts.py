"""
Dataset sync and health alerting.

Dispatches operator alerts when canonical datasets have issues:
- Sync failure      → Slack #analytics-ops (immediate)
- Compatibility failure → Slack + PagerDuty (blocking schema change)
- Stale dataset     → Slack (dataset not synced beyond SLA)

Follows the same patterns as monitoring/freshness_alerts.py.

Configuration: backend/src/platform/alert_rules.yaml (OPS.001)
Environment variables:
- SLACK_DATASET_WEBHOOK_URL: Slack webhook for dataset alerts
- PAGERDUTY_DATASET_ROUTING_KEY: PagerDuty routing key

Story 5.2.9 — Operator Alerting
"""

import os
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

import httpx

logger = logging.getLogger(__name__)

_SLACK_WEBHOOK_URL = os.getenv("SLACK_DATASET_WEBHOOK_URL", "")
_PAGERDUTY_ROUTING_KEY = os.getenv("PAGERDUTY_DATASET_ROUTING_KEY", "")
_ALERT_COOLDOWN_SECONDS = 300  # 5 min cooldown per dataset per alert type


class DatasetAlertType(str, Enum):
    """Types of dataset-level alerts."""

    SYNC_FAILURE = "dataset.sync.failure"
    COMPATIBILITY_FAILURE = "dataset.compatibility.failure"
    STALE_DATASET = "dataset.stale"
    VERSION_ROLLED_BACK = "dataset.version.rolled_back"


class DatasetAlertSeverity(str, Enum):
    """Alert severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Severity mapping per alert type
_SEVERITY_MAP: dict[DatasetAlertType, DatasetAlertSeverity] = {
    DatasetAlertType.SYNC_FAILURE: DatasetAlertSeverity.HIGH,
    DatasetAlertType.COMPATIBILITY_FAILURE: DatasetAlertSeverity.CRITICAL,
    DatasetAlertType.STALE_DATASET: DatasetAlertSeverity.MEDIUM,
    DatasetAlertType.VERSION_ROLLED_BACK: DatasetAlertSeverity.HIGH,
}


@dataclass(frozen=True)
class DatasetAlert:
    """Immutable alert payload."""

    alert_type: DatasetAlertType
    severity: DatasetAlertSeverity
    dataset_name: str
    message: str
    details: dict
    timestamp: str


# ---------------------------------------------------------------------------
# Cooldown tracking (in-memory; resets on process restart)
# ---------------------------------------------------------------------------

_last_alert_times: dict[str, datetime] = {}


def _is_cooled_down(dataset_name: str, alert_type: DatasetAlertType) -> bool:
    """Check whether this alert type for this dataset is still in cooldown."""
    key = f"{dataset_name}:{alert_type.value}"
    last = _last_alert_times.get(key)
    if last is None:
        return True
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return elapsed >= _ALERT_COOLDOWN_SECONDS


def _record_alert(dataset_name: str, alert_type: DatasetAlertType) -> None:
    """Record that an alert was sent (for cooldown)."""
    key = f"{dataset_name}:{alert_type.value}"
    _last_alert_times[key] = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Slack notification
# ---------------------------------------------------------------------------

def _send_slack_alert(alert: DatasetAlert) -> bool:
    """Send alert to Slack #analytics-ops channel."""
    if not _SLACK_WEBHOOK_URL:
        logger.debug("dataset_alerts.slack_not_configured")
        return False

    emoji = {
        DatasetAlertSeverity.LOW: ":information_source:",
        DatasetAlertSeverity.MEDIUM: ":warning:",
        DatasetAlertSeverity.HIGH: ":rotating_light:",
        DatasetAlertSeverity.CRITICAL: ":fire:",
    }.get(alert.severity, ":warning:")

    payload = {
        "text": f"{emoji} *{alert.alert_type.value}* — `{alert.dataset_name}`",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Dataset Alert: {alert.dataset_name}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Type:* {alert.alert_type.value}"},
                    {"type": "mrkdwn", "text": f"*Severity:* {alert.severity.value}"},
                    {"type": "mrkdwn", "text": f"*Message:* {alert.message}"},
                    {"type": "mrkdwn", "text": f"*Time:* {alert.timestamp}"},
                ],
            },
        ],
    }

    try:
        response = httpx.post(_SLACK_WEBHOOK_URL, json=payload, timeout=10.0)
        response.raise_for_status()
        return True
    except Exception:
        logger.warning(
            "dataset_alerts.slack_send_failed",
            extra={"dataset_name": alert.dataset_name},
            exc_info=True,
        )
        return False


# ---------------------------------------------------------------------------
# PagerDuty escalation
# ---------------------------------------------------------------------------

def _send_pagerduty_alert(alert: DatasetAlert) -> bool:
    """Escalate to PagerDuty for critical alerts."""
    if not _PAGERDUTY_ROUTING_KEY:
        logger.debug("dataset_alerts.pagerduty_not_configured")
        return False

    pd_severity = {
        DatasetAlertSeverity.LOW: "info",
        DatasetAlertSeverity.MEDIUM: "warning",
        DatasetAlertSeverity.HIGH: "error",
        DatasetAlertSeverity.CRITICAL: "critical",
    }.get(alert.severity, "warning")

    payload = {
        "routing_key": _PAGERDUTY_ROUTING_KEY,
        "event_action": "trigger",
        "payload": {
            "summary": f"[{alert.dataset_name}] {alert.message}",
            "severity": pd_severity,
            "source": "dataset-sync",
            "component": alert.dataset_name,
            "custom_details": alert.details,
        },
    }

    try:
        response = httpx.post(
            "https://events.pagerduty.com/v2/enqueue",
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        return True
    except Exception:
        logger.warning(
            "dataset_alerts.pagerduty_send_failed",
            extra={"dataset_name": alert.dataset_name},
            exc_info=True,
        )
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def dispatch_alert(
    alert_type: DatasetAlertType,
    dataset_name: str,
    message: str,
    details: dict | None = None,
) -> bool:
    """
    Dispatch a dataset alert to the appropriate channels.

    Respects cooldown to avoid alert fatigue. Critical alerts always
    escalate to PagerDuty.

    Returns True if at least one channel received the alert.
    """
    if not _is_cooled_down(dataset_name, alert_type):
        logger.debug(
            "dataset_alerts.cooled_down",
            extra={"dataset_name": dataset_name, "alert_type": alert_type.value},
        )
        return False

    severity = _SEVERITY_MAP.get(alert_type, DatasetAlertSeverity.MEDIUM)
    alert = DatasetAlert(
        alert_type=alert_type,
        severity=severity,
        dataset_name=dataset_name,
        message=message,
        details=details or {},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    sent = False

    # Always send to Slack
    if _send_slack_alert(alert):
        sent = True

    # Escalate HIGH/CRITICAL to PagerDuty
    if severity in (DatasetAlertSeverity.HIGH, DatasetAlertSeverity.CRITICAL):
        if _send_pagerduty_alert(alert):
            sent = True

    if sent:
        _record_alert(dataset_name, alert_type)

    logger.info(
        "dataset_alerts.dispatched",
        extra={
            "dataset_name": dataset_name,
            "alert_type": alert_type.value,
            "severity": severity.value,
            "sent": sent,
        },
    )
    return sent


def alert_sync_failure(
    dataset_name: str,
    error: str,
    retry_count: int = 0,
    will_retry: bool = False,
) -> bool:
    """Alert on dataset sync failure."""
    return dispatch_alert(
        DatasetAlertType.SYNC_FAILURE,
        dataset_name,
        f"Sync failed: {error}",
        {
            "error": error,
            "retry_count": retry_count,
            "will_retry": will_retry,
        },
    )


def alert_compatibility_failure(
    dataset_name: str,
    reason: str,
    removed_columns: list[str] | None = None,
) -> bool:
    """Alert on schema compatibility failure (blocking)."""
    return dispatch_alert(
        DatasetAlertType.COMPATIBILITY_FAILURE,
        dataset_name,
        f"Schema incompatible: {reason}",
        {
            "reason": reason,
            "removed_columns": removed_columns or [],
            "action_required": "Review schema changes and re-run sync with --force if intended",
        },
    )


def alert_stale_dataset(
    dataset_name: str,
    last_sync_at: str | None,
    stale_minutes: int,
    sla_minutes: int,
) -> bool:
    """Alert when a dataset exceeds its freshness SLA."""
    return dispatch_alert(
        DatasetAlertType.STALE_DATASET,
        dataset_name,
        f"Dataset stale for {stale_minutes} minutes (SLA: {sla_minutes}m)",
        {
            "last_sync_at": last_sync_at,
            "stale_minutes": stale_minutes,
            "sla_minutes": sla_minutes,
        },
    )


def alert_version_rolled_back(
    dataset_name: str,
    rolled_back_version: str,
    restored_version: str,
) -> bool:
    """Alert when a dataset version is rolled back."""
    return dispatch_alert(
        DatasetAlertType.VERSION_ROLLED_BACK,
        dataset_name,
        f"Version {rolled_back_version} rolled back → {restored_version}",
        {
            "rolled_back_version": rolled_back_version,
            "restored_version": restored_version,
        },
    )
