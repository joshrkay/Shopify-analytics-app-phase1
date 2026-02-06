"""
Unit tests for root cause signal model, enum, and hypothesis dataclass.

Story 4.2 - Data Quality Root Cause Signals (Prompt 4.2.1)
"""

from unittest.mock import patch, MagicMock

from src.models.root_cause_signal import (
    RootCauseType,
    RootCauseHypothesis,
    RootCauseSignal,
)
from src.platform.audit import AuditAction, AuditOutcome, AUDITABLE_EVENTS
from src.services.audit_logger import emit_root_cause_signal_generated


# ---------------------------------------------------------------------------
# RootCauseType enum
# ---------------------------------------------------------------------------

class TestRootCauseType:
    """Verify all five root cause types."""

    def test_all_five_types_exist(self):
        assert len(RootCauseType) == 5

    def test_ingestion_failure(self):
        assert RootCauseType.INGESTION_FAILURE.value == "ingestion_failure"

    def test_schema_drift(self):
        assert RootCauseType.SCHEMA_DRIFT.value == "schema_drift"

    def test_transformation_regression(self):
        assert RootCauseType.TRANSFORMATION_REGRESSION.value == "transformation_regression"

    def test_upstream_data_shift(self):
        assert RootCauseType.UPSTREAM_DATA_SHIFT.value == "upstream_data_shift"

    def test_downstream_logic_change(self):
        assert RootCauseType.DOWNSTREAM_LOGIC_CHANGE.value == "downstream_logic_change"

    def test_enum_values_are_strings(self):
        for member in RootCauseType:
            assert isinstance(member.value, str)

    def test_enum_values_are_snake_case(self):
        for member in RootCauseType:
            assert member.value == member.value.lower()
            assert " " not in member.value


# ---------------------------------------------------------------------------
# RootCauseHypothesis dataclass
# ---------------------------------------------------------------------------

class TestRootCauseHypothesis:
    """Verify hypothesis serialization and deserialization."""

    def _make_hypothesis(self, **overrides):
        defaults = {
            "cause_type": "ingestion_failure",
            "confidence_score": 0.85,
            "evidence": {"signal": "sync_failure", "error_code": "auth_error"},
            "first_seen_at": "2026-02-06T12:00:00Z",
            "suggested_next_step": "Check credentials",
        }
        defaults.update(overrides)
        return RootCauseHypothesis(**defaults)

    def test_to_dict_roundtrip(self):
        original = self._make_hypothesis()
        d = original.to_dict()
        restored = RootCauseHypothesis.from_dict(d)

        assert restored.cause_type == original.cause_type
        assert restored.confidence_score == original.confidence_score
        assert restored.evidence == original.evidence
        assert restored.first_seen_at == original.first_seen_at
        assert restored.suggested_next_step == original.suggested_next_step

    def test_to_dict_keys(self):
        h = self._make_hypothesis()
        d = h.to_dict()
        expected_keys = {
            "cause_type", "confidence_score", "evidence",
            "first_seen_at", "suggested_next_step",
        }
        assert set(d.keys()) == expected_keys

    def test_from_dict_missing_fields(self):
        h = RootCauseHypothesis.from_dict({})
        assert h.cause_type == ""
        assert h.confidence_score == 0.0
        assert h.evidence == {}
        assert h.first_seen_at is None
        assert h.suggested_next_step == ""

    def test_confidence_float_conversion(self):
        h = RootCauseHypothesis.from_dict({"confidence_score": "0.9"})
        assert h.confidence_score == 0.9

    def test_evidence_preserved(self):
        evidence = {
            "signal": "sync_failure",
            "nested": {"key": [1, 2, 3]},
        }
        h = self._make_hypothesis(evidence=evidence)
        d = h.to_dict()
        restored = RootCauseHypothesis.from_dict(d)
        assert restored.evidence == evidence


# ---------------------------------------------------------------------------
# RootCauseSignal model
# ---------------------------------------------------------------------------

