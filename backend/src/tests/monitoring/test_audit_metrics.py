"""
Unit tests for audit metrics.

Story 10.5 - Monitoring & Alerting for Audit System
"""

import pytest
from unittest.mock import patch, MagicMock

from src.monitoring.audit_metrics import AuditMetrics, get_audit_metrics


class TestAuditMetrics:
    """Test suite for AuditMetrics class."""

    def test_singleton_returns_same_instance(self):
        """get_instance should return same instance."""
        # Reset singleton for test
        AuditMetrics._instance = None

        instance1 = AuditMetrics.get_instance()
        instance2 = AuditMetrics.get_instance()

        assert instance1 is instance2

    def test_get_audit_metrics_returns_singleton(self):
        """get_audit_metrics should return singleton."""
        AuditMetrics._instance = None

        metrics1 = get_audit_metrics()
        metrics2 = get_audit_metrics()

        assert metrics1 is metrics2

    def test_record_event_logs_metric(self):
        """record_event should log structured metric."""
        metrics = AuditMetrics()

        with patch("src.monitoring.audit_metrics.metrics_logger") as mock_logger:
            metrics.record_event(
                action="auth.login",
                outcome="success",
                tenant_id="tenant-1",
                source="api",
            )

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "audit_event_recorded"
            assert call_args[1]["extra"]["metric"] == "audit_event_recorded"
            assert call_args[1]["extra"]["action"] == "auth.login"
            assert call_args[1]["extra"]["outcome"] == "success"
            assert call_args[1]["extra"]["tenant_id"] == "tenant-1"
            assert call_args[1]["extra"]["source"] == "api"

    def test_record_failure_logs_warning(self):
        """record_failure should log warning metric."""
        metrics = AuditMetrics()

        with patch("src.monitoring.audit_metrics.metrics_logger") as mock_logger:
            metrics.record_failure(
                error_type="DatabaseError",
                tenant_id="tenant-1",
            )

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert call_args[0][0] == "audit_event_failed"
            assert call_args[1]["extra"]["metric"] == "audit_event_failed"
            assert call_args[1]["extra"]["error_type"] == "DatabaseError"
            assert call_args[1]["extra"]["tenant_id"] == "tenant-1"

    def test_record_retention_deletion_logs_metric(self):
        """record_retention_deletion should log metric with count."""
        metrics = AuditMetrics()

        with patch("src.monitoring.audit_metrics.metrics_logger") as mock_logger:
            metrics.record_retention_deletion(count=100, tenant_id="tenant-1")

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "audit_retention_deleted"
            assert call_args[1]["extra"]["metric"] == "audit_retention_deleted"
            assert call_args[1]["extra"]["count"] == 100
            assert call_args[1]["extra"]["tenant_id"] == "tenant-1"


class TestAuditMetricsIntegration:
    """Integration tests for metrics in audit.py."""

    def test_write_audit_log_records_metric_on_success(self):
        """write_audit_log_sync should record metric on success."""
        from unittest.mock import MagicMock
        from src.platform.audit import write_audit_log_sync, AuditEvent, AuditAction, AuditOutcome
        from datetime import datetime, timezone

        mock_db = MagicMock()

        event = AuditEvent(
            tenant_id="tenant-1",
            user_id="user-1",
            action=AuditAction.AUTH_LOGIN,
            timestamp=datetime.now(timezone.utc),
            source="api",
            outcome=AuditOutcome.SUCCESS,
        )

        with patch("src.platform.audit.get_audit_metrics") as mock_get_metrics:
            mock_metrics = MagicMock()
            mock_get_metrics.return_value = mock_metrics

            write_audit_log_sync(mock_db, event)

            mock_metrics.record_event.assert_called_once_with(
                action="auth.login",
                outcome="success",
                tenant_id="tenant-1",
                source="api",
            )

    def test_write_audit_log_records_failure_on_exception(self):
        """write_audit_log_sync should record failure metric on exception."""
        from src.platform.audit import write_audit_log_sync, AuditEvent, AuditAction, AuditOutcome
        from datetime import datetime, timezone

        mock_db = MagicMock()
        mock_db.add.side_effect = Exception("DB connection failed")

        event = AuditEvent(
            tenant_id="tenant-1",
            user_id="user-1",
            action=AuditAction.AUTH_LOGIN,
            timestamp=datetime.now(timezone.utc),
            source="api",
            outcome=AuditOutcome.SUCCESS,
        )

        with patch("src.platform.audit.get_audit_metrics") as mock_get_metrics:
            mock_metrics = MagicMock()
            mock_get_metrics.return_value = mock_metrics

            result = write_audit_log_sync(mock_db, event)

            assert result is None
            mock_metrics.record_failure.assert_called_once()
            call_kwargs = mock_metrics.record_failure.call_args[1]
            assert call_kwargs["tenant_id"] == "tenant-1"
