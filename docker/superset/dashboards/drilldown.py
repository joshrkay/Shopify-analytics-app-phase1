"""
Drilldown Chain Configuration for Merchant Analytics Dashboard

Drilldown mechanics:
- Revenue Summary → Revenue by Category → Revenue by SKU
- Implemented via dashboard links with dynamic URL params
- Filters passed via URL for context preservation

Drilldown Flow (ASCII):
    Revenue Summary (Chart 1)
         ↓ click
    Revenue by Category (Chart 4)
         ↓ click
    Revenue by SKU (Chart 6)
"""

from typing import Any
from dataclasses import dataclass
from enum import Enum


class DrilldownLevel(Enum):
    """Drilldown hierarchy levels."""
    SUMMARY = 1
    CATEGORY = 2
    DETAIL = 3


@dataclass
class DrilldownStep:
    """Represents a single step in the drilldown chain."""
    level: DrilldownLevel
    chart_id: int
    groupby: str
    filters_from_parent: list[str]


@dataclass
class DrilldownChain:
    """Represents a complete drilldown chain."""
    name: str
    steps: list[DrilldownStep]
    enabled: bool = True


# Only allow drilldowns to predefined dashboards (no Explore links).
ALLOWED_DASHBOARD_TARGETS: set[str] = {
    "core_merchant_dashboard",
    "merchant-analytics",
}

ALLOWED_DRILLDOWN_FILTERS: set[str] = {
    "date_range",
    "channel",
    "order_date",
    "order_created_at",
    "campaign_date",
    "period_start",
    "platform",
}


def _validate_drilldown_target(dashboard_id: str) -> None:
    if dashboard_id not in ALLOWED_DASHBOARD_TARGETS:
        raise ValueError(f"Dashboard '{dashboard_id}' is not an allowed drilldown target.")


def _sanitize_filters(filters: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in filters.items() if key in ALLOWED_DRILLDOWN_FILTERS}


# Revenue Drilldown Chain
REVENUE_DRILLDOWN_CHAIN = DrilldownChain(
    name='Revenue Drill',
    steps=[
        DrilldownStep(
            level=DrilldownLevel.SUMMARY,
            chart_id=1,
            groupby='order_created_at',
            filters_from_parent=[],
        ),
        DrilldownStep(
            level=DrilldownLevel.CATEGORY,
            chart_id=4,
            groupby='tags',  # product_category proxy
            filters_from_parent=['order_created_at'],
        ),
        DrilldownStep(
            level=DrilldownLevel.DETAIL,
            chart_id=6,
            groupby='order_id',
            filters_from_parent=['order_created_at', 'tags'],
        ),
    ],
    enabled=True,
)


# Drilldown configuration in Superset format
DRILLDOWN_CHAINS: dict[str, Any] = {
    'enabled': True,
    'chains': [
        {
            'name': 'Revenue Drill',
            'description': 'Drill from revenue summary to category to SKU detail',
            'steps': [
                {
                    'level': 1,
                    'chart_id': 1,
                    'groupby': 'order_created_at',
                    'label': 'Revenue Summary',
                    'next_level_filters': ['date_range', 'channel'],
                },
                {
                    'level': 2,
                    'chart_id': 4,
                    'groupby': 'tags',
                    'label': 'Revenue by Category',
                    'next_level_filters': ['date_range', 'channel'],
                },
                {
                    'level': 3,
                    'chart_id': 6,
                    'groupby': 'order_id',
                    'label': 'Revenue by SKU',
                    'next_level_filters': [],
                },
            ],
        },
        {
            'name': 'Campaign Performance Drill',
            'description': 'Drill from channel spend to campaign detail',
            'steps': [
                {
                    'level': 1,
                    'chart_id': 2,
                    'groupby': 'platform',
                    'label': 'Spend by Channel',
                    'next_level_filters': ['date_range', 'channel'],
                },
                {
                    'level': 2,
                    'chart_id': 3,
                    'groupby': 'campaign_id',
                    'label': 'ROAS by Campaign',
                    'next_level_filters': [],
                },
            ],
        },
    ],
}


