"""
Unit tests for data quality audit event emitters.

Tests cover:
- Correct AuditAction dispatched for each event type
- Required metadata fields present (tenant_id, dataset, rule_type, severity, detected_at)
- FAILURE outcome on emit_quality_fail, SUCCESS on warn/recovered
- Audit failures never propagate to callers
- Enum and registry registration
"""

from unittest.mock import patch, MagicMock

from src.platform.audit import AuditAction, AuditOutcome, AUDITABLE_EVENTS
from src.platform.audit_events import (
    AUDITABLE_EVENTS as CANONICAL_EVENTS,
    EVENT_CATEGORIES,
    EVENT_SEVERITY,
)
from src.services.audit_logger import (
    emit_quality_warn,
    emit_quality_fail,
    emit_quality_recovered,
)

_TENANT = "tenant-test-001"
_DATASET = "shopify_orders"
_RULE = "freshness"
_SEVERITY = "warning"
_DETECTED = "2026-02-06T12:00:00Z"


# ---------------------------------------------------------------------------
# Emitter behaviour
# ---------------------------------------------------------------------------

class TestEmitQualityWarn:
    """Tests for emit_quality_warn."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_calls_with_correct_action(self, mock_log):
        emit_quality_warn(
            db=MagicMock(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            rule_type=_RULE,
            severity=_SEVERITY,
            detected_at=_DETECTED,
        )

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["action"] == AuditAction.DATA_QUALITY_WARN
        assert call_kwargs["outcome"] == AuditOutcome.SUCCESS

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_metadata_fields(self, mock_log):
        emit_quality_warn(
            db=MagicMock(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            rule_type=_RULE,
            severity=_SEVERITY,
            detected_at=_DETECTED,
        )

        metadata = mock_log.call_args[1]["metadata"]
        assert metadata["tenant_id"] == _TENANT
        assert metadata["dataset"] == _DATASET
        assert metadata["rule_type"] == _RULE
        assert metadata["severity"] == _SEVERITY
        assert metadata["detected_at"] == _DETECTED


class TestEmitQualityFail:
    """Tests for emit_quality_fail."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_calls_with_failure_outcome(self, mock_log):
        emit_quality_fail(
            db=MagicMock(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            rule_type=_RULE,
            severity="critical",
            detected_at=_DETECTED,
        )

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["action"] == AuditAction.DATA_QUALITY_FAIL
        assert call_kwargs["outcome"] == AuditOutcome.FAILURE


class TestEmitQualityRecovered:
    """Tests for emit_quality_recovered."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_calls_with_success_outcome(self, mock_log):
        emit_quality_recovered(
            db=MagicMock(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            rule_type=_RULE,
            severity=_SEVERITY,
            detected_at=_DETECTED,
        )

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["action"] == AuditAction.DATA_QUALITY_RECOVERED
        assert call_kwargs["outcome"] == AuditOutcome.SUCCESS


class TestAuditFailureIsolation:
    """Audit failures must never propagate to callers."""

    @patch(
        "src.platform.audit.log_system_audit_event_sync",
        side_effect=RuntimeError("DB down"),
    )
    def test_warn_swallows_exception(self, _mock_log):
        # Should not raise
        emit_quality_warn(
            db=MagicMock(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            rule_type=_RULE,
            severity=_SEVERITY,
            detected_at=_DETECTED,
        )

    @patch(
        "src.platform.audit.log_system_audit_event_sync",
        side_effect=RuntimeError("DB down"),
    )
    def test_fail_swallows_exception(self, _mock_log):
        emit_quality_fail(
            db=MagicMock(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            rule_type=_RULE,
            severity=_SEVERITY,
            detected_at=_DETECTED,
        )

    @patch(
        "src.platform.audit.log_system_audit_event_sync",
        side_effect=RuntimeError("DB down"),
    )
    def test_recovered_swallows_exception(self, _mock_log):
        emit_quality_recovered(
            db=MagicMock(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            rule_type=_RULE,
            severity=_SEVERITY,
            detected_at=_DETECTED,
        )


# ---------------------------------------------------------------------------
# Enum and registry registration
# ---------------------------------------------------------------------------

class TestEnumRegistration:
    """AuditAction enum has the 3 DQ values."""

    def test_warn_enum_exists(self):
        assert AuditAction.DATA_QUALITY_WARN.value == "data.quality.warn"

    def test_fail_enum_exists(self):
        assert AuditAction.DATA_QUALITY_FAIL.value == "data.quality.fail"

    def test_recovered_enum_exists(self):
        assert AuditAction.DATA_QUALITY_RECOVERED.value == "data.quality.recovered"


class TestAuditableEventsRegistry:
    """AUDITABLE_EVENTS in audit.py has all 3 DQ entries with required fields."""

    def test_warn_registered(self):
        meta = AUDITABLE_EVENTS[AuditAction.DATA_QUALITY_WARN]
        assert "tenant_id" in meta.required_fields
        assert "dataset" in meta.required_fields
        assert "rule_type" in meta.required_fields
        assert "severity" in meta.required_fields
        assert "detected_at" in meta.required_fields

    def test_fail_registered(self):
        meta = AUDITABLE_EVENTS[AuditAction.DATA_QUALITY_FAIL]
        assert meta.risk_level == "high"

    def test_recovered_registered(self):
        meta = AUDITABLE_EVENTS[AuditAction.DATA_QUALITY_RECOVERED]
        assert meta.risk_level == "low"


class TestCanonicalRegistry:
    """audit_events.py canonical registry has DQ events."""

    def test_events_defined(self):
        assert "data.quality.warn" in CANONICAL_EVENTS
        assert "data.quality.fail" in CANONICAL_EVENTS
        assert "data.quality.recovered" in CANONICAL_EVENTS

    def test_category_exists(self):
        assert "data_quality" in EVENT_CATEGORIES
        assert "data.quality.warn" in EVENT_CATEGORIES["data_quality"]
        assert "data.quality.fail" in EVENT_CATEGORIES["data_quality"]
        assert "data.quality.recovered" in EVENT_CATEGORIES["data_quality"]

    def test_severity_levels(self):
        assert EVENT_SEVERITY["data.quality.warn"] == "medium"
        assert EVENT_SEVERITY["data.quality.fail"] == "high"
        assert EVENT_SEVERITY["data.quality.recovered"] == "low"
