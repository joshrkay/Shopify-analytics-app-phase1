"""
Unit tests for admin diagnostics API routes and schemas.

Story 4.2 - Data Quality Root Cause Signals (Prompts 4.2.7-4.2.8)
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.api.routes.admin_diagnostics import (
    _build_evidence_links,
    _build_investigation_steps,
    _signal_to_response,
)
from src.api.schemas.diagnostics_response import (
    AnomalySummaryResponse,
    DiagnosticsListResponse,
    DiagnosticsResponse,
    EvidenceLink,
    RankedCauseResponse,
)
from src.models.root_cause_signal import RootCauseHypothesis
from src.platform.audit import AuditAction, AUDITABLE_EVENTS
from src.services.audit_logger import (
    emit_root_cause_signal_generated,
    emit_root_cause_signal_updated,
)


_TENANT = "tenant_test_123"
_DATASET = "shopify_orders"
_NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Schema Tests
# ---------------------------------------------------------------------------


class TestDiagnosticsSchemas:
    """Verify Pydantic response schemas."""

    def test_evidence_link_creation(self):
        link = EvidenceLink(
            label="Sync history",
            link_type="sync_run",
            resource_id="conn_123",
        )
        assert link.label == "Sync history"
        assert link.link_type == "sync_run"
        assert link.resource_id == "conn_123"

    def test_evidence_link_null_resource(self):
        link = EvidenceLink(label="DQ results", link_type="dq_result")
        assert link.resource_id is None

    def test_ranked_cause_response(self):
        cause = RankedCauseResponse(
            rank=1,
            cause_type="ingestion_failure",
            confidence_score=0.85,
            evidence={"signal": "sync_failure"},
            first_seen_at="2025-06-15T12:00:00+00:00",
            suggested_next_step="Check Airbyte",
            evidence_links=[],
        )
        assert cause.rank == 1
        assert cause.confidence_score == 0.85

    def test_ranked_cause_confidence_bounds(self):
        with pytest.raises(Exception):
            RankedCauseResponse(
                rank=1,
                cause_type="test",
                confidence_score=1.5,
                evidence={},
                suggested_next_step="",
                evidence_links=[],
            )

    def test_anomaly_summary_response(self):
        summary = AnomalySummaryResponse(
            dataset="shopify_orders",
            anomaly_type="volume_anomaly",
            detected_at="2025-06-15T12:00:00+00:00",
        )
        assert summary.dataset == "shopify_orders"
        assert summary.connector_id is None

    def test_diagnostics_response(self):
        resp = DiagnosticsResponse(
            signal_id="sig_123",
            anomaly_summary=AnomalySummaryResponse(
                dataset="shopify_orders",
                anomaly_type="volume_anomaly",
                detected_at="2025-06-15T12:00:00+00:00",
            ),
            ranked_causes=[],
            total_hypotheses=0,
            confidence_sum=0.0,
            analysis_duration_ms=12.5,
            investigation_steps=["Manual review"],
            is_active=True,
        )
        assert resp.signal_id == "sig_123"
        assert resp.total_hypotheses == 0
        assert resp.is_active is True

    def test_diagnostics_list_response(self):
        resp = DiagnosticsListResponse(
            signals=[],
            total=0,
            has_more=False,
        )
        assert resp.total == 0
        assert resp.has_more is False


# ---------------------------------------------------------------------------
# Evidence Link Building
# ---------------------------------------------------------------------------


class TestBuildEvidenceLinks:
    """Verify evidence link construction."""

    def test_sync_run_link_from_connector_id(self):
        links = _build_evidence_links(
            {"evidence": {"signal": "sync_failure"}},
            connector_id="conn_abc",
        )
        sync_links = [l for l in links if l.link_type == "sync_run"]
        assert len(sync_links) == 1
        assert sync_links[0].resource_id == "conn_abc"

    def test_dbt_link_for_model_failure(self):
        links = _build_evidence_links(
            {"evidence": {"signal": "dbt_model_failure", "dbt_generated_at": "2025-06-15"}},
        )
        dbt_links = [l for l in links if l.link_type == "dbt_run"]
        assert len(dbt_links) == 1

    def test_log_link_for_sync_failure(self):
        links = _build_evidence_links(
            {"evidence": {"signal": "sync_failure", "failed_job_id": "job_123"}},
        )
        log_links = [l for l in links if l.link_type == "log"]
        assert len(log_links) == 1
        assert log_links[0].resource_id == "job_123"

    def test_no_links_for_unknown_signal(self):
        links = _build_evidence_links(
            {"evidence": {"signal": "unknown"}},
        )
        assert len(links) == 0

    def test_dq_result_link_for_historical_drift(self):
        links = _build_evidence_links(
            {"evidence": {"signal": "historical_drift_detected"}},
        )
        dq_links = [l for l in links if l.link_type == "dq_result"]
        assert len(dq_links) == 1


# ---------------------------------------------------------------------------
# Investigation Steps
# ---------------------------------------------------------------------------


class TestBuildInvestigationSteps:
    """Verify investigation step generation."""

    def test_steps_from_ranked_causes(self):
        causes = [
            RankedCauseResponse(
                rank=1, cause_type="ingestion_failure",
                confidence_score=0.85, evidence={},
                suggested_next_step="Check Airbyte connection",
                evidence_links=[],
            ),
            RankedCauseResponse(
                rank=2, cause_type="schema_drift",
                confidence_score=0.60, evidence={},
                suggested_next_step="Compare column snapshots",
                evidence_links=[],
            ),
        ]
        steps = _build_investigation_steps(causes)
        assert len(steps) == 2
        assert "ingestion_failure" in steps[0]
        assert "schema_drift" in steps[1]

    def test_deduplication(self):
        causes = [
            RankedCauseResponse(
                rank=1, cause_type="a",
                confidence_score=0.5, evidence={},
                suggested_next_step="Same step",
                evidence_links=[],
            ),
            RankedCauseResponse(
                rank=2, cause_type="b",
                confidence_score=0.3, evidence={},
                suggested_next_step="Same step",
                evidence_links=[],
            ),
        ]
        steps = _build_investigation_steps(causes)
        assert len(steps) == 1

    def test_fallback_when_no_causes(self):
        steps = _build_investigation_steps([])
        assert len(steps) == 1
        assert "manual" in steps[0].lower()


# ---------------------------------------------------------------------------
# Signal to Response Conversion
# ---------------------------------------------------------------------------


class TestSignalToResponse:
    """Verify conversion from model to API response."""

    def _make_signal(self, **overrides):
        defaults = {
            "id": "sig_abc",
            "tenant_id": _TENANT,
            "dataset": _DATASET,
            "anomaly_type": "volume_anomaly",
            "detected_at": _NOW,
            "connector_id": "conn_123",
            "correlation_id": "corr_456",
            "hypotheses": [
                {
                    "cause_type": "ingestion_failure",
                    "confidence_score": 0.85,
                    "evidence": {"signal": "sync_failure"},
                    "first_seen_at": "2025-06-15T12:00:00+00:00",
                    "suggested_next_step": "Check Airbyte",
                },
            ],
            "top_cause_type": "ingestion_failure",
            "top_confidence": 0.85,
            "hypothesis_count": 1,
            "is_active": True,
        }
        defaults.update(overrides)
        signal = MagicMock()
        for k, v in defaults.items():
            setattr(signal, k, v)
        return signal

    def test_basic_conversion(self):
        signal = self._make_signal()
        resp = _signal_to_response(signal)

        assert resp.signal_id == "sig_abc"
        assert resp.anomaly_summary.dataset == _DATASET
        assert resp.anomaly_summary.anomaly_type == "volume_anomaly"
        assert len(resp.ranked_causes) == 1
        assert resp.ranked_causes[0].cause_type == "ingestion_failure"
        assert resp.ranked_causes[0].confidence_score == 0.85
        assert resp.is_active is True

    def test_empty_hypotheses(self):
        signal = self._make_signal(hypotheses=[], hypothesis_count=0)
        resp = _signal_to_response(signal)

        assert len(resp.ranked_causes) == 0
        assert resp.total_hypotheses == 0
        assert resp.confidence_sum == 0.0

    def test_investigation_steps_populated(self):
        signal = self._make_signal()
        resp = _signal_to_response(signal)

        assert len(resp.investigation_steps) > 0

    def test_evidence_links_populated(self):
        signal = self._make_signal()
        resp = _signal_to_response(signal)

        # Should have sync_run link from connector_id and log link from sync_failure
        link_types = [l.link_type for c in resp.ranked_causes for l in c.evidence_links]
        assert "sync_run" in link_types

    def test_multiple_hypotheses_ranked(self):
        signal = self._make_signal(
            hypotheses=[
                {
                    "cause_type": "ingestion_failure",
                    "confidence_score": 0.85,
                    "evidence": {"signal": "sync_failure"},
                    "first_seen_at": None,
                    "suggested_next_step": "Check Airbyte",
                },
                {
                    "cause_type": "schema_drift",
                    "confidence_score": 0.60,
                    "evidence": {"signal": "column_removed"},
                    "first_seen_at": None,
                    "suggested_next_step": "Compare columns",
                },
            ],
            hypothesis_count=2,
        )
        resp = _signal_to_response(signal)

        assert len(resp.ranked_causes) == 2
        assert resp.ranked_causes[0].rank == 1
        assert resp.ranked_causes[1].rank == 2
        assert resp.confidence_sum == 1.45


# ---------------------------------------------------------------------------
# Audit Event Registration
# ---------------------------------------------------------------------------


class TestAuditEventRegistration:
    """Verify audit events are properly registered."""

    def test_root_cause_generated_registered(self):
        assert AuditAction.ROOT_CAUSE_SIGNAL_GENERATED in AUDITABLE_EVENTS

    def test_root_cause_updated_registered(self):
        assert AuditAction.ROOT_CAUSE_SIGNAL_UPDATED in AUDITABLE_EVENTS

    def test_generated_event_metadata(self):
        meta = AUDITABLE_EVENTS[AuditAction.ROOT_CAUSE_SIGNAL_GENERATED]
        assert "signal_id" in meta.required_fields
        assert "tenant_id" in meta.required_fields
        assert "hypothesis_count" in meta.required_fields
        assert meta.risk_level == "medium"

    def test_updated_event_metadata(self):
        meta = AUDITABLE_EVENTS[AuditAction.ROOT_CAUSE_SIGNAL_UPDATED]
        assert "signal_id" in meta.required_fields
        assert "update_type" in meta.required_fields
        assert "highest_confidence" in meta.required_fields
        assert meta.risk_level == "low"

    def test_generated_event_value(self):
        assert AuditAction.ROOT_CAUSE_SIGNAL_GENERATED.value == "data.quality.root_cause_generated"

    def test_updated_event_value(self):
        assert AuditAction.ROOT_CAUSE_SIGNAL_UPDATED.value == "data.quality.root_cause_updated"


# ---------------------------------------------------------------------------
# Audit Emitter Tests
# ---------------------------------------------------------------------------


class TestEmitRootCauseSignalUpdated:
    """Verify the updated audit emitter function."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_emits_correct_action(self, mock_log):
        db = MagicMock()
        emit_root_cause_signal_updated(
            db=db,
            tenant_id=_TENANT,
            dataset=_DATASET,
            signal_id="sig_abc",
            update_type="resolved",
            highest_confidence=0.85,
            hypothesis_count=2,
        )

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["action"] == AuditAction.ROOT_CAUSE_SIGNAL_UPDATED
        assert call_kwargs["resource_type"] == "root_cause_signal"
        assert call_kwargs["resource_id"] == "sig_abc"

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_metadata_fields(self, mock_log):
        db = MagicMock()
        emit_root_cause_signal_updated(
            db=db,
            tenant_id=_TENANT,
            dataset=_DATASET,
            signal_id="sig_abc",
            update_type="re_analyzed",
            highest_confidence=0.75,
            hypothesis_count=3,
            correlation_id="corr_xyz",
        )

        meta = mock_log.call_args[1]["metadata"]
        assert meta["tenant_id"] == _TENANT
        assert meta["dataset"] == _DATASET
        assert meta["signal_id"] == "sig_abc"
        assert meta["update_type"] == "re_analyzed"
        assert meta["highest_confidence"] == 0.75
        assert meta["hypothesis_count"] == 3

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_correlation_id_passed(self, mock_log):
        db = MagicMock()
        emit_root_cause_signal_updated(
            db=db,
            tenant_id=_TENANT,
            dataset=_DATASET,
            signal_id="sig_abc",
            update_type="resolved",
            highest_confidence=0.0,
            hypothesis_count=0,
            correlation_id="corr_999",
        )

        assert mock_log.call_args[1]["correlation_id"] == "corr_999"

    @patch(
        "src.platform.audit.log_system_audit_event_sync",
        side_effect=RuntimeError("audit down"),
    )
    def test_failure_does_not_raise(self, mock_log):
        db = MagicMock()
        # Should not raise
        emit_root_cause_signal_updated(
            db=db,
            tenant_id=_TENANT,
            dataset=_DATASET,
            signal_id="sig_abc",
            update_type="resolved",
            highest_confidence=0.0,
            hypothesis_count=0,
        )
