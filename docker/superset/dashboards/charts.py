"""
Chart Definitions for Merchant Analytics Dashboard

Each chart answers one of the 5 core merchant questions:
1. Revenue last month - Line chart
2. Spend by channel - Bar chart
3. ROAS by campaign - Table
4. Revenue by category - Bar chart
5. Trend WoW - Line chart
"""

from typing import Any, Optional

# Chart type constants for Superset
class ChartTypes:
    LINE = 'echarts_timeseries_line'
    BAR = 'echarts_timeseries_bar'
    TABLE = 'table'
    BIG_NUMBER = 'big_number_total'
    PIE = 'pie'


# Temporal range constants
class TemporalRange:
    LAST_7_DAYS = 'LAST_7_DAYS'
    LAST_30_DAYS = 'LAST_30_DAYS'
    LAST_90_DAYS = 'LAST_90_DAYS'
    LAST_MONTH = 'previous_calendar_month'
    LAST_WEEK = 'previous_calendar_week'


def create_temporal_filter(column: str, range_value: str) -> dict:
    """Create a temporal range filter for a chart."""
    return {
        'col': column,
        'op': 'TEMPORAL_RANGE',
        'val': range_value
    }


# Chart 1: Revenue Last 30 Days (Line Chart)
CHART_REVENUE_LAST_30_DAYS: dict[str, Any] = {
    'chart_id': 1,
    'slice_name': 'Revenue Last 30 Days',
    'viz_type': ChartTypes.LINE,
    'datasource': 'fact_orders',
    'description': 'Daily revenue trend for the last 30 days',
    'params': {
        'metrics': [
            {
                'expressionType': 'SQL',
                'sqlExpression': 'SUM(revenue)',
                'label': 'Total Revenue',
            }
        ],
        'groupby': [],
        'x_axis': 'order_created_at',
        'time_grain_sqla': 'P1D',  # Daily granularity
        'adhoc_filters': [
            {
                'clause': 'WHERE',
                'expressionType': 'SQL',
                'sqlExpression': "order_created_at >= CURRENT_DATE - INTERVAL '30 days'",
            }
        ],
        'time_range': TemporalRange.LAST_30_DAYS,
        'row_limit': 10000,
        'color_scheme': 'supersetColors',
        'show_legend': True,
        'legendOrientation': 'top',
        'rich_tooltip': True,
        'y_axis_format': '$,.2f',
        'x_axis_title': 'Date',
        'y_axis_title': 'Revenue',
        'truncateYAxis': False,
        'zoomable': True,
    },
    'cache_timeout': 300,  # 5 minute cache
    'width': 6,
    'height': 4,
}


# Chart 2: Marketing Spend by Channel (Bar Chart)
CHART_SPEND_BY_CHANNEL: dict[str, Any] = {
    'chart_id': 2,
    'slice_name': 'Marketing Spend by Channel',
    'viz_type': ChartTypes.BAR,
    'datasource': 'fact_ad_spend',
    'description': 'Total marketing spend broken down by advertising platform/channel',
    'params': {
        'metrics': [
            {
                'expressionType': 'SQL',
                'sqlExpression': 'SUM(spend)',
                'label': 'Total Spend',
            }
        ],
        'groupby': ['platform'],
        'adhoc_filters': [
            {
                'clause': 'WHERE',
                'expressionType': 'SQL',
                'sqlExpression': "spend_date >= CURRENT_DATE - INTERVAL '30 days'",
            }
        ],
        'time_range': TemporalRange.LAST_30_DAYS,
        'row_limit': 1000,
        'color_scheme': 'supersetColors',
        'show_legend': True,
        'legendOrientation': 'top',
        'rich_tooltip': True,
        'y_axis_format': '$,.2f',
        'x_axis_title': 'Channel',
        'y_axis_title': 'Spend',
        'bar_stacked': False,
        'order_bars': True,
    },
    'cache_timeout': 300,
    'width': 6,
    'height': 4,
}


# Chart 3: ROAS by Campaign (Table)
CHART_ROAS_BY_CAMPAIGN: dict[str, Any] = {
    'chart_id': 3,
    'slice_name': 'ROAS by Campaign',
    'viz_type': ChartTypes.TABLE,
    'datasource': 'fact_campaign_performance',
    'description': 'Return on Ad Spend by campaign with revenue, spend, and ROAS metrics',
    'params': {
        'query_mode': 'aggregate',
        'groupby': ['campaign_id', 'campaign_name', 'platform'],
        'metrics': [
            {
                'expressionType': 'SQL',
                'sqlExpression': 'SUM(spend)',
                'label': 'Spend',
            },
            {
                'expressionType': 'SQL',
                'sqlExpression': 'SUM(conversions)',
                'label': 'Conversions',
            },
            {
                'expressionType': 'SQL',
                'sqlExpression': """
                    CASE
                        WHEN SUM(spend) = 0 THEN NULL
                        ELSE SUM(conversions * 50) / NULLIF(SUM(spend), 0)
                    END
                """,
                'label': 'ROAS',
            }
        ],
        'adhoc_filters': [
            {
                'clause': 'WHERE',
                'expressionType': 'SQL',
                'sqlExpression': "performance_date >= CURRENT_DATE - INTERVAL '30 days'",
            }
        ],
        'time_range': TemporalRange.LAST_30_DAYS,
        'row_limit': 1000,
        'order_by_cols': [['ROAS', False]],  # Descending by ROAS
        'table_timestamp_format': '%Y-%m-%d',
        'page_length': 25,
        'include_search': True,
        'show_cell_bars': True,
        # ROAS formatting with N/A for zero spend
        'column_config': {
            'ROAS': {
                'd3Format': '.2f',
                'emptyValuePlaceholder': 'N/A',
            },
            'Spend': {
                'd3Format': '$,.2f',
            },
            'Conversions': {
                'd3Format': ',d',
            },
        },
    },
    'cache_timeout': 300,
    'width': 12,
    'height': 4,
}


