"""
Unit tests for audit alerting.

Story 10.5 - Monitoring & Alerting for Audit System
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from src.monitoring.audit_alerts import (
    AuditAlertManager,
    AuditAlertType,
    AuditAlertSeverity,
    AuditAlert,
    get_audit_alert_manager,
)


class TestAuditAlertManager:
    """Test suite for AuditAlertManager class."""

    def test_singleton_returns_same_instance(self):
        """get_instance should return same instance."""
        AuditAlertManager._instance = None

        instance1 = AuditAlertManager.get_instance()
        instance2 = AuditAlertManager.get_instance()

        assert instance1 is instance2

    def test_get_audit_alert_manager_returns_singleton(self):
        """get_audit_alert_manager should return singleton."""
        AuditAlertManager._instance = None

        manager1 = get_audit_alert_manager()
        manager2 = get_audit_alert_manager()

        assert manager1 is manager2


class TestRecordLoggingFailure:
    """Test suite for record_logging_failure method."""

    def test_does_not_alert_below_threshold(self):
        """Should not alert when failure count is below threshold."""
        manager = AuditAlertManager()

        with patch.object(manager, "_send_alert") as mock_send:
            # Record failures below threshold (5)
            for _ in range(4):
                result = manager.record_logging_failure(
                    tenant_id="tenant-1", error_type="DatabaseError"
                )
                assert result is False

            mock_send.assert_not_called()

    def test_alerts_when_threshold_exceeded(self):
        """Should alert when failure count exceeds threshold."""
        manager = AuditAlertManager()

        with patch.object(manager, "_send_alert") as mock_send:
            # Record failures to exceed threshold
            for i in range(5):
                result = manager.record_logging_failure(
                    tenant_id="tenant-1", error_type="DatabaseError"
                )

            assert result is True
            mock_send.assert_called_once()
            alert = mock_send.call_args[0][0]
            assert alert.alert_type == AuditAlertType.AUDIT_LOGGING_FAILURE
            assert alert.severity == AuditAlertSeverity.CRITICAL
            assert "tenant-1" in alert.metadata.get("tenant_id", "")

    def test_tracks_failures_per_tenant(self):
        """Should track failures independently per tenant."""
        manager = AuditAlertManager()

        with patch.object(manager, "_send_alert") as mock_send:
            # Record 3 failures for tenant-1
            for _ in range(3):
                manager.record_logging_failure(tenant_id="tenant-1")

            # Record 3 failures for tenant-2
            for _ in range(3):
                manager.record_logging_failure(tenant_id="tenant-2")

            # Neither should trigger alert (below threshold of 5)
            mock_send.assert_not_called()

    def test_cleans_old_failures_outside_window(self):
        """Should clean failures outside the time window."""
        manager = AuditAlertManager()

        # Manually add old failures
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        manager._failure_counts["tenant-1"] = [old_time] * 10

        with patch.object(manager, "_send_alert") as mock_send:
            # New failure should not trigger alert since old ones are cleaned
            result = manager.record_logging_failure(tenant_id="tenant-1")

            assert result is False
            mock_send.assert_not_called()

    def test_respects_cooldown_period(self):
        """Should not send duplicate alerts within cooldown period."""
        manager = AuditAlertManager()

        with patch.object(manager, "_send_alert") as mock_send:
            # Trigger first alert
            for _ in range(5):
                manager.record_logging_failure(tenant_id="tenant-1")

            # Add more failures
            for _ in range(5):
                manager.record_logging_failure(tenant_id="tenant-1")

            # Should only alert once due to cooldown
            assert mock_send.call_count == 1


class TestAlertCrossTenantAccess:
    """Test suite for alert_cross_tenant_access method."""

    def test_sends_alert_on_cross_tenant_access(self):
        """Should send critical alert on cross-tenant access attempt."""
        manager = AuditAlertManager()

        with patch.object(manager, "_send_alert") as mock_send:
            result = manager.alert_cross_tenant_access(
                requesting_tenant="tenant-1",
                target_tenant="tenant-2",
                user_id="user-123",
            )

            assert result is True
            mock_send.assert_called_once()
            alert = mock_send.call_args[0][0]
            assert alert.alert_type == AuditAlertType.CROSS_TENANT_ACCESS
            assert alert.severity == AuditAlertSeverity.CRITICAL
            assert alert.metadata["requesting_tenant"] == "tenant-1"
            assert alert.metadata["target_tenant"] == "tenant-2"
            assert alert.metadata["user_id"] == "user-123"

    def test_respects_cooldown_for_same_user_tenant(self):
        """Should not send duplicate alerts for same user/tenant in cooldown."""
        manager = AuditAlertManager()

        with patch.object(manager, "_send_alert") as mock_send:
            # First alert
            result1 = manager.alert_cross_tenant_access(
                requesting_tenant="tenant-1",
                target_tenant="tenant-2",
                user_id="user-123",
            )

            # Second alert for same user/tenant
            result2 = manager.alert_cross_tenant_access(
                requesting_tenant="tenant-1",
                target_tenant="tenant-3",
                user_id="user-123",
            )

            assert result1 is True
            assert result2 is False
            assert mock_send.call_count == 1

    def test_allows_alert_for_different_user(self):
        """Should allow alerts for different users."""
        manager = AuditAlertManager()

        with patch.object(manager, "_send_alert") as mock_send:
            result1 = manager.alert_cross_tenant_access(
                requesting_tenant="tenant-1",
                target_tenant="tenant-2",
                user_id="user-123",
            )

            result2 = manager.alert_cross_tenant_access(
                requesting_tenant="tenant-1",
                target_tenant="tenant-2",
                user_id="user-456",
            )

            assert result1 is True
            assert result2 is True
            assert mock_send.call_count == 2


class TestAlertRetentionJobFailed:
    """Test suite for alert_retention_job_failed method."""

    def test_sends_alert_on_job_failure(self):
        """Should send error alert on retention job failure."""
        manager = AuditAlertManager()

        with patch.object(manager, "_send_alert") as mock_send:
            manager.alert_retention_job_failed(
                error="Connection timeout",
                tenants_processed=5,
                total_deleted=100,
            )

            mock_send.assert_called_once()
            alert = mock_send.call_args[0][0]
            assert alert.alert_type == AuditAlertType.RETENTION_JOB_FAILED
            assert alert.severity == AuditAlertSeverity.ERROR
            assert alert.metadata["error"] == "Connection timeout"
            assert alert.metadata["tenants_processed"] == 5
            assert alert.metadata["total_deleted"] == 100

    def test_respects_cooldown(self):
        """Should not send duplicate alerts within cooldown."""
        manager = AuditAlertManager()

        with patch.object(manager, "_send_alert") as mock_send:
            manager.alert_retention_job_failed(error="Error 1")
            manager.alert_retention_job_failed(error="Error 2")

            assert mock_send.call_count == 1


class TestSendAlert:
    """Test suite for _send_alert method."""

    def test_logs_critical_alert(self):
        """Should log critical alerts at critical level."""
        manager = AuditAlertManager()
        alert = AuditAlert(
            alert_type=AuditAlertType.CROSS_TENANT_ACCESS,
            severity=AuditAlertSeverity.CRITICAL,
            title="Test Alert",
            message="Test message",
        )

        with patch("src.monitoring.audit_alerts.logger") as mock_logger:
            manager._send_alert(alert)
            mock_logger.critical.assert_called_once()

    def test_logs_error_alert(self):
        """Should log error alerts at error level."""
        manager = AuditAlertManager()
        alert = AuditAlert(
            alert_type=AuditAlertType.RETENTION_JOB_FAILED,
            severity=AuditAlertSeverity.ERROR,
            title="Test Alert",
            message="Test message",
        )

        with patch("src.monitoring.audit_alerts.logger") as mock_logger:
            manager._send_alert(alert)
            mock_logger.error.assert_called_once()

    def test_logs_warning_alert(self):
        """Should log warning alerts at warning level."""
        manager = AuditAlertManager()
        alert = AuditAlert(
            alert_type=AuditAlertType.AUDIT_LOGGING_FAILURE,
            severity=AuditAlertSeverity.WARNING,
            title="Test Alert",
            message="Test message",
        )

        with patch("src.monitoring.audit_alerts.logger") as mock_logger:
            manager._send_alert(alert)
            mock_logger.warning.assert_called_once()

    def test_logs_info_alert(self):
        """Should log info alerts at info level."""
        manager = AuditAlertManager()
        alert = AuditAlert(
            alert_type=AuditAlertType.AUDIT_LOGGING_FAILURE,
            severity=AuditAlertSeverity.INFO,
            title="Test Alert",
            message="Test message",
        )

        with patch("src.monitoring.audit_alerts.logger") as mock_logger:
            manager._send_alert(alert)
            mock_logger.info.assert_called_once()


class TestAuditAlertIntegration:
    """Integration tests for alerts in other modules."""

    def test_fallback_log_triggers_alert_on_threshold(self):
        """_write_fallback_log should trigger alert via alert manager."""
        from src.platform.audit import _write_fallback_log, AuditEvent, AuditAction, AuditOutcome
        from datetime import datetime, timezone

        event = AuditEvent(
            tenant_id="tenant-1",
            user_id="user-1",
            action=AuditAction.AUTH_LOGIN,
            timestamp=datetime.now(timezone.utc),
            source="api",
            outcome=AuditOutcome.SUCCESS,
        )

        with patch("src.platform.audit.get_audit_alert_manager") as mock_get_manager:
            mock_manager = MagicMock()
            mock_get_manager.return_value = mock_manager

            _write_fallback_log(event, "audit-123", "Database connection failed")

            mock_manager.record_logging_failure.assert_called_once()
            call_kwargs = mock_manager.record_logging_failure.call_args[1]
            assert call_kwargs["tenant_id"] == "tenant-1"

    def test_cross_tenant_denial_triggers_alert(self):
        """Cross-tenant access denial should trigger alert."""
        from src.services.audit_access_control import AuditAccessContext, AuditAccessControl

        ctx = AuditAccessContext(
            user_id="user-1",
            role="merchant_admin",
            tenant_id="tenant-1",
            allowed_tenants=set(),
            is_super_admin=False,
        )
        ac = AuditAccessControl(ctx)

        with patch("src.services.audit_access_control.get_audit_alert_manager") as mock_get_manager:
            mock_manager = MagicMock()
            mock_get_manager.return_value = mock_manager

            with pytest.raises(Exception):
                ac.validate_access("tenant-2", db_session=MagicMock())

            mock_manager.alert_cross_tenant_access.assert_called_once_with(
                requesting_tenant="tenant-1",
                target_tenant="tenant-2",
                user_id="user-1",
            )
