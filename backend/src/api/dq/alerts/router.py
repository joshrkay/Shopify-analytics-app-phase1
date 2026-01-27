"""
Alert router for data quality events.

Routes alerts to appropriate channels based on severity:
- critical => PagerDuty + Slack #alerts
- high => Slack #alerts
- warning => logged only (no external notification)

This follows the locked alert routing decisions.
"""

import logging
from typing import List, Optional

from src.api.dq.service import DQEvent, DQEventType
from src.api.dq.alerts.slack import SlackNotifier
from src.api.dq.alerts.pagerduty import PagerDutyNotifier
from src.models.dq_models import DQSeverity

logger = logging.getLogger(__name__)


class AlertRouter:
    """
    Routes DQ events to appropriate alert channels.

    Routing rules (locked):
    - critical => PagerDuty + Slack #alerts
    - high => Slack #alerts
    - warning => logged only

    Usage:
        router = AlertRouter()
        await router.route(event)
    """

    def __init__(
        self,
        slack_notifier: Optional[SlackNotifier] = None,
        pagerduty_notifier: Optional[PagerDutyNotifier] = None,
    ):
        """
        Initialize alert router.

        Args:
            slack_notifier: Optional Slack notifier instance.
                           If not provided, creates one with default config.
            pagerduty_notifier: Optional PagerDuty notifier instance.
                               If not provided, creates one with default config.
        """
        self.slack = slack_notifier or SlackNotifier()
        self.pagerduty = pagerduty_notifier or PagerDutyNotifier()

    def _should_alert(self, event: DQEvent) -> bool:
        """
        Determine if event should trigger external alerts.

        Warning severity is logged only, not alerted.
        """
        # Always alert on resolution events if there was a previous alert
        if event.event_type == DQEventType.RESOLVED:
            return True

        # Warning severity: log only
        if event.severity == DQSeverity.WARNING:
            logger.info(
                "DQ warning logged (no external alert)",
                extra={
                    "event_type": event.event_type.value,
                    "tenant_id": event.tenant_id,
                    "connector_id": event.connector_id,
                    "severity": event.severity.value,
                    "message": event.message,
                },
            )
            return False

        return True

    async def route(self, event: DQEvent) -> List[str]:
        """
        Route a DQ event to appropriate alert channels.

        Args:
            event: DQ event to route

        Returns:
            List of channels that received the alert
        """
        if not self._should_alert(event):
            return []

        channels_notified = []

        # Route based on severity
        if event.severity == DQSeverity.CRITICAL:
            # Critical: PagerDuty + Slack
            logger.warning(
                "Routing CRITICAL alert to PagerDuty + Slack",
                extra={
                    "event_type": event.event_type.value,
                    "tenant_id": event.tenant_id,
                    "connector_id": event.connector_id,
                },
            )

            # Send to PagerDuty
            pd_success = await self.pagerduty.send(event)
            if pd_success:
                channels_notified.append("pagerduty")

            # Send to Slack
            slack_success = await self.slack.send(event)
            if slack_success:
                channels_notified.append("slack")

        elif event.severity == DQSeverity.HIGH:
            # High: Slack only
            logger.info(
                "Routing HIGH alert to Slack",
                extra={
                    "event_type": event.event_type.value,
                    "tenant_id": event.tenant_id,
                    "connector_id": event.connector_id,
                },
            )

            slack_success = await self.slack.send(event)
            if slack_success:
                channels_notified.append("slack")

        elif event.event_type == DQEventType.RESOLVED:
            # Resolve: Send to both to clear any open alerts
            logger.info(
                "Routing RESOLVED event to all channels",
                extra={
                    "tenant_id": event.tenant_id,
                    "connector_id": event.connector_id,
                },
            )

            # Try to resolve in PagerDuty
            pd_success = await self.pagerduty.send(event)
            if pd_success:
                channels_notified.append("pagerduty")

            # Notify in Slack
            slack_success = await self.slack.send(event)
            if slack_success:
                channels_notified.append("slack")

        return channels_notified

    def route_sync(self, event: DQEvent) -> List[str]:
        """
        Synchronous version of route() for non-async contexts.

        Args:
            event: DQ event to route

        Returns:
            List of channels that received the alert
        """
        if not self._should_alert(event):
            return []

        channels_notified = []

        if event.severity == DQSeverity.CRITICAL:
            pd_success = self.pagerduty.send_sync(event)
            if pd_success:
                channels_notified.append("pagerduty")

            slack_success = self.slack.send_sync(event)
            if slack_success:
                channels_notified.append("slack")

        elif event.severity == DQSeverity.HIGH:
            slack_success = self.slack.send_sync(event)
            if slack_success:
                channels_notified.append("slack")

        elif event.event_type == DQEventType.RESOLVED:
            pd_success = self.pagerduty.send_sync(event)
            if pd_success:
                channels_notified.append("pagerduty")

            slack_success = self.slack.send_sync(event)
            if slack_success:
                channels_notified.append("slack")

        return channels_notified

    async def route_batch(self, events: List[DQEvent]) -> dict:
        """
        Route multiple events efficiently.

        Args:
            events: List of DQ events to route

        Returns:
            Dictionary mapping event index to channels notified
        """
        results = {}

        for i, event in enumerate(events):
            channels = await self.route(event)
            results[i] = channels

        return results


# Singleton instance
_alert_router: Optional[AlertRouter] = None


def get_alert_router() -> AlertRouter:
    """Get the singleton alert router instance."""
    global _alert_router
    if _alert_router is None:
        _alert_router = AlertRouter()
    return _alert_router
