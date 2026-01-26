"""
Billing monitoring and alerting system.

Provides:
- Health checks for billing system
- Alert definitions for critical events
- Metrics collection for dashboards
- Integration with external monitoring (Slack, PagerDuty, etc.)
"""

import os
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertType(str, Enum):
    """Types of billing alerts."""
    # Subscription alerts
    SUBSCRIPTION_DRIFT = "subscription_drift"
    STUCK_PENDING = "stuck_pending"
    GRACE_PERIOD_EXPIRING = "grace_period_expiring"
    INVALID_STATE_TRANSITION = "invalid_state_transition"
    DOUBLE_SUBSCRIPTION = "double_subscription"

    # Webhook alerts
    WEBHOOK_VERIFICATION_FAILED = "webhook_verification_failed"
    WEBHOOK_PROCESSING_ERROR = "webhook_processing_error"
    HIGH_WEBHOOK_LATENCY = "high_webhook_latency"

    # Reconciliation alerts
    RECONCILIATION_FAILED = "reconciliation_failed"
    HIGH_DRIFT_COUNT = "high_drift_count"
    ORPHANED_SUBSCRIPTION = "orphaned_subscription"

    # API alerts
    SHOPIFY_API_ERROR = "shopify_api_error"
    SHOPIFY_RATE_LIMITED = "shopify_rate_limited"

    # Business alerts
    PAYMENT_FAILURE_SPIKE = "payment_failure_spike"
    CANCELLATION_SPIKE = "cancellation_spike"


@dataclass
class Alert:
    """Represents a billing system alert."""
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary for serialization."""
        return {
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class BillingHealthStatus:
    """Overall health status of billing system."""
    healthy: bool
    status: str
    last_reconciliation: Optional[datetime]
    pending_subscriptions: int
    frozen_subscriptions: int
    reconciliation_drift_count: int
    webhook_error_rate: float
    checks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "healthy": self.healthy,
            "status": self.status,
            "last_reconciliation": self.last_reconciliation.isoformat() if self.last_reconciliation else None,
            "pending_subscriptions": self.pending_subscriptions,
            "frozen_subscriptions": self.frozen_subscriptions,
            "reconciliation_drift_count": self.reconciliation_drift_count,
            "webhook_error_rate": self.webhook_error_rate,
            "checks": self.checks
        }


class AlertManager:
    """
    Manages billing system alerts.

    Sends alerts to configured channels (Slack, PagerDuty, etc.)
    and tracks alert state to prevent duplicate notifications.
    """

    def __init__(self):
        self.slack_webhook_url = os.getenv("SLACK_BILLING_WEBHOOK_URL")
        self.pagerduty_key = os.getenv("PAGERDUTY_BILLING_KEY")
        self._recent_alerts: Dict[str, datetime] = {}
        self._cooldown_minutes = 15

    def _should_send(self, alert: Alert) -> bool:
        """Check if alert should be sent (cooldown period)."""
        key = f"{alert.alert_type.value}:{alert.metadata.get('tenant_id', 'global')}"
        last_sent = self._recent_alerts.get(key)

        if last_sent:
            cooldown = timedelta(minutes=self._cooldown_minutes)
            if datetime.now(timezone.utc) - last_sent < cooldown:
                return False

        self._recent_alerts[key] = datetime.now(timezone.utc)
        return True

    async def send_alert(self, alert: Alert) -> bool:
        """
        Send an alert to configured channels.

        Args:
            alert: Alert to send

        Returns:
            True if alert was sent, False if suppressed
        """
        if not self._should_send(alert):
            logger.debug("Alert suppressed (cooldown)", extra={
                "alert_type": alert.alert_type.value
            })
            return False

        # Log the alert
        log_extra = {
            "alert_type": alert.alert_type.value,
            "severity": alert.severity.value,
            **alert.metadata
        }

        if alert.severity == AlertSeverity.CRITICAL:
            logger.critical(alert.message, extra=log_extra)
        elif alert.severity == AlertSeverity.ERROR:
            logger.error(alert.message, extra=log_extra)
        elif alert.severity == AlertSeverity.WARNING:
            logger.warning(alert.message, extra=log_extra)
        else:
            logger.info(alert.message, extra=log_extra)

        # Send to Slack
        if self.slack_webhook_url:
            await self._send_to_slack(alert)

        # Send to PagerDuty for critical alerts
        if self.pagerduty_key and alert.severity == AlertSeverity.CRITICAL:
            await self._send_to_pagerduty(alert)

        return True

    async def _send_to_slack(self, alert: Alert) -> None:
        """Send alert to Slack webhook."""
        severity_emoji = {
            AlertSeverity.INFO: ":information_source:",
            AlertSeverity.WARNING: ":warning:",
            AlertSeverity.ERROR: ":x:",
            AlertSeverity.CRITICAL: ":rotating_light:"
        }

        color = {
            AlertSeverity.INFO: "#36a64f",
            AlertSeverity.WARNING: "#ff9800",
            AlertSeverity.ERROR: "#f44336",
            AlertSeverity.CRITICAL: "#9c27b0"
        }

        payload = {
            "attachments": [
                {
                    "color": color.get(alert.severity, "#808080"),
                    "title": f"{severity_emoji.get(alert.severity, '')} {alert.title}",
                    "text": alert.message,
                    "fields": [
                        {
                            "title": key.replace("_", " ").title(),
                            "value": str(value),
                            "short": True
                        }
                        for key, value in alert.metadata.items()
                    ],
                    "ts": int(alert.timestamp.timestamp())
                }
            ]
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.slack_webhook_url,
                    json=payload,
                    timeout=10.0
                )
                if response.status_code != 200:
                    logger.error("Failed to send Slack alert", extra={
                        "status_code": response.status_code
                    })
        except Exception as e:
            logger.error("Error sending Slack alert", extra={"error": str(e)})

    async def _send_to_pagerduty(self, alert: Alert) -> None:
        """Send critical alert to PagerDuty."""
        payload = {
            "routing_key": self.pagerduty_key,
            "event_action": "trigger",
            "payload": {
                "summary": alert.title,
                "severity": "critical",
                "source": "billing-system",
                "custom_details": {
                    "message": alert.message,
                    **alert.metadata
                }
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://events.pagerduty.com/v2/enqueue",
                    json=payload,
                    timeout=10.0
                )
        except Exception as e:
            logger.error("Error sending PagerDuty alert", extra={"error": str(e)})


# Singleton alert manager
_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """Get the singleton alert manager instance."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager


