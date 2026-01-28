"""
Template-based natural language summary generation.

Provides deterministic, human-readable insight summaries.
No LLM dependency - ensures same inputs produce same outputs.

Story 8.1 - AI Insight Generation (Read-Only Analytics)
Story 8.2 - Insight Explainability & Evidence
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.insight_generation_service import DetectedInsight

from src.models.ai_insight import InsightType, InsightSeverity


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


# Templates organized by: InsightType -> direction -> severity
INSIGHT_TEMPLATES = {
    InsightType.SPEND_ANOMALY: {
        "increase": {
            InsightSeverity.CRITICAL: (
                "Marketing spend increased significantly by {delta_pct:.1f}% {timeframe}, "
                "reaching {currency_symbol}{current_value:,.0f}{platform_suffix}. "
                "This is a critical change that warrants immediate review."
            ),
            InsightSeverity.WARNING: (
                "Marketing spend increased by {delta_pct:.1f}% {timeframe} "
                "to {currency_symbol}{current_value:,.0f}{platform_suffix}. "
                "Review campaign budgets to ensure alignment with targets."
            ),
            InsightSeverity.INFO: (
                "Marketing spend increased by {delta_pct:.1f}% {timeframe}{platform_suffix}."
            ),
        },
        "decrease": {
            InsightSeverity.CRITICAL: (
                "Marketing spend dropped significantly by {delta_pct:.1f}% {timeframe}, "
                "now at {currency_symbol}{current_value:,.0f}{platform_suffix}. "
                "This may impact campaign reach and performance."
            ),
            InsightSeverity.WARNING: (
                "Marketing spend decreased by {delta_pct:.1f}% {timeframe} "
                "to {currency_symbol}{current_value:,.0f}{platform_suffix}. "
                "Check if this aligns with planned budget adjustments."
            ),
            InsightSeverity.INFO: (
                "Marketing spend decreased by {delta_pct:.1f}% {timeframe}{platform_suffix}."
            ),
        },
    },
    InsightType.ROAS_CHANGE: {
        "increase": {
            InsightSeverity.CRITICAL: (
                "ROAS improved dramatically by {delta_pct:.1f}% {timeframe}, "
                "now at {current_value:.2f}x{platform_suffix}. "
                "Identify what's working and consider scaling successful campaigns."
            ),
            InsightSeverity.WARNING: (
                "ROAS improved by {delta_pct:.1f}% {timeframe} "
                "to {current_value:.2f}x{platform_suffix}. "
                "Good performance - monitor for sustainability."
            ),
            InsightSeverity.INFO: (
                "ROAS improved by {delta_pct:.1f}% {timeframe}{platform_suffix}."
            ),
        },
        "decrease": {
            InsightSeverity.CRITICAL: (
                "ROAS declined significantly by {delta_pct:.1f}% {timeframe}, "
                "now at {current_value:.2f}x{platform_suffix}. "
                "Urgent review of ad efficiency recommended."
            ),
            InsightSeverity.WARNING: (
                "ROAS declined by {delta_pct:.1f}% {timeframe} "
                "to {current_value:.2f}x{platform_suffix}. "
                "Review campaign targeting and creative performance."
            ),
            InsightSeverity.INFO: (
                "ROAS declined by {delta_pct:.1f}% {timeframe}{platform_suffix}."
            ),
        },
    },
    InsightType.REVENUE_VS_SPEND_DIVERGENCE: {
        "default": {
            InsightSeverity.WARNING: (
                "Revenue and spend are moving in opposite directions: "
                "revenue {revenue_direction} by {revenue_delta_pct:.1f}% while "
                "spend {spend_direction} by {spend_delta_pct:.1f}% {timeframe}. "
                "Review marketing efficiency."
            ),
            InsightSeverity.CRITICAL: (
                "Significant divergence detected: revenue {revenue_direction} by "
                "{revenue_delta_pct:.1f}% while spend {spend_direction} by "
                "{spend_delta_pct:.1f}% {timeframe}. Immediate review recommended."
            ),
        },
    },
    InsightType.CHANNEL_MIX_SHIFT: {
        "default": {
            InsightSeverity.WARNING: (
                "Significant shift in channel mix: {platform} share changed by "
                "{delta_pct:.1f}% {timeframe}. Evaluate if this aligns with strategy."
            ),
            InsightSeverity.INFO: (
                "Channel mix shifted with {platform} changing by "
                "{delta_pct:.1f}% {timeframe}."
            ),
        },
    },
    InsightType.CAC_ANOMALY: {
        "increase": {
            InsightSeverity.CRITICAL: (
                "Customer acquisition cost increased significantly by {delta_pct:.1f}% "
                "{timeframe}, now at {currency_symbol}{current_value:,.0f}{platform_suffix}. "
                "Review targeting and funnel efficiency."
            ),
            InsightSeverity.WARNING: (
                "CAC increased by {delta_pct:.1f}% {timeframe} to "
                "{currency_symbol}{current_value:,.0f}{platform_suffix}. "
                "Monitor acquisition efficiency."
            ),
            InsightSeverity.INFO: (
                "CAC increased by {delta_pct:.1f}% {timeframe}{platform_suffix}."
            ),
        },
        "decrease": {
            InsightSeverity.INFO: (
                "CAC improved by {delta_pct:.1f}% {timeframe} to "
                "{currency_symbol}{current_value:,.0f}{platform_suffix}. "
                "Acquisition efficiency is improving."
            ),
            InsightSeverity.WARNING: (
                "CAC improved by {delta_pct:.1f}% {timeframe}{platform_suffix}. "
                "Good trend - acquisition is becoming more efficient."
            ),
        },
    },
    InsightType.AOV_CHANGE: {
        "increase": {
            InsightSeverity.INFO: (
                "Average order value increased by {delta_pct:.1f}% {timeframe} "
                "to {currency_symbol}{current_value:,.2f}. Customers are spending more per order."
            ),
            InsightSeverity.WARNING: (
                "AOV increased significantly by {delta_pct:.1f}% {timeframe} to "
                "{currency_symbol}{current_value:,.2f}. Verify this aligns with pricing strategy."
            ),
        },
        "decrease": {
            InsightSeverity.WARNING: (
                "Average order value decreased by {delta_pct:.1f}% {timeframe} "
                "to {currency_symbol}{current_value:,.2f}. Review product mix and pricing."
            ),
            InsightSeverity.CRITICAL: (
                "AOV dropped significantly by {delta_pct:.1f}% {timeframe} to "
                "{currency_symbol}{current_value:,.2f}. Urgent review of pricing and promotions."
            ),
        },
    },
}


def _format_timeframe(comparison_type: str) -> str:
    """Format comparison type as readable timeframe."""
    mappings = {
        "week_over_week": "week-over-week",
        "month_over_month": "month-over-month",
        "day_over_day": "day-over-day",
        "quarter_over_quarter": "quarter-over-quarter",
        "year_over_year": "year-over-year",
    }
    return mappings.get(comparison_type, comparison_type.replace("_", " "))


def _get_direction(delta_pct: float) -> str:
    """Get direction word based on delta."""
    return "increased" if delta_pct > 0 else "decreased"


def render_insight_summary(detected: "DetectedInsight") -> str:
    """
    Render a natural language summary for a detected insight.

    Args:
        detected: DetectedInsight object with metrics and context

    Returns:
        Human-readable summary string (deterministic)
    """
    templates = INSIGHT_TEMPLATES.get(detected.insight_type, {})

    # Get primary metric
    if not detected.metrics:
        return f"Insight detected: {detected.insight_type.value.replace('_', ' ')}"

    primary_metric = detected.metrics[0]

    # Determine direction
    direction = "increase" if primary_metric.delta_pct > 0 else "decrease"

    # Get severity-specific template
    direction_templates = templates.get(direction, templates.get("default", {}))
    template = direction_templates.get(detected.severity)

    # Fallback to INFO if specific severity not found
    if not template:
        template = direction_templates.get(InsightSeverity.INFO)

    # Final fallback
    if not template:
        return (
            f"{detected.insight_type.value.replace('_', ' ').title()} detected "
            f"with {abs(primary_metric.delta_pct):.1f}% change."
        )

    # Build context for template
    currency_symbol = CURRENCY_SYMBOLS.get(detected.currency or "USD", "$")
    platform_suffix = ""
    if detected.platform:
        platform_suffix = f" on {detected.platform.replace('_', ' ').title()}"

    context = {
        "delta_pct": abs(primary_metric.delta_pct),
        "current_value": float(primary_metric.current_value),
        "prior_value": float(primary_metric.prior_value),
        "timeframe": _format_timeframe(primary_metric.timeframe),
        "currency_symbol": currency_symbol,
        "platform_suffix": platform_suffix,
        "platform": (detected.platform or "").replace("_", " ").title(),
        "insight_type": detected.insight_type.value,
    }

    # Add secondary metrics for divergence insights
    if (
        detected.insight_type == InsightType.REVENUE_VS_SPEND_DIVERGENCE
        and len(detected.metrics) >= 2
    ):
        revenue_metric = detected.metrics[0]
        spend_metric = detected.metrics[1]
        context["revenue_delta_pct"] = abs(revenue_metric.delta_pct)
        context["spend_delta_pct"] = abs(spend_metric.delta_pct)
        context["revenue_direction"] = _get_direction(revenue_metric.delta_pct)
        context["spend_direction"] = _get_direction(spend_metric.delta_pct)

    try:
        return template.format(**context)
    except KeyError:
        # Fallback if template has missing keys
        return (
            f"{detected.insight_type.value.replace('_', ' ').title()} detected "
            f"with {abs(primary_metric.delta_pct):.1f}% change."
        )


# =============================================================================
# Story 8.2 - Explainability: Why It Matters Templates
# =============================================================================

# Metric display names for business-friendly API responses
METRIC_DISPLAY_NAMES = {
    "spend": "Marketing Spend",
    "gross_roas": "Return on Ad Spend (ROAS)",
    "net_roas": "Net ROAS",
    "net_revenue": "Net Revenue",
    "gross_revenue": "Gross Revenue",
    "cac": "Customer Acquisition Cost (CAC)",
    "aov": "Average Order Value (AOV)",
    "new_customers": "New Customers",
    "order_count": "Order Count",
}

# Why it matters templates by insight type -> direction -> severity
WHY_IT_MATTERS_TEMPLATES = {
    InsightType.SPEND_ANOMALY: {
        "increase": {
            InsightSeverity.CRITICAL: (
                "A significant increase in marketing spend without corresponding "
                "revenue growth may indicate budget inefficiency. Review campaign "
                "performance to ensure spend is driving results."
            ),
            InsightSeverity.WARNING: (
                "Rising marketing spend should be monitored to ensure it aligns "
                "with your growth targets and delivers expected returns."
            ),
            InsightSeverity.INFO: (
                "Tracking spend changes helps you maintain budget control "
                "and optimize marketing efficiency."
            ),
        },
        "decrease": {
            InsightSeverity.CRITICAL: (
                "A sharp drop in marketing spend may reduce your store's visibility "
                "and customer acquisition. Review if this aligns with your strategy."
            ),
            InsightSeverity.WARNING: (
                "Reduced spend may impact reach. Monitor performance to ensure "
                "visibility goals are still met."
            ),
            InsightSeverity.INFO: (
                "Lower spending can be strategic. Ensure it aligns with your "
                "current business objectives."
            ),
        },
    },
    InsightType.ROAS_CHANGE: {
        "increase": {
            InsightSeverity.CRITICAL: (
                "Your marketing efficiency has improved significantly. Identify "
                "what's working well and consider scaling those campaigns."
            ),
            InsightSeverity.WARNING: (
                "Improving ROAS is positive. Analyze which channels are "
                "performing best to replicate success."
            ),
            InsightSeverity.INFO: (
                "Steady ROAS improvements indicate effective optimization. "
                "Continue monitoring to maintain momentum."
            ),
        },
        "decrease": {
            InsightSeverity.CRITICAL: (
                "A declining ROAS means you're earning less revenue per dollar "
                "spent on ads. This could impact profitability if not addressed."
            ),
            InsightSeverity.WARNING: (
                "Lower returns on ad spend may indicate ad fatigue, increased "
                "competition, or targeting issues worth investigating."
            ),
            InsightSeverity.INFO: (
                "Monitor ROAS trends to ensure your marketing investment "
                "continues to generate positive returns."
            ),
        },
    },
    InsightType.REVENUE_VS_SPEND_DIVERGENCE: {
        "default": {
            InsightSeverity.CRITICAL: (
                "When revenue and spend move in opposite directions, it signals "
                "a potential efficiency problem. Investigate whether your marketing "
                "is reaching the right audience."
            ),
            InsightSeverity.WARNING: (
                "Diverging revenue and spend trends warrant attention. Review "
                "which channels are underperforming relative to investment."
            ),
            InsightSeverity.INFO: (
                "Keep an eye on the relationship between spend and revenue "
                "to maintain marketing efficiency."
            ),
        },
    },
    InsightType.CHANNEL_MIX_SHIFT: {
        "default": {
            InsightSeverity.WARNING: (
                "Significant changes in channel mix can affect overall performance. "
                "Evaluate if this shift aligns with your marketing strategy."
            ),
            InsightSeverity.INFO: (
                "Channel mix naturally evolves. Monitor to ensure changes "
                "support your business goals."
            ),
        },
    },
    InsightType.CAC_ANOMALY: {
        "increase": {
            InsightSeverity.CRITICAL: (
                "Rising customer acquisition costs directly impact profitability. "
                "Review targeting, creative, and funnel conversion rates."
            ),
            InsightSeverity.WARNING: (
                "Higher acquisition costs may indicate market saturation or "
                "increased competition. Optimize your funnel efficiency."
            ),
            InsightSeverity.INFO: (
                "Monitor CAC trends relative to customer lifetime value "
                "to ensure sustainable growth."
            ),
        },
        "decrease": {
            InsightSeverity.CRITICAL: (
                "Significantly lower acquisition costs is excellent. Identify "
                "and scale what's working."
            ),
            InsightSeverity.WARNING: (
                "Improved CAC is positive. Analyze the contributing factors "
                "to replicate success."
            ),
            InsightSeverity.INFO: (
                "Lower acquisition costs mean more efficient growth. Continue "
                "optimizing your campaigns."
            ),
        },
    },
    InsightType.AOV_CHANGE: {
        "increase": {
            InsightSeverity.CRITICAL: (
                "Significant AOV increase improves revenue without needing "
                "more customers. Identify what's driving this positive trend."
            ),
            InsightSeverity.WARNING: (
                "Higher average order values are positive. Consider what's "
                "driving this trend to replicate it."
            ),
            InsightSeverity.INFO: (
                "Steady AOV improvements indicate effective upselling or "
                "product mix optimization."
            ),
        },
        "decrease": {
            InsightSeverity.CRITICAL: (
                "Sharp AOV decline may indicate customers buying fewer items "
                "or lower-priced products. Review product mix and pricing strategy."
            ),
            InsightSeverity.WARNING: (
                "Declining order values may impact revenue. Review product "
                "recommendations and bundling strategies."
            ),
            InsightSeverity.INFO: (
                "Monitor AOV alongside conversion rates for a complete picture "
                "of customer behavior."
            ),
        },
    },
}


def get_metric_display_name(metric_name: str) -> str:
    """Get business-friendly display name for a metric."""
    return METRIC_DISPLAY_NAMES.get(metric_name, metric_name.replace("_", " ").title())


def format_timeframe_human(period_type: str) -> str:
    """Convert period type to human-readable timeframe."""
    mappings = {
        "last_7_days": "Last 7 days",
        "last_14_days": "Last 14 days",
        "last_30_days": "Last 30 days",
        "last_90_days": "Last 90 days",
        "weekly": "Last 7 days",
        "monthly": "Last 30 days",
        "daily": "Last 24 hours",
    }
    return mappings.get(period_type, period_type.replace("_", " ").title())


def render_why_it_matters(detected: "DetectedInsight") -> str:
    """
    Render business-friendly explanation of why an insight matters.

    Args:
        detected: DetectedInsight object with type, severity, and metrics

    Returns:
        Human-readable explanation string (deterministic)
    """
    templates = WHY_IT_MATTERS_TEMPLATES.get(detected.insight_type, {})

    # Determine direction from primary metric
    direction = "default"
    if detected.metrics:
        direction = "increase" if detected.metrics[0].delta_pct > 0 else "decrease"

    # Get direction-specific templates, fall back to default
    direction_templates = templates.get(direction, templates.get("default", {}))

    # Get severity-specific template
    template = direction_templates.get(detected.severity)

    # Fallback chain: try INFO, then any available template
    if not template:
        template = direction_templates.get(InsightSeverity.INFO)
    if not template and templates.get("default"):
        template = templates["default"].get(detected.severity) or templates["default"].get(
            InsightSeverity.INFO
        )

    # Final fallback
    if not template:
        return "Monitor this metric for changes that may impact your business performance."

    return template
