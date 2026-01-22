"""
Mock Shopify Billing Client for testing.

Provides deterministic responses without making real Shopify API calls.
Supports configuring mock state for different test scenarios.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from dataclasses import dataclass, field


@dataclass
class MockShopifySubscription:
    """Mock subscription data."""
    id: str
    name: str
    status: str
    created_at: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    trial_days: int = 0
    test: bool = True


@dataclass
class MockCreateSubscriptionResult:
    """Mock result from create_subscription."""
    confirmation_url: str
    app_subscription: Optional[MockShopifySubscription] = None
    user_errors: List[Dict] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.user_errors) == 0


class MockShopifyBillingClient:
    """
    Mock Shopify Billing Client for testing.

    Features:
    - Deterministic responses (no network calls)
    - Configurable subscription state
    - Supports all billing client methods
    - Can simulate errors and edge cases
    """

    def __init__(self):
        """Initialize mock client with empty state."""
        self._subscriptions: Dict[str, MockShopifySubscription] = {}
        self._next_subscription_num = 1
        self._should_fail = False
        self._fail_message = ""
        self._confirmation_url_base = "https://test-store.myshopify.com/admin/charges"

    def reset(self):
        """Reset all mock state."""
        self._subscriptions.clear()
        self._next_subscription_num = 1
        self._should_fail = False
        self._fail_message = ""

    def configure_failure(self, message: str = "Mock API failure"):
        """Configure the mock to fail on next call."""
        self._should_fail = True
        self._fail_message = message

    def set_subscription_status(self, subscription_gid: str, status: str):
        """
        Set the status of a subscription in mock state.

        Use this to simulate Shopify state changes for reconciliation tests.

        Args:
            subscription_gid: The subscription GraphQL ID
            status: New status (ACTIVE, CANCELLED, FROZEN, etc.)
        """
        if subscription_gid in self._subscriptions:
            self._subscriptions[subscription_gid].status = status

    def add_subscription(
        self,
        subscription_gid: str,
        name: str = "Test Subscription",
        status: str = "ACTIVE",
        current_period_end: Optional[datetime] = None
    ) -> MockShopifySubscription:
        """
        Add a subscription to mock state.

        Use this to pre-populate subscriptions for testing.
        """
        if current_period_end is None:
            current_period_end = datetime.now(timezone.utc) + timedelta(days=30)

        subscription = MockShopifySubscription(
            id=subscription_gid,
            name=name,
            status=status,
            created_at=datetime.now(timezone.utc),
            current_period_end=current_period_end,
            test=True
        )
        self._subscriptions[subscription_gid] = subscription
        return subscription

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        pass

    async def close(self):
        """Close the mock client (no-op)."""
        pass

    async def create_subscription(
        self,
        name: str,
        price_amount: float,
        currency_code: str = "USD",
        interval: str = "EVERY_30_DAYS",
        return_url: str = None,
        trial_days: int = 0,
        test: bool = True,
        replacement_behavior: str = "APPLY_IMMEDIATELY"
    ) -> MockCreateSubscriptionResult:
        """
        Mock creating a subscription.

        Returns a deterministic result with a mock confirmation URL.
        """
        if self._should_fail:
            self._should_fail = False  # Reset for next call
            return MockCreateSubscriptionResult(
                confirmation_url="",
                app_subscription=None,
                user_errors=[{"field": "base", "message": self._fail_message}]
            )

        # Generate subscription ID
        subscription_gid = f"gid://shopify/AppSubscription/mock_{self._next_subscription_num}"
        self._next_subscription_num += 1

        # Create mock subscription
        subscription = MockShopifySubscription(
            id=subscription_gid,
            name=name,
            status="PENDING",
            created_at=datetime.now(timezone.utc),
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
            trial_days=trial_days,
            test=test
        )

        # Store in mock state
        self._subscriptions[subscription_gid] = subscription

        # Generate confirmation URL
        confirmation_url = f"{self._confirmation_url_base}/{self._next_subscription_num - 1}/confirm"

        return MockCreateSubscriptionResult(
            confirmation_url=confirmation_url,
            app_subscription=subscription,
            user_errors=[]
        )

    async def get_subscription(self, subscription_gid: str) -> Optional[MockShopifySubscription]:
        """
        Get a subscription by GraphQL ID.

        Returns from mock state, or None if not found.
        """
        if self._should_fail:
            self._should_fail = False
            from src.integrations.shopify.billing_client import ShopifyAPIError
            raise ShopifyAPIError(self._fail_message, status_code=500)

        return self._subscriptions.get(subscription_gid)

    async def get_active_subscriptions(self) -> List[MockShopifySubscription]:
        """
        Get all active subscriptions.

        Returns subscriptions from mock state with ACTIVE status.
        """
        if self._should_fail:
            self._should_fail = False
            from src.integrations.shopify.billing_client import ShopifyAPIError
            raise ShopifyAPIError(self._fail_message, status_code=500)

        return [
            sub for sub in self._subscriptions.values()
            if sub.status == "ACTIVE"
        ]

    async def cancel_subscription(self, subscription_gid: str) -> bool:
        """
        Cancel a subscription.

        Updates mock state to CANCELLED status.
        """
        if self._should_fail:
            self._should_fail = False
            return False

        if subscription_gid in self._subscriptions:
            self._subscriptions[subscription_gid].status = "CANCELLED"
            return True

        return False
