"""
Audit system metrics for monitoring.

Emits structured log events that can be picked up by log aggregators
(Datadog, Splunk, CloudWatch, etc.) for dashboards and alerting.

Story 10.5 - Monitoring & Alerting for Audit System
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Dedicated metrics logger for easy filtering
metrics_logger = logging.getLogger("audit.metrics")


class AuditMetrics:
    """
    Collects and emits audit system metrics via structured logging.

    Metrics emitted:
    - audit_event_recorded: Successful audit event write
    - audit_event_failed: Failed audit event write (used fallback)
    - audit_retention_deleted: Records deleted by retention job
    """

    _instance: Optional["AuditMetrics"] = None

    @classmethod
    def get_instance(cls) -> "AuditMetrics":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def record_event(
        self,
        action: str,
        outcome: str,
        tenant_id: str,
        source: str,
    ) -> None:
        """Record successful audit event write."""
        metrics_logger.info(
            "audit_event_recorded",
            extra={
                "metric": "audit_event_recorded",
                "action": action,
                "outcome": outcome,
                "tenant_id": tenant_id,
                "source": source,
            }
        )

    def record_failure(
        self,
        error_type: str,
        tenant_id: Optional[str] = None,
    ) -> None:
        """Record failed audit event write (fallback used)."""
        metrics_logger.warning(
            "audit_event_failed",
            extra={
                "metric": "audit_event_failed",
                "error_type": error_type,
                "tenant_id": tenant_id,
            }
        )

    def record_retention_deletion(
        self,
        count: int,
        tenant_id: str,
    ) -> None:
        """Record audit logs deleted by retention job."""
        metrics_logger.info(
            "audit_retention_deleted",
            extra={
                "metric": "audit_retention_deleted",
                "count": count,
                "tenant_id": tenant_id,
            }
        )


def get_audit_metrics() -> AuditMetrics:
    """Get the audit metrics singleton."""
    return AuditMetrics.get_instance()
