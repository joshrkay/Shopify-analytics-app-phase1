"""
Template-based action proposal text generation.

Provides deterministic, human-readable risk disclaimers and expected effects.
No LLM dependency - ensures same inputs produce same outputs.

KEY REQUIREMENTS:
- Every proposal MUST have a risk disclaimer
- Expected effects must be clear and honest
- No guarantees or promises of outcome

Story 8.4 - Action Proposals (Approval Required)
"""

from typing import Any

from src.models.action_proposal import ActionType, TargetPlatform, TargetEntityType
from src.models.ai_recommendation import RiskLevel


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
# Risk Disclaimer Templates
# Organized by: ActionType -> RiskLevel
#
# Every proposal MUST have a risk disclaimer that clearly communicates
# potential consequences of the action.
# =============================================================================

RISK_DISCLAIMERS: dict[ActionType, dict[RiskLevel, str]] = {
    ActionType.REDUCE_BUDGET: {
        RiskLevel.LOW: (
            "Reducing budget may decrease ad impressions and reach. "
            "Monitor campaign performance after making changes. "
            "You can increase budget again at any time."
        ),
        RiskLevel.MEDIUM: (
            "Budget reduction will lower ad delivery and may impact conversion volume. "
            "Campaigns may take time to stabilize after budget changes. "
            "Consider the potential impact on your marketing goals."
        ),
        RiskLevel.HIGH: (
            "Significant budget reduction will substantially decrease campaign reach "
            "and conversions. This may affect your ability to hit performance targets. "
            "Ensure you understand the impact before proceeding."
        ),
    },
    ActionType.INCREASE_BUDGET: {
        RiskLevel.LOW: (
            "Increasing budget will raise ad spend. Ensure sufficient funds are available. "
            "Monitor ROAS to ensure efficiency is maintained at higher spend levels."
        ),
        RiskLevel.MEDIUM: (
            "Budget increase will result in higher ad spend and may affect ROAS. "
            "Campaigns may need time to optimize at new budget levels. "
            "Consider starting with a gradual increase."
        ),
        RiskLevel.HIGH: (
            "Substantial budget increase carries risk of diminishing returns. "
            "Higher spend does not guarantee proportional results. "
            "Monitor closely for signs of declining efficiency."
        ),
    },
    ActionType.PAUSE_CAMPAIGN: {
        RiskLevel.LOW: (
            "Pausing will stop ad delivery immediately. No further spend will occur. "
            "You can resume the campaign at any time."
        ),
        RiskLevel.MEDIUM: (
            "Pausing may affect campaign learning phase and optimization. "
            "When resumed, the campaign may need time to regain performance. "
            "Consider the impact on ongoing promotions or seasonal timing."
        ),
        RiskLevel.HIGH: (
            "Extended pause may reset campaign optimization and audience targeting. "
            "Resuming after a long pause may result in a learning period with "
            "reduced performance. Consider impact on business goals carefully."
        ),
    },
    ActionType.RESUME_CAMPAIGN: {
        RiskLevel.LOW: (
            "Resuming will restart ad delivery and budget spending. "
            "Ensure your budget and billing are set up correctly."
        ),
        RiskLevel.MEDIUM: (
            "After being paused, the campaign may need time to re-optimize. "
            "Initial performance may differ from before the pause. "
            "Monitor closely during the first few days."
        ),
        RiskLevel.HIGH: (
            "Campaign has been paused for an extended period. "
            "Audience targeting and optimization may need to rebuild. "
            "Expect a learning period with potentially reduced efficiency."
        ),
    },
    ActionType.ADJUST_TARGETING: {
        RiskLevel.LOW: (
            "Targeting changes will affect which audiences see your ads. "
            "Monitor reach and engagement metrics after changes."
        ),
        RiskLevel.MEDIUM: (
            "Targeting adjustments will change your audience reach. "
            "This may affect conversion rates and cost per acquisition. "
            "Consider testing changes on a subset first."
        ),
        RiskLevel.HIGH: (
            "Significant targeting changes may substantially alter campaign performance. "
            "Narrowing audiences too much may limit scale. "
            "Expanding too broadly may reduce relevance and efficiency."
        ),
    },
    ActionType.MODIFY_BIDDING: {
        RiskLevel.LOW: (
            "Bidding changes will affect how you compete in ad auctions. "
            "Monitor cost metrics and delivery after making changes."
        ),
        RiskLevel.MEDIUM: (
            "Bid adjustments may impact ad delivery and costs. "
            "Lower bids may reduce impressions; higher bids may increase costs. "
            "Allow time for the campaign to adjust to new settings."
        ),
        RiskLevel.HIGH: (
            "Substantial bid changes may significantly affect campaign economics. "
            "Aggressive bidding changes can lead to rapid spend or delivery issues. "
            "Consider making incremental adjustments instead."
        ),
    },
}


