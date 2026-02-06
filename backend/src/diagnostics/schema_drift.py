"""
Schema drift detection for root cause analysis.

Detects schema-level changes that may cause data quality anomalies:
- Column additions
- Column removals
- Column type changes

Correlates with dbt run results for higher confidence.

Story 4.2 - Data Quality Root Cause Signals (Prompt 4.2.3)

SECURITY: All queries are tenant-scoped via tenant_id from JWT.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.ingestion.dbt_artifact_parser import DbtRunSummary

logger = logging.getLogger(__name__)


@dataclass
class ColumnChange:
    """A single column-level schema change."""
    column_name: str
    change_type: str  # "added", "removed", "type_changed"
    old_type: Optional[str] = None
    new_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "column_name": self.column_name,
            "change_type": self.change_type,
            "old_type": self.old_type,
            "new_type": self.new_type,
        }


@dataclass
class SchemaDriftResult:
    """Result of schema drift diagnosis."""
    detected: bool
    cause_type: str = "schema_drift"
    confidence_score: float = 0.0
    evidence: Dict[str, Any] = field(default_factory=dict)
    first_seen_at: Optional[datetime] = None
    suggested_next_step: str = ""


def _detect_column_changes(
    current_columns: Dict[str, str],
    baseline_columns: Dict[str, str],
) -> List[ColumnChange]:
    """Compare two column schemas and return list of changes."""
    changes: List[ColumnChange] = []

    current_names = set(current_columns.keys())
    baseline_names = set(baseline_columns.keys())

    # Removed columns
    for col in baseline_names - current_names:
        changes.append(ColumnChange(
            column_name=col,
            change_type="removed",
            old_type=baseline_columns[col],
            new_type=None,
        ))

    # Added columns
    for col in current_names - baseline_names:
        changes.append(ColumnChange(
            column_name=col,
            change_type="added",
            old_type=None,
            new_type=current_columns[col],
        ))

    # Type changes
    for col in current_names & baseline_names:
        if current_columns[col] != baseline_columns[col]:
            changes.append(ColumnChange(
                column_name=col,
                change_type="type_changed",
                old_type=baseline_columns[col],
                new_type=current_columns[col],
            ))

    return changes


def _score_changes(changes: List[ColumnChange]) -> float:
    """Score confidence based on the type and quantity of changes."""
    if not changes:
        return 0.0

    # Weight by change type
    weights = {
        "removed": 0.90,
        "type_changed": 0.75,
        "added": 0.40,
    }

    max_score = 0.0
    for change in changes:
        score = weights.get(change.change_type, 0.30)
        max_score = max(max_score, score)

    # Boost for multiple changes (up to +0.05)
    multi_boost = min(len(changes) - 1, 5) * 0.01
    return min(max_score + multi_boost, 0.95)


def _find_correlated_dbt_failures(
    dbt_run_summary: Optional[DbtRunSummary],
    dataset: str,
) -> List[str]:
    """Find dbt model failures that match the affected dataset."""
    if not dbt_run_summary or not dbt_run_summary.results:
        return []

    dataset_lower = dataset.lower()
    failing_models = []

    for result in dbt_run_summary.results:
        if result.status in ("error", "fail"):
            # Match by model name containing the dataset identifier
            if dataset_lower in result.model_name.lower():
                failing_models.append(result.model_name)

    return failing_models


def diagnose_schema_drift(
    db_session: Session,
    tenant_id: str,
    dataset: str,
    anomaly_detected_at: datetime,
    current_columns: Optional[Dict[str, str]] = None,
    baseline_columns: Optional[Dict[str, str]] = None,
    dbt_run_summary: Optional[DbtRunSummary] = None,
) -> SchemaDriftResult:
    """
    Detect schema drift as a root cause for a data quality anomaly.

    Compares current vs baseline column schemas and correlates with
    dbt run results for confidence adjustment.

    Args:
        db_session: Database session (for potential future queries)
        tenant_id: Tenant ID from JWT
        dataset: Dataset name for matching
        anomaly_detected_at: When the anomaly was detected
        current_columns: Current schema {col_name: col_type}
        baseline_columns: Baseline schema {col_name: col_type}
        dbt_run_summary: Optional dbt run results for correlation

    Returns:
        SchemaDriftResult with detection status and evidence
    """
    # Graceful degradation if schemas not provided
    if current_columns is None or baseline_columns is None:
        return SchemaDriftResult(detected=False)

    changes = _detect_column_changes(current_columns, baseline_columns)

    if not changes:
        return SchemaDriftResult(detected=False)

    confidence = _score_changes(changes)

    # Correlate with dbt failures
    correlated_dbt_failures = _find_correlated_dbt_failures(
        dbt_run_summary, dataset,
    )
    if correlated_dbt_failures:
        confidence = min(confidence + 0.05, 0.95)

    # Categorize changes for evidence
    removed = [c for c in changes if c.change_type == "removed"]
    added = [c for c in changes if c.change_type == "added"]
    type_changed = [c for c in changes if c.change_type == "type_changed"]

    # Determine primary signal type
    if removed:
        signal = "column_removed"
    elif type_changed:
        signal = "type_changed"
    else:
        signal = "column_added"

    # Determine next step based on signal type
    if removed:
        next_step = (
            "Investigate removed columns in source schema — check for "
            "upstream API changes or connector configuration drift"
        )
    elif type_changed:
        next_step = (
            "Review column type changes in source — verify data type "
            "compatibility with downstream models"
        )
    else:
        next_step = (
            "Review newly added columns — verify they are handled "
            "correctly by transformation models"
        )

    return SchemaDriftResult(
        detected=True,
        confidence_score=round(confidence, 3),
        evidence={
            "signal": signal,
            "changes": [c.to_dict() for c in changes],
            "removed_count": len(removed),
            "added_count": len(added),
            "type_changed_count": len(type_changed),
            "total_changes": len(changes),
            "correlated_dbt_failures": correlated_dbt_failures,
            "affected_model_count": len(correlated_dbt_failures),
        },
        first_seen_at=anomaly_detected_at,
        suggested_next_step=next_step,
    )
