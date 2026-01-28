"""
AI Insights API routes.

Provides endpoints for:
- Listing AI-generated insights
- Marking insights as read
- Dismissing insights

SECURITY: All routes require valid tenant context from JWT.
Insights are tenant-scoped - users can only see their own insights.
Entitlement check enforced for AI_INSIGHTS feature.

Story 8.1 - AI Insight Generation (Read-Only Analytics)
"""

import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session
from src.models.ai_insight import AIInsight, InsightType, InsightSeverity
from src.services.billing_entitlements import (
    BillingEntitlementsService,
    BillingFeature,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/insights", tags=["insights"])


# =============================================================================
# Response Models
# =============================================================================


class SupportingMetricResponse(BaseModel):
    """A single supporting metric for an insight (Story 8.2 format)."""

    metric: str  # Business-friendly display name
    previous: Optional[float] = None
    current: Optional[float] = None
    change: Optional[float] = None  # Absolute change
    change_pct: Optional[float] = None  # Percentage change


class InsightResponse(BaseModel):
    """Response model for a single insight (Story 8.2 format)."""

    insight_id: str
    insight_type: str
    severity: str
    summary: str
    why_it_matters: Optional[str] = None  # Story 8.2
    supporting_metrics: List[SupportingMetricResponse]
    timeframe: str  # Story 8.2: human-readable timeframe
    confidence_score: float
    platform: Optional[str] = None
    campaign_id: Optional[str] = None
    currency: Optional[str] = None
    generated_at: datetime
    is_read: bool
    is_dismissed: bool

    class Config:
        from_attributes = True


class InsightsListResponse(BaseModel):
    """Response model for listing insights."""

    insights: List[InsightResponse]
    total: int
    has_more: bool


class InsightActionResponse(BaseModel):
    """Response model for insight actions (read, dismiss)."""

    status: str = "ok"
    insight_id: str


# =============================================================================
# Dependencies
# =============================================================================


def check_ai_insights_entitlement(request: Request, db_session=Depends(get_db_session)):
    """
    Dependency to check AI insights entitlement.

    Raises 402 Payment Required if tenant is not entitled.
    """
    tenant_ctx = get_tenant_context(request)
    service = BillingEntitlementsService(db_session, tenant_ctx.tenant_id)
    result = service.check_feature_entitlement(BillingFeature.AI_INSIGHTS)

    if not result.is_entitled:
        logger.warning(
            "AI insights access denied - not entitled",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "current_tier": result.current_tier,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"AI Insights requires a {result.required_tier or 'paid'} plan",
        )

    return db_session


# =============================================================================
# Helper Functions
# =============================================================================


def _format_metric_value(value: float | None) -> float | None:
    """Format metric value with 2 decimal precision."""
    if value is None:
        return None
    return round(float(value), 2)


def _insight_to_response(insight: AIInsight) -> InsightResponse:
    """Convert AIInsight model to response model (Story 8.2 format)."""
    from src.services.insight_templates import get_metric_display_name, format_timeframe_human

    # Parse supporting metrics with business-friendly names
    metrics = []
    for m in insight.supporting_metrics or []:
        metrics.append(
            SupportingMetricResponse(
                metric=get_metric_display_name(m.get("metric", "")),
                previous=_format_metric_value(m.get("prior_value")),
                current=_format_metric_value(m.get("current_value")),
                change=_format_metric_value(m.get("delta")),
                change_pct=_format_metric_value(m.get("delta_pct")),
            )
        )

    return InsightResponse(
        insight_id=insight.id,
        insight_type=insight.insight_type.value if insight.insight_type else "",
        severity=insight.severity.value if insight.severity else "",
        summary=insight.summary or "",
        why_it_matters=insight.why_it_matters,
        supporting_metrics=metrics,
        timeframe=format_timeframe_human(insight.period_type or ""),
        confidence_score=insight.confidence_score or 0,
        platform=insight.platform,
        campaign_id=insight.campaign_id,
        currency=insight.currency,
        generated_at=insight.generated_at,
        is_read=bool(insight.is_read),
        is_dismissed=bool(insight.is_dismissed),
    )


# =============================================================================
# Routes
# =============================================================================


@router.get(
    "",
    response_model=InsightsListResponse,
)
async def list_insights(
    request: Request,
    db_session=Depends(check_ai_insights_entitlement),
    insight_type: Optional[str] = Query(
        None, description="Filter by insight type (spend_anomaly, roas_change, etc.)"
    ),
    severity: Optional[str] = Query(
        None, description="Filter by severity (info, warning, critical)"
    ),
    include_dismissed: bool = Query(
        False, description="Include dismissed insights"
    ),
    include_read: bool = Query(
        True, description="Include read insights"
    ),
    limit: int = Query(20, le=100, description="Maximum insights to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """
    List AI-generated insights for the current tenant.

    Insights are sorted by generated_at (newest first).
    By default, dismissed insights are excluded.

    SECURITY: Only returns insights belonging to the authenticated tenant.
    Requires AI_INSIGHTS entitlement.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Insights list requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "insight_type": insight_type,
            "severity": severity,
            "include_dismissed": include_dismissed,
        },
    )

    # Build query
    query = db_session.query(AIInsight).filter(
        AIInsight.tenant_id == tenant_ctx.tenant_id
    )

    # Apply filters
    if insight_type:
        try:
            type_enum = InsightType(insight_type)
            query = query.filter(AIInsight.insight_type == type_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid insight_type: {insight_type}",
            )

    if severity:
        try:
            severity_enum = InsightSeverity(severity)
            query = query.filter(AIInsight.severity == severity_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid severity: {severity}",
            )

    if not include_dismissed:
        query = query.filter(AIInsight.is_dismissed == 0)

    if not include_read:
        query = query.filter(AIInsight.is_read == 0)

    # Get total count
    total = query.count()

    # Get paginated results (fetch one extra to check has_more)
    insights = (
        query.order_by(AIInsight.generated_at.desc())
        .offset(offset)
        .limit(limit + 1)
        .all()
    )

    has_more = len(insights) > limit
    insights = insights[:limit]

    return InsightsListResponse(
        insights=[_insight_to_response(i) for i in insights],
        total=total,
        has_more=has_more,
    )


@router.get(
    "/{insight_id}",
    response_model=InsightResponse,
)
async def get_insight(
    request: Request,
    insight_id: str,
    db_session=Depends(check_ai_insights_entitlement),
):
    """
    Get a single insight by ID.

    SECURITY: Only returns insight if it belongs to the authenticated tenant.
    Requires AI_INSIGHTS entitlement.
    """
    tenant_ctx = get_tenant_context(request)

    insight = (
        db_session.query(AIInsight)
        .filter(
            AIInsight.id == insight_id,
            AIInsight.tenant_id == tenant_ctx.tenant_id,
        )
        .first()
    )

    if not insight:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Insight not found",
        )

    return _insight_to_response(insight)


