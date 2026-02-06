"""
Unit tests for the root cause ranking engine.

Story 4.2 - Data Quality Root Cause Signals (Prompt 4.2.5)
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.services.root_cause_ranker import (
    RootCauseRanker,
    RankedRootCause,
    RootCauseAnalysis,
    _normalize_confidences,
    _apply_causal_ordering,
)
from src.diagnostics.ingestion_diagnostics import IngestionDiagnosticResult
from src.diagnostics.schema_drift import SchemaDriftResult
from src.diagnostics.transformation_regression import TransformationRegressionResult
from src.diagnostics.upstream_shift import UpstreamShiftResult

_TENANT = "tenant-test-001"
_DATASET = "shopify_orders"
_NOW = datetime(2026, 2, 6, 12, 0, 0, tzinfo=timezone.utc)


def _mock_db():
    """Create a mock db session."""
    db = MagicMock()
    query = MagicMock()
    query.filter = MagicMock(return_value=query)
    query.order_by = MagicMock(return_value=query)
    query.limit = MagicMock(return_value=query)
    query.all = MagicMock(return_value=[])
    query.first = MagicMock(return_value=None)
    db.query = MagicMock(return_value=query)
    db.add = MagicMock()
    db.commit = MagicMock()
    return db


def _make_ranked(cause_type, confidence, rank=0):
    return RankedRootCause(
        rank=rank,
        cause_type=cause_type,
        confidence_score=confidence,
        evidence={"signal": "test"},
        first_seen_at=_NOW,
        suggested_next_step="Test step",
    )


# ===========================================================================
# Confidence Normalization
# ===========================================================================


class TestConfidenceNormalization:
    """Tests for _normalize_confidences."""

    def test_already_valid_unchanged(self):
        hypotheses = [
            _make_ranked("ingestion_failure", 0.5),
            _make_ranked("schema_drift", 0.3),
        ]
        result = _normalize_confidences(hypotheses)
        assert result[0].confidence_score == 0.5
        assert result[1].confidence_score == 0.3

    def test_proportional_scaling(self):
        hypotheses = [
            _make_ranked("ingestion_failure", 0.9),
            _make_ranked("schema_drift", 0.6),
        ]
        result = _normalize_confidences(hypotheses)
        total = sum(h.confidence_score for h in result)
        assert total <= 1.0 + 0.001  # Allow tiny float rounding

    def test_single_hypothesis_above_one(self):
        hypotheses = [_make_ranked("ingestion_failure", 1.2)]
        result = _normalize_confidences(hypotheses)
        assert result[0].confidence_score <= 1.0

    def test_empty_list(self):
        result = _normalize_confidences([])
        assert result == []


# ===========================================================================
# Causal Ordering
# ===========================================================================


class TestCausalOrdering:
    """Tests for _apply_causal_ordering."""

    def test_sorts_by_confidence_desc(self):
        hypotheses = [
            _make_ranked("schema_drift", 0.5),
            _make_ranked("ingestion_failure", 0.9),
        ]
        result = _apply_causal_ordering(hypotheses)
        assert result[0].cause_type == "ingestion_failure"
        assert result[1].cause_type == "schema_drift"

    def test_ingestion_before_transform_same_confidence(self):
        hypotheses = [
            _make_ranked("transformation_regression", 0.8),
            _make_ranked("ingestion_failure", 0.8),
        ]
        result = _apply_causal_ordering(hypotheses)
        assert result[0].cause_type == "ingestion_failure"

    def test_high_ingestion_dampens_transformation(self):
        hypotheses = [
            _make_ranked("ingestion_failure", 0.9),
            _make_ranked("transformation_regression", 0.8),
        ]
        result = _apply_causal_ordering(hypotheses)
        # Transformation should be dampened to 0.4 (0.8 * 0.5)
        assert result[1].confidence_score == pytest.approx(0.4, abs=0.01)

    def test_no_dampening_below_threshold(self):
        hypotheses = [
            _make_ranked("ingestion_failure", 0.5),
            _make_ranked("transformation_regression", 0.6),
        ]
        result = _apply_causal_ordering(hypotheses)
        # Transformation should NOT be dampened (ingestion <= 0.7)
        # But transformation is sorted first (higher confidence)
        # After sort: transformation 0.6, ingestion 0.5
        # No dampening since top cause is not ingestion with > 0.7
        assert result[0].cause_type == "transformation_regression"
        assert result[0].confidence_score == 0.6

    def test_empty_list(self):
        result = _apply_causal_ordering([])
        assert result == []


# ===========================================================================
# RootCauseRanker
# ===========================================================================


class TestRootCauseRanker:
    """Tests for the main RootCauseRanker class."""

    def test_tenant_id_required(self):
        with pytest.raises(ValueError, match="tenant_id"):
            RootCauseRanker(db_session=_mock_db(), tenant_id="")

    @patch("src.services.root_cause_ranker.diagnose_ingestion_failure")
    @patch("src.services.root_cause_ranker.diagnose_schema_drift")
    @patch("src.services.root_cause_ranker.diagnose_transformation_regression")
    @patch("src.services.root_cause_ranker.diagnose_upstream_shift")
    @patch("src.services.audit_logger.emit_root_cause_signal_generated")
    def test_single_cause_returned(
        self, mock_audit, mock_upstream, mock_transform, mock_schema, mock_ingestion
    ):
        mock_ingestion.return_value = IngestionDiagnosticResult(
            detected=True,
            confidence_score=0.85,
            evidence={"signal": "sync_failure"},
            first_seen_at=_NOW,
            suggested_next_step="Check connection",
        )
        mock_schema.return_value = SchemaDriftResult(detected=False)
        mock_transform.return_value = TransformationRegressionResult(detected=False)
        mock_upstream.return_value = UpstreamShiftResult(detected=False)

        db = _mock_db()
        ranker = RootCauseRanker(db, _TENANT)
        result = ranker.analyze(
            dataset=_DATASET,
            anomaly_type="freshness",
            anomaly_detected_at=_NOW,
            connector_id="conn-001",
        )

        assert len(result.ranked_causes) == 1
        assert result.ranked_causes[0].cause_type == "ingestion_failure"
        assert result.ranked_causes[0].rank == 1

    @patch("src.services.root_cause_ranker.diagnose_ingestion_failure")
    @patch("src.services.root_cause_ranker.diagnose_schema_drift")
    @patch("src.services.root_cause_ranker.diagnose_transformation_regression")
    @patch("src.services.root_cause_ranker.diagnose_upstream_shift")
    @patch("src.services.audit_logger.emit_root_cause_signal_generated")
    def test_multiple_causes_ranked(
        self, mock_audit, mock_upstream, mock_transform, mock_schema, mock_ingestion
    ):
        mock_ingestion.return_value = IngestionDiagnosticResult(
            detected=True, confidence_score=0.60,
            evidence={"signal": "partial_sync"},
            suggested_next_step="Check rows",
        )
        mock_schema.return_value = SchemaDriftResult(
            detected=True, confidence_score=0.80,
            evidence={"signal": "column_removed"},
            suggested_next_step="Check schema",
        )
        mock_transform.return_value = TransformationRegressionResult(
            detected=True, confidence_score=0.40,
            evidence={"signal": "dbt_model_failure"},
            suggested_next_step="Check dbt",
        )
        mock_upstream.return_value = UpstreamShiftResult(detected=False)

        db = _mock_db()
        ranker = RootCauseRanker(db, _TENANT)
        result = ranker.analyze(
            dataset=_DATASET,
            anomaly_type="volume_anomaly",
            anomaly_detected_at=_NOW,
        )

        assert len(result.ranked_causes) == 3
        # Should be sorted by confidence desc
        assert result.ranked_causes[0].confidence_score >= result.ranked_causes[1].confidence_score

    @patch("src.services.root_cause_ranker.diagnose_ingestion_failure")
    @patch("src.services.root_cause_ranker.diagnose_schema_drift")
    @patch("src.services.root_cause_ranker.diagnose_transformation_regression")
    @patch("src.services.root_cause_ranker.diagnose_upstream_shift")
    @patch("src.services.audit_logger.emit_root_cause_signal_generated")
    def test_confidence_sum_le_one(
        self, mock_audit, mock_upstream, mock_transform, mock_schema, mock_ingestion
    ):
        mock_ingestion.return_value = IngestionDiagnosticResult(
            detected=True, confidence_score=0.90,
            evidence={}, suggested_next_step="",
        )
        mock_schema.return_value = SchemaDriftResult(
            detected=True, confidence_score=0.85,
            evidence={}, suggested_next_step="",
        )
        mock_transform.return_value = TransformationRegressionResult(
            detected=True, confidence_score=0.70,
            evidence={}, suggested_next_step="",
        )
        mock_upstream.return_value = UpstreamShiftResult(
            detected=True, confidence_score=0.60,
            evidence={}, suggested_next_step="",
        )

        db = _mock_db()
        ranker = RootCauseRanker(db, _TENANT)
        result = ranker.analyze(
            dataset=_DATASET,
            anomaly_type="freshness",
            anomaly_detected_at=_NOW,
        )

        assert result.confidence_sum <= 1.0 + 0.001

    @patch("src.services.root_cause_ranker.diagnose_ingestion_failure")
    @patch("src.services.root_cause_ranker.diagnose_schema_drift")
    @patch("src.services.root_cause_ranker.diagnose_transformation_regression")
    @patch("src.services.root_cause_ranker.diagnose_upstream_shift")
    @patch("src.services.audit_logger.emit_root_cause_signal_generated")
    def test_top_n_truncation(
        self, mock_audit, mock_upstream, mock_transform, mock_schema, mock_ingestion
    ):
        mock_ingestion.return_value = IngestionDiagnosticResult(
            detected=True, confidence_score=0.5,
            evidence={}, suggested_next_step="",
        )
        mock_schema.return_value = SchemaDriftResult(
            detected=True, confidence_score=0.5,
            evidence={}, suggested_next_step="",
        )
        mock_transform.return_value = TransformationRegressionResult(
            detected=True, confidence_score=0.5,
            evidence={}, suggested_next_step="",
        )
        mock_upstream.return_value = UpstreamShiftResult(
            detected=True, confidence_score=0.5,
            evidence={}, suggested_next_step="",
        )

        db = _mock_db()
        ranker = RootCauseRanker(db, _TENANT)
        result = ranker.analyze(
            dataset=_DATASET,
            anomaly_type="freshness",
            anomaly_detected_at=_NOW,
            top_n=2,
        )

        assert len(result.ranked_causes) == 2

    @patch("src.services.root_cause_ranker.diagnose_ingestion_failure")
    @patch("src.services.root_cause_ranker.diagnose_schema_drift")
    @patch("src.services.root_cause_ranker.diagnose_transformation_regression")
    @patch("src.services.root_cause_ranker.diagnose_upstream_shift")
    @patch("src.services.audit_logger.emit_root_cause_signal_generated")
    def test_no_causes_empty_list(
        self, mock_audit, mock_upstream, mock_transform, mock_schema, mock_ingestion
    ):
        mock_ingestion.return_value = IngestionDiagnosticResult(detected=False)
        mock_schema.return_value = SchemaDriftResult(detected=False)
        mock_transform.return_value = TransformationRegressionResult(detected=False)
        mock_upstream.return_value = UpstreamShiftResult(detected=False)

        db = _mock_db()
        ranker = RootCauseRanker(db, _TENANT)
        result = ranker.analyze(
            dataset=_DATASET,
            anomaly_type="freshness",
            anomaly_detected_at=_NOW,
        )

        assert result.ranked_causes == []
        assert result.total_hypotheses == 0
        assert result.confidence_sum == 0.0

    @patch("src.services.root_cause_ranker.diagnose_ingestion_failure")
    @patch("src.services.root_cause_ranker.diagnose_schema_drift")
    @patch("src.services.root_cause_ranker.diagnose_transformation_regression")
    @patch("src.services.root_cause_ranker.diagnose_upstream_shift")
    @patch("src.services.audit_logger.emit_root_cause_signal_generated")
    def test_signal_persisted(
        self, mock_audit, mock_upstream, mock_transform, mock_schema, mock_ingestion
    ):
        mock_ingestion.return_value = IngestionDiagnosticResult(
            detected=True, confidence_score=0.85,
            evidence={}, suggested_next_step="",
        )
        mock_schema.return_value = SchemaDriftResult(detected=False)
        mock_transform.return_value = TransformationRegressionResult(detected=False)
        mock_upstream.return_value = UpstreamShiftResult(detected=False)

        db = _mock_db()
        ranker = RootCauseRanker(db, _TENANT)
        ranker.analyze(
            dataset=_DATASET,
            anomaly_type="freshness",
            anomaly_detected_at=_NOW,
        )

        db.add.assert_called_once()
        db.commit.assert_called_once()

    @patch("src.services.root_cause_ranker.diagnose_ingestion_failure")
    @patch("src.services.root_cause_ranker.diagnose_schema_drift")
    @patch("src.services.root_cause_ranker.diagnose_transformation_regression")
    @patch("src.services.root_cause_ranker.diagnose_upstream_shift")
    @patch("src.services.audit_logger.emit_root_cause_signal_generated")
    def test_audit_event_emitted(
        self, mock_audit, mock_upstream, mock_transform, mock_schema, mock_ingestion
    ):
        mock_ingestion.return_value = IngestionDiagnosticResult(detected=False)
        mock_schema.return_value = SchemaDriftResult(detected=False)
        mock_transform.return_value = TransformationRegressionResult(detected=False)
        mock_upstream.return_value = UpstreamShiftResult(detected=False)

        db = _mock_db()
        ranker = RootCauseRanker(db, _TENANT)
        ranker.analyze(
            dataset=_DATASET,
            anomaly_type="freshness",
            anomaly_detected_at=_NOW,
        )

        mock_audit.assert_called_once()

    @patch("src.services.root_cause_ranker.diagnose_ingestion_failure")
    @patch("src.services.root_cause_ranker.diagnose_schema_drift")
    @patch("src.services.root_cause_ranker.diagnose_transformation_regression")
    @patch("src.services.root_cause_ranker.diagnose_upstream_shift")
    @patch(
        "src.services.audit_logger.emit_root_cause_signal_generated",
        side_effect=RuntimeError("audit failed"),
    )
    def test_audit_failure_does_not_crash(
        self, mock_audit, mock_upstream, mock_transform, mock_schema, mock_ingestion
    ):
        mock_ingestion.return_value = IngestionDiagnosticResult(detected=False)
        mock_schema.return_value = SchemaDriftResult(detected=False)
        mock_transform.return_value = TransformationRegressionResult(detected=False)
        mock_upstream.return_value = UpstreamShiftResult(detected=False)

        db = _mock_db()
        ranker = RootCauseRanker(db, _TENANT)
        # Should not raise
        result = ranker.analyze(
            dataset=_DATASET,
            anomaly_type="freshness",
            anomaly_detected_at=_NOW,
        )
        assert result is not None

    @patch("src.services.root_cause_ranker.diagnose_ingestion_failure")
    @patch("src.services.root_cause_ranker.diagnose_schema_drift")
    @patch("src.services.root_cause_ranker.diagnose_transformation_regression")
    @patch("src.services.root_cause_ranker.diagnose_upstream_shift")
    @patch("src.services.audit_logger.emit_root_cause_signal_generated")
    def test_analysis_duration_tracked(
        self, mock_audit, mock_upstream, mock_transform, mock_schema, mock_ingestion
    ):
        mock_ingestion.return_value = IngestionDiagnosticResult(detected=False)
        mock_schema.return_value = SchemaDriftResult(detected=False)
        mock_transform.return_value = TransformationRegressionResult(detected=False)
        mock_upstream.return_value = UpstreamShiftResult(detected=False)

        db = _mock_db()
        ranker = RootCauseRanker(db, _TENANT)
        result = ranker.analyze(
            dataset=_DATASET,
            anomaly_type="freshness",
            anomaly_detected_at=_NOW,
        )

        assert result.analysis_duration_ms >= 0

    @patch("src.services.root_cause_ranker.diagnose_ingestion_failure")
    @patch("src.services.root_cause_ranker.diagnose_schema_drift")
    @patch("src.services.root_cause_ranker.diagnose_transformation_regression")
    @patch("src.services.root_cause_ranker.diagnose_upstream_shift")
    @patch("src.services.audit_logger.emit_root_cause_signal_generated")
    def test_default_top_n_is_three(
        self, mock_audit, mock_upstream, mock_transform, mock_schema, mock_ingestion
    ):
        mock_ingestion.return_value = IngestionDiagnosticResult(
            detected=True, confidence_score=0.5,
            evidence={}, suggested_next_step="",
        )
        mock_schema.return_value = SchemaDriftResult(
            detected=True, confidence_score=0.5,
            evidence={}, suggested_next_step="",
        )
        mock_transform.return_value = TransformationRegressionResult(
            detected=True, confidence_score=0.5,
            evidence={}, suggested_next_step="",
        )
        mock_upstream.return_value = UpstreamShiftResult(
            detected=True, confidence_score=0.5,
            evidence={}, suggested_next_step="",
        )

        db = _mock_db()
        ranker = RootCauseRanker(db, _TENANT)
        result = ranker.analyze(
            dataset=_DATASET,
            anomaly_type="freshness",
            anomaly_detected_at=_NOW,
            # top_n defaults to 3
        )

        assert len(result.ranked_causes) == 3


class TestRankedRootCause:
    """Tests for RankedRootCause.to_hypothesis."""

    def test_to_hypothesis(self):
        rc = _make_ranked("ingestion_failure", 0.85)
        h = rc.to_hypothesis()
        assert h.cause_type == "ingestion_failure"
        assert h.confidence_score == 0.85
        assert h.suggested_next_step == "Test step"

    def test_to_hypothesis_none_first_seen(self):
        rc = RankedRootCause(
            rank=1,
            cause_type="schema_drift",
            confidence_score=0.7,
            evidence={},
            first_seen_at=None,
            suggested_next_step="Check",
        )
        h = rc.to_hypothesis()
        assert h.first_seen_at is None
