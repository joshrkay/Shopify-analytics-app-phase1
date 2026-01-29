"""
Audit system alerting.

Provides alerting for audit system failures and security events.
Uses the existing AlertManager pattern for delivery.

Story 10.5 - Monitoring & Alerting for Audit System
"""

import logging
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class AuditAlertType(str, Enum):
    """Types of audit system alerts."""
    AUDIT_LOGGING_FAILURE = "audit_logging_failure"
    CROSS_TENANT_ACCESS = "cross_tenant_access"
    RETENTION_JOB_FAILED = "retention_job_failed"


class AuditAlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AuditAlert:
    """Represents an audit system alert."""
    alert_type: AuditAlertType
    severity: AuditAlertSeverity
    title: str
    message: str
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AuditAlertManager:
    """
    Manages audit system alerts.

    Tracks failure counts and alerts when thresholds are exceeded.
    Uses structured logging for alert delivery (picked up by log aggregator).
    """

    _instance: Optional["AuditAlertManager"] = None

    # Alert thresholds
    FAILURE_THRESHOLD = 5  # Alert after 5 failures in window
    FAILURE_WINDOW_MINUTES = 5

    def __init__(self):
        self._failure_counts: dict[str, list[datetime]] = {}
        self._cooldown_minutes = 15
        self._recent_alerts: dict[str, datetime] = {}

    @classmethod
    def get_instance(cls) -> "AuditAlertManager":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _should_alert(self, alert_type: str, key: str) -> bool:
        """Check if alert should be sent (cooldown period)."""
        full_key = f"{alert_type}:{key}"
        last_sent = self._recent_alerts.get(full_key)

        if last_sent:
            cooldown = timedelta(minutes=self._cooldown_minutes)
            if datetime.now(timezone.utc) - last_sent < cooldown:
                return False

        self._recent_alerts[full_key] = datetime.now(timezone.utc)
        return True

    def _send_alert(self, alert: AuditAlert) -> None:
        """Send alert via structured logging."""
        log_extra = {
            "alert_type": alert.alert_type.value,
            "severity": alert.severity.value,
            "title": alert.title,
            **alert.metadata,
        }

        if alert.severity == AuditAlertSeverity.CRITICAL:
            logger.critical(alert.message, extra=log_extra)
        elif alert.severity == AuditAlertSeverity.ERROR:
            logger.error(alert.message, extra=log_extra)
        elif alert.severity == AuditAlertSeverity.WARNING:
            logger.warning(alert.message, extra=log_extra)
        else:
            logger.info(alert.message, extra=log_extra)

    def record_logging_failure(
        self,
        tenant_id: Optional[str] = None,
        error_type: str = "unknown",
    ) -> bool:
        """
        Record an audit logging failure and alert if threshold exceeded.

        Returns True if alert was triggered.
        """
        now = datetime.now(timezone.utc)
        key = tenant_id or "global"
        window = timedelta(minutes=self.FAILURE_WINDOW_MINUTES)

        # Track failure
        if key not in self._failure_counts:
            self._failure_counts[key] = []

        # Clean old entries
        self._failure_counts[key] = [
            ts for ts in self._failure_counts[key]
            if ts > now - window
        ]
        self._failure_counts[key].append(now)

        # Check threshold
        failure_count = len(self._failure_counts[key])
        if failure_count >= self.FAILURE_THRESHOLD:
            if self._should_alert(AuditAlertType.AUDIT_LOGGING_FAILURE.value, key):
                alert = AuditAlert(
                    alert_type=AuditAlertType.AUDIT_LOGGING_FAILURE,
                    severity=AuditAlertSeverity.CRITICAL,
                    title="Audit Logging Failures Detected",
                    message=f"Audit logging has failed {failure_count} times in {self.FAILURE_WINDOW_MINUTES} minutes",
                    metadata={
                        "tenant_id": tenant_id,
                        "failure_count": failure_count,
                        "error_type": error_type,
                        "window_minutes": self.FAILURE_WINDOW_MINUTES,
                    },
                )
                self._send_alert(alert)
                return True

        return False

    def alert_cross_tenant_access(
        self,
        requesting_tenant: str,
        target_tenant: str,
        user_id: str,
        correlation_id: Optional[str] = None,
    ) -> bool:
        """
        Alert on cross-tenant access attempt.

        Always alerts (no threshold) as this is a security event.
        Returns True if alert was sent.
        """
        key = f"{requesting_tenant}:{user_id}"
        if not self._should_alert(AuditAlertType.CROSS_TENANT_ACCESS.value, key):
            return False

        alert = AuditAlert(
            alert_type=AuditAlertType.CROSS_TENANT_ACCESS,
            severity=AuditAlertSeverity.CRITICAL,
            title="Cross-Tenant Access Attempt",
            message=f"User {user_id} from {requesting_tenant} attempted to access {target_tenant}",
            metadata={
                "requesting_tenant": requesting_tenant,
                "target_tenant": target_tenant,
                "user_id": user_id,
                "correlation_id": correlation_id,
            },
        )
        self._send_alert(alert)
        return True

    def alert_retention_job_failed(
        self,
        error: str,
        tenants_processed: int = 0,
        total_deleted: int = 0,
    ) -> None:
        """Alert when retention job fails."""
        if not self._should_alert(AuditAlertType.RETENTION_JOB_FAILED.value, "global"):
            return

        alert = AuditAlert(
            alert_type=AuditAlertType.RETENTION_JOB_FAILED,
            severity=AuditAlertSeverity.ERROR,
            title="Audit Retention Job Failed",
            message=f"Audit retention job failed: {error}",
            metadata={
                "error": error,
                "tenants_processed": tenants_processed,
                "total_deleted": total_deleted,
            },
        )
        self._send_alert(alert)


def get_audit_alert_manager() -> AuditAlertManager:
    """Get the audit alert manager singleton."""
    return AuditAlertManager.get_instance()
