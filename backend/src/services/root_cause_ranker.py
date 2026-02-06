"""
Root cause ranking engine.

Orchestrates all diagnostic modules, normalizes confidence scores,
applies causal ordering, and persists ranked hypotheses.

Story 4.2 - Data Quality Root Cause Signals (Prompt 4.2.5)

SECURITY: All operations are tenant-scoped via tenant_id from JWT.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

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
    DbtRunSummary,
    DbtFreshnessSummary,
)
from src.models.root_cause_signal import (
    RootCauseHypothesis,
    RootCauseSignal,
)

logger = logging.getLogger(__name__)


# Causal priority ordering: lower = more upstream (more likely root cause)
CAUSAL_PRIORITY = {
    "ingestion_failure": 1,
    "schema_drift": 2,
    "transformation_regression": 3,
    "upstream_data_shift": 4,
    "downstream_logic_change": 5,
}


@dataclass
class RankedRootCause:
    """A single ranked root cause hypothesis."""
    rank: int
    cause_type: str
    confidence_score: float
    evidence: Dict[str, Any]
    first_seen_at: Optional[datetime]
    suggested_next_step: str

    def to_hypothesis(self) -> RootCauseHypothesis:
        """Convert to a RootCauseHypothesis for persistence."""
        return RootCauseHypothesis(
            cause_type=self.cause_type,
            confidence_score=self.confidence_score,
            evidence=self.evidence,
            first_seen_at=(
                self.first_seen_at.isoformat()
                if self.first_seen_at
                else None
            ),
            suggested_next_step=self.suggested_next_step,
        )


@dataclass
class RootCauseAnalysis:
    """Complete root cause analysis result."""
    signal_id: str
    tenant_id: str
    dataset: str
    anomaly_type: str
    detected_at: datetime
    ranked_causes: List[RankedRootCause]
    total_hypotheses: int
    confidence_sum: float
    analysis_duration_ms: float


def _normalize_confidences(
    hypotheses: List[RankedRootCause],
) -> List[RankedRootCause]:
    """Normalize confidence scores so sum <= 1.0.

    If the sum already satisfies the constraint, scores are unchanged.
    Otherwise, scales proportionally.
    """
    if not hypotheses:
        return hypotheses

    total = sum(h.confidence_score for h in hypotheses)
    if total <= 1.0:
        return hypotheses

    for h in hypotheses:
        h.confidence_score = round(h.confidence_score / total, 3)

    return hypotheses


def _apply_causal_ordering(
    hypotheses: List[RankedRootCause],
) -> List[RankedRootCause]:
    """Apply causal priority rules and dampen downstream effects.

    If the top cause is ingestion failure with high confidence (> 0.7),
    downstream signals like transformation_regression are dampened
    since they are likely consequences, not independent causes.
    """
    if not hypotheses:
        return hypotheses

    # Sort by confidence desc, then by causal priority asc
    hypotheses.sort(
        key=lambda h: (
            -h.confidence_score,
            CAUSAL_PRIORITY.get(h.cause_type, 99),
        ),
    )

    # Dampen downstream effects when upstream cause has high confidence
    if (
        hypotheses[0].cause_type == "ingestion_failure"
        and hypotheses[0].confidence_score > 0.7
    ):
        for h in hypotheses[1:]:
            if h.cause_type == "transformation_regression":
                h.confidence_score = round(h.confidence_score * 0.5, 3)

    return hypotheses


class RootCauseRanker:
    """
    Ranks root cause hypotheses from multiple diagnostic detectors.

    Workflow:
    1. Calls each diagnostic module independently
    2. Collects detected signals
    3. Applies causal ordering and dampening
    4. Normalizes confidence scores (sum <= 1.0)
    5. Returns top N hypotheses
    6. Persists result as RootCauseSignal
    7. Emits audit event

    Story 4.2 - Data Quality Root Cause Signals
    """

    def __init__(self, db_session: Session, tenant_id: str):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.db = db_session
        self.tenant_id = tenant_id

    def analyze(
        self,
        dataset: str,
        anomaly_type: str,
        anomaly_detected_at: datetime,
        connector_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        top_n: int = 3,
        # Optional pre-computed inputs for diagnostics
        current_columns: Optional[Dict[str, str]] = None,
        baseline_columns: Optional[Dict[str, str]] = None,
        dbt_run_summary: Optional[DbtRunSummary] = None,
        dbt_freshness_summary: Optional[DbtFreshnessSummary] = None,
        previous_run_summary: Optional[DbtRunSummary] = None,
        current_distribution: Optional[Dict[str, float]] = None,
        baseline_distribution: Optional[Dict[str, float]] = None,
        current_cardinality: Optional[Dict[str, int]] = None,
        baseline_cardinality: Optional[Dict[str, int]] = None,
    ) -> RootCauseAnalysis:
        """Run all diagnostics, rank, persist, and audit.

        Args:
            dataset: Dataset name (e.g. "shopify_orders")
            anomaly_type: DQCheckType value that triggered this analysis
            anomaly_detected_at: When the anomaly was detected
            connector_id: Optional connector scope
            correlation_id: Optional correlation ID for tracing
            top_n: Maximum hypotheses to return (default 3)
            current_columns: Current schema for schema drift detection
            baseline_columns: Baseline schema for schema drift detection
            dbt_run_summary: Current dbt run results
            dbt_freshness_summary: Current dbt freshness results
            previous_run_summary: Previous dbt run results
            current_distribution: Current distribution for shift detection
            baseline_distribution: Baseline distribution for shift detection
            current_cardinality: Current cardinality for shift detection
            baseline_cardinality: Baseline cardinality for shift detection

        Returns:
            RootCauseAnalysis with ranked causes and metadata
        """
        start_time = time.monotonic()

        # Phase 1: Collect hypotheses from all detectors
        raw_hypotheses = self._collect_hypotheses(
            dataset=dataset,
            anomaly_detected_at=anomaly_detected_at,
            connector_id=connector_id,
            current_columns=current_columns,
            baseline_columns=baseline_columns,
            dbt_run_summary=dbt_run_summary,
            dbt_freshness_summary=dbt_freshness_summary,
            previous_run_summary=previous_run_summary,
            current_distribution=current_distribution,
            baseline_distribution=baseline_distribution,
            current_cardinality=current_cardinality,
            baseline_cardinality=baseline_cardinality,
        )

        # Phase 2: Causal ordering and dampening
        ordered = _apply_causal_ordering(raw_hypotheses)

        # Phase 3: Normalize confidences
        normalized = _normalize_confidences(ordered)

        # Phase 4: Truncate to top N and assign ranks
        ranked = normalized[:top_n]
        for i, h in enumerate(ranked):
            h.rank = i + 1

        confidence_sum = round(sum(h.confidence_score for h in ranked), 3)
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        # Phase 5: Persist signal
        signal_id = self._persist_signal(
            dataset=dataset,
            anomaly_type=anomaly_type,
            anomaly_detected_at=anomaly_detected_at,
            connector_id=connector_id,
            correlation_id=correlation_id,
            ranked_causes=ranked,
        )

        # Phase 6: Emit audit event
        self._emit_audit(
            dataset=dataset,
            anomaly_type=anomaly_type,
            signal_id=signal_id,
            top_cause_type=ranked[0].cause_type if ranked else None,
            hypothesis_count=len(ranked),
            detected_at=anomaly_detected_at,
            correlation_id=correlation_id,
        )

        return RootCauseAnalysis(
            signal_id=signal_id,
            tenant_id=self.tenant_id,
            dataset=dataset,
            anomaly_type=anomaly_type,
            detected_at=anomaly_detected_at,
            ranked_causes=ranked,
            total_hypotheses=len(ranked),
            confidence_sum=confidence_sum,
            analysis_duration_ms=duration_ms,
        )

    def _collect_hypotheses(
        self,
        dataset: str,
        anomaly_detected_at: datetime,
        connector_id: Optional[str],
        current_columns: Optional[Dict[str, str]],
        baseline_columns: Optional[Dict[str, str]],
        dbt_run_summary: Optional[DbtRunSummary],
        dbt_freshness_summary: Optional[DbtFreshnessSummary],
        previous_run_summary: Optional[DbtRunSummary],
        current_distribution: Optional[Dict[str, float]],
        baseline_distribution: Optional[Dict[str, float]],
        current_cardinality: Optional[Dict[str, int]],
        baseline_cardinality: Optional[Dict[str, int]],
    ) -> List[RankedRootCause]:
        """Call all diagnostic modules and collect detected hypotheses."""
        hypotheses: List[RankedRootCause] = []

        # 1. Ingestion failure
        ingestion = self._safe_diagnose(
            "ingestion",
            lambda: diagnose_ingestion_failure(
                db_session=self.db,
                tenant_id=self.tenant_id,
                connector_id=connector_id or "",
                dataset=dataset,
                anomaly_detected_at=anomaly_detected_at,
            ),
        )
        if ingestion and ingestion.detected:
            hypotheses.append(self._to_ranked(ingestion))

        # 2. Schema drift
        schema = self._safe_diagnose(
            "schema_drift",
            lambda: diagnose_schema_drift(
                db_session=self.db,
                tenant_id=self.tenant_id,
                dataset=dataset,
                anomaly_detected_at=anomaly_detected_at,
                current_columns=current_columns,
                baseline_columns=baseline_columns,
                dbt_run_summary=dbt_run_summary,
            ),
        )
        if schema and schema.detected:
            hypotheses.append(self._to_ranked(schema))

        # 3. Transformation regression
        transform = self._safe_diagnose(
            "transformation_regression",
            lambda: diagnose_transformation_regression(
                db_session=self.db,
                tenant_id=self.tenant_id,
                dataset=dataset,
                anomaly_detected_at=anomaly_detected_at,
                dbt_run_summary=dbt_run_summary,
                dbt_freshness_summary=dbt_freshness_summary,
                previous_run_summary=previous_run_summary,
            ),
        )
        if transform and transform.detected:
            hypotheses.append(self._to_ranked(transform))

        # 4. Upstream shift
        upstream = self._safe_diagnose(
            "upstream_shift",
            lambda: diagnose_upstream_shift(
                db_session=self.db,
                tenant_id=self.tenant_id,
                dataset=dataset,
                anomaly_detected_at=anomaly_detected_at,
                connector_id=connector_id,
                current_distribution=current_distribution,
                baseline_distribution=baseline_distribution,
                current_cardinality=current_cardinality,
                baseline_cardinality=baseline_cardinality,
            ),
        )
        if upstream and upstream.detected:
            hypotheses.append(self._to_ranked(upstream))

        return hypotheses

    @staticmethod
    def _safe_diagnose(name: str, fn):
        """Run a diagnostic function safely, logging any exceptions."""
        try:
            return fn()
        except Exception:
            logger.warning(
                f"root_cause_ranker.{name}_diagnostic_failed",
                exc_info=True,
            )
            return None

    @staticmethod
    def _to_ranked(result) -> RankedRootCause:
        """Convert a diagnostic result to a RankedRootCause."""
        return RankedRootCause(
            rank=0,  # Assigned after sorting
            cause_type=result.cause_type,
            confidence_score=result.confidence_score,
            evidence=result.evidence,
            first_seen_at=result.first_seen_at,
            suggested_next_step=result.suggested_next_step,
        )

    def _persist_signal(
        self,
        dataset: str,
        anomaly_type: str,
        anomaly_detected_at: datetime,
        connector_id: Optional[str],
        correlation_id: Optional[str],
        ranked_causes: List[RankedRootCause],
    ) -> str:
        """Persist the root cause signal and return its ID."""
        hypotheses_dicts = [
            h.to_hypothesis().to_dict() for h in ranked_causes
        ]

        signal = RootCauseSignal(
            tenant_id=self.tenant_id,
            dataset=dataset,
            anomaly_type=anomaly_type,
            detected_at=anomaly_detected_at,
            correlation_id=correlation_id,
            connector_id=connector_id,
            hypotheses=hypotheses_dicts,
            top_cause_type=(
                ranked_causes[0].cause_type if ranked_causes else None
            ),
            top_confidence=(
                ranked_causes[0].confidence_score if ranked_causes else None
            ),
            hypothesis_count=len(ranked_causes),
        )

        self.db.add(signal)
        self.db.commit()

        logger.info(
            "root_cause_signal_persisted",
            extra={
                "signal_id": signal.id,
                "tenant_id": self.tenant_id,
                "dataset": dataset,
                "hypothesis_count": len(ranked_causes),
                "top_cause_type": signal.top_cause_type,
            },
        )

        return signal.id

    def _emit_audit(
        self,
        dataset: str,
        anomaly_type: str,
        signal_id: str,
        top_cause_type: Optional[str],
        hypothesis_count: int,
        detected_at: datetime,
        correlation_id: Optional[str],
    ) -> None:
        """Emit audit event for the generated signal."""
        try:
            from src.services.audit_logger import (
                emit_root_cause_signal_generated,
            )

            emit_root_cause_signal_generated(
                db=self.db,
                tenant_id=self.tenant_id,
                dataset=dataset,
                anomaly_type=anomaly_type,
                signal_id=signal_id,
                top_cause_type=top_cause_type,
                hypothesis_count=hypothesis_count,
                detected_at=detected_at.isoformat(),
                correlation_id=correlation_id,
            )
        except Exception:
            logger.warning(
                "root_cause_ranker.audit_emit_failed",
                extra={"signal_id": signal_id},
                exc_info=True,
            )
