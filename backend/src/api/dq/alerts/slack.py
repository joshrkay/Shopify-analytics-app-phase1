"""
Slack notifier for data quality alerts.

Sends alerts to Slack via incoming webhook.
Supports severity-based formatting and cooldown to prevent alert fatigue.

Configuration:
- SLACK_DQ_WEBHOOK_URL: Slack incoming webhook URL for #alerts channel
- SLACK_DQ_COOLDOWN_MINUTES: Cooldown period between duplicate alerts (default: 15)
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Any

import httpx

from src.api.dq.service import DQEvent, DQEventType
from src.models.dq_models import DQSeverity

logger = logging.getLogger(__name__)


class SlackNotifier:
    """
    Slack notification adapter for DQ alerts.

    Features:
    - Severity-based color coding and emoji
    - Cooldown to prevent duplicate alerts
    - Async HTTP requests
    - Graceful failure handling
    """

    # Severity to Slack color mapping
    SEVERITY_COLORS = {
        DQSeverity.WARNING: "#ff9800",  # Orange
        DQSeverity.HIGH: "#f44336",     # Red
        DQSeverity.CRITICAL: "#9c27b0",  # Purple
    }

    # Severity to emoji mapping
    SEVERITY_EMOJI = {
        DQSeverity.WARNING: ":warning:",
        DQSeverity.HIGH: ":x:",
        DQSeverity.CRITICAL: ":rotating_light:",
    }

    # Event type to emoji mapping
    EVENT_EMOJI = {
        DQEventType.FRESHNESS_FAILED: ":clock1:",
        DQEventType.ANOMALY_DETECTED: ":chart_with_downwards_trend:",
        DQEventType.SEVERE_BLOCK: ":no_entry:",
        DQEventType.RESOLVED: ":white_check_mark:",
    }

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        cooldown_minutes: int = 15,
    ):
        """
        Initialize Slack notifier.

        Args:
            webhook_url: Slack incoming webhook URL. If not provided,
                         reads from SLACK_DQ_WEBHOOK_URL environment variable.
            cooldown_minutes: Minutes to wait before sending duplicate alerts.
        """
        self.webhook_url = webhook_url or os.getenv("SLACK_DQ_WEBHOOK_URL")
        self.cooldown_minutes = int(
            os.getenv("SLACK_DQ_COOLDOWN_MINUTES", str(cooldown_minutes))
        )
        self._recent_alerts: Dict[str, datetime] = {}

    def _get_alert_key(self, event: DQEvent) -> str:
        """Generate a unique key for deduplication."""
        return f"{event.event_type.value}:{event.tenant_id}:{event.connector_id}"

    def _should_send(self, event: DQEvent) -> bool:
        """Check if alert should be sent (cooldown period)."""
        key = self._get_alert_key(event)
        last_sent = self._recent_alerts.get(key)

        if last_sent:
            cooldown = timedelta(minutes=self.cooldown_minutes)
            if datetime.now(timezone.utc) - last_sent < cooldown:
                logger.debug(
                    "Slack alert suppressed (cooldown)",
                    extra={
                        "event_type": event.event_type.value,
                        "tenant_id": event.tenant_id,
                        "connector_id": event.connector_id,
                    },
                )
                return False

        self._recent_alerts[key] = datetime.now(timezone.utc)
        return True

    def _format_title(self, event: DQEvent) -> str:
        """Format alert title with emoji."""
        event_emoji = self.EVENT_EMOJI.get(event.event_type, ":bell:")
        severity_emoji = ""
        if event.severity:
            severity_emoji = self.SEVERITY_EMOJI.get(event.severity, "")

        type_names = {
            DQEventType.FRESHNESS_FAILED: "Freshness Alert",
            DQEventType.ANOMALY_DETECTED: "Anomaly Detected",
            DQEventType.SEVERE_BLOCK: "Dashboard Blocked",
            DQEventType.RESOLVED: "Issue Resolved",
        }
        type_name = type_names.get(event.event_type, "DQ Alert")

        return f"{event_emoji} {severity_emoji} {type_name}".strip()

    def _format_color(self, event: DQEvent) -> str:
        """Get Slack attachment color based on severity."""
        if event.event_type == DQEventType.RESOLVED:
            return "#36a64f"  # Green

        if event.severity:
            return self.SEVERITY_COLORS.get(event.severity, "#808080")

        return "#808080"  # Gray

    def _format_fields(self, event: DQEvent) -> list:
        """Format Slack attachment fields."""
        fields = [
            {
                "title": "Tenant",
                "value": event.tenant_id[:20] + "..." if len(event.tenant_id) > 20 else event.tenant_id,
                "short": True,
            },
            {
                "title": "Connector",
                "value": event.connector_id[:20] + "..." if len(event.connector_id) > 20 else event.connector_id,
                "short": True,
            },
            {
                "title": "Check Type",
                "value": event.check_type.replace("_", " ").title(),
                "short": True,
            },
        ]

        if event.severity:
            fields.append({
                "title": "Severity",
                "value": event.severity.value.upper(),
                "short": True,
            })

        # Add metadata fields
        for key, value in event.metadata.items():
            if key not in ["tenant_id", "connector_id", "check_type", "severity"]:
                fields.append({
                    "title": key.replace("_", " ").title(),
                    "value": str(value)[:100],
                    "short": True,
                })

        return fields

    def _build_payload(self, event: DQEvent) -> Dict[str, Any]:
        """Build Slack webhook payload."""
        return {
            "attachments": [
                {
                    "color": self._format_color(event),
                    "title": self._format_title(event),
                    "text": event.support_details or event.message,
                    "fields": self._format_fields(event),
                    "footer": "Data Quality Monitor",
                    "ts": int(event.timestamp.timestamp()),
                }
            ]
        }

    async def send(self, event: DQEvent) -> bool:
        """
        Send a DQ event to Slack.

        Args:
            event: DQ event to send

        Returns:
            True if alert was sent successfully, False otherwise
        """
        if not self.webhook_url:
            logger.warning(
                "Slack webhook URL not configured, skipping notification",
                extra={"event_type": event.event_type.value},
            )
            return False

        if not self._should_send(event):
            return False

        payload = self._build_payload(event)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url,
                    json=payload,
                    timeout=10.0,
                )

                if response.status_code == 200:
                    logger.info(
                        "Slack alert sent successfully",
                        extra={
                            "event_type": event.event_type.value,
                            "tenant_id": event.tenant_id,
                            "connector_id": event.connector_id,
                        },
                    )
                    return True
                else:
                    logger.error(
                        "Failed to send Slack alert",
                        extra={
                            "status_code": response.status_code,
                            "response": response.text[:200],
                        },
                    )
                    return False

        except httpx.TimeoutException:
            logger.error(
                "Slack alert timed out",
                extra={"event_type": event.event_type.value},
            )
            return False
        except Exception as e:
            logger.error(
                "Error sending Slack alert",
                extra={"error": str(e), "event_type": event.event_type.value},
            )
            return False

    def send_sync(self, event: DQEvent) -> bool:
        """
        Synchronous version of send() for non-async contexts.

        Args:
            event: DQ event to send

        Returns:
            True if alert was sent successfully, False otherwise
        """
        if not self.webhook_url:
            logger.warning(
                "Slack webhook URL not configured, skipping notification",
            )
            return False

        if not self._should_send(event):
            return False

        payload = self._build_payload(event)

        try:
            with httpx.Client() as client:
                response = client.post(
                    self.webhook_url,
                    json=payload,
                    timeout=10.0,
                )

                if response.status_code == 200:
                    logger.info(
                        "Slack alert sent successfully",
                        extra={
                            "event_type": event.event_type.value,
                            "tenant_id": event.tenant_id,
                        },
                    )
                    return True
                else:
                    logger.error(
                        "Failed to send Slack alert",
                        extra={"status_code": response.status_code},
                    )
                    return False

        except Exception as e:
            logger.error("Error sending Slack alert", extra={"error": str(e)})
            return False
