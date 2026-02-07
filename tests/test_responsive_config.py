"""
Tests for Responsive Configuration Logic.
Verifies breakpoint definitions and mobile optimization settings.
"""

import sys
import os
import pytest

# Add docker/superset to path to import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../docker/superset')))

from dashboards.responsive import (
    DeviceType,
    get_layout_for_device,
    get_grid_config,
    generate_superset_position_json,
    MOBILE_OPTIMIZATIONS
)

class TestResponsiveConfig:
    
    def test_mobile_layout_stacking(self):
        """Verify mobile layout stacks charts in a single column."""
        layout = get_layout_for_device(DeviceType.MOBILE)
        grid = get_grid_config(DeviceType.MOBILE)
        
        assert grid['grid_columns'] == 1
        
        # Check that chart 1 and 2 are stacked (y positions increase)
        c1 = layout[1]
        c2 = layout[2]
        
        assert c1['x'] == 0
        assert c2['x'] == 0
        assert c2['y'] >= c1['y'] + c1['h'] # C2 starts after C1 ends

    def test_desktop_layout_grid(self):
        """Verify desktop layout uses multi-column grid."""
        grid = get_grid_config(DeviceType.DESKTOP)
        assert grid['grid_columns'] == 12

    def test_mobile_optimizations(self):
        """Verify key mobile optimizations are enabled."""
        assert MOBILE_OPTIMIZATIONS['lazy_load_charts'] is True
        assert MOBILE_OPTIMIZATIONS['max_data_points_mobile'] < MOBILE_OPTIMIZATIONS['max_data_points_desktop']

    def test_position_json_structure(self):
        """Verify the generated JSON matches Superset structure."""
        pos_json = generate_superset_position_json(DeviceType.MOBILE)
        
        assert 'DASHBOARD_VERSION_KEY' in pos_json
        assert 'ROOT_ID' in pos_json
        assert 'GRID_ID' in pos_json
        assert 'HEADER_ID' in pos_json
        assert 'CHART-1' in pos_json # Check presence of a chart
