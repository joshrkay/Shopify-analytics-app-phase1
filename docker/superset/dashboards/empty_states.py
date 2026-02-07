"""
Empty State and Edge Case Handling for Merchant Analytics Dashboard

Handles various scenarios where data may be missing or edge cases occur:
- No data (new tenant)
- No results for filtered query
- Zero spend campaigns (ROAS = N/A)
- Null values in numeric fields
"""

from typing import Any, Optional
from enum import Enum
from dataclasses import dataclass


class EmptyStateType(Enum):
    """Types of empty states in the dashboard."""
    NO_DATA = 'no_data'
    NO_RESULTS_FILTERED = 'no_results_filtered'
    INSUFFICIENT_DATA = 'insufficient_data'
    LOADING = 'loading'
    ERROR = 'error'


@dataclass
class EmptyStateConfig:
    """Configuration for an empty state display."""
    type: EmptyStateType
    message: str
    icon: str
    action_text: Optional[str]
    action_url: Optional[str]


# Empty state messages and configurations
EMPTY_STATE_CONFIGS: dict[EmptyStateType, EmptyStateConfig] = {
    EmptyStateType.NO_DATA: EmptyStateConfig(
        type=EmptyStateType.NO_DATA,
        message='No data yet. Add your first order to get started.',
        icon='inbox',
        action_text='Connect your store',
        action_url='/settings/connections',
    ),
    EmptyStateType.NO_RESULTS_FILTERED: EmptyStateConfig(
        type=EmptyStateType.NO_RESULTS_FILTERED,
        message='No results match your filters. Try adjusting your selections.',
        icon='filter',
        action_text='Clear filters',
        action_url=None,  # Handled by client-side filter reset
    ),
    EmptyStateType.INSUFFICIENT_DATA: EmptyStateConfig(
        type=EmptyStateType.INSUFFICIENT_DATA,
        message='Not enough data for this period. Check back later.',
        icon='calendar',
        action_text='Change date range',
        action_url=None,
    ),
    EmptyStateType.LOADING: EmptyStateConfig(
        type=EmptyStateType.LOADING,
        message='Loading your analytics...',
        icon='spinner',
        action_text=None,
        action_url=None,
    ),
    EmptyStateType.ERROR: EmptyStateConfig(
        type=EmptyStateType.ERROR,
        message='Unable to load data. Please try again.',
        icon='alert-circle',
        action_text='Retry',
        action_url=None,
    ),
}


# Edge case value mappings
EDGE_CASE_DISPLAY_VALUES: dict[str, dict[str, str]] = {
    'zero_spend': {
        'roas': 'N/A',
        'cpa': 'N/A',
        'cpc': 'N/A',
    },
    'zero_impressions': {
        'ctr': '0%',
    },
    'zero_clicks': {
        'cpc': 'N/A',
    },
    'zero_conversions': {
        'cpa': 'N/A',
        'roas': '0',
    },
    'null_value': {
        'numeric': '—',
        'string': '—',
        'date': '—',
    },
}


def get_empty_state_message(state_type: EmptyStateType) -> str:
    """Get the message for an empty state type."""
    config = EMPTY_STATE_CONFIGS.get(state_type)
    return config.message if config else 'No data available.'


def get_empty_state_config(state_type: EmptyStateType) -> Optional[EmptyStateConfig]:
    """Get the full configuration for an empty state type."""
    return EMPTY_STATE_CONFIGS.get(state_type)


def format_edge_case_value(
    value: Any,
    metric_name: str,
    edge_case_type: Optional[str] = None
) -> str:
    """
    Format a value for display, handling edge cases.

    Args:
        value: The value to format
        metric_name: Name of the metric (roas, cpa, cpc, ctr)
        edge_case_type: Type of edge case if known

    Returns:
        Formatted display string
    """
    # Check for null/None
    if value is None:
        return EDGE_CASE_DISPLAY_VALUES['null_value']['numeric']

    # Check for specific edge cases
    if edge_case_type and edge_case_type in EDGE_CASE_DISPLAY_VALUES:
        edge_values = EDGE_CASE_DISPLAY_VALUES[edge_case_type]
        if metric_name in edge_values:
            return edge_values[metric_name]

    # Return formatted value
    return str(value)


def should_show_empty_state(row_count: int, has_filters: bool = False) -> Optional[EmptyStateType]:
    """
    Determine if an empty state should be shown based on data.

    Args:
        row_count: Number of rows in query result
        has_filters: Whether any filters are applied

    Returns:
        EmptyStateType if empty state should be shown, None otherwise
    """
    if row_count == 0:
        if has_filters:
            return EmptyStateType.NO_RESULTS_FILTERED
        else:
            return EmptyStateType.NO_DATA
    return None


def get_roas_display_value(revenue: Optional[float], spend: Optional[float]) -> str:
    """
    Get ROAS display value with edge case handling.

    Args:
        revenue: Total revenue
        spend: Total spend

    Returns:
        ROAS display string
    """
    if spend is None or spend == 0:
        return 'N/A'

    if revenue is None:
        revenue = 0

    roas = revenue / spend
    return f'{roas:.2f}'


def get_ctr_display_value(clicks: Optional[int], impressions: Optional[int]) -> str:
    """
    Get CTR display value with edge case handling.

    Args:
        clicks: Number of clicks
        impressions: Number of impressions

    Returns:
        CTR display string (percentage)
    """
    if impressions is None or impressions == 0:
        return '0%'

    if clicks is None:
        clicks = 0

    ctr = (clicks / impressions) * 100
    return f'{ctr:.2f}%'


def get_cpc_display_value(spend: Optional[float], clicks: Optional[int]) -> str:
    """
    Get CPC display value with edge case handling.

    Args:
        spend: Total spend
        clicks: Number of clicks

    Returns:
        CPC display string
    """
    if clicks is None or clicks == 0:
        return 'N/A'

    if spend is None:
        spend = 0

    cpc = spend / clicks
    return f'${cpc:.2f}'


def get_cpa_display_value(spend: Optional[float], conversions: Optional[int]) -> str:
    """
    Get CPA display value with edge case handling.

    Args:
        spend: Total spend
        conversions: Number of conversions

    Returns:
        CPA display string
    """
    if conversions is None or conversions == 0:
        return 'N/A'

    if spend is None:
        spend = 0

    cpa = spend / conversions
    return f'${cpa:.2f}'


# Superset chart empty state configuration
SUPERSET_EMPTY_STATE_CONFIG: dict[str, Any] = {
    'emptyStateConfig': {
        'message': EMPTY_STATE_CONFIGS[EmptyStateType.NO_DATA].message,
        'description': 'Start by connecting your data sources.',
        'showButton': True,
        'buttonText': 'Connect Store',
        'buttonUrl': '/settings/connections',
    },
    'noResultsConfig': {
        'message': EMPTY_STATE_CONFIGS[EmptyStateType.NO_RESULTS_FILTERED].message,
        'description': 'Try adjusting your filters or date range.',
        'showButton': True,
        'buttonText': 'Reset Filters',
        'buttonAction': 'RESET_FILTERS',
    },
}
