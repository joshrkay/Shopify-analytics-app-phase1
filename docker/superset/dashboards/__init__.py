"""
Superset Dashboard Configurations

This module contains dashboard definitions for the Shopify Analytics Platform.
Dashboards are defined as Python dictionaries that can be imported via Superset CLI
or programmatically via the Superset API.

Dashboard Architecture:
    dbt run → manifest.json → sync job → Superset datasets → Dashboard

JWT Flow:
    App → JWT → Superset API → RLS → Dataset → Dashboard
"""

from .merchant_analytics import MERCHANT_ANALYTICS_DASHBOARD
from .charts import CHART_DEFINITIONS
from .filters import FILTER_DEFINITIONS
from .drilldown import DRILLDOWN_CHAINS
from .responsive import RESPONSIVE_CONFIG
from .empty_states import (
    EMPTY_STATE_CONFIGS,
    EmptyStateType,
    get_empty_state_message,
    get_roas_display_value,
)

__all__ = [
    'MERCHANT_ANALYTICS_DASHBOARD',
    'CHART_DEFINITIONS',
    'FILTER_DEFINITIONS',
    'DRILLDOWN_CHAINS',
    'RESPONSIVE_CONFIG',
    'EMPTY_STATE_CONFIGS',
    'EmptyStateType',
    'get_empty_state_message',
    'get_roas_display_value',
]
