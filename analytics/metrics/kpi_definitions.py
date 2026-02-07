"""
KPI Definitions for Core Merchant Dashboard (Story 5.3).

These definitions MUST match the logic in:
- analytics/metrics/metric_registry.yaml
- analytics/models/metrics/fct_*.sql

Strict adherence to the registry is required for consistency across
Superset, dbt, and the application backend.
"""

from typing import Optional, Union
from decimal import Decimal, ROUND_HALF_UP

def calculate_revenue(revenue_values: list[Union[float, Decimal]]) -> Decimal:
    """
    Calculate total Revenue.
    
    Definition: SUM(revenue)
    
    Args:
        revenue_values: List of revenue amounts.
        
    Returns:
        Total revenue as Decimal.
    """
    if not revenue_values:
        return Decimal("0.00")
        
    total = sum((Decimal(str(v)) for v in revenue_values), Decimal("0"))
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def calculate_orders(order_ids: list) -> int:
    """
    Calculate total Orders.
    
    Definition: COUNT(order_id)
    
    Args:
        order_ids: List of order IDs (can be empty).
        
    Returns:
        Count of orders.
    """
    return len(order_ids)

def calculate_roas(revenue: Union[float, Decimal], spend: Union[float, Decimal]) -> Decimal:
    """
    Calculate Return on Ad Spend (ROAS).
    
    Definition: SUM(revenue) / SUM(spend)
    Registry Rule: IF spend = 0 OR spend IS NULL THEN 0
    
    Args:
        revenue: Total attributed revenue.
        spend: Total ad spend.
        
    Returns:
        ROAS as Decimal (rounded to 4 decimal places).
    """
    rev_dec = Decimal(str(revenue)) if revenue is not None else Decimal("0")
    spend_dec = Decimal(str(spend)) if spend is not None else Decimal("0")
    
    if spend_dec == 0:
        return Decimal("0.0000")
        
    roas = rev_dec / spend_dec
    return roas.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

def calculate_cac(spend: Union[float, Decimal], new_customers: int) -> Decimal:
    """
    Calculate Customer Acquisition Cost (CAC).
    
    Definition: SUM(spend) / COUNT(new_customers)
    Registry Rule: IF new_customers = 0 OR new_customers IS NULL THEN 0
    registry rationale: Avoids NULL/infinity, indicates no acquisitions.
    
    Args:
        spend: Total ad spend.
        new_customers: Count of new customers.
        
    Returns:
        CAC as Decimal (rounded to 2 decimal places).
    """
    spend_dec = Decimal(str(spend)) if spend is not None else Decimal("0")
    
    if new_customers is None or new_customers == 0:
        return Decimal("0.00")
        
    cac = spend_dec / Decimal(new_customers)
    return cac.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
