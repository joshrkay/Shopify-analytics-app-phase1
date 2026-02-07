"""
Tests for Core Merchant Dashboard KPIs (Story 5.3).

Verifies logic matches `metric_registry.yaml` edge cases:
- Zero divide handling
- Null handling
- Precision/Rounding
"""

import pytest
from decimal import Decimal
from analytics.metrics.kpi_definitions import (
    calculate_revenue,
    calculate_orders,
    calculate_roas,
    calculate_cac
)

class TestKPIs:
    
    # --- Revenue ---
    def test_revenue_sum(self):
        inputs = [100.50, 200.25, 50.25]
        assert calculate_revenue(inputs) == Decimal("351.00")

    def test_revenue_empty(self):
        assert calculate_revenue([]) == Decimal("0.00")

    def test_revenue_negative(self):
        # Refunds > Revenue
        inputs = [100.00, -150.00]
        assert calculate_revenue(inputs) == Decimal("-50.00")

    # --- Orders ---
    def test_orders_count(self):
        assert calculate_orders([1, 2, 3]) == 3

    def test_orders_empty(self):
        assert calculate_orders([]) == 0

    # --- ROAS ---
    def test_roas_happy_path(self):
        # 1000 revenue / 200 spend = 5.0
        assert calculate_roas(1000, 200) == Decimal("5.0000")

    def test_roas_zero_spend(self):
        # Registry: separate behavior: "Returns 0"
        assert calculate_roas(1000, 0) == Decimal("0.0000")
        
    def test_roas_null_spend(self):
        # Registry: "Treated as 0" -> Returns 0
        assert calculate_roas(1000, None) == Decimal("0.0000")

    def test_roas_zero_revenue(self):
        # 0 / 100 = 0
        assert calculate_roas(0, 100) == Decimal("0.0000")

    # --- CAC ---
    def test_cac_happy_path(self):
        # 500 spend / 10 customers = 50.00
        assert calculate_cac(500, 10) == Decimal("50.00")

    def test_cac_zero_customers(self):
        # Registry: "Returns 0"
        assert calculate_cac(500, 0) == Decimal("0.00")

    def test_cac_null_customers(self):
        # Registry: "Treated as 0"
        assert calculate_cac(500, None) == Decimal("0.00")

    def test_cac_zero_spend(self):
        # 0 spend / 5 customers = 0
        assert calculate_cac(0, 5) == Decimal("0.00")
