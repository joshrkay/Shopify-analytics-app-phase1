"""
Tests for Drilldown Configuration Logic.
Verifies URL generation and context retrieval for dashboard linking.
"""

import sys
import os
import pytest
from typing import Any

# Add docker/superset to path to import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../docker/superset')))

from dashboards.drilldown import (
    generate_drilldown_url,
    get_drilldown_context,
    REVENUE_DRILLDOWN_CHAIN,
    DrilldownLevel
)

class TestDrilldownConfig:
    
    def test_generate_drilldown_url_params(self):
        """Verify URL parameters are correctly encoded."""
        url = generate_drilldown_url(
            dashboard_id='merchant-analytics',
            target_chart_id=4,
            filters={'date_range': 'Last 7 days', 'channel': 'Social'}
        )
        
        assert '/superset/dashboard/merchant-analytics/' in url
        assert 'standalone=1' in url
        assert 'show_filters=0' in url
        # Check simple filter presence (URL encoded)
        assert 'Last+7+days' in url or 'Last%207%20days' in url
        assert 'slice_id=4' in url

    def test_generate_drilldown_url_disallowed_dashboard(self):
        with pytest.raises(ValueError):
            generate_drilldown_url(
                dashboard_id='explore',
                target_chart_id=4,
                filters={'date_range': 'Last 7 days', 'channel': 'Social'}
            )

    def test_drilldown_chain_integrity(self):
        """Verify the revenue chain is correctly linked."""
        steps = REVENUE_DRILLDOWN_CHAIN.steps
        assert len(steps) == 3
        assert steps[0].level == DrilldownLevel.SUMMARY
        assert steps[1].level == DrilldownLevel.CATEGORY
        assert steps[2].level == DrilldownLevel.DETAIL
        
        # Verify columns passed down
        assert steps[1].filters_from_parent == ['order_created_at']

    def test_get_drilldown_context_found(self):
        """Verify context retrieval for a known chart ID."""
        # Chart ID 1 is the summary in Revenue Drill
        context = get_drilldown_context(source_chart_id=1, clicked_value='2023-10-01', clicked_column='order_created_at')
        
        assert context['has_drilldown'] is True
        assert context['target_chart_id'] == 4 # Next step
        assert context['filter_value'] == '2023-10-01'

    def test_get_drilldown_context_endpoint(self):
        """Verify no drilldown from the last step."""
        # Chart ID 6 is the detail step
        context = get_drilldown_context(source_chart_id=6, clicked_value='123', clicked_column='order_id')
        
        assert context['has_drilldown'] is False

    def test_get_drilldown_context_disallowed_column(self):
        context = get_drilldown_context(source_chart_id=1, clicked_value='123', clicked_column='order_id')
        assert context['has_drilldown'] is False