# =============================================================================
# Expected Effect Templates
# Organized by: ActionType
#
# Templates describe what will happen if the action is taken.
# Use placeholders for dynamic values.
# =============================================================================

EXPECTED_EFFECT_TEMPLATES: dict[ActionType, str] = {
    ActionType.REDUCE_BUDGET: (
        "Budget for '{entity_name}' will decrease from {current_value} to "
        "{proposed_value} ({change_description}). Expected reduction in "
        "impressions and reach proportional to budget decrease."
    ),
    ActionType.INCREASE_BUDGET: (
        "Budget for '{entity_name}' will increase from {current_value} to "
        "{proposed_value} ({change_description}). This may result in increased "
        "reach and impressions, subject to auction dynamics."
    ),
    ActionType.PAUSE_CAMPAIGN: (
        "Campaign '{entity_name}' will stop serving ads immediately. "
        "No further ad spend will occur until the campaign is resumed. "
        "All scheduled ads will be paused."
    ),
    ActionType.RESUME_CAMPAIGN: (
        "Campaign '{entity_name}' will begin serving ads again. "
        "Budget will start being spent according to campaign settings. "
        "Delivery may take time to ramp up."
    ),
    ActionType.ADJUST_TARGETING: (
        "Targeting for '{entity_name}' will be modified. "
        "{change_description}. Audience reach and composition will change "
        "based on the new targeting parameters."
    ),
    ActionType.MODIFY_BIDDING: (
        "Bidding strategy for '{entity_name}' will be updated. "
        "{change_description}. This will affect how the campaign competes "
        "in ad auctions and may impact delivery and costs."
    ),
}


# =============================================================================
# Action Description Templates
# Human-readable descriptions of what the action will do
# =============================================================================

ACTION_DESCRIPTION_TEMPLATES: dict[ActionType, str] = {
    ActionType.REDUCE_BUDGET: "Reduce daily budget by {change_value}",
    ActionType.INCREASE_BUDGET: "Increase daily budget by {change_value}",
    ActionType.PAUSE_CAMPAIGN: "Pause campaign",
    ActionType.RESUME_CAMPAIGN: "Resume campaign",
    ActionType.ADJUST_TARGETING: "Adjust audience targeting",
    ActionType.MODIFY_BIDDING: "Modify bidding strategy",
}


# =============================================================================
# Helper Functions
# =============================================================================


def get_risk_disclaimer(
    action_type: ActionType,
    risk_level: RiskLevel,
) -> str:
    """
    Get the risk disclaimer text for an action type and risk level.

    Args:
        action_type: Type of action being proposed
        risk_level: Risk level of the action

    Returns:
        Risk disclaimer text
    """
    action_disclaimers = RISK_DISCLAIMERS.get(action_type, {})
    disclaimer = action_disclaimers.get(risk_level)

    if not disclaimer:
        # Fallback generic disclaimer
        return (
            f"This action will modify your ad campaign settings. "
            f"Risk level: {risk_level.value}. "
            f"Review the proposed changes carefully before approving. "
            f"Changes may take time to take effect and impact performance."
        )

    return disclaimer


