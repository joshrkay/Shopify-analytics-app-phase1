"""
AI Recommendations API routes.

Provides endpoints for:
- Listing AI-generated recommendations
- Getting single recommendation
- Accepting/dismissing recommendations

SECURITY: All routes require valid tenant context from JWT.
Recommendations are tenant-scoped - users can only see their own recommendations.
Entitlement check enforced for AI_RECOMMENDATIONS feature.

NO AUTO-EXECUTION: All recommendations are advisory only.

Story 8.3 - AI Recommendations (No Actions)
"""

import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session
from src.models.ai_recommendation import (
    AIRecommendation,
    RecommendationType,
    RecommendationPriority,
    EstimatedImpact,
    RiskLevel,
)
from src.api.dependencies.entitlements import check_ai_recommendations_entitlement


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


# =============================================================================
# Response Models
# =============================================================================


class RecommendationResponse(BaseModel):
    """Response model for a single recommendation."""

    model_config = ConfigDict(from_attributes=True)

    recommendation_id: str
    related_insight_id: str
    recommendation_type: str
    priority: str
    recommendation_text: str  # Uses conditional language
    rationale: Optional[str] = None
    estimated_impact: str  # Qualitative: minimal/moderate/significant
    risk_level: str  # low/medium/high
    confidence_score: float
    affected_entity: Optional[str] = None
    affected_entity_type: Optional[str] = None
    currency: Optional[str] = None
    generated_at: datetime
    is_accepted: bool
    is_dismissed: bool


class RecommendationsListResponse(BaseModel):
    """Response model for listing recommendations."""

    recommendations: List[RecommendationResponse]
    total: int
    has_more: bool


class RecommendationActionResponse(BaseModel):
    """Response model for recommendation actions (accept, dismiss)."""

    status: str = "ok"
    recommendation_id: str


# =============================================================================
# Helper Functions
# =============================================================================


def _recommendation_to_response(rec: AIRecommendation) -> RecommendationResponse:
    """Convert AIRecommendation model to response model."""
    return RecommendationResponse(
        recommendation_id=rec.id,
        related_insight_id=rec.related_insight_id,
        recommendation_type=rec.recommendation_type.value if rec.recommendation_type else "",
        priority=rec.priority.value if rec.priority else "",
        recommendation_text=rec.recommendation_text or "",
        rationale=rec.rationale,
        estimated_impact=rec.estimated_impact.value if rec.estimated_impact else "",
        risk_level=rec.risk_level.value if rec.risk_level else "",
        confidence_score=rec.confidence_score or 0,
        affected_entity=rec.affected_entity,
        affected_entity_type=rec.affected_entity_type.value if rec.affected_entity_type else None,
        currency=rec.currency,
        generated_at=rec.generated_at,
        is_accepted=bool(rec.is_accepted),
        is_dismissed=bool(rec.is_dismissed),
    )


# =============================================================================
# Routes
# =============================================================================


@router.get(
    "",
    response_model=RecommendationsListResponse,
)
async def list_recommendations(
    request: Request,
    db_session=Depends(check_ai_recommendations_entitlement),
    recommendation_type: Optional[str] = Query(
        None, description="Filter by recommendation type"
    ),
    priority: Optional[str] = Query(
        None, description="Filter by priority (low, medium, high)"
    ),
    risk_level: Optional[str] = Query(
        None, description="Filter by risk level (low, medium, high)"
    ),
    related_insight_id: Optional[str] = Query(
        None, description="Get recommendations for a specific insight"
    ),
    include_dismissed: bool = Query(
        False, description="Include dismissed recommendations"
    ),
    include_accepted: bool = Query(
        True, description="Include accepted recommendations"
    ),
    limit: int = Query(20, le=100, description="Maximum recommendations to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """
    List AI-generated recommendations for the current tenant.

    Recommendations are sorted by generated_at (newest first).
    By default, dismissed recommendations are excluded.

    SECURITY: Only returns recommendations belonging to the authenticated tenant.
    Requires AI_RECOMMENDATIONS entitlement.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Recommendations list requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "recommendation_type": recommendation_type,
            "priority": priority,
            "include_dismissed": include_dismissed,
        },
    )

    # Build query
    query = db_session.query(AIRecommendation).filter(
        AIRecommendation.tenant_id == tenant_ctx.tenant_id
    )

    # Apply filters
    if recommendation_type:
        try:
            type_enum = RecommendationType(recommendation_type)
            query = query.filter(AIRecommendation.recommendation_type == type_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid recommendation_type: {recommendation_type}",
            )

    if priority:
        try:
            priority_enum = RecommendationPriority(priority)
            query = query.filter(AIRecommendation.priority == priority_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid priority: {priority}",
            )

    if risk_level:
        try:
            risk_enum = RiskLevel(risk_level)
            query = query.filter(AIRecommendation.risk_level == risk_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid risk_level: {risk_level}",
            )

    if related_insight_id:
        query = query.filter(AIRecommendation.related_insight_id == related_insight_id)

    if not include_dismissed:
        query = query.filter(AIRecommendation.is_dismissed == 0)

    if not include_accepted:
        query = query.filter(AIRecommendation.is_accepted == 0)

    # Get total count
    total = query.count()

    # Get paginated results (fetch one extra to check has_more)
    recommendations = (
        query.order_by(AIRecommendation.generated_at.desc())
        .offset(offset)
        .limit(limit + 1)
        .all()
    )

    has_more = len(recommendations) > limit
    recommendations = recommendations[:limit]

    return RecommendationsListResponse(
        recommendations=[_recommendation_to_response(r) for r in recommendations],
        total=total,
        has_more=has_more,
    )


