"""
Merchant Analytics Dashboard Configuration

Main dashboard that answers the 5 core merchant questions:
1. Revenue last month - Line chart
2. Spend by channel - Bar chart
3. ROAS by campaign - Table
4. Revenue by category - Bar chart
5. Trend WoW - Line chart

Dashboard Features:
- Responsive layout (mobile, tablet, desktop)
- Drilldown navigation
- Default filters with persistence
- RLS tenant isolation
- Empty state handling
"""

from typing import Any, Optional
import json

from .charts import CHART_DEFINITIONS, ChartTypes
from .filters import FILTER_DEFINITIONS, get_native_filter_configuration, DEFAULT_FILTER_STATE
from .drilldown import DRILLDOWN_CHAINS, CROSS_FILTER_CONFIG
from .responsive import (
    RESPONSIVE_CONFIG,
    CHART_LAYOUTS,
    MOBILE_OPTIMIZATIONS,
    PERFORMANCE_TARGETS,
    DeviceType,
    generate_superset_position_json,
)


# Dashboard metadata
DASHBOARD_METADATA: dict[str, Any] = {
    'dashboard_title': 'Merchant Analytics Dashboard',
    'slug': 'merchant-analytics',
    'description': 'Core merchant business metrics answering key performance questions',
    'owners': [],  # Set dynamically based on tenant
    'published': True,
    'refresh_frequency': 300,  # 5 minute auto-refresh
    'css': '',  # Custom CSS if needed
    'json_metadata': {},
}


# Empty state messages for various scenarios
EMPTY_STATE_MESSAGES: dict[str, str] = {
    'no_data': 'No data yet. Add your first order to get started.',
    'no_results_filtered': 'No results match your filters. Try adjusting your selections.',
    'insufficient_data': 'Not enough data for this period. Check back later.',
    'loading': 'Loading your analytics...',
    'error': 'Unable to load data. Please try again.',
    'zero_spend_roas': 'N/A',  # ROAS display when spend is 0
}


# Edge case handling configuration
EDGE_CASE_CONFIG: dict[str, Any] = {
    'zero_spend': {
        'roas_display': 'N/A',
        'cpa_display': 'N/A',
        'cpc_display': 'N/A',
    },
    'zero_impressions': {
        'ctr_display': '0%',
    },
    'null_values': {
        'numeric_default': 0,
        'string_default': '-',
    },
    'empty_dataset': {
        'show_empty_state': True,
        'message_key': 'no_data',
    },
}


def build_dashboard_metadata() -> dict[str, Any]:
    """
    Build complete dashboard metadata including filters, charts, and layout.

    Returns:
        Complete dashboard metadata dictionary
    """
    return {
        'timed_refresh_immune_slices': [],
        'expanded_slices': {},
        'refresh_frequency': DASHBOARD_METADATA['refresh_frequency'],
        'default_filters': json.dumps(DEFAULT_FILTER_STATE),
        'color_scheme': 'supersetColors',
        'label_colors': {},
        'shared_label_colors': {},
        'color_scheme_domain': [],
        'cross_filters_enabled': CROSS_FILTER_CONFIG['enabled'],
        'native_filter_configuration': get_native_filter_configuration(),
        'chart_configuration': {
            str(chart_id): {
                'id': chart_id,
                'crossFilters': {
                    'scope': {
                        'rootPath': ['ROOT_ID'],
                        'excluded': [],
                    },
                    'chartsInScope': CROSS_FILTER_CONFIG.get('chartsInScope', {}).get(chart_id, []),
                },
            }
            for chart_id in CHART_DEFINITIONS.keys()
        },
    }


def build_position_json(device_type: DeviceType = DeviceType.DESKTOP) -> dict[str, Any]:
    """
    Build position JSON for dashboard layout.

    Args:
        device_type: Target device type for layout

    Returns:
        Position JSON dictionary for Superset
    """
    return generate_superset_position_json(device_type)