# Chart 4: Revenue by Product Category (Bar Chart)
CHART_REVENUE_BY_CATEGORY: dict[str, Any] = {
    'chart_id': 4,
    'slice_name': 'Revenue by Product Category',
    'viz_type': ChartTypes.BAR,
    'datasource': 'fact_orders',
    'description': 'Revenue distribution across product categories',
    'params': {
        'metrics': [
            {
                'expressionType': 'SQL',
                'sqlExpression': 'SUM(revenue)',
                'label': 'Total Revenue',
            }
        ],
        # Note: This requires a product_category field - may need fact_order_items
        # For now, we use tags as a proxy for category
        'groupby': ['tags'],
        'adhoc_filters': [
            {
                'clause': 'WHERE',
                'expressionType': 'SQL',
                'sqlExpression': "order_created_at >= CURRENT_DATE - INTERVAL '30 days'",
            }
        ],
        'time_range': TemporalRange.LAST_30_DAYS,
        'row_limit': 20,  # Top 20 categories
        'color_scheme': 'supersetColors',
        'show_legend': False,
        'rich_tooltip': True,
        'y_axis_format': '$,.2f',
        'x_axis_title': 'Category',
        'y_axis_title': 'Revenue',
        'bar_stacked': False,
        'order_bars': True,
        'orientation': 'horizontal',  # Horizontal for readability with many categories
    },
    'cache_timeout': 300,
    'width': 6,
    'height': 4,
}


# Chart 5: Week-over-Week Revenue Trend (Line Chart)
CHART_WOW_TREND: dict[str, Any] = {
    'chart_id': 5,
    'slice_name': 'Week-over-Week Revenue Trend',
    'viz_type': ChartTypes.LINE,
    'datasource': 'fact_orders',
    'description': 'Weekly revenue trend with week-over-week comparison',
    'params': {
        'metrics': [
            {
                'expressionType': 'SQL',
                'sqlExpression': 'SUM(revenue)',
                'label': 'Weekly Revenue',
            }
        ],
        'groupby': [],
        'x_axis': 'order_created_at',
        'time_grain_sqla': 'P1W',  # Weekly granularity
        'adhoc_filters': [
            {
                'clause': 'WHERE',
                'expressionType': 'SQL',
                'sqlExpression': "order_created_at >= CURRENT_DATE - INTERVAL '90 days'",
            }
        ],
        'time_range': TemporalRange.LAST_90_DAYS,
        'row_limit': 10000,
        'color_scheme': 'supersetColors',
        'show_legend': True,
        'legendOrientation': 'top',
        'rich_tooltip': True,
        'y_axis_format': '$,.2f',
        'x_axis_title': 'Week',
        'y_axis_title': 'Revenue',
        'truncateYAxis': False,
        'zoomable': True,
        # Time comparison for WoW
        'comparison_type': 'values',
        'time_compare': ['P1W'],  # Compare with 1 week ago
    },
    'cache_timeout': 300,
    'width': 6,
    'height': 4,
}


# Chart 6: Revenue by SKU (Detail drilldown chart)
CHART_REVENUE_BY_SKU: dict[str, Any] = {
    'chart_id': 6,
    'slice_name': 'Revenue by SKU',
    'viz_type': ChartTypes.TABLE,
    'datasource': 'fact_orders',
    'description': 'Detailed revenue breakdown by product SKU (drilldown target)',
    'params': {
        'query_mode': 'aggregate',
        'groupby': ['order_id', 'order_name'],
        'metrics': [
            {
                'expressionType': 'SQL',
                'sqlExpression': 'SUM(revenue)',
                'label': 'Revenue',
            },
            {
                'expressionType': 'SQL',
                'sqlExpression': 'COUNT(*)',
                'label': 'Order Count',
            }
        ],
        'adhoc_filters': [
            {
                'clause': 'WHERE',
                'expressionType': 'SQL',
                'sqlExpression': "order_created_at >= CURRENT_DATE - INTERVAL '30 days'",
            }
        ],
        'time_range': TemporalRange.LAST_30_DAYS,
        'row_limit': 100,
        'order_by_cols': [['Revenue', False]],
        'table_timestamp_format': '%Y-%m-%d',
        'page_length': 25,
        'include_search': True,
        'show_cell_bars': True,
        'column_config': {
            'Revenue': {
                'd3Format': '$,.2f',
            },
            'Order Count': {
                'd3Format': ',d',
            },
        },
    },
    'cache_timeout': 300,
    'width': 12,
    'height': 6,
}


# Aggregate all chart definitions
CHART_DEFINITIONS: dict[int, dict[str, Any]] = {
    1: CHART_REVENUE_LAST_30_DAYS,
    2: CHART_SPEND_BY_CHANNEL,
    3: CHART_ROAS_BY_CAMPAIGN,
    4: CHART_REVENUE_BY_CATEGORY,
    5: CHART_WOW_TREND,
    6: CHART_REVENUE_BY_SKU,
}


def get_chart_by_id(chart_id: int) -> Optional[dict[str, Any]]:
    """Retrieve a chart definition by its ID."""
    return CHART_DEFINITIONS.get(chart_id)


def get_charts_for_dataset(dataset_name: str) -> list[dict[str, Any]]:
    """Get all charts that use a specific dataset."""
    return [
        chart for chart in CHART_DEFINITIONS.values()
        if chart['datasource'] == dataset_name
    ]
