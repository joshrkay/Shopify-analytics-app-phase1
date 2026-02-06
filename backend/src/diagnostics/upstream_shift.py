"""
Upstream behavioral data shift detection for root cause analysis.

Detects upstream data shifts:
- Distribution drift (channel mix changes)
- Cardinality explosion (campaign count spikes)
- New dimension values appearing suddenly

Correlates with DQ check results and ingestion health to
distinguish real upstream changes from pipeline issues.

Story 4.2 - Data Quality Root Cause Signals (Prompt 4.2.4)

SECURITY: All queries are tenant-scoped via tenant_id from JWT.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.models.dq_models import DQResult, SyncRun, SyncRunStatus

logger = logging.getLogger(__name__)


@dataclass
class UpstreamShiftResult:
    """Result of upstream behavioral shift diagnosis."""
    detected: bool
    cause_type: str = "upstream_data_shift"
    confidence_score: float = 0.0
    evidence: Dict[str, Any] = field(default_factory=dict)
    first_seen_at: Optional[datetime] = None
    suggested_next_step: str = ""


def _jensen_shannon_divergence(
    p: Dict[str, float],
    q: Dict[str, float],
) -> float:
    """
    Compute Jensen-Shannon divergence between two categorical distributions.

    Returns a value in [0, 1]. 0 = identical, 1 = maximally different.
    """
    all_keys = set(p) | set(q)
    if not all_keys:
        return 0.0

    epsilon = 1e-10
    p_vec = [p.get(k, 0.0) + epsilon for k in all_keys]
    q_vec = [q.get(k, 0.0) + epsilon for k in all_keys]

    p_sum = sum(p_vec)
    q_sum = sum(q_vec)
    p_vec = [x / p_sum for x in p_vec]
    q_vec = [x / q_sum for x in q_vec]

    m_vec = [(pi + qi) / 2 for pi, qi in zip(p_vec, q_vec)]

    def _kl(a: List[float], b: List[float]) -> float:
        return sum(ai * math.log2(ai / bi) for ai, bi in zip(a, b))

    return (_kl(p_vec, m_vec) + _kl(q_vec, m_vec)) / 2


def _compute_top_movers(
    current: Dict[str, float],
    baseline: Dict[str, float],
    top_n: int = 3,
) -> List[Dict[str, Any]]:
    """Compute top N categories by absolute proportion change."""
    all_keys = set(current) | set(baseline)
    changes = [
        (k, current.get(k, 0.0) - baseline.get(k, 0.0))
        for k in all_keys
    ]
    changes.sort(key=lambda x: abs(x[1]), reverse=True)
    return [
        {"category": k, "change": round(v, 4)} for k, v in changes[:top_n]
    ]


def _check_ingestion_healthy(
    db_session: Session,
    tenant_id: str,
    connector_id: Optional[str],
    since: datetime,
) -> bool:
    """Check if recent ingestion was successful."""
    if not connector_id:
        return True  # Cannot determine, assume healthy

    recent_runs = (
        db_session.query(SyncRun)
        .filter(
            SyncRun.tenant_id == tenant_id,
            SyncRun.connector_id == connector_id,
            SyncRun.started_at >= since,
        )
        .order_by(desc(SyncRun.started_at))
        .limit(3)
        .all()
    )

    if not recent_runs:
        return True  # No data, assume healthy

    # Check if the most recent run succeeded
    return recent_runs[0].status == SyncRunStatus.SUCCESS.value


def _get_recent_drift_results(
    db_session: Session,
    tenant_id: str,
    connector_id: Optional[str],
    since: datetime,
) -> List[DQResult]:
    """Query recent distribution drift and cardinality shift DQ results."""
    query = (
        db_session.query(DQResult)
        .filter(
            DQResult.tenant_id == tenant_id,
            DQResult.status == "failed",
            DQResult.executed_at >= since,
        )
    )

    if connector_id:
        query = query.filter(DQResult.connector_id == connector_id)

    return (
        query
        .order_by(desc(DQResult.executed_at))
        .limit(20)
        .all()
    )


def diagnose_upstream_shift(
    db_session: Session,
    tenant_id: str,
    dataset: str,
    anomaly_detected_at: datetime,
    connector_id: Optional[str] = None,
    current_distribution: Optional[Dict[str, float]] = None,
    baseline_distribution: Optional[Dict[str, float]] = None,
    current_cardinality: Optional[Dict[str, int]] = None,
    baseline_cardinality: Optional[Dict[str, int]] = None,
    lookback_days: int = 30,
) -> UpstreamShiftResult:
    """
    Detect upstream behavioral data shifts as a root cause.

    Combines direct distribution/cardinality comparisons with
    historical DQ check results. Confirms ingestion health to
    distinguish real upstream shifts from pipeline failures.

    Args:
        db_session: Database session
        tenant_id: Tenant ID from JWT
        dataset: Dataset name for context
        anomaly_detected_at: When the anomaly was detected
        connector_id: Optional connector ID for scoping
        current_distribution: Current categorical distribution {cat: proportion}
        baseline_distribution: Baseline distribution {cat: proportion}
        current_cardinality: Current distinct counts {dimension: count}
        baseline_cardinality: Baseline distinct counts {dimension: count}
        lookback_days: Days to look back for DQ results

    Returns:
        UpstreamShiftResult with detection status and evidence
    """
    since = anomaly_detected_at - timedelta(days=lookback_days)
    ingestion_healthy = _check_ingestion_healthy(
        db_session, tenant_id, connector_id, since,
    )

    # --- Signal 1: Direct distribution drift ---
    if current_distribution and baseline_distribution:
        jsd = _jensen_shannon_divergence(
            baseline_distribution, current_distribution,
        )
        # Threshold: JSD > 0.1 indicates meaningful drift
        if jsd > 0.1:
            confidence = 0.75 + min(jsd * 0.5, 0.15)  # 0.75 - 0.90
            if not ingestion_healthy:
                confidence *= 0.7  # Dampen: could be ingestion issue

            top_movers = _compute_top_movers(
                current_distribution, baseline_distribution,
            )

            return UpstreamShiftResult(
                detected=True,
                confidence_score=round(confidence, 3),
                evidence={
                    "signal": "distribution_drift",
                    "jsd_score": round(jsd, 6),
                    "top_movers": top_movers,
                    "ingestion_healthy": ingestion_healthy,
                },
                first_seen_at=anomaly_detected_at,
                suggested_next_step=(
                    "Review upstream data source for distribution changes — "
                    "check channel mix, campaign structure, or platform changes"
                ),
            )

    # --- Signal 2: Cardinality explosion ---
    if current_cardinality and baseline_cardinality:
        for dimension in current_cardinality:
            current_count = current_cardinality[dimension]
            baseline_count = baseline_cardinality.get(dimension, 0)

            if baseline_count > 0:
                pct_change = (
                    (current_count - baseline_count) / baseline_count * 100
                )
                if pct_change > 50:
                    confidence = 0.70 + min(pct_change / 500, 0.15)
                    if not ingestion_healthy:
                        confidence *= 0.7

                    return UpstreamShiftResult(
                        detected=True,
                        confidence_score=round(confidence, 3),
                        evidence={
                            "signal": "cardinality_explosion",
                            "dimension": dimension,
                            "baseline_cardinality": baseline_count,
                            "current_cardinality": current_count,
                            "cardinality_change_pct": round(pct_change, 1),
                            "ingestion_healthy": ingestion_healthy,
                        },
                        first_seen_at=anomaly_detected_at,
                        suggested_next_step=(
                            f"Investigate cardinality spike in '{dimension}' — "
                            "check for new campaigns, products, or IDs appearing"
                        ),
                    )
            elif current_count > 0:
                # New dimension values from zero baseline
                return UpstreamShiftResult(
                    detected=True,
                    confidence_score=0.65,
                    evidence={
                        "signal": "new_values_appearing",
                        "dimension": dimension,
                        "baseline_cardinality": 0,
                        "current_cardinality": current_count,
                        "ingestion_healthy": ingestion_healthy,
                    },
                    first_seen_at=anomaly_detected_at,
                    suggested_next_step=(
                        f"New values detected in '{dimension}' — verify "
                        "these are expected upstream additions"
                    ),
                )

    # --- Signal 3: Recent DQ drift results as evidence ---
    recent_results = _get_recent_drift_results(
        db_session, tenant_id, connector_id, since,
    )

    drift_results = [
        r for r in recent_results
        if r.check_id and r.context_metadata
    ]

    if drift_results:
        # Look for distribution_drift or cardinality_shift in metadata
        drift_evidence = []
        for result in drift_results[:5]:  # Top 5 most recent
            meta = result.context_metadata or {}
            drift_evidence.append({
                "check_type": result.check_id,
                "severity": result.severity,
                "anomaly_score": meta.get("anomaly_score"),
                "jsd": meta.get("jsd"),
                "pct_change": meta.get("pct_change"),
                "executed_at": (
                    result.executed_at.isoformat()
                    if result.executed_at
                    else None
                ),
            })

        if drift_evidence:
            confidence = 0.55
            if ingestion_healthy:
                confidence = 0.65

            return UpstreamShiftResult(
                detected=True,
                confidence_score=confidence,
                evidence={
                    "signal": "historical_drift_detected",
                    "drift_results": drift_evidence,
                    "result_count": len(drift_evidence),
                    "ingestion_healthy": ingestion_healthy,
                },
                first_seen_at=drift_results[0].executed_at,
                suggested_next_step=(
                    "Review recent data quality drift signals — correlate "
                    "with upstream source changes"
                ),
            )

    # No upstream shift signals detected
    return UpstreamShiftResult(detected=False)