@router.patch(
    "/{insight_id}/read",
    response_model=InsightActionResponse,
)
async def mark_insight_read(
    request: Request,
    insight_id: str,
    db_session=Depends(check_ai_insights_entitlement),
):
    """
    Mark an insight as read.

    SECURITY: Only marks insight if it belongs to the authenticated tenant.
    Requires AI_INSIGHTS entitlement.
    """
    tenant_ctx = get_tenant_context(request)

    insight = (
        db_session.query(AIInsight)
        .filter(
            AIInsight.id == insight_id,
            AIInsight.tenant_id == tenant_ctx.tenant_id,
        )
        .first()
    )

    if not insight:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Insight not found",
        )

    insight.mark_read()
    db_session.commit()

    logger.info(
        "Insight marked as read",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "insight_id": insight_id,
        },
    )

    return InsightActionResponse(status="ok", insight_id=insight_id)


@router.patch(
    "/{insight_id}/dismiss",
    response_model=InsightActionResponse,
)
async def dismiss_insight(
    request: Request,
    insight_id: str,
    db_session=Depends(check_ai_insights_entitlement),
):
    """
    Dismiss an insight (hide from default list).

    Dismissed insights are excluded from the default list view
    but can still be retrieved with include_dismissed=true.

    SECURITY: Only dismisses insight if it belongs to the authenticated tenant.
    Requires AI_INSIGHTS entitlement.
    """
    tenant_ctx = get_tenant_context(request)

    insight = (
        db_session.query(AIInsight)
        .filter(
            AIInsight.id == insight_id,
            AIInsight.tenant_id == tenant_ctx.tenant_id,
        )
        .first()
    )

    if not insight:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Insight not found",
        )

    insight.mark_dismissed()
    db_session.commit()

    logger.info(
        "Insight dismissed",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "insight_id": insight_id,
        },
    )

    return InsightActionResponse(status="ok", insight_id=insight_id)


@router.post(
    "/batch/read",
    response_model=dict,
)
async def mark_insights_read_batch(
    request: Request,
    insight_ids: List[str],
    db_session=Depends(check_ai_insights_entitlement),
):
    """
    Mark multiple insights as read in batch.

    SECURITY: Only marks insights belonging to the authenticated tenant.
    Requires AI_INSIGHTS entitlement.
    """
    tenant_ctx = get_tenant_context(request)

    if not insight_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="insight_ids list cannot be empty",
        )

    if len(insight_ids) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 100 insights per batch",
        )

    # Update all matching insights
    updated = (
        db_session.query(AIInsight)
        .filter(
            AIInsight.id.in_(insight_ids),
            AIInsight.tenant_id == tenant_ctx.tenant_id,
        )
        .update({AIInsight.is_read: 1}, synchronize_session=False)
    )

    db_session.commit()

    logger.info(
        "Insights marked as read (batch)",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "requested": len(insight_ids),
            "updated": updated,
        },
    )

    return {"status": "ok", "updated": updated}