def generate_drilldown_url(
    dashboard_id: str,
    target_chart_id: int,
    filters: dict[str, Any],
    base_url: str = '/superset/dashboard'
) -> str:
    """
    Generate a drilldown URL with filter context.

    Args:
        dashboard_id: The target dashboard ID or slug
        target_chart_id: The chart to focus on after drilldown
        filters: Dictionary of filter values to pass
        base_url: Base URL for dashboard

    Returns:
        Full URL with filter parameters

    Example:
        >>> generate_drilldown_url(
        ...     'merchant-analytics',
        ...     4,
        ...     {'date_range': 'Last 30 days', 'category': 'Electronics'}
        ... )
        '/superset/dashboard/merchant-analytics/?native_filters=...'
    """
    import json
    import urllib.parse

    _validate_drilldown_target(dashboard_id)

    # Build native filter state
    filters = _sanitize_filters(filters)
    native_filter_state = []
    for filter_id, value in filters.items():
        if value is not None:
            native_filter_state.append({
                'id': filter_id,
                'value': value,
            })

    params = {
        'native_filters_key': json.dumps(native_filter_state),
        'standalone': '1',  # Focus mode
        'show_filters': '0',  # Hide filter bar initially
    }

    # Add focus chart parameter if specified
    if target_chart_id:
        params['slice_id'] = str(target_chart_id)

    url = f"{base_url}/{dashboard_id}/"
    if params:
        url += '?' + urllib.parse.urlencode(params)

    return url


def get_drilldown_context(
    source_chart_id: int,
    clicked_value: Any,
    clicked_column: str,
) -> dict[str, Any]:
    """
    Get drilldown context based on source chart and clicked value.

    Args:
        source_chart_id: The chart where user clicked
        clicked_value: The value that was clicked
        clicked_column: The column that was clicked

    Returns:
        Drilldown context with target chart and filters
    """
    if clicked_column not in ALLOWED_DRILLDOWN_FILTERS:
        return {
            'has_drilldown': False,
            'target_chart_id': None,
            'target_groupby': None,
            'filter_column': None,
            'filter_value': None,
        }
    # Find which chain contains this source chart
    for chain in DRILLDOWN_CHAINS['chains']:
        for i, step in enumerate(chain['steps']):
            if step['chart_id'] == source_chart_id:
                # Found the source step, get next step
                if i < len(chain['steps']) - 1:
                    next_step = chain['steps'][i + 1]
                    return {
                        'has_drilldown': True,
                        'target_chart_id': next_step['chart_id'],
                        'target_groupby': next_step['groupby'],
                        'filter_column': clicked_column,
                        'filter_value': clicked_value,
                        'chain_name': chain['name'],
                        'current_level': step['level'],
                        'next_level': next_step['level'],
                    }

    return {
        'has_drilldown': False,
        'target_chart_id': None,
        'target_groupby': None,
        'filter_column': None,
        'filter_value': None,
    }


# Cross-filtering configuration
CROSS_FILTER_CONFIG: dict[str, Any] = {
    'enabled': True,
    'scoped': True,  # Filters only apply to charts in same scope
    'chartsInScope': {
        # Chart 1 (Revenue) cross-filters to charts 4, 5, 6
        1: [4, 5, 6],
        # Chart 2 (Spend by Channel) cross-filters to chart 3
        2: [3],
        # Chart 4 (Revenue by Category) cross-filters to chart 6
        4: [6],
    },
}


def get_cross_filter_targets(source_chart_id: int) -> list[int]:
    """Get list of chart IDs that should be filtered when source is clicked."""
    return CROSS_FILTER_CONFIG.get('chartsInScope', {}).get(source_chart_id, [])
