"""
Standardized Test Data Sets for E2E Testing.

Contains predefined data sets with known expected outcomes
for reliable and reproducible testing.
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import uuid


class TestDataProvider:
    """
    Provides test data with methods to customize and extend.

    Usage:
        provider = TestDataProvider()
        orders = provider.get_orders("new_merchant_initial")
        provider.add_custom_order(orders, total_price=500.0)
    """

    def __init__(self):
        self._custom_data: Dict[str, Dict] = {}

    def get_orders(self, scenario: str) -> List[Dict]:
        """Get orders for a specific scenario."""
        if scenario in self._custom_data:
            return self._custom_data[scenario].get("orders", [])
        return TEST_DATA_SETS.get(scenario, {}).get("_airbyte_raw_shopify_orders", [])

    def get_customers(self, scenario: str) -> List[Dict]:
        """Get customers for a specific scenario."""
        if scenario in self._custom_data:
            return self._custom_data[scenario].get("customers", [])
        return TEST_DATA_SETS.get(scenario, {}).get("_airbyte_raw_shopify_customers", [])

    def get_data_for_connection(self, connection_id: str) -> Dict[str, List[Dict]]:
        """Get all data for a specific connection (used by mock Airbyte)."""
        # Default to new_merchant_initial if no specific data configured
        return TEST_DATA_SETS.get("new_merchant_initial", {})

    def add_custom_order(
        self,
        orders: List[Dict],
        order_id: Optional[str] = None,
        total_price: float = 99.99,
        **kwargs
    ) -> Dict:
        """Add a custom order to a list."""
        order = create_order(
            order_id=order_id,
            total_price=total_price,
            **kwargs
        )
        orders.append(order)
        return order

    def set_scenario_data(self, scenario: str, data: Dict) -> None:
        """Set custom data for a scenario."""
        self._custom_data[scenario] = data


# =============================================================================
# Helper Functions
# =============================================================================

def create_order(
    order_id: Optional[str] = None,
    order_number: Optional[int] = None,
    total_price: float = 99.99,
    financial_status: str = "paid",
    fulfillment_status: str = "fulfilled",
    created_at: Optional[str] = None,
    currency: str = "USD",
    customer_email: Optional[str] = None,
    refunds: Optional[List[Dict]] = None,
    cancelled_at: Optional[str] = None,
    line_items: Optional[List[Dict]] = None,
) -> Dict:
    """Create a single order record."""
    order_id = order_id or f"gid://shopify/Order/{uuid.uuid4().hex[:12]}"
    customer_id = f"gid://shopify/Customer/{uuid.uuid4().hex[:12]}"

    return {
        "id": order_id,
        "order_number": order_number or (1000 + hash(order_id) % 9000),
        "total_price": str(total_price),
        "subtotal_price": str(round(total_price * 0.9, 2)),
        "total_tax": str(round(total_price * 0.1, 2)),
        "currency": currency,
        "financial_status": financial_status,
        "fulfillment_status": fulfillment_status,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cancelled_at": cancelled_at,
        "customer": {
            "id": customer_id,
            "email": customer_email or f"customer-{uuid.uuid4().hex[:8]}@example.com",
            "first_name": "Test",
            "last_name": "Customer",
        },
        "line_items": line_items or [
            {
                "id": f"gid://shopify/LineItem/{uuid.uuid4().hex[:12]}",
                "product_id": f"gid://shopify/Product/{uuid.uuid4().hex[:12]}",
                "variant_id": f"gid://shopify/ProductVariant/{uuid.uuid4().hex[:12]}",
                "title": "Test Product",
                "quantity": 1,
                "price": str(total_price),
            }
        ],
        "shipping_address": {
            "country_code": "US",
            "province_code": "CA",
        },
        "refunds": refunds or [],
    }


def create_customer(
    customer_id: Optional[str] = None,
    email: Optional[str] = None,
    orders_count: int = 1,
    total_spent: float = 99.99,
) -> Dict:
    """Create a single customer record."""
    customer_id = customer_id or f"gid://shopify/Customer/{uuid.uuid4().hex[:12]}"

    return {
        "id": customer_id,
        "email": email or f"customer-{uuid.uuid4().hex[:8]}@example.com",
        "first_name": "Test",
        "last_name": "Customer",
        "orders_count": orders_count,
        "total_spent": str(total_spent),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "verified_email": True,
        "accepts_marketing": True,
    }


# =============================================================================
# Predefined Test Data Sets
# =============================================================================

# Base date for consistent test data
BASE_DATE = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


TEST_DATA_SETS: Dict[str, Dict[str, List[Dict]]] = {
    # =========================================================================
    # Scenario: New Merchant Initial Sync
    # Small data set for quick onboarding tests
    # =========================================================================
    "new_merchant_initial": {
        "_airbyte_raw_shopify_orders": [
            create_order(
                order_id="gid://shopify/Order/1001",
                order_number=1001,
                total_price=99.99,
                created_at=(BASE_DATE).isoformat(),
                customer_email="john.doe@example.com",
            ),
            create_order(
                order_id="gid://shopify/Order/1002",
                order_number=1002,
                total_price=149.99,
                created_at=(BASE_DATE + timedelta(hours=2)).isoformat(),
                customer_email="jane.smith@example.com",
            ),
            create_order(
                order_id="gid://shopify/Order/1003",
                order_number=1003,
                total_price=75.50,
                created_at=(BASE_DATE + timedelta(hours=5)).isoformat(),
                customer_email="bob.wilson@example.com",
            ),
        ],
        "_airbyte_raw_shopify_customers": [
            create_customer(
                customer_id="gid://shopify/Customer/2001",
                email="john.doe@example.com",
                orders_count=1,
                total_spent=99.99,
            ),
            create_customer(
                customer_id="gid://shopify/Customer/2002",
                email="jane.smith@example.com",
                orders_count=1,
                total_spent=149.99,
            ),
            create_customer(
                customer_id="gid://shopify/Customer/2003",
                email="bob.wilson@example.com",
                orders_count=1,
                total_spent=75.50,
            ),
        ],
    },

    # =========================================================================
    # Scenario: Revenue with Refunds and Cancellations
    # Tests revenue calculation edge cases
    # Expected: Gross=575, Refunds=75, Cancellations=50, Net=450
    # =========================================================================
    "revenue_scenario_complex": {
        "_airbyte_raw_shopify_orders": [
            # Regular paid order
            create_order(
                order_id="gid://shopify/Order/R001",
                total_price=100.00,
                financial_status="paid",
                created_at=(BASE_DATE).isoformat(),
            ),
            # Another regular order
            create_order(
                order_id="gid://shopify/Order/R002",
                total_price=150.00,
                financial_status="paid",
                created_at=(BASE_DATE + timedelta(hours=1)).isoformat(),
            ),
            # Large order
            create_order(
                order_id="gid://shopify/Order/R003",
                total_price=200.00,
                financial_status="paid",
                created_at=(BASE_DATE + timedelta(days=1)).isoformat(),
            ),
            # Fully refunded order
            create_order(
                order_id="gid://shopify/Order/R004",
                total_price=75.00,
                financial_status="refunded",
                created_at=(BASE_DATE + timedelta(days=1, hours=1)).isoformat(),
                refunds=[{"id": "refund-1", "amount": "75.00", "created_at": (BASE_DATE + timedelta(days=2)).isoformat()}],
            ),
            # Cancelled order
            create_order(
                order_id="gid://shopify/Order/R005",
                total_price=50.00,
                financial_status="paid",
                created_at=(BASE_DATE + timedelta(days=2)).isoformat(),
                cancelled_at=(BASE_DATE + timedelta(days=2, hours=1)).isoformat(),
            ),
        ],
        "_airbyte_raw_shopify_customers": [
            create_customer(email="revenue-test-1@example.com"),
            create_customer(email="revenue-test-2@example.com"),
        ],
    },

    # =========================================================================
    # Scenario: Declining Revenue Pattern
    # For testing revenue anomaly detection in AI insights
    # Week 1: ~$700/day, Week 2: ~$500/day (28% decline)
    # =========================================================================
    "declining_revenue_pattern": {
        "_airbyte_raw_shopify_orders": [
            # Week 1 - Higher revenue (7 orders/day, ~$100 each)
            *[
                create_order(
                    order_id=f"gid://shopify/Order/D1{day:02d}{i}",
                    total_price=95.00 + (i * 5),
                    created_at=(BASE_DATE + timedelta(days=day, hours=i*3)).isoformat(),
                )
                for day in range(7)
                for i in range(7)
            ],
            # Week 2 - Lower revenue (5 orders/day, ~$100 each)
            *[
                create_order(
                    order_id=f"gid://shopify/Order/D2{day:02d}{i}",
                    total_price=90.00 + (i * 5),
                    created_at=(BASE_DATE + timedelta(days=7+day, hours=i*4)).isoformat(),
                )
                for day in range(7)
                for i in range(5)
            ],
        ],
        "_airbyte_raw_shopify_customers": [],
    },

    # =========================================================================
    # Scenario: Multi-Currency Orders
    # Tests currency handling in revenue calculations
    # =========================================================================
    "multi_currency": {
        "_airbyte_raw_shopify_orders": [
            create_order(
                order_id="gid://shopify/Order/MC001",
                total_price=100.00,
                currency="USD",
                created_at=BASE_DATE.isoformat(),
            ),
            create_order(
                order_id="gid://shopify/Order/MC002",
                total_price=85.00,
                currency="EUR",
                created_at=(BASE_DATE + timedelta(hours=1)).isoformat(),
            ),
            create_order(
                order_id="gid://shopify/Order/MC003",
                total_price=12000.00,
                currency="JPY",
                created_at=(BASE_DATE + timedelta(hours=2)).isoformat(),
            ),
            create_order(
                order_id="gid://shopify/Order/MC004",
                total_price=130.00,
                currency="CAD",
                created_at=(BASE_DATE + timedelta(hours=3)).isoformat(),
            ),
        ],
        "_airbyte_raw_shopify_customers": [],
    },

    # =========================================================================
    # Scenario: Edge Cases
    # Tests handling of unusual data
    # =========================================================================
    "edge_cases": {
        "_airbyte_raw_shopify_orders": [
            # Zero value order
            create_order(
                order_id="gid://shopify/Order/EC001",
                total_price=0.00,
                financial_status="paid",
                created_at=BASE_DATE.isoformat(),
            ),
            # Very high value order
            create_order(
                order_id="gid://shopify/Order/EC002",
                total_price=99999.99,
                financial_status="paid",
                created_at=(BASE_DATE + timedelta(hours=1)).isoformat(),
            ),
            # Order with very long decimal
            create_order(
                order_id="gid://shopify/Order/EC003",
                total_price=123.456789,  # Will be truncated
                financial_status="paid",
                created_at=(BASE_DATE + timedelta(hours=2)).isoformat(),
            ),
            # Pending order (not yet paid)
            create_order(
                order_id="gid://shopify/Order/EC004",
                total_price=50.00,
                financial_status="pending",
                fulfillment_status=None,
                created_at=(BASE_DATE + timedelta(hours=3)).isoformat(),
            ),
            # Partially refunded order
            create_order(
                order_id="gid://shopify/Order/EC005",
                total_price=100.00,
                financial_status="partially_refunded",
                refunds=[{"id": "refund-partial", "amount": "25.00"}],
                created_at=(BASE_DATE + timedelta(hours=4)).isoformat(),
            ),
        ],
        "_airbyte_raw_shopify_customers": [],
    },

    # =========================================================================
    # Scenario: High Volume
    # Large data set for performance testing
    # =========================================================================
    "high_volume": {
        "_airbyte_raw_shopify_orders": [
            create_order(
                order_id=f"gid://shopify/Order/HV{i:05d}",
                total_price=50.00 + (i % 150),  # $50-$200 range
                created_at=(BASE_DATE + timedelta(minutes=i*5)).isoformat(),
            )
            for i in range(500)  # 500 orders
        ],
        "_airbyte_raw_shopify_customers": [
            create_customer(
                customer_id=f"gid://shopify/Customer/HVC{i:05d}",
                email=f"volume-test-{i}@example.com",
                orders_count=(i % 5) + 1,
            )
            for i in range(100)  # 100 customers
        ],
    },

    # =========================================================================
    # Scenario: Empty Data
    # Tests handling of new stores with no data
    # =========================================================================
    "empty_store": {
        "_airbyte_raw_shopify_orders": [],
        "_airbyte_raw_shopify_customers": [],
    },
}


# =============================================================================
# Expected Outcomes for Test Validation
# =============================================================================

EXPECTED_OUTCOMES: Dict[str, Dict[str, Any]] = {
    "new_merchant_initial": {
        "order_count": 3,
        "customer_count": 3,
        "total_gross_revenue": 325.48,  # 99.99 + 149.99 + 75.50
    },
    "revenue_scenario_complex": {
        "order_count": 5,
        "gross_revenue": 575.00,
        "refunds": 75.00,
        "cancellations": 50.00,
        "net_revenue": 450.00,
    },
    "declining_revenue_pattern": {
        "week1_orders": 49,
        "week2_orders": 35,
        "expected_decline_percent": 28.57,  # Approximate
    },
    "empty_store": {
        "order_count": 0,
        "customer_count": 0,
        "total_gross_revenue": 0.0,
    },
}