def render_expected_effect(
    action_type: ActionType,
    entity_name: str,
    current_value: dict[str, Any] | None,
    proposed_change: dict[str, Any],
    currency: str = "USD",
) -> str:
    """
    Render the expected effect description for an action.

    Args:
        action_type: Type of action being proposed
        entity_name: Name of the target entity (campaign, ad set, etc.)
        current_value: Current state snapshot
        proposed_change: Proposed change details
        currency: Currency code for formatting

    Returns:
        Human-readable expected effect description
    """
    template = EXPECTED_EFFECT_TEMPLATES.get(action_type)

    if not template:
        return f"This action will modify '{entity_name}' according to the proposed changes."

    currency_symbol = CURRENCY_SYMBOLS.get(currency, "$")

    # Build context for template
    context = {
        "entity_name": entity_name,
        "currency_symbol": currency_symbol,
    }

    # Format current value
    if current_value and "budget" in current_value:
        context["current_value"] = f"{currency_symbol}{current_value['budget']:,.2f}"
    elif current_value and "value" in current_value:
        context["current_value"] = str(current_value["value"])
    else:
        context["current_value"] = "current value"

    # Format proposed value and change description
    if proposed_change.get("type") == "percentage":
        pct = proposed_change.get("value", 0)
        sign = "+" if pct > 0 else ""
        context["change_description"] = f"{sign}{pct}%"

        if current_value and "budget" in current_value:
            new_budget = current_value["budget"] * (1 + pct / 100)
            context["proposed_value"] = f"{currency_symbol}{new_budget:,.2f}"
        else:
            context["proposed_value"] = f"{sign}{pct}% from current"
    elif proposed_change.get("type") == "absolute":
        new_value = proposed_change.get("value", 0)
        context["proposed_value"] = f"{currency_symbol}{new_value:,.2f}"
        context["change_description"] = "absolute change"
    elif proposed_change.get("type") == "status":
        context["proposed_value"] = proposed_change.get("value", "changed")
        context["change_description"] = f"status: {proposed_change.get('value', 'changed')}"
    else:
        context["proposed_value"] = str(proposed_change.get("value", "updated"))
        context["change_description"] = str(proposed_change.get("description", "as specified"))

    try:
        return template.format(**context)
    except KeyError:
        return f"This action will modify '{entity_name}' according to the proposed changes."


def render_action_description(
    action_type: ActionType,
    proposed_change: dict[str, Any],
    currency: str = "USD",
) -> str:
    """
    Render a short action description.

    Args:
        action_type: Type of action being proposed
        proposed_change: Proposed change details
        currency: Currency code for formatting

    Returns:
        Short action description
    """
    template = ACTION_DESCRIPTION_TEMPLATES.get(action_type)

    if not template:
        return f"Perform {action_type.value.replace('_', ' ')}"

    currency_symbol = CURRENCY_SYMBOLS.get(currency, "$")

    # Format change value
    if proposed_change.get("type") == "percentage":
        pct = proposed_change.get("value", 0)
        sign = "+" if pct > 0 else ""
        change_value = f"{sign}{pct}%"
    elif proposed_change.get("type") == "absolute":
        value = proposed_change.get("value", 0)
        change_value = f"{currency_symbol}{value:,.2f}"
    else:
        change_value = str(proposed_change.get("value", ""))

    try:
        return template.format(change_value=change_value)
    except KeyError:
        return f"Perform {action_type.value.replace('_', ' ')}"


def get_platform_display_name(platform: TargetPlatform) -> str:
    """Get human-readable platform name."""
    display_names = {
        TargetPlatform.META: "Meta (Facebook/Instagram)",
        TargetPlatform.GOOGLE: "Google Ads",
        TargetPlatform.TIKTOK: "TikTok Ads",
    }
    return display_names.get(platform, platform.value.title())


def get_entity_type_display_name(entity_type: TargetEntityType) -> str:
    """Get human-readable entity type name."""
    display_names = {
        TargetEntityType.CAMPAIGN: "Campaign",
        TargetEntityType.AD_SET: "Ad Set",
        TargetEntityType.AD: "Ad",
    }
    return display_names.get(entity_type, entity_type.value.replace("_", " ").title())