class TestRootCauseSignalModel:
    """Verify SQLAlchemy model structure."""

    def test_tablename(self):
        assert RootCauseSignal.__tablename__ == "root_cause_signals"

    def test_has_id_column(self):
        columns = {c.name for c in RootCauseSignal.__table__.columns}
        assert "id" in columns

    def test_has_tenant_id_column(self):
        columns = {c.name for c in RootCauseSignal.__table__.columns}
        assert "tenant_id" in columns

    def test_has_timestamp_columns(self):
        columns = {c.name for c in RootCauseSignal.__table__.columns}
        assert "created_at" in columns
        assert "updated_at" in columns

    def test_has_all_required_columns(self):
        columns = {c.name for c in RootCauseSignal.__table__.columns}
        required = {
            "id", "tenant_id", "dataset", "anomaly_type", "detected_at",
            "hypotheses", "top_cause_type", "top_confidence",
            "hypothesis_count", "is_active", "connector_id",
            "correlation_id", "created_at", "updated_at",
        }
        assert required.issubset(columns)

    def test_hypotheses_default(self):
        col = RootCauseSignal.__table__.columns["hypotheses"]
        assert col.default is not None

    def test_is_active_default(self):
        col = RootCauseSignal.__table__.columns["is_active"]
        assert col.default is not None

    def test_hypothesis_count_default(self):
        col = RootCauseSignal.__table__.columns["hypothesis_count"]
        assert col.default is not None


# ---------------------------------------------------------------------------
# Audit enum and registry
# ---------------------------------------------------------------------------

class TestRootCauseAuditRegistration:
    """Verify audit action enum and AUDITABLE_EVENTS registry."""

    def test_enum_exists(self):
        assert AuditAction.ROOT_CAUSE_SIGNAL_GENERATED.value == "data.quality.root_cause_generated"

    def test_registered_in_auditable_events(self):
        meta = AUDITABLE_EVENTS[AuditAction.ROOT_CAUSE_SIGNAL_GENERATED]
        assert "tenant_id" in meta.required_fields
        assert "dataset" in meta.required_fields
        assert "anomaly_type" in meta.required_fields
        assert "signal_id" in meta.required_fields
        assert "top_cause_type" in meta.required_fields
        assert "hypothesis_count" in meta.required_fields

    def test_risk_level(self):
        meta = AUDITABLE_EVENTS[AuditAction.ROOT_CAUSE_SIGNAL_GENERATED]
        assert meta.risk_level == "medium"


# ---------------------------------------------------------------------------
# Audit emitter
# ---------------------------------------------------------------------------

class TestEmitRootCauseSignalGenerated:
    """Tests for emit_root_cause_signal_generated."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_calls_with_correct_action(self, mock_log):
        emit_root_cause_signal_generated(
            db=MagicMock(),
            tenant_id="t-001",
            dataset="shopify_orders",
            anomaly_type="freshness",
            signal_id="sig-001",
            top_cause_type="ingestion_failure",
            hypothesis_count=2,
            detected_at="2026-02-06T12:00:00Z",
        )

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["action"] == AuditAction.ROOT_CAUSE_SIGNAL_GENERATED
        assert call_kwargs["outcome"] == AuditOutcome.SUCCESS

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_metadata_fields(self, mock_log):
        emit_root_cause_signal_generated(
            db=MagicMock(),
            tenant_id="t-001",
            dataset="shopify_orders",
            anomaly_type="freshness",
            signal_id="sig-001",
            top_cause_type="ingestion_failure",
            hypothesis_count=2,
            detected_at="2026-02-06T12:00:00Z",
        )

        metadata = mock_log.call_args[1]["metadata"]
        assert metadata["tenant_id"] == "t-001"
        assert metadata["dataset"] == "shopify_orders"
        assert metadata["signal_id"] == "sig-001"
        assert metadata["top_cause_type"] == "ingestion_failure"
        assert metadata["hypothesis_count"] == 2

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_none_top_cause_type(self, mock_log):
        emit_root_cause_signal_generated(
            db=MagicMock(),
            tenant_id="t-001",
            dataset="shopify_orders",
            anomaly_type="freshness",
            signal_id="sig-001",
            top_cause_type=None,
            hypothesis_count=0,
            detected_at="2026-02-06T12:00:00Z",
        )

        metadata = mock_log.call_args[1]["metadata"]
        assert metadata["top_cause_type"] == "none"

    @patch(
        "src.platform.audit.log_system_audit_event_sync",
        side_effect=RuntimeError("DB down"),
    )
    def test_swallows_exception(self, _mock):
        # Should not raise
        emit_root_cause_signal_generated(
            db=MagicMock(),
            tenant_id="t-001",
            dataset="shopify_orders",
            anomaly_type="freshness",
            signal_id="sig-001",
            top_cause_type="ingestion_failure",
            hypothesis_count=1,
            detected_at="2026-02-06T12:00:00Z",
        )
