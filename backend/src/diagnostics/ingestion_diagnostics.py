"""
Ingestion failure root cause detection.

Detects ingestion-related root causes by correlating:
- Airbyte sync failures (IngestionJob FAILED/DEAD_LETTER)
- Partial syncs (low row count vs baseline)
- Long-running syncs (> 2x median duration)
- Missing expected sync runs

Story 4.2 - Data Quality Root Cause Signals (Prompt 4.2.2)

SECURITY: All queries are tenant-scoped via tenant_id from JWT.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from src.ingestion.jobs.models import IngestionJob, JobStatus
from src.models.airbyte_connection import TenantAirbyteConnection
from src.models.dq_models import SyncRun, SyncRunStatus

logger = logging.getLogger(__name__)


@dataclass
class IngestionDiagnosticResult:
    """Result of ingestion failure diagnosis."""
    detected: bool
    cause_type: str = "ingestion_failure"
    confidence_score: float = 0.0
    evidence: Dict[str, Any] = field(default_factory=dict)
    first_seen_at: Optional[datetime] = None
    suggested_next_step: str = ""


def _get_recent_failed_jobs(
    db_session: Session,
    tenant_id: str,
    connector_id: str,
    since: datetime,
) -> List[IngestionJob]:
    """Query recent failed/dead-letter ingestion jobs."""
    return (
        db_session.query(IngestionJob)
        .filter(
            IngestionJob.tenant_id == tenant_id,
            IngestionJob.connector_id == connector_id,
            IngestionJob.status.in_([JobStatus.FAILED, JobStatus.DEAD_LETTER]),
            IngestionJob.created_at >= since,
        )
        .order_by(desc(IngestionJob.created_at))
        .all()
    )


def _get_running_jobs(
    db_session: Session,
    tenant_id: str,
    connector_id: str,
) -> List[IngestionJob]:
    """Query currently running ingestion jobs."""
    return (
        db_session.query(IngestionJob)
        .filter(
            IngestionJob.tenant_id == tenant_id,
            IngestionJob.connector_id == connector_id,
            IngestionJob.status == JobStatus.RUNNING,
        )
        .all()
    )


def _get_recent_sync_runs(
    db_session: Session,
    tenant_id: str,
    connector_id: str,
    limit: int = 10,
) -> List[SyncRun]:
    """Query recent sync runs for baseline calculations."""
    return (
        db_session.query(SyncRun)
        .filter(
            SyncRun.tenant_id == tenant_id,
            SyncRun.connector_id == connector_id,
            SyncRun.status == SyncRunStatus.SUCCESS.value,
        )
        .order_by(desc(SyncRun.started_at))
        .limit(limit)
        .all()
    )


def _compute_median(values: List[float]) -> float:
    """Compute median of a list of floats."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n % 2 == 1:
        return sorted_vals[n // 2]
    return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0


def diagnose_ingestion_failure(
    db_session: Session,
    tenant_id: str,
    connector_id: str,
    dataset: str,
    anomaly_detected_at: datetime,
    lookback_hours: int = 48,
) -> IngestionDiagnosticResult:
    """
    Detect ingestion-related root causes for a data quality anomaly.

    Checks for:
    1. Recent Airbyte sync failures (FAILED/DEAD_LETTER status)
    2. Partial syncs (rows < 50% of baseline average)
    3. Long-running syncs (RUNNING for > 2x median duration)
    4. Missing expected sync runs (no recent sync in expected window)

    Args:
        db_session: Database session
        tenant_id: Tenant ID from JWT
        connector_id: Connector to diagnose
        dataset: Dataset name for context
        anomaly_detected_at: When the anomaly was detected
        lookback_hours: How far back to search for evidence

    Returns:
        IngestionDiagnosticResult with detection status and evidence
    """
    if not tenant_id or not connector_id:
        return IngestionDiagnosticResult(detected=False)

    since = anomaly_detected_at - timedelta(hours=lookback_hours)

    # Get connector info
    connector = (
        db_session.query(TenantAirbyteConnection)
        .filter(
            TenantAirbyteConnection.tenant_id == tenant_id,
            TenantAirbyteConnection.id == connector_id,
        )
        .first()
    )

    last_sync_at = connector.last_sync_at if connector else None
    last_sync_status = connector.last_sync_status if connector else None

    # --- Signal 1: Sync failures ---
    failed_jobs = _get_recent_failed_jobs(db_session, tenant_id, connector_id, since)
    if failed_jobs:
        job = failed_jobs[0]  # Most recent failure
        confidence = 0.85
        # Boost for specific error codes
        if job.error_code in ("auth_error", "rate_limit"):
            confidence = 0.95

        next_step = "Check Airbyte connection status and API credentials"
        if job.error_code == "rate_limit":
            next_step = "Check for rate limiting on source API"
        elif job.error_code == "auth_error":
            next_step = "Verify API credentials and OAuth tokens"

        return IngestionDiagnosticResult(
            detected=True,
            confidence_score=confidence,
            evidence={
                "signal": "sync_failure",
                "failed_job_id": job.job_id,
                "error_message": job.error_message or "",
                "error_code": job.error_code or "",
                "retry_count": job.retry_count,
                "last_successful_sync_at": (
                    last_sync_at.isoformat() if last_sync_at else None
                ),
                "failure_count": len(failed_jobs),
            },
            first_seen_at=job.created_at,
            suggested_next_step=next_step,
        )

    # --- Signal 2: Long-running syncs ---
    running_jobs = _get_running_jobs(db_session, tenant_id, connector_id)
    if running_jobs:
        recent_runs = _get_recent_sync_runs(db_session, tenant_id, connector_id)
        durations = [
            float(r.duration_seconds)
            for r in recent_runs
            if r.duration_seconds is not None
        ]
        median_duration = _compute_median(durations)

        for job in running_jobs:
            if job.started_at:
                started = job.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                running_seconds = (now - started).total_seconds()

                if median_duration > 0 and running_seconds > median_duration * 2:
                    return IngestionDiagnosticResult(
                        detected=True,
                        confidence_score=0.60,
                        evidence={
                            "signal": "long_running_sync",
                            "running_job_id": job.job_id,
                            "running_seconds": round(running_seconds, 1),
                            "median_duration_seconds": round(median_duration, 1),
                            "duration_ratio": round(
                                running_seconds / median_duration, 2
                            ),
                            "last_successful_sync_at": (
                                last_sync_at.isoformat() if last_sync_at else None
                            ),
                        },
                        first_seen_at=job.started_at,
                        suggested_next_step=(
                            "Investigate long-running sync — check source API "
                            "responsiveness and data volume"
                        ),
                    )

    # --- Signal 3: Partial sync ---
    recent_runs = _get_recent_sync_runs(db_session, tenant_id, connector_id)
    if len(recent_runs) >= 2:
        latest_run = recent_runs[0]
        baseline_runs = recent_runs[1:]
        baseline_rows = [
            r.rows_synced for r in baseline_runs if r.rows_synced is not None
        ]

        if baseline_rows and latest_run.rows_synced is not None:
            avg_rows = sum(baseline_rows) / len(baseline_rows)
            if avg_rows > 0:
                ratio = latest_run.rows_synced / avg_rows
                if ratio < 0.5:
                    drop_pct = round((1 - ratio) * 100, 1)
                    confidence = min(0.60 + (1 - ratio) * 0.2, 0.80)

                    return IngestionDiagnosticResult(
                        detected=True,
                        confidence_score=round(confidence, 3),
                        evidence={
                            "signal": "partial_sync",
                            "latest_rows_synced": latest_run.rows_synced,
                            "baseline_avg_rows": round(avg_rows, 1),
                            "volume_drop_pct": drop_pct,
                            "last_successful_sync_at": (
                                last_sync_at.isoformat() if last_sync_at else None
                            ),
                        },
                        first_seen_at=latest_run.started_at,
                        suggested_next_step=(
                            "Investigate partial sync — compare row counts "
                            "and check for API pagination issues"
                        ),
                    )

    # --- Signal 4: Missing expected sync ---
    if connector and last_sync_at:
        sync_at = last_sync_at
        if sync_at.tzinfo is None:
            sync_at = sync_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        gap_minutes = (now - sync_at).total_seconds() / 60

        # Use source-type-aware expected intervals
        # Shopify/Recharge: expect sync every ~120 min
        # Ads/email: expect sync every ~1440 min
        source = (connector.source_type or "").lower()
        if source in ("shopify", "shopify_orders", "shopify_refunds", "recharge"):
            expected_interval = 120
        else:
            expected_interval = 1440

        # If gap exceeds 3x expected interval, flag as missing
        if gap_minutes > expected_interval * 3:
            return IngestionDiagnosticResult(
                detected=True,
                confidence_score=0.75,
                evidence={
                    "signal": "missing_sync",
                    "last_successful_sync_at": sync_at.isoformat(),
                    "expected_sync_interval_minutes": expected_interval,
                    "actual_gap_minutes": round(gap_minutes, 1),
                    "gap_ratio": round(gap_minutes / expected_interval, 2),
                },
                first_seen_at=sync_at,
                suggested_next_step=(
                    "Verify sync schedule is configured correctly "
                    "and check Airbyte connection health"
                ),
            )

    # No ingestion signals detected
    return IngestionDiagnosticResult(detected=False)
