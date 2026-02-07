"""
Tests for Chart Configuration Builder.

Verifies:
- JSON structure generation
- Validation logic (invalid types, missing metrics)
- Edge case handling
"""

import pytest
import json
from superset.charts.chart_config_builder import ChartConfigBuilder

class TestChartBuilder:
    
    def setup_method(self):
        self.builder = ChartConfigBuilder()

    def test_build_line_chart_success(self):
        chart = self.builder.build_chart(
            slice_name="Test Line",
            viz_type="echarts_timeseries_line",
            dataset_name="fact_test",
            metrics=["count"]
        )
        assert chart["slice_name"] == "Test Line"
        assert chart["viz_type"] == "echarts_timeseries_line"
        
        params = json.loads(chart["params"])
        assert params["metrics"] == ["count"]
        assert params["row_limit"] == 50000

    def test_build_bar_chart_success(self):
        chart = self.builder.build_chart(
            slice_name="Test Bar",
            viz_type="echarts_timeseries_bar",
            dataset_name="fact_test",
            metrics=["sum__revenue"],
            groupby=["channel"]
        )
        assert chart["viz_type"] == "echarts_timeseries_bar"
        params = json.loads(chart["params"])
        assert params["groupby"] == ["channel"]

    def test_invalid_viz_type(self):
        with pytest.raises(ValueError, match="Unsupported viz_type"):
            self.builder.build_chart(
                slice_name="Bad Chart",
                viz_type="pie_chart", # Not supported yet
                dataset_name="fact_test",
                metrics=["count"]
            )

    def test_missing_metrics(self):
        with pytest.raises(ValueError, match="At least one metric"):
            self.builder.build_chart(
                slice_name="No Metric",
                viz_type="echarts_timeseries_line",
                dataset_name="fact_test",
                metrics=[]
            )

    def test_missing_dataset(self):
        with pytest.raises(ValueError, match="Dataset name is required"):
            self.builder.build_chart(
                slice_name="No Data",
                viz_type="echarts_timeseries_line",
                dataset_name="",
                metrics=["count"]
            )
