"""
Admin Diagnostics API routes for root cause signal inspection.

Provides operator-only endpoints for:
- Viewing root cause diagnostics for a dataset
- Listing recent signals for a tenant
- Running on-demand root cause analysis

SECURITY: All routes require admin role verification.
Tenant scoping comes from JWT (never from path parameters).

Story 4.2 - Data Quality Root Cause Signals (Prompt 4.2.7)
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.platform.tenant_context import get_tenant_context, TenantContext
from src.database.session import get_db_session
from src.api.schemas.diagnostics_response import (
    AnomalySummaryResponse,
    DiagnosticsListResponse,
    DiagnosticsResponse,
    EvidenceLink,
    RankedCauseResponse,
)
from src.models.root_cause_signal import (
    RootCauseHypothesis,
    RootCauseSignal,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/diagnostics",
    tags=["admin-diagnostics"],
)


# =============================================================================
# Dependencies
# =============================================================================


def verify_admin_role(request: Request) -> TenantContext:
    """
    Verify that the user has admin role.

    SECURITY: Admin endpoints require explicit admin role.
    """
    tenant_ctx = get_tenant_context(request)

    admin_roles = ["admin", "Admin", "ADMIN", "owner", "Owner", "OWNER", "MERCHANT_ADMIN", "merchant_admin"]
    has_admin = any(role in tenant_ctx.roles for role in admin_roles)

    if not has_admin:
        logger.warning(
            "Unauthorized diagnostics access attempt",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "user_id": tenant_ctx.user_id,
                "roles": tenant_ctx.roles,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )

    return tenant_ctx


# =============================================================================
# Helpers
# =============================================================================


def _build_evidence_links(
    hypothesis: dict,
    connector_id: Optional[str] = None,
) -> list[EvidenceLink]:
    """Build evidence links from hypothesis evidence dict."""
    links: list[EvidenceLink] = []
    evidence = hypothesis.get("evidence", {})
    signal = evidence.get("signal", "")

    if connector_id:
        links.append(EvidenceLink(
            label="Sync history",
            link_type="sync_run",
            resource_id=connector_id,
        ))

    if signal in ("dbt_model_failure", "pass_to_fail_transition",
                   "execution_time_regression"):
        links.append(EvidenceLink(
            label="dbt run details",
            link_type="dbt_run",
            resource_id=evidence.get("dbt_generated_at"),
        ))

    if signal == "sync_failure":
        failed_job_id = evidence.get("failed_job_id")
        if failed_job_id:
            links.append(EvidenceLink(
                label="Failed ingestion job",
                link_type="log",
                resource_id=failed_job_id,
            ))

    if signal == "historical_drift_detected":
        links.append(EvidenceLink(
            label="DQ drift results",
            link_type="dq_result",
        ))

    return links


def _build_investigation_steps(
    ranked_causes: list[RankedCauseResponse],
) -> list[str]:
    """Build ordered investigation steps from ranked causes."""
    steps: list[str] = []
    seen: set[str] = set()

    for cause in ranked_causes:
        if cause.suggested_next_step and cause.suggested_next_step not in seen:
            steps.append(
                f"[{cause.cause_type}] {cause.suggested_next_step}"
            )
            seen.add(cause.suggested_next_step)

    if not steps:
        steps.append(
            "No automated root cause signals detected — "
            "review recent changes and sync history manually"
        )

    return steps


def _signal_to_response(signal: RootCauseSignal) -> DiagnosticsResponse:
    """Convert a RootCauseSignal model to API response."""
    hypotheses_raw = signal.hypotheses or []
    ranked_causes: list[RankedCauseResponse] = []

    for i, h_dict in enumerate(hypotheses_raw):
        hyp = RootCauseHypothesis.from_dict(h_dict)
        evidence_links = _build_evidence_links(
            h_dict, connector_id=signal.connector_id,
        )
        ranked_causes.append(RankedCauseResponse(
            rank=i + 1,
            cause_type=hyp.cause_type,
            confidence_score=hyp.confidence_score,
            evidence=hyp.evidence,
            first_seen_at=hyp.first_seen_at,
            suggested_next_step=hyp.suggested_next_step,
            evidence_links=evidence_links,
        ))

    investigation_steps = _build_investigation_steps(ranked_causes)

    confidence_sum = round(
        sum(c.confidence_score for c in ranked_causes), 3,
    )

    return DiagnosticsResponse(
        signal_id=signal.id,
        anomaly_summary=AnomalySummaryResponse(
            dataset=signal.dataset,
            anomaly_type=signal.anomaly_type,
            detected_at=(
                signal.detected_at.isoformat()
                if signal.detected_at
                else ""
            ),
            connector_id=signal.connector_id,
            correlation_id=signal.correlation_id,
        ),
        ranked_causes=ranked_causes,
        total_hypotheses=signal.hypothesis_count or len(ranked_causes),
        confidence_sum=confidence_sum,
        analysis_duration_ms=0.0,  # Not stored in persisted signal
        investigation_steps=investigation_steps,
        is_active=signal.is_active,
    )


# =============================================================================
# Routes
# =============================================================================


@router.get(
    "/{dataset}",
    response_model=DiagnosticsListResponse,
)
async def get_diagnostics_for_dataset(
    request: Request,
    dataset: str,
    active_only: bool = Query(
        True, description="Only return active (non-resolved) signals"
    ),
    limit: int = Query(10, ge=1, le=100, description="Maximum signals to return"),
    offset: int = Query(0, ge=0, description="Number of signals to skip"),
    tenant_ctx: TenantContext = Depends(verify_admin_role),
    db_session: Session = Depends(get_db_session),
):
    """
    Get root cause diagnostics for a dataset.

    Returns ranked root cause hypotheses, evidence links,
    and suggested investigation steps for recent anomalies
    on the specified dataset.

    SECURITY: Requires admin role. Data is tenant-scoped via JWT.
    """
    logger.info(
        "Diagnostics requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
            "dataset": dataset,
        },
    )

    query = (
        db_session.query(RootCauseSignal)
        .filter(
            RootCauseSignal.tenant_id == tenant_ctx.tenant_id,
            RootCauseSignal.dataset == dataset,
        )
    )

    if active_only:
        query = query.filter(RootCauseSignal.is_active.is_(True))

    total = query.count()

    signals = (
        query
        .order_by(desc(RootCauseSignal.detected_at))
        .offset(offset)
        .limit(limit)
        .all()
    )

    return DiagnosticsListResponse(
        signals=[_signal_to_response(s) for s in signals],
        total=total,
        has_more=(offset + limit) < total,
    )


@router.get(
    "/{dataset}/{signal_id}",
    response_model=DiagnosticsResponse,
)
async def get_diagnostic_signal(
    request: Request,
    dataset: str,
    signal_id: str,
    tenant_ctx: TenantContext = Depends(verify_admin_role),
    db_session: Session = Depends(get_db_session),
):
    """
    Get a specific root cause signal by ID.

    SECURITY: Requires admin role. Data is tenant-scoped via JWT.
    """
    logger.info(
        "Diagnostic signal requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "signal_id": signal_id,
        },
    )

    signal = (
        db_session.query(RootCauseSignal)
        .filter(
            RootCauseSignal.tenant_id == tenant_ctx.tenant_id,
            RootCauseSignal.dataset == dataset,
            RootCauseSignal.id == signal_id,
        )
        .first()
    )

    if not signal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal not found: {signal_id}",
        )

    return _signal_to_response(signal)


@router.post(
    "/{dataset}/analyze",
    response_model=DiagnosticsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def run_diagnostics(
    request: Request,
    dataset: str,
    anomaly_type: str = Query(
        ..., description="DQ check type that triggered analysis"
    ),
    connector_id: Optional[str] = Query(
        None, description="Connector to scope analysis to"
    ),
    correlation_id: Optional[str] = Query(
        None, description="Correlation ID for tracing"
    ),
    tenant_ctx: TenantContext = Depends(verify_admin_role),
    db_session: Session = Depends(get_db_session),
):
    """
    Run on-demand root cause analysis for a dataset.

    Triggers the ranking engine to collect signals from all
    diagnostic modules and return ranked hypotheses.

    SECURITY: Requires admin role. Analysis is tenant-scoped via JWT.
    """
    from src.services.root_cause_ranker import RootCauseRanker

    logger.info(
        "On-demand diagnostics requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
            "dataset": dataset,
            "anomaly_type": anomaly_type,
        },
    )

    ranker = RootCauseRanker(db_session, tenant_ctx.tenant_id)
    analysis = ranker.analyze(
        dataset=dataset,
        anomaly_type=anomaly_type,
        anomaly_detected_at=datetime.now(timezone.utc),
        connector_id=connector_id,
        correlation_id=correlation_id,
    )

    # Re-fetch the persisted signal for the response
    signal = (
        db_session.query(RootCauseSignal)
        .filter(RootCauseSignal.id == analysis.signal_id)
        .first()
    )

    if not signal:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Signal was not persisted",
        )

    response = _signal_to_response(signal)
    response.analysis_duration_ms = analysis.analysis_duration_ms
    return response