@router.get(
    "/{recommendation_id}",
    response_model=RecommendationResponse,
)
async def get_recommendation(
    request: Request,
    recommendation_id: str,
    db_session=Depends(check_ai_recommendations_entitlement),
):
    """
    Get a single recommendation by ID.

    SECURITY: Only returns recommendation if it belongs to the authenticated tenant.
    Requires AI_RECOMMENDATIONS entitlement.
    """
    tenant_ctx = get_tenant_context(request)

    recommendation = (
        db_session.query(AIRecommendation)
        .filter(
            AIRecommendation.id == recommendation_id,
            AIRecommendation.tenant_id == tenant_ctx.tenant_id,
        )
        .first()
    )

    if not recommendation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation not found",
        )

    return _recommendation_to_response(recommendation)


@router.patch(
    "/{recommendation_id}/accept",
    response_model=RecommendationActionResponse,
)
async def accept_recommendation(
    request: Request,
    recommendation_id: str,
    db_session=Depends(check_ai_recommendations_entitlement),
):
    """
    Mark a recommendation as accepted.

    This is for tracking user feedback - it does NOT execute any action.
    Recommendations are advisory only.

    SECURITY: Only marks recommendation if it belongs to the authenticated tenant.
    Requires AI_RECOMMENDATIONS entitlement.
    """
    tenant_ctx = get_tenant_context(request)

    recommendation = (
        db_session.query(AIRecommendation)
        .filter(
            AIRecommendation.id == recommendation_id,
            AIRecommendation.tenant_id == tenant_ctx.tenant_id,
        )
        .first()
    )

    if not recommendation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation not found",
        )

    recommendation.mark_accepted()
    db_session.commit()

    logger.info(
        "Recommendation accepted",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "recommendation_id": recommendation_id,
            "recommendation_type": recommendation.recommendation_type.value,
        },
    )

    return RecommendationActionResponse(status="ok", recommendation_id=recommendation_id)


@router.patch(
    "/{recommendation_id}/dismiss",
    response_model=RecommendationActionResponse,
)
async def dismiss_recommendation(
    request: Request,
    recommendation_id: str,
    db_session=Depends(check_ai_recommendations_entitlement),
):
    """
    Dismiss a recommendation (hide from default list).

    Dismissed recommendations are excluded from the default list view
    but can still be retrieved with include_dismissed=true.

    SECURITY: Only dismisses recommendation if it belongs to the authenticated tenant.
    Requires AI_RECOMMENDATIONS entitlement.
    """
    tenant_ctx = get_tenant_context(request)

    recommendation = (
        db_session.query(AIRecommendation)
        .filter(
            AIRecommendation.id == recommendation_id,
            AIRecommendation.tenant_id == tenant_ctx.tenant_id,
        )
        .first()
    )

    if not recommendation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation not found",
        )

    recommendation.mark_dismissed()
    db_session.commit()

    logger.info(
        "Recommendation dismissed",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "recommendation_id": recommendation_id,
        },
    )

    return RecommendationActionResponse(status="ok", recommendation_id=recommendation_id)


@router.post(
    "/batch/dismiss",
    response_model=dict,
)
async def dismiss_recommendations_batch(
    request: Request,
    recommendation_ids: List[str],
    db_session=Depends(check_ai_recommendations_entitlement),
):
    """
    Dismiss multiple recommendations in batch.

    SECURITY: Only dismisses recommendations belonging to the authenticated tenant.
    Requires AI_RECOMMENDATIONS entitlement.
    """
    tenant_ctx = get_tenant_context(request)

    if not recommendation_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="recommendation_ids list cannot be empty",
        )

    if len(recommendation_ids) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 100 recommendations per batch",
        )

    # Update all matching recommendations
    updated = (
        db_session.query(AIRecommendation)
        .filter(
            AIRecommendation.id.in_(recommendation_ids),
            AIRecommendation.tenant_id == tenant_ctx.tenant_id,
        )
        .update({AIRecommendation.is_dismissed: 1}, synchronize_session=False)
    )

    db_session.commit()

    logger.info(
        "Recommendations dismissed (batch)",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "requested": len(recommendation_ids),
            "updated": updated,
        },
    )

    return {"status": "ok", "updated": updated}
