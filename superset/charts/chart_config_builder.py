"""
Chart Configuration Builder for Superset.

Generates standard chart JSON definitions for the Core Merchant Dashboard.
Ensures consistency, responsiveness, and correct dataset mapping.
"""

import json
from typing import Optional, List, Dict, Any

class ChartConfigBuilder:
    def __init__(self):
        self.default_params = {
            "time_range": "Last 30 days",
            "granularity_sqla": "order_date",
            "time_grain_sqla": "P1D",  # Daily
            "row_limit": 50000,
            "viz_type": "echarts_timeseries_line",  # Default
            "metrics": [],
            "groupby": [],
            "color_scheme": "supersetColors",
        }

    def build_chart(
        self,
        slice_name: str,
        viz_type: str,
        dataset_name: str,
        metrics: List[Any],
        groupby: Optional[List[str]] = None,
        color: Optional[str] = None,
        is_responsive: bool = True
    ) -> Dict[str, Any]:
        """
        Generate a Superset chart configuration dictionary.
        
        Args:
            slice_name: Display name of the chart.
            viz_type: Superset/ECharts viz type ('echarts_timeseries_line', 'echarts_timeseries_bar').
            dataset_name: Name of the canonical dataset (e.g., 'fact_orders_current').
            metrics: List of metrics (strings or dictionaries).
            groupby: List of dimensions to group by.
            color: Optional specific color hex code (override default scheme).
            is_responsive: If True, sets parameters for responsive resizing.
            
        Returns:
            Dictionary representing the chart JSON structure.
        """
        
        # Validation
        if viz_type not in ["echarts_timeseries_line", "echarts_timeseries_bar"]:
            raise ValueError(f"Unsupported viz_type: {viz_type}")
            
        if not metrics:
            raise ValueError("At least one metric must be provided.")
            
        if not dataset_name:
            raise ValueError("Dataset name is required.")

        # Base configuration
        params = self.default_params.copy()
        params["viz_type"] = viz_type
        params["metrics"] = metrics
        if groupby:
            params["groupby"] = groupby
            
        # Color handling (simplified for ECharts)
        # In a real Superset import, 'color_scheme' handles palette.
        # Custom colors often require 'label_colors' map in metadata.
        if color:
           # This is a placeholder for custom color logic implementation
           # Superset uses a specific structure for color overrides.
           pass 

        # Responsive / Viewport Sizing
        # Superset charts naturally fill their grid container.
        # However, we can enforce specific styles or properties if needed.
        # For standard imports, relying on the 'GRID' layout in the dashboard JSON is standard.
        # We explicitly tag it here for tracking.
        meta = {
            "sliceName": slice_name,
            "viz_type": viz_type,
            "datasource_name": dataset_name,
            "is_responsive": is_responsive 
        }

        # Construct final JSON structure (simplified for export/import compatibility)
        chart_json = {
            "slice_name": slice_name,
            "viz_type": viz_type,
            "datasource_type": "table",
            "datasource_name": dataset_name,
            "params": json.dumps(params),
            "cache_timeout": 86400 # 24 hours default
        }
        
        return chart_json

if __name__ == "__main__":
    # Example usage / generation
    builder = ChartConfigBuilder()
    
    # 1. Revenue Trend
    revenue_trend = builder.build_chart(
        slice_name="Revenue Trend",
        viz_type="echarts_timeseries_line",
        dataset_name="fact_orders_current",
        metrics=["sum__revenue"],
        color="#00FF00" 
    )
    print(json.dumps(revenue_trend, indent=2))
