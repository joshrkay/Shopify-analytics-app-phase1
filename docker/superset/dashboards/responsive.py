"""
Responsive Layout Configuration for Merchant Analytics Dashboard

Mobile Testing Criteria:
- Devices: iPhone SE, iPhone Pro Max, iPad, Android tablet
- Browsers: Safari iOS 15+, Chrome Android 12+, Chrome Desktop
- Performance SLA: Chart ≤ 3s, Dashboard ≤ 5s (4G simulated, 5yr data)

Layout breakpoints:
- Mobile: < 600px (1 column)
- Tablet: 600-1024px (2 columns)
- Desktop: > 1024px (12 columns)
"""

from typing import Any
from dataclasses import dataclass
from enum import Enum


class DeviceType(Enum):
    """Device types for responsive layouts."""
    MOBILE = 'mobile'
    TABLET = 'tablet'
    DESKTOP = 'desktop'


class Breakpoint(Enum):
    """Responsive breakpoints in pixels."""
    MOBILE_MAX = 600
    TABLET_MIN = 601
    TABLET_MAX = 1024
    DESKTOP_MIN = 1025


@dataclass
class ViewportConfig:
    """Viewport configuration for a specific device."""
    width: int
    height: int
    device_pixel_ratio: float
    name: str


# Device viewport configurations for testing
DEVICE_VIEWPORTS: dict[str, ViewportConfig] = {
    'iphone_se': ViewportConfig(
        width=375,
        height=667,
        device_pixel_ratio=2.0,
        name='iPhone SE',
    ),
    'iphone_pro_max': ViewportConfig(
        width=430,
        height=932,
        device_pixel_ratio=3.0,
        name='iPhone 14 Pro Max',
    ),
    'ipad': ViewportConfig(
        width=768,
        height=1024,
        device_pixel_ratio=2.0,
        name='iPad',
    ),
    'android_tablet': ViewportConfig(
        width=600,
        height=1024,
        device_pixel_ratio=1.5,
        name='Android Tablet',
    ),
}


# Performance SLA targets
PERFORMANCE_TARGETS: dict[str, float] = {
    'chart_load_time_seconds': 3.0,
    'dashboard_load_time_seconds': 5.0,
    'cached_dashboard_load_time_seconds': 1.0,
    'network_condition': '4G',  # Simulated 4G for testing
    'max_dataset_history_years': 5,
}


# Responsive grid configuration
RESPONSIVE_CONFIG: dict[str, Any] = {
    'breakpoints': {
        'mobile': {
            'max_width': Breakpoint.MOBILE_MAX.value,
            'grid_columns': 1,
            'chart_height': 300,
            'margin': 8,
            'row_height': 50,
        },
        'tablet': {
            'min_width': Breakpoint.TABLET_MIN.value,
            'max_width': Breakpoint.TABLET_MAX.value,
            'grid_columns': 2,
            'chart_height': 350,
            'margin': 12,
            'row_height': 60,
        },
        'desktop': {
            'min_width': Breakpoint.DESKTOP_MIN.value,
            'grid_columns': 12,
            'chart_height': 400,
            'margin': 16,
            'row_height': 80,
        },
    },
    'touch_interactions': {
        'enabled': True,
        'gestures': ['tap', 'long_press', 'swipe', 'pinch_zoom'],
        'minimum_touch_target': 44,  # Minimum touch target size (px)
    },
    'browsers_tested': {
        'ios': ['Safari 15+'],
        'android': ['Chrome 12+'],
        'desktop': ['Chrome', 'Safari', 'Firefox', 'Edge'],
    },
}


# Chart position layouts for each breakpoint
CHART_LAYOUTS: dict[str, dict[int, dict[str, int]]] = {
    'desktop': {
        # chart_id: {x, y, w, h} on 12-column grid
        1: {'x': 0, 'y': 0, 'w': 6, 'h': 4},   # Revenue Last 30 Days
        2: {'x': 6, 'y': 0, 'w': 6, 'h': 4},   # Spend by Channel
        3: {'x': 0, 'y': 4, 'w': 12, 'h': 4},  # ROAS by Campaign (full width)
        4: {'x': 0, 'y': 8, 'w': 6, 'h': 4},   # Revenue by Category
        5: {'x': 6, 'y': 8, 'w': 6, 'h': 4},   # WoW Trend
    },
    'tablet': {
        # chart_id: {x, y, w, h} on 2-column grid
        1: {'x': 0, 'y': 0, 'w': 2, 'h': 4},   # Full width
        2: {'x': 0, 'y': 4, 'w': 2, 'h': 4},   # Full width
        3: {'x': 0, 'y': 8, 'w': 2, 'h': 5},   # Full width, taller for table
        4: {'x': 0, 'y': 13, 'w': 1, 'h': 4},  # Half width
        5: {'x': 1, 'y': 13, 'w': 1, 'h': 4},  # Half width
    },
    'mobile': {
        # chart_id: {x, y, w, h} on 1-column grid (stacked)
        1: {'x': 0, 'y': 0, 'w': 1, 'h': 5},
        2: {'x': 0, 'y': 5, 'w': 1, 'h': 5},
        3: {'x': 0, 'y': 10, 'w': 1, 'h': 6},  # Taller for scrollable table
        4: {'x': 0, 'y': 16, 'w': 1, 'h': 5},
        5: {'x': 0, 'y': 21, 'w': 1, 'h': 5},
    },
}