# Alert factory functions

async def alert_subscription_drift(
    tenant_id: str,
    subscription_id: str,
    local_status: str,
    shopify_status: str
) -> None:
    """Alert for subscription state drift between local and Shopify."""
    alert = Alert(
        alert_type=AlertType.SUBSCRIPTION_DRIFT,
        severity=AlertSeverity.WARNING,
        title="Subscription State Drift Detected",
        message=f"Subscription {subscription_id} has state drift: local={local_status}, Shopify={shopify_status}",
        metadata={
            "tenant_id": tenant_id,
            "subscription_id": subscription_id,
            "local_status": local_status,
            "shopify_status": shopify_status
        }
    )
    await get_alert_manager().send_alert(alert)


async def alert_invalid_state_transition(
    tenant_id: str,
    subscription_id: str,
    from_state: str,
    to_state: str
) -> None:
    """Alert for invalid subscription state transition."""
    alert = Alert(
        alert_type=AlertType.INVALID_STATE_TRANSITION,
        severity=AlertSeverity.CRITICAL,
        title="Invalid Subscription State Transition",
        message=f"Invalid transition from {from_state} to {to_state} for subscription {subscription_id}",
        metadata={
            "tenant_id": tenant_id,
            "subscription_id": subscription_id,
            "from_state": from_state,
            "to_state": to_state
        }
    )
    await get_alert_manager().send_alert(alert)


async def alert_stuck_pending(
    subscription_id: str,
    tenant_id: str,
    pending_since: datetime
) -> None:
    """Alert for subscriptions stuck in pending state."""
    days_pending = (datetime.now(timezone.utc) - pending_since).days

    alert = Alert(
        alert_type=AlertType.STUCK_PENDING,
        severity=AlertSeverity.WARNING,
        title="Subscription Stuck in Pending",
        message=f"Subscription {subscription_id} has been pending for {days_pending} days",
        metadata={
            "tenant_id": tenant_id,
            "subscription_id": subscription_id,
            "days_pending": days_pending,
            "pending_since": pending_since.isoformat()
        }
    )
    await get_alert_manager().send_alert(alert)


async def alert_grace_period_expiring(
    tenant_id: str,
    subscription_id: str,
    expires_at: datetime,
    days_remaining: int
) -> None:
    """Alert for grace periods about to expire."""
    alert = Alert(
        alert_type=AlertType.GRACE_PERIOD_EXPIRING,
        severity=AlertSeverity.INFO,
        title="Grace Period Expiring Soon",
        message=f"Subscription {subscription_id} grace period expires in {days_remaining} days",
        metadata={
            "tenant_id": tenant_id,
            "subscription_id": subscription_id,
            "expires_at": expires_at.isoformat(),
            "days_remaining": days_remaining
        }
    )
    await get_alert_manager().send_alert(alert)


async def alert_reconciliation_failed(error: str, stats: dict) -> None:
    """Alert for reconciliation job failure."""
    alert = Alert(
        alert_type=AlertType.RECONCILIATION_FAILED,
        severity=AlertSeverity.ERROR,
        title="Reconciliation Job Failed",
        message=f"Reconciliation job failed: {error}",
        metadata={
            "error": error,
            **stats
        }
    )
    await get_alert_manager().send_alert(alert)