# Complete dashboard configuration
MERCHANT_ANALYTICS_DASHBOARD: dict[str, Any] = {
    # Dashboard identity
    'dashboard_title': DASHBOARD_METADATA['dashboard_title'],
    'slug': DASHBOARD_METADATA['slug'],
    'description': DASHBOARD_METADATA['description'],
    'published': DASHBOARD_METADATA['published'],

    # Charts included in this dashboard
    'charts': list(CHART_DEFINITIONS.values()),

    # Native filters
    'filters': list(FILTER_DEFINITIONS.values()),

    # Drilldown configuration
    'drilldown_config': DRILLDOWN_CHAINS,

    # Cross-filter configuration
    'cross_filter_config': CROSS_FILTER_CONFIG,

    # Responsive layout configuration
    'responsive_config': RESPONSIVE_CONFIG,

    # Layout positions for each device type
    'position_json': {
        'desktop': CHART_LAYOUTS['desktop'],
        'tablet': CHART_LAYOUTS['tablet'],
        'mobile': CHART_LAYOUTS['mobile'],
    },

    # Performance configuration
    'performance': PERFORMANCE_TARGETS,

    # Mobile optimizations
    'mobile_optimizations': MOBILE_OPTIMIZATIONS,

    # Empty state messages
    'empty_states': EMPTY_STATE_MESSAGES,

    # Edge case handling
    'edge_cases': EDGE_CASE_CONFIG,

    # Metadata
    'json_metadata': build_dashboard_metadata(),

    # Refresh configuration
    'refresh_frequency': DASHBOARD_METADATA['refresh_frequency'],

    # Cache settings
    'cache_timeout': 300,  # 5 minutes
}


def export_dashboard_json() -> str:
    """
    Export dashboard configuration as JSON for import via Superset CLI.

    Returns:
        JSON string of dashboard configuration
    """
    return json.dumps(MERCHANT_ANALYTICS_DASHBOARD, indent=2, default=str)


def get_chart_config(chart_id: int) -> Optional[dict[str, Any]]:
    """Get configuration for a specific chart."""
    return CHART_DEFINITIONS.get(chart_id)


def get_empty_state_message(scenario: str) -> str:
    """Get empty state message for a scenario."""
    return EMPTY_STATE_MESSAGES.get(scenario, EMPTY_STATE_MESSAGES['no_data'])


def validate_dashboard_config() -> list[str]:
    """
    Validate dashboard configuration for completeness.

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    # Check all required charts exist
    required_chart_ids = [1, 2, 3, 4, 5]
    for chart_id in required_chart_ids:
        if chart_id not in CHART_DEFINITIONS:
            errors.append(f"Missing required chart: {chart_id}")

    # Check all required filters exist
    required_filters = ['date_range']
    for filter_id in required_filters:
        if filter_id not in FILTER_DEFINITIONS:
            errors.append(f"Missing required filter: {filter_id}")

    # Check responsive layouts exist
    required_layouts = ['desktop', 'tablet', 'mobile']
    for layout in required_layouts:
        if layout not in CHART_LAYOUTS:
            errors.append(f"Missing layout for device type: {layout}")

    # Check drilldown configuration
    if not DRILLDOWN_CHAINS.get('enabled'):
        errors.append("Drilldown chains not enabled")

    return errors


# Superset API payload format
def get_superset_api_payload() -> dict[str, Any]:
    """
    Generate payload for Superset REST API dashboard creation.

    Returns:
        Dictionary formatted for Superset API
    """
    return {
        'dashboard_title': DASHBOARD_METADATA['dashboard_title'],
        'slug': DASHBOARD_METADATA['slug'],
        'published': DASHBOARD_METADATA['published'],
        'json_metadata': json.dumps(build_dashboard_metadata()),
        'position_json': json.dumps(build_position_json()),
        'css': DASHBOARD_METADATA['css'],
    }
