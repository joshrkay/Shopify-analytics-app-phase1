"""
Transformation regression detection for root cause analysis.

Detects dbt transformation regressions:
- dbt model execution failures (error/fail status)
- dbt test failures on relevant models
- Execution time regression (> 3x historical median)
- Pass-to-fail transitions between runs

Story 4.2 - Data Quality Root Cause Signals (Prompt 4.2.3)

SECURITY: All queries are tenant-scoped via tenant_id from JWT.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.ingestion.dbt_artifact_parser import (
    DbtModelResult,
    DbtRunSummary,
    DbtFreshnessSummary,
)

logger = logging.getLogger(__name__)


@dataclass
class TransformationRegressionResult:
    """Result of transformation regression diagnosis."""
    detected: bool
    cause_type: str = "transformation_regression"
    confidence_score: float = 0.0
    evidence: Dict[str, Any] = field(default_factory=dict)
    first_seen_at: Optional[datetime] = None
    suggested_next_step: str = ""


def _filter_models_by_dataset(
    results: List[DbtModelResult],
    dataset: str,
) -> List[DbtModelResult]:
    """Filter dbt model results to those matching the dataset."""
    dataset_lower = dataset.lower()
    return [
        r for r in results
        if dataset_lower in r.model_name.lower()
    ]


def _find_failing_models(
    models: List[DbtModelResult],
) -> List[DbtModelResult]:
    """Find models with error or fail status."""
    return [m for m in models if m.status in ("error", "fail")]


def _find_pass_to_fail_transitions(
    current_models: List[DbtModelResult],
    previous_models: List[DbtModelResult],
) -> List[Dict[str, Any]]:
    """Find models that transitioned from pass to fail/error."""
    previous_by_name = {m.model_name: m for m in previous_models}
    transitions = []

    for current in current_models:
        if current.status in ("error", "fail"):
            previous = previous_by_name.get(current.model_name)
            if previous and previous.status == "pass":
                transitions.append({
                    "model_name": current.model_name,
                    "previous_status": previous.status,
                    "current_status": current.status,
                    "previous_execution_time": previous.execution_time_seconds,
                    "current_execution_time": current.execution_time_seconds,
                })

    return transitions


def _detect_execution_time_regression(
    current_models: List[DbtModelResult],
    previous_models: List[DbtModelResult],
    threshold_ratio: float = 3.0,
) -> List[Dict[str, Any]]:
    """Detect models with execution time significantly exceeding historical."""
    previous_by_name = {m.model_name: m for m in previous_models}
    regressions = []

    for current in current_models:
        previous = previous_by_name.get(current.model_name)
        if (
            previous
            and previous.execution_time_seconds > 0
            and current.execution_time_seconds > 0
        ):
            ratio = current.execution_time_seconds / previous.execution_time_seconds
            if ratio >= threshold_ratio:
                regressions.append({
                    "model_name": current.model_name,
                    "previous_seconds": round(previous.execution_time_seconds, 2),
                    "current_seconds": round(current.execution_time_seconds, 2),
                    "execution_time_ratio": round(ratio, 2),
                })

    return regressions


def diagnose_transformation_regression(
    db_session: Session,
    tenant_id: str,
    dataset: str,
    anomaly_detected_at: datetime,
    dbt_run_summary: Optional[DbtRunSummary] = None,
    dbt_freshness_summary: Optional[DbtFreshnessSummary] = None,
    previous_run_summary: Optional[DbtRunSummary] = None,
) -> TransformationRegressionResult:
    """
    Detect dbt transformation regression as a root cause.

    Compares current dbt run results against previous results to identify
    model failures, test failures, and performance regressions.

    Args:
        db_session: Database session (for potential future queries)
        tenant_id: Tenant ID from JWT
        dataset: Dataset name for model filtering
        anomaly_detected_at: When the anomaly was detected
        dbt_run_summary: Current dbt run results
        dbt_freshness_summary: Current dbt freshness results
        previous_run_summary: Previous (known-good) dbt run results

    Returns:
        TransformationRegressionResult with detection status and evidence
    """
    # Graceful degradation if no dbt artifacts available
    if dbt_run_summary is None:
        return TransformationRegressionResult(detected=False)

    current_models = _filter_models_by_dataset(
        dbt_run_summary.results, dataset,
    )

    if not current_models:
        return TransformationRegressionResult(detected=False)

    # --- Signal 1: Model execution failures ---
    failing_models = _find_failing_models(current_models)
    if failing_models:
        confidence = 0.85
        if len(failing_models) > 1:
            confidence = min(confidence + len(failing_models) * 0.02, 0.90)

        return TransformationRegressionResult(
            detected=True,
            confidence_score=round(confidence, 3),
            evidence={
                "signal": "dbt_model_failure",
                "failing_models": [
                    {
                        "model_name": m.model_name,
                        "status": m.status,
                        "execution_time": m.execution_time_seconds,
                    }
                    for m in failing_models
                ],
                "total_models_checked": len(current_models),
                "failure_count": len(failing_models),
                "dbt_generated_at": (
                    dbt_run_summary.generated_at.isoformat()
                    if dbt_run_summary.generated_at
                    else None
                ),
            },
            first_seen_at=dbt_run_summary.generated_at or anomaly_detected_at,
            suggested_next_step=(
                "Review dbt model errors — check SQL compilation, "
                "schema references, and upstream dependencies"
            ),
        )

    # --- Signal 2: Pass-to-fail transitions ---
    if previous_run_summary:
        previous_models = _filter_models_by_dataset(
            previous_run_summary.results, dataset,
        )
        transitions = _find_pass_to_fail_transitions(
            current_models, previous_models,
        )
        if transitions:
            return TransformationRegressionResult(
                detected=True,
                confidence_score=0.85,
                evidence={
                    "signal": "pass_to_fail_transition",
                    "transitions": transitions,
                    "transition_count": len(transitions),
                    "dbt_generated_at": (
                        dbt_run_summary.generated_at.isoformat()
                        if dbt_run_summary.generated_at
                        else None
                    ),
                },
                first_seen_at=dbt_run_summary.generated_at or anomaly_detected_at,
                suggested_next_step=(
                    "Review recent dbt model changes — a previously passing "
                    "model is now failing"
                ),
            )

        # --- Signal 3: Execution time regression ---
        time_regressions = _detect_execution_time_regression(
            current_models, previous_models,
        )
        if time_regressions:
            return TransformationRegressionResult(
                detected=True,
                confidence_score=0.50,
                evidence={
                    "signal": "execution_time_regression",
                    "regressions": time_regressions,
                    "regression_count": len(time_regressions),
                    "dbt_generated_at": (
                        dbt_run_summary.generated_at.isoformat()
                        if dbt_run_summary.generated_at
                        else None
                    ),
                },
                first_seen_at=dbt_run_summary.generated_at or anomaly_detected_at,
                suggested_next_step=(
                    "Investigate dbt model performance regression — check "
                    "data volume changes and query optimization"
                ),
            )

    # --- Signal 4: Freshness degradation ---
    if dbt_freshness_summary and dbt_freshness_summary.results:
        dataset_lower = dataset.lower()
        degraded_sources = [
            r for r in dbt_freshness_summary.results
            if r.status in ("warn", "error", "runtime_error")
            and dataset_lower in f"{r.source_name}.{r.table_name}".lower()
        ]
        if degraded_sources:
            return TransformationRegressionResult(
                detected=True,
                confidence_score=0.40,
                evidence={
                    "signal": "freshness_degradation",
                    "degraded_sources": [
                        {
                            "source_name": s.source_name,
                            "table_name": s.table_name,
                            "status": s.status,
                            "max_loaded_at": (
                                s.max_loaded_at.isoformat()
                                if s.max_loaded_at
                                else None
                            ),
                        }
                        for s in degraded_sources
                    ],
                },
                first_seen_at=(
                    dbt_freshness_summary.generated_at or anomaly_detected_at
                ),
                suggested_next_step=(
                    "Check dbt source freshness — source data may be "
                    "stale or unavailable"
                ),
            )

    # No transformation signals detected
    return TransformationRegressionResult(detected=False)
