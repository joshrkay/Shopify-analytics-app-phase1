"""
Recommendation rules mapping insights to recommendations.

Defines which recommendation types are applicable for each insight type
and direction. Also includes logic for calculating priority, risk, and
estimated impact.

Story 8.3 - AI Recommendations (No Actions)
"""

from src.models.ai_insight import InsightType, InsightSeverity
from src.models.ai_recommendation import (
    RecommendationType,
    RecommendationPriority,
    EstimatedImpact,
    RiskLevel,
)


# =============================================================================
# Insight to Recommendation Mapping
# Defines which recommendations are applicable for each insight type/direction
# =============================================================================

INSIGHT_TO_RECOMMENDATION_RULES: dict[
    InsightType,
    dict[str, list[RecommendationType]]
] = {
    InsightType.SPEND_ANOMALY: {
        "increase": [
            RecommendationType.REDUCE_SPEND,
            RecommendationType.REVIEW_CREATIVE,
        ],
        "decrease": [
            RecommendationType.INCREASE_SPEND,
            RecommendationType.REVIEW_CREATIVE,
        ],
    },
    InsightType.ROAS_CHANGE: {
        "increase": [
            RecommendationType.SCALE_CAMPAIGN,
            RecommendationType.INCREASE_SPEND,
        ],
        "decrease": [
            RecommendationType.REDUCE_SPEND,
            RecommendationType.REALLOCATE_BUDGET,
            RecommendationType.OPTIMIZE_TARGETING,
            RecommendationType.REVIEW_CREATIVE,
            RecommendationType.PAUSE_CAMPAIGN,
            RecommendationType.ADJUST_BIDDING,
        ],
    },
    InsightType.REVENUE_VS_SPEND_DIVERGENCE: {
        "default": [
            RecommendationType.REALLOCATE_BUDGET,
            RecommendationType.REDUCE_SPEND,
            RecommendationType.PAUSE_CAMPAIGN,
        ],
    },
    InsightType.CHANNEL_MIX_SHIFT: {
        "default": [
            RecommendationType.REALLOCATE_BUDGET,
        ],
    },
    InsightType.CAC_ANOMALY: {
        "increase": [
            RecommendationType.REDUCE_SPEND,
            RecommendationType.OPTIMIZE_TARGETING,
            RecommendationType.ADJUST_BIDDING,
            RecommendationType.PAUSE_CAMPAIGN,
        ],
        "decrease": [
            RecommendationType.SCALE_CAMPAIGN,
            RecommendationType.INCREASE_SPEND,
        ],
    },
    InsightType.AOV_CHANGE: {
        "increase": [
            # Positive change - no urgent action needed
        ],
        "decrease": [
            RecommendationType.REVIEW_CREATIVE,
        ],
    },
}


# =============================================================================
# Priority Calculation
# Maps insight severity to recommendation priority
# =============================================================================

SEVERITY_TO_PRIORITY: dict[InsightSeverity, RecommendationPriority] = {
    InsightSeverity.CRITICAL: RecommendationPriority.HIGH,
    InsightSeverity.WARNING: RecommendationPriority.MEDIUM,
    InsightSeverity.INFO: RecommendationPriority.LOW,
}


def calculate_priority(
    insight_severity: InsightSeverity,
    recommendation_type: RecommendationType,
) -> RecommendationPriority:
    """
    Calculate recommendation priority based on insight severity and type.

    Priority is primarily driven by insight severity, with some adjustments
    based on recommendation type.

    Args:
        insight_severity: Severity of the source insight
        recommendation_type: Type of recommendation being made

    Returns:
        RecommendationPriority
    """
    base_priority = SEVERITY_TO_PRIORITY.get(
        insight_severity,
        RecommendationPriority.MEDIUM
    )

    # Boost priority for certain high-impact recommendation types
    high_impact_types = {
        RecommendationType.PAUSE_CAMPAIGN,
        RecommendationType.REDUCE_SPEND,
    }

    if recommendation_type in high_impact_types:
        if base_priority == RecommendationPriority.LOW:
            return RecommendationPriority.MEDIUM
        # Don't boost already-high priority

    return base_priority


# =============================================================================
# Risk Level Calculation
# Risk based on recommendation type and potential consequences
# =============================================================================

# Base risk levels by recommendation type
RECOMMENDATION_TYPE_RISK: dict[RecommendationType, RiskLevel] = {
    # High risk - significant operational changes
    RecommendationType.PAUSE_CAMPAIGN: RiskLevel.HIGH,

    # Medium risk - budget changes
    RecommendationType.REDUCE_SPEND: RiskLevel.MEDIUM,
    RecommendationType.INCREASE_SPEND: RiskLevel.MEDIUM,
    RecommendationType.REALLOCATE_BUDGET: RiskLevel.MEDIUM,
    RecommendationType.SCALE_CAMPAIGN: RiskLevel.MEDIUM,

    # Low risk - optimization without budget impact
    RecommendationType.OPTIMIZE_TARGETING: RiskLevel.LOW,
    RecommendationType.REVIEW_CREATIVE: RiskLevel.LOW,
    RecommendationType.ADJUST_BIDDING: RiskLevel.LOW,
}