def get_device_type(viewport_width: int) -> DeviceType:
    """
    Determine device type based on viewport width.

    Args:
        viewport_width: Current viewport width in pixels

    Returns:
        DeviceType enum value
    """
    if viewport_width <= Breakpoint.MOBILE_MAX.value:
        return DeviceType.MOBILE
    elif viewport_width <= Breakpoint.TABLET_MAX.value:
        return DeviceType.TABLET
    else:
        return DeviceType.DESKTOP


def get_layout_for_device(device_type: DeviceType) -> dict[int, dict[str, int]]:
    """
    Get chart layout configuration for a specific device type.

    Args:
        device_type: The target device type

    Returns:
        Dictionary mapping chart_id to position configuration
    """
    return CHART_LAYOUTS.get(device_type.value, CHART_LAYOUTS['desktop'])


def get_grid_config(device_type: DeviceType) -> dict[str, Any]:
    """
    Get grid configuration for a specific device type.

    Args:
        device_type: The target device type

    Returns:
        Grid configuration dictionary
    """
    return RESPONSIVE_CONFIG['breakpoints'].get(
        device_type.value,
        RESPONSIVE_CONFIG['breakpoints']['desktop']
    )


def generate_superset_position_json(device_type: DeviceType = DeviceType.DESKTOP) -> dict[str, Any]:
    """
    Generate Superset dashboard position JSON for a device type.

    This creates the position_json format expected by Superset's
    dashboard API.

    Args:
        device_type: Target device type

    Returns:
        Position JSON dictionary
    """
    layout = get_layout_for_device(device_type)
    grid_config = get_grid_config(device_type)

    position_json = {
        'DASHBOARD_VERSION_KEY': 'v2',
        'ROOT_ID': {
            'type': 'ROOT',
            'id': 'ROOT_ID',
            'children': ['GRID_ID'],
        },
        'GRID_ID': {
            'type': 'GRID',
            'id': 'GRID_ID',
            'children': [],
            'parents': ['ROOT_ID'],
        },
        'HEADER_ID': {
            'type': 'HEADER',
            'id': 'HEADER_ID',
            'meta': {
                'text': 'Merchant Analytics Dashboard',
            },
        },
    }

    # Add chart components
    for chart_id, pos in layout.items():
        chart_key = f'CHART-{chart_id}'
        position_json['GRID_ID']['children'].append(chart_key)
        position_json[chart_key] = {
            'type': 'CHART',
            'id': chart_key,
            'meta': {
                'chartId': chart_id,
                'width': pos['w'],
                'height': pos['h'],
            },
            'parents': ['ROOT_ID', 'GRID_ID'],
        }

    return position_json


# Mobile-specific optimizations
MOBILE_OPTIMIZATIONS: dict[str, Any] = {
    'lazy_load_charts': True,
    'reduce_animation_duration': True,
    'animation_duration_ms': 150,  # Faster animations on mobile
    'skeleton_loading': True,
    'compress_images': True,
    'max_data_points_mobile': 100,  # Reduce data points for performance
    'max_data_points_tablet': 500,
    'max_data_points_desktop': 10000,
    'enable_virtual_scrolling': True,  # For long tables
    'table_page_size': {
        'mobile': 10,
        'tablet': 15,
        'desktop': 25,
    },
}


def get_max_data_points(device_type: DeviceType) -> int:
    """Get maximum data points for a device type."""
    key = f'max_data_points_{device_type.value}'
    return MOBILE_OPTIMIZATIONS.get(key, MOBILE_OPTIMIZATIONS['max_data_points_desktop'])


def get_table_page_size(device_type: DeviceType) -> int:
    """Get table page size for a device type."""
    return MOBILE_OPTIMIZATIONS['table_page_size'].get(
        device_type.value,
        MOBILE_OPTIMIZATIONS['table_page_size']['desktop']
    )
