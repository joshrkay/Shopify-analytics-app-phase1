"""
Template-based recommendation text generation.

Provides deterministic, human-readable recommendation summaries.
No LLM dependency - ensures same inputs produce same outputs.

LANGUAGE RULES (CRITICAL):
- ALLOWED: "Consider...", "You may want...", "may help...", "could improve..."
- FORBIDDEN: "You should...", "You must...", "Do this...", "Need to..."

NO AUTO-EXECUTION:
- All recommendations are advisory only
- No guarantees of outcome
- No specific numerical predictions

Story 8.3 - AI Recommendations (No Actions)
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.recommendation_generation_service import DetectedRecommendation

from src.models.ai_insight import InsightType, InsightSeverity
from src.models.ai_recommendation import (
    RecommendationType,
    RecommendationPriority,
    EstimatedImpact,
    RiskLevel,
)


# Currency symbols for formatting
CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "\u20ac",
    "GBP": "\u00a3",
    "CAD": "C$",
    "AUD": "A$",
    "JPY": "\u00a5",
    "CNY": "\u00a5",
    "INR": "\u20b9",
    "BRL": "R$",
    "MXN": "MX$",
}


# =============================================================================
# Recommendation Text Templates
# Organized by: RecommendationType -> InsightType -> direction
#
# ALL templates use CONDITIONAL language:
# - "Consider...", "You may want...", "may help...", "could improve..."
#
# NO IMPERATIVE language allowed:
# - NOT "You should...", "You must...", "Do this..."
# =============================================================================

RECOMMENDATION_TEMPLATES = {
    RecommendationType.REDUCE_SPEND: {
        InsightType.SPEND_ANOMALY: {
            "increase": (
                "Consider reducing spend{entity_suffix} by approximately 10-15% to "
                "align with historical performance levels. This may help control costs "
                "while you investigate the factors driving the increase."
            ),
        },
        InsightType.ROAS_CHANGE: {
            "decrease": (
                "Consider reducing spend{entity_suffix} while ROAS remains below target. "
                "This may help preserve budget until you can identify and address the "
                "factors affecting return on ad spend."
            ),
        },
        InsightType.CAC_ANOMALY: {
            "increase": (
                "Consider reducing spend{entity_suffix} to help control rising customer "
                "acquisition costs. Pausing or reducing budget on underperforming "
                "campaigns may improve overall efficiency."
            ),
        },
        InsightType.REVENUE_VS_SPEND_DIVERGENCE: {
            "default": (
                "Consider reducing spend{entity_suffix} given the divergence between "
                "spend and revenue trends. This may help improve marketing efficiency "
                "while you analyze channel performance."
            ),
        },
    },
    RecommendationType.INCREASE_SPEND: {
        InsightType.SPEND_ANOMALY: {
            "decrease": (
                "You may want to review whether the spend reduction{entity_suffix} was "
                "intentional. If campaigns are underdelivering, consider gradually "
                "increasing budget to restore reach."
            ),
        },
        InsightType.ROAS_CHANGE: {
            "increase": (
                "Consider gradually increasing spend{entity_suffix} to capitalize on "
                "improved ROAS. Testing higher budgets on well-performing campaigns "
                "may help scale results."
            ),
        },
        InsightType.CAC_ANOMALY: {
            "decrease": (
                "Consider increasing spend{entity_suffix} to take advantage of improved "
                "acquisition efficiency. Lower CAC may indicate an opportunity to "
                "acquire more customers cost-effectively."
            ),
        },
    },
    RecommendationType.REALLOCATE_BUDGET: {
        InsightType.ROAS_CHANGE: {
            "decrease": (
                "You may want to reallocate budget from{entity_suffix} to better-performing "
                "channels. Shifting spend toward higher-ROAS campaigns may help improve "
                "overall marketing efficiency."
            ),
        },
        InsightType.REVENUE_VS_SPEND_DIVERGENCE: {
            "default": (
                "Consider reallocating budget across channels to address the spend-revenue "
                "divergence. Moving budget from underperforming to higher-converting "
                "channels may help improve returns."
            ),
        },
        InsightType.CHANNEL_MIX_SHIFT: {
            "default": (
                "You may want to evaluate your budget allocation given the channel mix "
                "shift. Ensuring budget distribution aligns with channel performance "
                "may help optimize results."
            ),
        },
    },
    RecommendationType.PAUSE_CAMPAIGN: {
        InsightType.ROAS_CHANGE: {
            "decrease": (
                "Consider pausing{entity_suffix} temporarily while investigating the "
                "ROAS decline. This may help prevent further inefficient spend while "
                "you diagnose the issue."
            ),
        },
        InsightType.REVENUE_VS_SPEND_DIVERGENCE: {
            "default": (
                "You may want to consider pausing campaigns{entity_suffix} that show "
                "significant spend-revenue divergence. This could help preserve budget "
                "while you investigate performance issues."
            ),
        },
        InsightType.CAC_ANOMALY: {
            "increase": (
                "Consider pausing{entity_suffix} with the highest CAC increases. "
                "This may help control acquisition costs while you optimize targeting "
                "and creative strategies."
            ),
        },
    },
    RecommendationType.SCALE_CAMPAIGN: {
        InsightType.ROAS_CHANGE: {
            "increase": (
                "Consider scaling{entity_suffix} that are driving the ROAS improvement. "
                "Gradually increasing budget on high-performing campaigns may help "
                "capture additional conversions."
            ),
        },
        InsightType.CAC_ANOMALY: {
            "decrease": (
                "You may want to scale{entity_suffix} showing improved acquisition "
                "efficiency. Lower CAC presents an opportunity to grow customer "
                "acquisition while maintaining efficiency."
            ),
        },
    },
    RecommendationType.OPTIMIZE_TARGETING: {
        InsightType.ROAS_CHANGE: {
            "decrease": (
                "Consider reviewing audience targeting{entity_suffix} to address the "
                "ROAS decline. Refining targeting parameters or testing new audiences "
                "may help improve ad efficiency."
            ),
        },
        InsightType.CAC_ANOMALY: {
            "increase": (
                "You may want to review targeting settings{entity_suffix} to address "
                "rising acquisition costs. Narrowing or adjusting audiences may help "
                "improve conversion rates."
            ),
        },
    },
    RecommendationType.REVIEW_CREATIVE: {
        InsightType.ROAS_CHANGE: {
            "decrease": (
                "Consider reviewing ad creative{entity_suffix} for potential fatigue "
                "or relevance issues. Refreshing creative assets may help restore "
                "engagement and improve ROAS."
            ),
        },
        InsightType.SPEND_ANOMALY: {
            "increase": (
                "You may want to review whether creative changes are driving the "
                "spend increase{entity_suffix}. Ensuring ads are performing as expected "
                "may help optimize budget utilization."
            ),
            "decrease": (
                "Consider reviewing ad creative{entity_suffix} if the spend decrease "
                "is due to delivery issues. Creative that doesn't meet platform "
                "guidelines may affect ad delivery."
            ),
        },
        InsightType.AOV_CHANGE: {
            "decrease": (
                "You may want to review product creative and recommendations to "
                "address declining average order value. Promoting higher-value items "
                "or bundles in ads may help improve AOV."
            ),
        },
    },
    RecommendationType.ADJUST_BIDDING: {
        InsightType.CAC_ANOMALY: {
            "increase": (
                "Consider adjusting bid strategies{entity_suffix} to help control "
                "rising acquisition costs. Testing lower bids or different bidding "
                "strategies may improve cost efficiency."
            ),
        },
        InsightType.ROAS_CHANGE: {
            "decrease": (
                "You may want to review bid settings{entity_suffix} in light of the "
                "ROAS decline. Adjusting target ROAS or bid caps may help improve "
                "return on ad spend."
            ),
        },
    },
}


# =============================================================================
# Rationale Templates
# Explains WHY this recommendation is being made
# =============================================================================

RATIONALE_TEMPLATES = {
    RecommendationType.REDUCE_SPEND: {
        "default": (
            "Based on the detected performance change, reducing spend may help "
            "preserve budget and improve overall marketing efficiency until the "
            "underlying factors are addressed."
        ),
        InsightSeverity.CRITICAL: (
            "Given the significant performance change detected, reducing spend "
            "may help prevent further budget inefficiency while you investigate "
            "and address the root cause."
        ),
    },
    RecommendationType.INCREASE_SPEND: {
        "default": (
            "The performance indicators suggest an opportunity to scale. "
            "Gradually increasing spend may help capture additional value "
            "while maintaining efficiency."
        ),
    },
    RecommendationType.REALLOCATE_BUDGET: {
        "default": (
            "Budget reallocation may help optimize overall marketing performance "
            "by shifting investment toward channels and campaigns showing stronger "
            "returns."
        ),
    },
    RecommendationType.PAUSE_CAMPAIGN: {
        "default": (
            "Temporarily pausing underperforming campaigns may help preserve "
            "budget while you diagnose issues and develop optimization strategies."
        ),
        InsightSeverity.CRITICAL: (
            "Given the significant performance decline, pausing affected campaigns "
            "may help prevent further budget loss while you investigate the cause."
        ),
    },
    RecommendationType.SCALE_CAMPAIGN: {
        "default": (
            "Strong performance metrics suggest an opportunity to scale. "
            "Increasing investment in high-performing campaigns may help "
            "capture additional conversions while efficiency remains high."
        ),
    },
    RecommendationType.OPTIMIZE_TARGETING: {
        "default": (
            "Reviewing and refining audience targeting may help improve ad "
            "relevance and conversion rates, potentially addressing the "
            "performance changes detected."
        ),
    },
    RecommendationType.REVIEW_CREATIVE: {
        "default": (
            "Ad creative can significantly impact performance. Reviewing and "
            "refreshing creative assets may help address engagement or "
            "conversion issues."
        ),
    },
    RecommendationType.ADJUST_BIDDING: {
        "default": (
            "Bid strategy adjustments may help optimize cost efficiency and "
            "improve return on ad spend by better aligning bids with "
            "performance goals."
        ),
    },
}


# =============================================================================
# Helper Functions
# =============================================================================


def _get_entity_suffix(
    affected_entity: str | None,
    affected_entity_type: str | None,
) -> str:
    """Generate entity suffix for templates."""
    if not affected_entity:
        return ""

    if affected_entity_type == "platform":
        return f" on {affected_entity.replace('_', ' ').title()}"
    elif affected_entity_type == "campaign":
        return f" for campaign {affected_entity}"
    else:
        return f" ({affected_entity})"


def render_recommendation_text(detected: "DetectedRecommendation") -> str:
    """
    Render recommendation text from templates.

    Args:
        detected: DetectedRecommendation with type, insight, and context

    Returns:
        Human-readable recommendation string (deterministic)
        Uses CONDITIONAL language only.
    """
    rec_type = detected.recommendation_type
    insight_type = detected.source_insight_type
    direction = detected.direction

    # Get templates for this recommendation type
    type_templates = RECOMMENDATION_TEMPLATES.get(rec_type, {})

    # Try to get insight-specific template
    insight_templates = type_templates.get(insight_type, {})

    # Try direction-specific, then "default"
    template = insight_templates.get(direction) or insight_templates.get("default")

    # Fallback to generic template
    if not template:
        template = (
            f"Consider reviewing your {rec_type.value.replace('_', ' ')} strategy "
            f"based on the detected changes. This may help optimize performance."
        )

    # Build context for template
    entity_suffix = _get_entity_suffix(
        detected.affected_entity,
        detected.affected_entity_type,
    )

    currency_symbol = CURRENCY_SYMBOLS.get(detected.currency or "USD", "$")

    context = {
        "entity_suffix": entity_suffix,
        "currency_symbol": currency_symbol,
        "platform": (detected.affected_entity or "").replace("_", " ").title(),
    }

    try:
        return template.format(**context)
    except KeyError:
        # Fallback if template has missing keys
        return template.replace("{entity_suffix}", entity_suffix)


def render_rationale(detected: "DetectedRecommendation") -> str:
    """
    Render rationale explaining why this recommendation is being made.

    Args:
        detected: DetectedRecommendation with type and context

    Returns:
        Human-readable rationale string (deterministic)
    """
    rec_type = detected.recommendation_type
    severity = detected.source_severity

    # Get templates for this recommendation type
    type_templates = RATIONALE_TEMPLATES.get(rec_type, {})

    # Try severity-specific, then "default"
    template = type_templates.get(severity) or type_templates.get("default")

    # Final fallback
    if not template:
        return (
            "This recommendation is based on the performance patterns detected "
            "in your marketing data. Taking action may help optimize results."
        )

    return template


# =============================================================================
# Validation Helpers
# =============================================================================


# Forbidden phrases that indicate imperative language
FORBIDDEN_PHRASES = [
    "you should",
    "you must",
    "you need to",
    "do this",
    "make sure",
    "ensure that",
    "it is necessary",
    "required to",
    "have to",
]

# Required conditional phrases (at least one should be present)
CONDITIONAL_PHRASES = [
    "consider",
    "may want",
    "may help",
    "could",
    "might",
    "you may",
    "potentially",
    "possibly",
]


def validate_recommendation_language(text: str) -> tuple[bool, str | None]:
    """
    Validate that recommendation text uses conditional language.

    Args:
        text: Recommendation text to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    text_lower = text.lower()

    # Check for forbidden imperative phrases
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text_lower:
            return False, f"Contains forbidden imperative phrase: '{phrase}'"

    # Check for at least one conditional phrase
    has_conditional = any(phrase in text_lower for phrase in CONDITIONAL_PHRASES)
    if not has_conditional:
        return False, "Missing conditional language (consider, may help, etc.)"

    return True, None