def calculate_risk_level(
    recommendation_type: RecommendationType,
    insight_severity: InsightSeverity,
    change_magnitude: float | None = None,
) -> RiskLevel:
    """
    Calculate risk level for a recommendation.

    Risk is based on:
    1. Base risk of the recommendation type
    2. Severity of the underlying insight
    3. Magnitude of the change being addressed

    Args:
        recommendation_type: Type of recommendation
        insight_severity: Severity of source insight
        change_magnitude: Optional percentage change from insight

    Returns:
        RiskLevel
    """
    base_risk = RECOMMENDATION_TYPE_RISK.get(
        recommendation_type,
        RiskLevel.MEDIUM
    )

    # Adjust risk based on severity
    if insight_severity == InsightSeverity.CRITICAL:
        # Critical insights dealing with budget recommendations = higher risk
        if recommendation_type in {
            RecommendationType.REDUCE_SPEND,
            RecommendationType.INCREASE_SPEND,
            RecommendationType.REALLOCATE_BUDGET,
        }:
            if base_risk == RiskLevel.LOW:
                return RiskLevel.MEDIUM
            elif base_risk == RiskLevel.MEDIUM:
                return RiskLevel.HIGH

    # Adjust risk based on change magnitude if provided
    if change_magnitude is not None:
        if abs(change_magnitude) > 40:
            # Very large changes warrant higher caution
            if base_risk == RiskLevel.LOW:
                return RiskLevel.MEDIUM

    return base_risk


# =============================================================================
# Estimated Impact Calculation
# Qualitative impact based on insight metrics
# =============================================================================

def calculate_estimated_impact(
    insight_severity: InsightSeverity,
    recommendation_type: RecommendationType,
    change_magnitude: float | None = None,
) -> EstimatedImpact:
    """
    Calculate estimated impact of following the recommendation.

    NOTE: This is QUALITATIVE only - no specific numbers or guarantees.

    Impact is based on:
    1. Severity of the underlying insight
    2. Type of recommendation
    3. Magnitude of the change being addressed

    Args:
        insight_severity: Severity of source insight
        recommendation_type: Type of recommendation
        change_magnitude: Optional percentage change from insight

    Returns:
        EstimatedImpact (qualitative: minimal, moderate, significant)
    """
    # Start with base impact from severity
    if insight_severity == InsightSeverity.CRITICAL:
        base_impact = EstimatedImpact.SIGNIFICANT
    elif insight_severity == InsightSeverity.WARNING:
        base_impact = EstimatedImpact.MODERATE
    else:
        base_impact = EstimatedImpact.MINIMAL

    # Adjust based on recommendation type
    high_impact_types = {
        RecommendationType.PAUSE_CAMPAIGN,
        RecommendationType.SCALE_CAMPAIGN,
        RecommendationType.REALLOCATE_BUDGET,
    }

    low_impact_types = {
        RecommendationType.REVIEW_CREATIVE,
        RecommendationType.ADJUST_BIDDING,
    }

    if recommendation_type in high_impact_types:
        if base_impact == EstimatedImpact.MINIMAL:
            base_impact = EstimatedImpact.MODERATE
    elif recommendation_type in low_impact_types:
        if base_impact == EstimatedImpact.SIGNIFICANT:
            base_impact = EstimatedImpact.MODERATE

    # Adjust based on change magnitude if provided
    if change_magnitude is not None:
        if abs(change_magnitude) > 30:
            if base_impact == EstimatedImpact.MINIMAL:
                return EstimatedImpact.MODERATE
            elif base_impact == EstimatedImpact.MODERATE:
                return EstimatedImpact.SIGNIFICANT
        elif abs(change_magnitude) < 10:
            if base_impact == EstimatedImpact.SIGNIFICANT:
                return EstimatedImpact.MODERATE

    return base_impact


# =============================================================================
# Confidence Score Calculation
# =============================================================================

def calculate_recommendation_confidence(
    insight_confidence: float,
    recommendation_type: RecommendationType,
    insight_severity: InsightSeverity,
) -> float:
    """
    Calculate confidence score for a recommendation.

    Recommendation confidence is derived from the source insight's
    confidence, adjusted by factors like recommendation complexity.

    Args:
        insight_confidence: Confidence score of source insight (0.0-1.0)
        recommendation_type: Type of recommendation
        insight_severity: Severity of source insight

    Returns:
        Confidence score between 0.0 and 1.0
    """
    # Start with insight confidence
    confidence = insight_confidence

    # Higher confidence for clear-cut recommendations
    simple_recommendations = {
        RecommendationType.REVIEW_CREATIVE,
        RecommendationType.OPTIMIZE_TARGETING,
    }

    complex_recommendations = {
        RecommendationType.REALLOCATE_BUDGET,
        RecommendationType.PAUSE_CAMPAIGN,
    }

    if recommendation_type in simple_recommendations:
        # Simple recommendations are easier to be confident about
        confidence = min(1.0, confidence + 0.05)
    elif recommendation_type in complex_recommendations:
        # Complex recommendations have more uncertainty
        confidence = max(0.5, confidence - 0.1)

    # Severity affects confidence
    if insight_severity == InsightSeverity.CRITICAL:
        # Critical insights give us more confidence to recommend action
        confidence = min(1.0, confidence + 0.05)

    return round(confidence, 2)


# =============================================================================
# Maximum Recommendations Per Insight
# =============================================================================

# Limit recommendations per insight to avoid overwhelming users
MAX_RECOMMENDATIONS_PER_INSIGHT = 3


def get_applicable_recommendations(
    insight_type: InsightType,
    direction: str,
) -> list[RecommendationType]:
    """
    Get list of applicable recommendation types for an insight.

    Args:
        insight_type: Type of insight
        direction: Direction of change ("increase", "decrease", or "default")

    Returns:
        List of applicable RecommendationType values (max 3)
    """
    type_rules = INSIGHT_TO_RECOMMENDATION_RULES.get(insight_type, {})

    # Try specific direction first, then "default"
    recommendations = type_rules.get(direction, type_rules.get("default", []))

    # Limit to max recommendations
    return recommendations[:MAX_RECOMMENDATIONS_PER_INSIGHT]
