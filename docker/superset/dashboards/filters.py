"""
Filter Definitions for Merchant Analytics Dashboard

Default filters and filter configurations:
- Date range: Last 30 days (server-side enforced, merchant configurable)
- Channel filter: Multi-select for marketing channels
- Platform filter: Filter by ad platform

Filters are persisted per tenant via user preferences.
"""

from typing import Any


class FilterOperators:
    """Superset filter operators."""
    TEMPORAL_RANGE = 'TEMPORAL_RANGE'
    IN = 'IN'
    EQUALS = '=='
    NOT_EQUALS = '!='
    GREATER_THAN = '>'
    LESS_THAN = '<'
    LIKE = 'LIKE'


# Filter 1: Date Range Filter (Primary)
FILTER_DATE_RANGE: dict[str, Any] = {
    'filter_id': 'date_range',
    'name': 'Date Range',
    'filter_type': 'filter_time',
    'column': 'order_created_at',
    'operator': FilterOperators.TEMPORAL_RANGE,
    'default_value': 'Last 30 days',
    'description': 'Filter all charts by date range',
    'config': {
        'defaultDataMask': {
            'filterState': {
                'value': 'Last 30 days',
            },
            'ownState': {},
        },
        'time_range': 'Last 30 days',
        'controlValues': {
            'enableEmptyFilter': False,
            'defaultToFirstItem': False,
            'multiSelect': False,
            'searchAllOptions': False,
            'inverseSelection': False,
        },
        'isInstant': True,
        'cascadeParentIds': [],
    },
    'scope': {
        'rootPath': ['ROOT_ID'],
        'excluded': [],
    },
    'targets': [
        {'column': {'name': 'order_created_at'}, 'datasetId': 1},  # fact_orders
        {'column': {'name': 'spend_date'}, 'datasetId': 2},  # fact_ad_spend
        {'column': {'name': 'performance_date'}, 'datasetId': 3},  # fact_campaign_performance
    ],
}


# Filter 2: Channel/Platform Filter
FILTER_CHANNEL: dict[str, Any] = {
    'filter_id': 'channel',
    'name': 'Channel',
    'filter_type': 'filter_select',
    'column': 'platform',
    'operator': FilterOperators.IN,
    'default_value': None,  # All channels by default
    'description': 'Filter by marketing channel/platform',
    'config': {
        'defaultDataMask': {
            'filterState': {
                'value': None,
            },
            'ownState': {},
        },
        'controlValues': {
            'enableEmptyFilter': True,
            'defaultToFirstItem': False,
            'multiSelect': True,
            'searchAllOptions': True,
            'inverseSelection': False,
        },
        'isInstant': True,
        'cascadeParentIds': [],
    },
    'scope': {
        'rootPath': ['ROOT_ID'],
        'excluded': [1, 4, 5, 6],  # Exclude order-based charts
    },
    'targets': [
        {'column': {'name': 'platform'}, 'datasetId': 2},  # fact_ad_spend
        {'column': {'name': 'platform'}, 'datasetId': 3},  # fact_campaign_performance
    ],
}


# Filter 3: Campaign Filter (Dependent on Channel)
FILTER_CAMPAIGN: dict[str, Any] = {
    'filter_id': 'campaign',
    'name': 'Campaign',
    'filter_type': 'filter_select',
    'column': 'campaign_id',
    'operator': FilterOperators.IN,
    'default_value': None,
    'description': 'Filter by specific campaign',
    'config': {
        'defaultDataMask': {
            'filterState': {
                'value': None,
            },
            'ownState': {},
        },
        'controlValues': {
            'enableEmptyFilter': True,
            'defaultToFirstItem': False,
            'multiSelect': True,
            'searchAllOptions': True,
            'inverseSelection': False,
        },
        'isInstant': True,
        'cascadeParentIds': ['channel'],  # Cascades from channel filter
    },
    'scope': {
        'rootPath': ['ROOT_ID'],
        'excluded': [1, 2, 4, 5, 6],  # Only applies to ROAS chart
    },
    'targets': [
        {'column': {'name': 'campaign_id'}, 'datasetId': 3},  # fact_campaign_performance
    ],
}


# Filter 4: Product Category Filter
FILTER_CATEGORY: dict[str, Any] = {
    'filter_id': 'category',
    'name': 'Product Category',
    'filter_type': 'filter_select',
    'column': 'tags',  # Using tags as proxy for category
    'operator': FilterOperators.IN,
    'default_value': None,
    'description': 'Filter by product category',
    'config': {
        'defaultDataMask': {
            'filterState': {
                'value': None,
            },
            'ownState': {},
        },
        'controlValues': {
            'enableEmptyFilter': True,
            'defaultToFirstItem': False,
            'multiSelect': True,
            'searchAllOptions': True,
            'inverseSelection': False,
        },
        'isInstant': True,
        'cascadeParentIds': [],
    },
    'scope': {
        'rootPath': ['ROOT_ID'],
        'excluded': [2, 3],  # Only applies to order-based charts
    },
    'targets': [
        {'column': {'name': 'tags'}, 'datasetId': 1},  # fact_orders
    ],
}


# Aggregate all filter definitions
FILTER_DEFINITIONS: dict[str, dict[str, Any]] = {
    'date_range': FILTER_DATE_RANGE,
    'channel': FILTER_CHANNEL,
    'campaign': FILTER_CAMPAIGN,
    'category': FILTER_CATEGORY,
}


# Default filter state - server-side enforced
DEFAULT_FILTER_STATE: dict[str, Any] = {
    'date_range': {
        'value': 'Last 30 days',
        'enforced': True,  # Server-side enforcement
    },
    'channel': {
        'value': None,
        'enforced': False,
    },
    'campaign': {
        'value': None,
        'enforced': False,
    },
    'category': {
        'value': None,
        'enforced': False,
    },
}


def get_native_filter_configuration() -> list[dict[str, Any]]:
    """
    Generate Superset native filter configuration.

    Returns the filter configuration in the format expected by
    Superset's dashboard metadata.
    """
    return [
        {
            'id': filter_def['filter_id'],
            'name': filter_def['name'],
            'filterType': filter_def['filter_type'],
            'targets': filter_def['targets'],
            'defaultDataMask': filter_def['config']['defaultDataMask'],
            'controlValues': filter_def['config']['controlValues'],
            'scope': filter_def['scope'],
            'cascadeParentIds': filter_def['config'].get('cascadeParentIds', []),
            'isInstant': filter_def['config'].get('isInstant', True),
        }
        for filter_def in FILTER_DEFINITIONS.values()
    ]


def create_filter_url_params(filters: dict[str, Any]) -> str:
    """
    Create URL parameters for filter state.

    Used for drilldown links that pass filter context.

    Args:
        filters: Dictionary of filter_id -> filter_value

    Returns:
        URL query string for filter parameters
    """
    import urllib.parse
    import json

    native_filters = {}
    for filter_id, value in filters.items():
        if value is not None:
            native_filters[filter_id] = {
                'id': filter_id,
                'value': value,
            }

    if not native_filters:
        return ''

    return urllib.parse.urlencode({
        'native_filters': json.dumps(native_filters)
    })
