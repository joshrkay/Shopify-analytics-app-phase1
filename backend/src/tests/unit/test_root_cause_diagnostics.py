"""
Unit tests for all four root cause diagnostic modules.

Story 4.2 - Data Quality Root Cause Signals (Prompts 4.2.2–4.2.4)
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.diagnostics.ingestion_diagnostics import (
    diagnose_ingestion_failure,
    IngestionDiagnosticResult,
)
from src.diagnostics.schema_drift import (
    diagnose_schema_drift,
    SchemaDriftResult,
)
from src.diagnostics.transformation_regression import (
    diagnose_transformation_regression,
    TransformationRegressionResult,
)
from src.diagnostics.upstream_shift import (
    diagnose_upstream_shift,
    UpstreamShiftResult,
)
from src.ingestion.dbt_artifact_parser import (
    DbtModelResult,
    DbtRunSummary,
    DbtFreshnessSummary,
    DbtSourceFreshnessResult,
)

_TENANT = "tenant-test-001"
_CONNECTOR = "conn-001"
_DATASET = "shopify_orders"
_NOW = datetime(2026, 2, 6, 12, 0, 0, tzinfo=timezone.utc)


def _mock_db():
    """Create a mock db session with chainable query interface."""
    db = MagicMock()
    query = MagicMock()
    query.filter = MagicMock(return_value=query)
    query.order_by = MagicMock(return_value=query)
    query.limit = MagicMock(return_value=query)
    query.all = MagicMock(return_value=[])
    query.first = MagicMock(return_value=None)
    db.query = MagicMock(return_value=query)
    return db


# ===========================================================================
# Ingestion Diagnostics
# ===========================================================================


class TestIngestionDiagnostics:
    """Tests for ingestion failure detection."""

    def test_empty_tenant_returns_not_detected(self):
        result = diagnose_ingestion_failure(
            db_session=_mock_db(),
            tenant_id="",
            connector_id=_CONNECTOR,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
        )
        assert result.detected is False

    def test_empty_connector_returns_not_detected(self):
        result = diagnose_ingestion_failure(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            connector_id="",
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
        )
        assert result.detected is False

    @patch("src.diagnostics.ingestion_diagnostics._get_recent_failed_jobs")
    @patch("src.diagnostics.ingestion_diagnostics._get_running_jobs")
    @patch("src.diagnostics.ingestion_diagnostics._get_recent_sync_runs")
    def test_sync_failure_detected(
        self, mock_sync_runs, mock_running, mock_failed
    ):
        failed_job = MagicMock()
        failed_job.job_id = "job-001"
        failed_job.error_message = "Connection refused"
        failed_job.error_code = "server_error"
        failed_job.retry_count = 3
        failed_job.created_at = _NOW - timedelta(hours=1)

        mock_failed.return_value = [failed_job]
        mock_running.return_value = []
        mock_sync_runs.return_value = []

        db = _mock_db()
        # Mock connector query
        connector = MagicMock()
        connector.last_sync_at = _NOW - timedelta(hours=2)
        connector.last_sync_status = "failed"
        db.query.return_value.filter.return_value.first.return_value = connector

        result = diagnose_ingestion_failure(
            db_session=db,
            tenant_id=_TENANT,
            connector_id=_CONNECTOR,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
        )

        assert result.detected is True
        assert result.cause_type == "ingestion_failure"
        assert result.confidence_score >= 0.85
        assert result.evidence["signal"] == "sync_failure"
        assert result.evidence["failed_job_id"] == "job-001"
        assert result.evidence["error_message"] == "Connection refused"

    @patch("src.diagnostics.ingestion_diagnostics._get_recent_failed_jobs")
    @patch("src.diagnostics.ingestion_diagnostics._get_running_jobs")
    @patch("src.diagnostics.ingestion_diagnostics._get_recent_sync_runs")
    def test_auth_error_boosts_confidence(
        self, mock_sync_runs, mock_running, mock_failed
    ):
        failed_job = MagicMock()
        failed_job.job_id = "job-001"
        failed_job.error_message = "Invalid token"
        failed_job.error_code = "auth_error"
        failed_job.retry_count = 1
        failed_job.created_at = _NOW - timedelta(hours=1)

        mock_failed.return_value = [failed_job]
        mock_running.return_value = []
        mock_sync_runs.return_value = []

        db = _mock_db()
        connector = MagicMock()
        connector.last_sync_at = _NOW - timedelta(hours=2)
        connector.last_sync_status = "failed"
        db.query.return_value.filter.return_value.first.return_value = connector

        result = diagnose_ingestion_failure(
            db_session=db,
            tenant_id=_TENANT,
            connector_id=_CONNECTOR,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
        )

        assert result.detected is True
        assert result.confidence_score >= 0.95

    @patch("src.diagnostics.ingestion_diagnostics._get_recent_failed_jobs")
    @patch("src.diagnostics.ingestion_diagnostics._get_running_jobs")
    @patch("src.diagnostics.ingestion_diagnostics._get_recent_sync_runs")
    def test_healthy_ingestion_not_detected(
        self, mock_sync_runs, mock_running, mock_failed
    ):
        mock_failed.return_value = []
        mock_running.return_value = []
        mock_sync_runs.return_value = []

        db = _mock_db()
        connector = MagicMock()
        connector.last_sync_at = _NOW - timedelta(minutes=30)
        connector.last_sync_status = "success"
        connector.source_type = "shopify"
        db.query.return_value.filter.return_value.first.return_value = connector

        result = diagnose_ingestion_failure(
            db_session=db,
            tenant_id=_TENANT,
            connector_id=_CONNECTOR,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
        )

        assert result.detected is False

    @patch("src.diagnostics.ingestion_diagnostics._get_recent_failed_jobs")
    @patch("src.diagnostics.ingestion_diagnostics._get_running_jobs")
    @patch("src.diagnostics.ingestion_diagnostics._get_recent_sync_runs")
    def test_partial_sync_detected(
        self, mock_sync_runs, mock_running, mock_failed
    ):
        mock_failed.return_value = []
        mock_running.return_value = []

        # Latest run has very few rows compared to baseline
        latest = MagicMock()
        latest.rows_synced = 10
        latest.started_at = _NOW - timedelta(hours=1)
        latest.duration_seconds = 30

        baseline1 = MagicMock()
        baseline1.rows_synced = 1000
        baseline1.duration_seconds = 30

        baseline2 = MagicMock()
        baseline2.rows_synced = 900
        baseline2.duration_seconds = 28

        mock_sync_runs.return_value = [latest, baseline1, baseline2]

        db = _mock_db()
        connector = MagicMock()
        connector.last_sync_at = _NOW - timedelta(hours=1)
        connector.last_sync_status = "success"
        db.query.return_value.filter.return_value.first.return_value = connector

        result = diagnose_ingestion_failure(
            db_session=db,
            tenant_id=_TENANT,
            connector_id=_CONNECTOR,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
        )

        assert result.detected is True
        assert result.evidence["signal"] == "partial_sync"
        assert 0.6 <= result.confidence_score <= 0.8

    @patch("src.diagnostics.ingestion_diagnostics._get_recent_failed_jobs")
    @patch("src.diagnostics.ingestion_diagnostics._get_running_jobs")
    @patch("src.diagnostics.ingestion_diagnostics._get_recent_sync_runs")
    def test_missing_sync_detected(
        self, mock_sync_runs, mock_running, mock_failed
    ):
        mock_failed.return_value = []
        mock_running.return_value = []
        mock_sync_runs.return_value = []

        db = _mock_db()
        connector = MagicMock()
        # Last sync was 12 hours ago for Shopify (expected every 2 hours)
        connector.last_sync_at = _NOW - timedelta(hours=12)
        connector.last_sync_status = "success"
        connector.source_type = "shopify"
        connector.id = _CONNECTOR
        db.query.return_value.filter.return_value.first.return_value = connector

        result = diagnose_ingestion_failure(
            db_session=db,
            tenant_id=_TENANT,
            connector_id=_CONNECTOR,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
        )

        assert result.detected is True
        assert result.evidence["signal"] == "missing_sync"
        assert result.confidence_score >= 0.7

    def test_result_cause_type(self):
        result = IngestionDiagnosticResult(detected=False)
        assert result.cause_type == "ingestion_failure"


# ===========================================================================
# Schema Drift
# ===========================================================================


class TestSchemaDrift:
    """Tests for schema drift detection."""

    def test_none_schemas_not_detected(self):
        result = diagnose_schema_drift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_columns=None,
            baseline_columns=None,
        )
        assert result.detected is False

    def test_identical_schemas_not_detected(self):
        cols = {"id": "integer", "name": "varchar"}
        result = diagnose_schema_drift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_columns=cols,
            baseline_columns=cols,
        )
        assert result.detected is False

    def test_column_removed_detected(self):
        result = diagnose_schema_drift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_columns={"id": "integer"},
            baseline_columns={"id": "integer", "name": "varchar"},
        )
        assert result.detected is True
        assert result.evidence["signal"] == "column_removed"
        assert result.confidence_score >= 0.85

    def test_column_added_detected(self):
        result = diagnose_schema_drift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_columns={"id": "integer", "name": "varchar", "new_col": "text"},
            baseline_columns={"id": "integer", "name": "varchar"},
        )
        assert result.detected is True
        assert result.evidence["signal"] == "column_added"
        assert result.confidence_score <= 0.50

    def test_type_change_detected(self):
        result = diagnose_schema_drift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_columns={"id": "integer", "amount": "integer"},
            baseline_columns={"id": "integer", "amount": "varchar"},
        )
        assert result.detected is True
        assert result.evidence["signal"] == "type_changed"
        assert result.confidence_score >= 0.70

    def test_multiple_changes_boost_confidence(self):
        result = diagnose_schema_drift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_columns={"id": "integer"},
            baseline_columns={
                "id": "integer", "a": "varchar", "b": "varchar",
                "c": "varchar", "d": "varchar",
            },
        )
        assert result.detected is True
        # 4 removals should push confidence near ceiling
        assert result.confidence_score >= 0.90

    def test_dbt_failure_correlation_boosts(self):
        summary = DbtRunSummary(
            generated_at=_NOW,
            elapsed_time_seconds=10.0,
            results=[
                DbtModelResult(
                    model_name="stg_shopify_orders",
                    schema_name="staging",
                    status="error",
                    execution_time_seconds=5.0,
                ),
            ],
            total_models=1, passed=0, failed=0, errored=1, skipped=0,
        )

        result_without = diagnose_schema_drift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_columns={"id": "integer", "amount": "integer"},
            baseline_columns={"id": "integer", "amount": "varchar"},
        )

        result_with = diagnose_schema_drift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_columns={"id": "integer", "amount": "integer"},
            baseline_columns={"id": "integer", "amount": "varchar"},
            dbt_run_summary=summary,
        )

        assert result_with.confidence_score > result_without.confidence_score

    def test_evidence_lists_changes(self):
        result = diagnose_schema_drift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_columns={"id": "integer"},
            baseline_columns={"id": "integer", "name": "varchar"},
        )
        assert len(result.evidence["changes"]) == 1
        assert result.evidence["changes"][0]["change_type"] == "removed"

    def test_result_cause_type(self):
        result = SchemaDriftResult(detected=False)
        assert result.cause_type == "schema_drift"


# ===========================================================================
# Transformation Regression
# ===========================================================================


class TestTransformationRegression:
    """Tests for transformation regression detection."""

    def test_no_summary_not_detected(self):
        result = diagnose_transformation_regression(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            dbt_run_summary=None,
        )
        assert result.detected is False

    def test_no_matching_models_not_detected(self):
        summary = DbtRunSummary(
            generated_at=_NOW,
            elapsed_time_seconds=10.0,
            results=[
                DbtModelResult(
                    model_name="stg_meta_ads",
                    schema_name="staging",
                    status="pass",
                    execution_time_seconds=2.0,
                ),
            ],
            total_models=1, passed=1, failed=0, errored=0, skipped=0,
        )

        result = diagnose_transformation_regression(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            dbt_run_summary=summary,
        )
        assert result.detected is False

    def test_model_failure_detected(self):
        summary = DbtRunSummary(
            generated_at=_NOW,
            elapsed_time_seconds=10.0,
            results=[
                DbtModelResult(
                    model_name="stg_shopify_orders",
                    schema_name="staging",
                    status="error",
                    execution_time_seconds=5.0,
                ),
            ],
            total_models=1, passed=0, failed=0, errored=1, skipped=0,
        )

        result = diagnose_transformation_regression(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            dbt_run_summary=summary,
        )

        assert result.detected is True
        assert result.evidence["signal"] == "dbt_model_failure"
        assert result.confidence_score >= 0.80

    def test_pass_to_fail_transition(self):
        current = DbtRunSummary(
            generated_at=_NOW,
            elapsed_time_seconds=10.0,
            results=[
                DbtModelResult(
                    model_name="stg_shopify_orders",
                    schema_name="staging",
                    status="error",
                    execution_time_seconds=5.0,
                ),
            ],
            total_models=1, passed=0, failed=0, errored=1, skipped=0,
        )
        previous = DbtRunSummary(
            generated_at=_NOW - timedelta(hours=1),
            elapsed_time_seconds=8.0,
            results=[
                DbtModelResult(
                    model_name="stg_shopify_orders",
                    schema_name="staging",
                    status="pass",
                    execution_time_seconds=3.0,
                ),
            ],
            total_models=1, passed=1, failed=0, errored=0, skipped=0,
        )

        # Note: model failure is checked first; pass_to_fail is signal 2
        # This test verifies that model failure (signal 1) still fires
        result = diagnose_transformation_regression(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            dbt_run_summary=current,
            previous_run_summary=previous,
        )

        assert result.detected is True
        assert result.confidence_score >= 0.80

    def test_execution_time_regression(self):
        current = DbtRunSummary(
            generated_at=_NOW,
            elapsed_time_seconds=100.0,
            results=[
                DbtModelResult(
                    model_name="stg_shopify_orders",
                    schema_name="staging",
                    status="pass",
                    execution_time_seconds=90.0,
                ),
            ],
            total_models=1, passed=1, failed=0, errored=0, skipped=0,
        )
        previous = DbtRunSummary(
            generated_at=_NOW - timedelta(hours=1),
            elapsed_time_seconds=10.0,
            results=[
                DbtModelResult(
                    model_name="stg_shopify_orders",
                    schema_name="staging",
                    status="pass",
                    execution_time_seconds=10.0,
                ),
            ],
            total_models=1, passed=1, failed=0, errored=0, skipped=0,
        )

        result = diagnose_transformation_regression(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            dbt_run_summary=current,
            previous_run_summary=previous,
        )

        assert result.detected is True
        assert result.evidence["signal"] == "execution_time_regression"
        assert 0.4 <= result.confidence_score <= 0.6

    def test_all_models_pass_not_detected(self):
        current = DbtRunSummary(
            generated_at=_NOW,
            elapsed_time_seconds=10.0,
            results=[
                DbtModelResult(
                    model_name="stg_shopify_orders",
                    schema_name="staging",
                    status="pass",
                    execution_time_seconds=5.0,
                ),
            ],
            total_models=1, passed=1, failed=0, errored=0, skipped=0,
        )
        previous = DbtRunSummary(
            generated_at=_NOW - timedelta(hours=1),
            elapsed_time_seconds=10.0,
            results=[
                DbtModelResult(
                    model_name="stg_shopify_orders",
                    schema_name="staging",
                    status="pass",
                    execution_time_seconds=5.0,
                ),
            ],
            total_models=1, passed=1, failed=0, errored=0, skipped=0,
        )

        result = diagnose_transformation_regression(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            dbt_run_summary=current,
            previous_run_summary=previous,
        )
        assert result.detected is False

    def test_freshness_degradation(self):
        summary = DbtRunSummary(
            generated_at=_NOW,
            elapsed_time_seconds=10.0,
            results=[
                DbtModelResult(
                    model_name="stg_shopify_orders",
                    schema_name="staging",
                    status="pass",
                    execution_time_seconds=5.0,
                ),
            ],
            total_models=1, passed=1, failed=0, errored=0, skipped=0,
        )
        freshness = DbtFreshnessSummary(
            generated_at=_NOW,
            results=[
                DbtSourceFreshnessResult(
                    source_name="shopify_orders",
                    table_name="raw_orders",
                    status="warn",
                    max_loaded_at=_NOW - timedelta(hours=4),
                ),
            ],
            total_sources=1, passed=0, warned=1, errored=0,
        )

        result = diagnose_transformation_regression(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            dbt_run_summary=summary,
            dbt_freshness_summary=freshness,
        )

        assert result.detected is True
        assert result.evidence["signal"] == "freshness_degradation"

    def test_result_cause_type(self):
        result = TransformationRegressionResult(detected=False)
        assert result.cause_type == "transformation_regression"


# ===========================================================================
# Upstream Shift
# ===========================================================================


class TestUpstreamShift:
    """Tests for upstream data shift detection."""

    def test_distribution_drift_detected(self):
        result = diagnose_upstream_shift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_distribution={"organic": 0.1, "paid": 0.7, "email": 0.2},
            baseline_distribution={"organic": 0.5, "paid": 0.3, "email": 0.2},
        )

        assert result.detected is True
        assert result.evidence["signal"] == "distribution_drift"
        assert result.evidence["jsd_score"] > 0.1
        assert 0.75 <= result.confidence_score <= 0.90

    def test_stable_distribution_not_detected(self):
        dist = {"organic": 0.4, "paid": 0.4, "email": 0.2}
        result = diagnose_upstream_shift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_distribution=dist,
            baseline_distribution=dist,
        )
        assert result.detected is False

    def test_cardinality_explosion_detected(self):
        result = diagnose_upstream_shift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_cardinality={"campaign_id": 150},
            baseline_cardinality={"campaign_id": 50},
        )

        assert result.detected is True
        assert result.evidence["signal"] == "cardinality_explosion"
        assert result.evidence["cardinality_change_pct"] == 200.0
        assert result.confidence_score >= 0.70

    def test_new_values_appearing(self):
        result = diagnose_upstream_shift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_cardinality={"new_channel": 5},
            baseline_cardinality={"new_channel": 0},
        )

        assert result.detected is True
        assert result.evidence["signal"] == "new_values_appearing"
        assert result.confidence_score == 0.65

    def test_no_inputs_checks_dq_results(self):
        """With no distribution/cardinality inputs, checks DQ results."""
        result = diagnose_upstream_shift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
        )
        # No DQ results in mock, should be not detected
        assert result.detected is False

    @patch("src.diagnostics.upstream_shift._check_ingestion_healthy")
    def test_ingestion_failure_dampens_confidence(self, mock_healthy):
        mock_healthy.return_value = False

        result = diagnose_upstream_shift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_distribution={"organic": 0.1, "paid": 0.7, "email": 0.2},
            baseline_distribution={"organic": 0.5, "paid": 0.3, "email": 0.2},
        )

        assert result.detected is True
        # Confidence should be dampened (multiplied by 0.7)
        assert result.confidence_score < 0.80

    def test_result_cause_type(self):
        result = UpstreamShiftResult(detected=False)
        assert result.cause_type == "upstream_data_shift"

    def test_top_movers_in_evidence(self):
        result = diagnose_upstream_shift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_distribution={"organic": 0.1, "paid": 0.7, "email": 0.2},
            baseline_distribution={"organic": 0.5, "paid": 0.3, "email": 0.2},
        )

        assert result.detected is True
        assert "top_movers" in result.evidence
        assert len(result.evidence["top_movers"]) > 0

    def test_small_cardinality_change_not_detected(self):
        result = diagnose_upstream_shift(
            db_session=_mock_db(),
            tenant_id=_TENANT,
            dataset=_DATASET,
            anomaly_detected_at=_NOW,
            current_cardinality={"campaign_id": 55},
            baseline_cardinality={"campaign_id": 50},
        )
        # 10% change is below 50% threshold
        assert result.detected is False
