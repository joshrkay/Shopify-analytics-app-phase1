"""
Data Quality alerting adapters.

Provides integrations with:
- Slack (webhook)
- PagerDuty (Events API)

Alert routing by severity:
- critical => PagerDuty + Slack #alerts
- high => Slack #alerts
- warning => logged only (no external notification)
"""

from src.api.dq.alerts.slack import SlackNotifier
from src.api.dq.alerts.pagerduty import PagerDutyNotifier
from src.api.dq.alerts.router import AlertRouter

__all__ = [
    "SlackNotifier",
    "PagerDutyNotifier",
    "AlertRouter",
]
