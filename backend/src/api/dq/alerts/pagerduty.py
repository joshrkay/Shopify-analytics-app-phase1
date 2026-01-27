"""
PagerDuty notifier for data quality alerts.

Sends critical alerts to PagerDuty via Events API v2.
Only CRITICAL severity events are sent to PagerDuty.

Configuration:
- PAGERDUTY_DQ_ROUTING_KEY: PagerDuty Events API routing key
- PAGERDUTY_DQ_COOLDOWN_MINUTES: Cooldown period (default: 15)

PagerDuty Events API v2: https://developer.pagerduty.com/api-reference/events-api-v2/send-an-event-to-pagerduty/
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Any

import httpx

from src.api.dq.service import DQEvent, DQEventType
from src.models.dq_models import DQSeverity

logger = logging.getLogger(__name__)

# PagerDuty Events API endpoint
PAGERDUTY_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"


class PagerDutyNotifier:
    """
    PagerDuty notification adapter for critical DQ alerts.

    Features:
    - Events API v2 integration
    - Deduplication key for intelligent grouping
    - Cooldown to prevent alert storms
    - Automatic resolution support
    - Async HTTP requests
    """

    def __init__(
        self,
        routing_key: Optional[str] = None,
        cooldown_minutes: int = 15,
    ):
        """
        Initialize PagerDuty notifier.

        Args:
            routing_key: PagerDuty Events API routing key. If not provided,
                         reads from PAGERDUTY_DQ_ROUTING_KEY environment variable.
            cooldown_minutes: Minutes to wait before sending duplicate alerts.
        """
        self.routing_key = routing_key or os.getenv("PAGERDUTY_DQ_ROUTING_KEY")
        self.cooldown_minutes = int(
            os.getenv("PAGERDUTY_DQ_COOLDOWN_MINUTES", str(cooldown_minutes))
        )
        self._recent_alerts: Dict[str, datetime] = {}

    def _get_dedup_key(self, event: DQEvent) -> str:
        """
        Generate a deduplication key for PagerDuty.

        Events with the same dedup_key will be grouped into a single incident.
        """
        return f"dq-{event.tenant_id}-{event.connector_id}-{event.check_type}"

    def _should_send(self, event: DQEvent) -> bool:
        """Check if alert should be sent (cooldown period)."""
        key = self._get_dedup_key(event)
        last_sent = self._recent_alerts.get(key)

        if last_sent:
            cooldown = timedelta(minutes=self.cooldown_minutes)
            if datetime.now(timezone.utc) - last_sent < cooldown:
                logger.debug(
                    "PagerDuty alert suppressed (cooldown)",
                    extra={
                        "event_type": event.event_type.value,
                        "tenant_id": event.tenant_id,
                        "connector_id": event.connector_id,
                    },
                )
                return False

        self._recent_alerts[key] = datetime.now(timezone.utc)
        return True

    def _get_event_action(self, event: DQEvent) -> str:
        """Get PagerDuty event action (trigger/resolve)."""
        if event.event_type == DQEventType.RESOLVED:
            return "resolve"
        return "trigger"

    def _get_severity(self, event: DQEvent) -> str:
        """Map DQ severity to PagerDuty severity."""
        severity_map = {
            DQSeverity.WARNING: "warning",
            DQSeverity.HIGH: "error",
            DQSeverity.CRITICAL: "critical",
        }
        if event.severity:
            return severity_map.get(event.severity, "error")
        return "error"

    def _format_summary(self, event: DQEvent) -> str:
        """Format alert summary for PagerDuty."""
        type_names = {
            DQEventType.FRESHNESS_FAILED: "Data Freshness Alert",
            DQEventType.ANOMALY_DETECTED: "Data Anomaly Detected",
            DQEventType.SEVERE_BLOCK: "Dashboard Blocked - Critical DQ Issue",
            DQEventType.RESOLVED: "DQ Issue Resolved",
        }
        type_name = type_names.get(event.event_type, "Data Quality Alert")

        return f"[{event.tenant_id[:20]}] {type_name}: {event.message[:100]}"

    def _build_payload(self, event: DQEvent) -> Dict[str, Any]:
        """Build PagerDuty Events API v2 payload."""
        event_action = self._get_event_action(event)

        payload = {
            "routing_key": self.routing_key,
            "event_action": event_action,
            "dedup_key": self._get_dedup_key(event),
        }

        if event_action == "trigger":
            payload["payload"] = {
                "summary": self._format_summary(event),
                "severity": self._get_severity(event),
                "source": "dq-monitor",
                "component": event.check_type,
                "group": event.connector_id,
                "class": event.event_type.value,
                "custom_details": {
                    "tenant_id": event.tenant_id,
                    "connector_id": event.connector_id,
                    "run_id": event.run_id,
                    "correlation_id": event.correlation_id,
                    "check_type": event.check_type,
                    "message": event.message,
                    "support_details": event.support_details,
                    "timestamp": event.timestamp.isoformat(),
                    **event.metadata,
                },
            }
            # Add links if available
            payload["links"] = [
                {
                    "href": f"https://app.example.com/sync-health?tenant={event.tenant_id}",
                    "text": "View Sync Health Dashboard",
                },
            ]

        return payload

    async def send(self, event: DQEvent) -> bool:
        """
        Send a DQ event to PagerDuty.

        Only CRITICAL severity events are sent (except for resolve events).

        Args:
            event: DQ event to send

        Returns:
            True if alert was sent successfully, False otherwise
        """
        if not self.routing_key:
            logger.warning(
                "PagerDuty routing key not configured, skipping notification",
                extra={"event_type": event.event_type.value},
            )
            return False

        # Only send CRITICAL severity to PagerDuty (or resolve events)
        if event.event_type != DQEventType.RESOLVED:
            if event.severity != DQSeverity.CRITICAL:
                logger.debug(
                    "Skipping PagerDuty notification for non-critical event",
                    extra={
                        "severity": event.severity.value if event.severity else None,
                        "event_type": event.event_type.value,
                    },
                )
                return False

        if not self._should_send(event):
            return False

        payload = self._build_payload(event)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    PAGERDUTY_EVENTS_URL,
                    json=payload,
                    timeout=10.0,
                )

                if response.status_code in [200, 201, 202]:
                    response_data = response.json()
                    logger.info(
                        "PagerDuty alert sent successfully",
                        extra={
                            "event_type": event.event_type.value,
                            "tenant_id": event.tenant_id,
                            "dedup_key": self._get_dedup_key(event),
                            "status": response_data.get("status"),
                        },
                    )
                    return True
                else:
                    logger.error(
                        "Failed to send PagerDuty alert",
                        extra={
                            "status_code": response.status_code,
                            "response": response.text[:200],
                        },
                    )
                    return False

        except httpx.TimeoutException:
            logger.error(
                "PagerDuty alert timed out",
                extra={"event_type": event.event_type.value},
            )
            return False
        except Exception as e:
            logger.error(
                "Error sending PagerDuty alert",
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
        if not self.routing_key:
            logger.warning(
                "PagerDuty routing key not configured, skipping notification",
            )
            return False

        # Only send CRITICAL severity to PagerDuty (or resolve events)
        if event.event_type != DQEventType.RESOLVED:
            if event.severity != DQSeverity.CRITICAL:
                return False

        if not self._should_send(event):
            return False

        payload = self._build_payload(event)

        try:
            with httpx.Client() as client:
                response = client.post(
                    PAGERDUTY_EVENTS_URL,
                    json=payload,
                    timeout=10.0,
                )

                if response.status_code in [200, 201, 202]:
                    logger.info(
                        "PagerDuty alert sent successfully",
                        extra={
                            "event_type": event.event_type.value,
                            "tenant_id": event.tenant_id,
                        },
                    )
                    return True
                else:
                    logger.error(
                        "Failed to send PagerDuty alert",
                        extra={"status_code": response.status_code},
                    )
                    return False

        except Exception as e:
            logger.error("Error sending PagerDuty alert", extra={"error": str(e)})
            return False

    async def resolve(
        self,
        tenant_id: str,
        connector_id: str,
        check_type: str,
    ) -> bool:
        """
        Send a resolve event to PagerDuty.

        Args:
            tenant_id: Tenant ID
            connector_id: Connector ID
            check_type: Check type

        Returns:
            True if resolve was sent successfully, False otherwise
        """
        if not self.routing_key:
            return False

        dedup_key = f"dq-{tenant_id}-{connector_id}-{check_type}"

        payload = {
            "routing_key": self.routing_key,
            "event_action": "resolve",
            "dedup_key": dedup_key,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    PAGERDUTY_EVENTS_URL,
                    json=payload,
                    timeout=10.0,
                )

                if response.status_code in [200, 201, 202]:
                    logger.info(
                        "PagerDuty incident resolved",
                        extra={
                            "tenant_id": tenant_id,
                            "connector_id": connector_id,
                            "dedup_key": dedup_key,
                        },
                    )
                    return True
                else:
                    logger.error(
                        "Failed to resolve PagerDuty incident",
                        extra={"status_code": response.status_code},
                    )
                    return False

        except Exception as e:
            logger.error(
                "Error resolving PagerDuty incident",
                extra={"error": str(e)},
            )
            return False