async def alert_high_drift_count(drift_count: int, threshold: int) -> None:
    """Alert when drift count exceeds threshold."""
    alert = Alert(
        alert_type=AlertType.HIGH_DRIFT_COUNT,
        severity=AlertSeverity.WARNING if drift_count < threshold * 2 else AlertSeverity.CRITICAL,
        title="High Subscription Drift Count",
        message=f"Reconciliation found {drift_count} subscriptions with state drift (threshold: {threshold})",
        metadata={
            "drift_count": drift_count,
            "threshold": threshold
        }
    )
    await get_alert_manager().send_alert(alert)


async def alert_shopify_api_error(
    shop_domain: str,
    error: str,
    status_code: Optional[int] = None
) -> None:
    """Alert for Shopify API errors."""
    alert = Alert(
        alert_type=AlertType.SHOPIFY_API_ERROR,
        severity=AlertSeverity.ERROR,
        title="Shopify API Error",
        message=f"Shopify API error for {shop_domain}: {error}",
        metadata={
            "shop_domain": shop_domain,
            "error": error,
            "status_code": status_code
        }
    )
    await get_alert_manager().send_alert(alert)


async def alert_webhook_error(
    shop_domain: str,
    topic: str,
    error: str
) -> None:
    """Alert for webhook processing errors."""
    alert = Alert(
        alert_type=AlertType.WEBHOOK_PROCESSING_ERROR,
        severity=AlertSeverity.ERROR,
        title="Webhook Processing Error",
        message=f"Failed to process {topic} webhook from {shop_domain}: {error}",
        metadata={
            "shop_domain": shop_domain,
            "topic": topic,
            "error": error
        }
    )
    await get_alert_manager().send_alert(alert)


# Health check functions

async def check_billing_health(db_session) -> BillingHealthStatus:
    """
    Perform comprehensive billing system health check.

    Args:
        db_session: Database session

    Returns:
        BillingHealthStatus with overall health and individual checks
    """
    from src.models.subscription import Subscription, SubscriptionStatus
    from src.models.billing_event import BillingEvent

    checks = []
    issues = 0

    # Check 1: Pending subscriptions
    pending_count = db_session.query(Subscription).filter(
        Subscription.status == SubscriptionStatus.PENDING.value
    ).count()

    old_pending = db_session.query(Subscription).filter(
        Subscription.status == SubscriptionStatus.PENDING.value,
        Subscription.created_at < datetime.now(timezone.utc) - timedelta(days=7)
    ).count()

    checks.append({
        "name": "pending_subscriptions",
        "status": "warning" if old_pending > 0 else "ok",
        "message": f"{pending_count} pending ({old_pending} older than 7 days)"
    })
    if old_pending > 0:
        issues += 1

    # Check 2: Frozen subscriptions
    frozen_count = db_session.query(Subscription).filter(
        Subscription.status == SubscriptionStatus.FROZEN.value
    ).count()

    checks.append({
        "name": "frozen_subscriptions",
        "status": "warning" if frozen_count > 10 else "ok",
        "message": f"{frozen_count} frozen subscriptions"
    })
    if frozen_count > 10:
        issues += 1

    # Check 3: Recent reconciliation
    last_reconciliation_event = db_session.query(BillingEvent).filter(
        BillingEvent.extra_metadata.contains({"source": "reconciliation"})
    ).order_by(BillingEvent.created_at.desc()).first()

    last_recon_time = last_reconciliation_event.created_at if last_reconciliation_event else None
    recon_stale = False

    if last_recon_time:
        hours_since = (datetime.now(timezone.utc) - last_recon_time).total_seconds() / 3600
        recon_stale = hours_since > 4

    checks.append({
        "name": "reconciliation",
        "status": "warning" if recon_stale else "ok",
        "message": f"Last run: {last_recon_time.isoformat() if last_recon_time else 'never'}"
    })
    if recon_stale:
        issues += 1

    # Check 4: Recent errors
    error_count = db_session.query(BillingEvent).filter(
        BillingEvent.event_type == "charge_failed",
        BillingEvent.created_at > datetime.now(timezone.utc) - timedelta(hours=24)
    ).count()

    checks.append({
        "name": "recent_errors",
        "status": "warning" if error_count > 5 else "ok",
        "message": f"{error_count} payment failures in last 24h"
    })
    if error_count > 5:
        issues += 1

    # Calculate drift count (approximation)
    drift_events = db_session.query(BillingEvent).filter(
        BillingEvent.extra_metadata.contains({"source": "reconciliation"}),
        BillingEvent.created_at > datetime.now(timezone.utc) - timedelta(hours=24)
    ).count()

    return BillingHealthStatus(
        healthy=issues == 0,
        status="healthy" if issues == 0 else f"{issues} issues detected",
        last_reconciliation=last_recon_time,
        pending_subscriptions=pending_count,
        frozen_subscriptions=frozen_count,
        reconciliation_drift_count=drift_events,
        webhook_error_rate=0.0,  # Would need separate tracking
        checks=checks
    )
