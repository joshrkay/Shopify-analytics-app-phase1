"""
Shopify Billing API client for subscription management.

Uses Shopify GraphQL Admin API for recurring app charges.
All public Shopify apps MUST use Shopify Billing API for payments.

Documentation: https://shopify.dev/docs/apps/billing
"""

import os
import logging
from typing import Optional, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import httpx

logger = logging.getLogger(__name__)

# Shopify API version - use stable version
SHOPIFY_API_VERSION = "2024-01"


class BillingInterval(str, Enum):
    """Billing interval for recurring charges."""
    EVERY_30_DAYS = "EVERY_30_DAYS"
    ANNUAL = "ANNUAL"


class SubscriptionLineItemType(str, Enum):
    """Type of subscription line item."""
    RECURRING = "RECURRING"
    USAGE = "USAGE"


@dataclass
class ShopifySubscription:
    """Represents a Shopify AppSubscription from the API."""
    id: str  # GraphQL GID
    name: str
    status: str
    created_at: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    trial_days: int = 0
    test: bool = False
    line_items: list = None

    def __post_init__(self):
        if self.line_items is None:
            self.line_items = []


@dataclass
class CreateSubscriptionResult:
    """Result of creating a subscription."""
    confirmation_url: str
    app_subscription: Optional[ShopifySubscription] = None
    user_errors: list = None

    def __post_init__(self):
        if self.user_errors is None:
            self.user_errors = []

    @property
    def success(self) -> bool:
        return bool(self.confirmation_url) and not self.user_errors


class ShopifyBillingError(Exception):
    """Base exception for Shopify Billing API errors."""
    pass


class ShopifyAPIError(ShopifyBillingError):
    """Error communicating with Shopify API."""
    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class ShopifyBillingClient:
    """
    Client for Shopify Billing API operations.

    Handles:
    - Creating recurring app subscriptions
    - Querying subscription status
    - Cancelling subscriptions
    - Usage-based billing (if needed)

    SECURITY: Access token must be encrypted at rest and decrypted only when needed.
    """

    def __init__(self, shop_domain: str, access_token: str):
        """
        Initialize billing client for a specific shop.

        Args:
            shop_domain: Shopify store domain (e.g., 'mystore.myshopify.com')
            access_token: Decrypted Shopify access token
        """
        if not shop_domain:
            raise ValueError("shop_domain is required")
        if not access_token:
            raise ValueError("access_token is required")

        self.shop_domain = shop_domain.replace("https://", "").replace("http://", "").rstrip("/")
        self.access_token = access_token
        self.api_version = SHOPIFY_API_VERSION
        self.graphql_url = f"https://{self.shop_domain}/admin/api/{self.api_version}/graphql.json"

        # HTTP client with appropriate timeouts
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": self.access_token
            }
        )

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _execute_graphql(self, query: str, variables: Optional[dict] = None) -> dict:
        """
        Execute a GraphQL query against Shopify Admin API.

        Args:
            query: GraphQL query or mutation
            variables: Optional query variables

        Returns:
            GraphQL response data

        Raises:
            ShopifyAPIError: If the API call fails
        """
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = await self._client.post(self.graphql_url, json=payload)

            if response.status_code == 401:
                logger.error("Shopify API authentication failed", extra={
                    "shop_domain": self.shop_domain,
                    "status_code": response.status_code
                })
                raise ShopifyAPIError(
                    "Authentication failed - access token may be invalid or expired",
                    status_code=401
                )

            if response.status_code == 402:
                logger.error("Shopify store frozen or payment required", extra={
                    "shop_domain": self.shop_domain
                })
                raise ShopifyAPIError(
                    "Store is frozen or payment required",
                    status_code=402
                )

            if response.status_code == 429:
                logger.warning("Shopify API rate limited", extra={
                    "shop_domain": self.shop_domain
                })
                raise ShopifyAPIError(
                    "Rate limited - please retry after a delay",
                    status_code=429
                )

            if response.status_code >= 400:
                logger.error("Shopify API error", extra={
                    "shop_domain": self.shop_domain,
                    "status_code": response.status_code,
                    "response_text": response.text[:500]
                })
                raise ShopifyAPIError(
                    f"Shopify API error: {response.status_code}",
                    status_code=response.status_code,
                    response=response.json() if response.text else None
                )

            result = response.json()

            # Check for GraphQL errors
            if "errors" in result:
                logger.error("GraphQL errors", extra={
                    "shop_domain": self.shop_domain,
                    "errors": result["errors"]
                })
                raise ShopifyAPIError(
                    f"GraphQL errors: {result['errors']}",
                    response=result
                )

            return result.get("data", {})

        except httpx.TimeoutException as e:
            logger.error("Shopify API timeout", extra={
                "shop_domain": self.shop_domain,
                "error": str(e)
            })
            raise ShopifyAPIError(f"Request timeout: {e}")
        except httpx.RequestError as e:
            logger.error("Shopify API request error", extra={
                "shop_domain": self.shop_domain,
                "error": str(e)
            })
            raise ShopifyAPIError(f"Request error: {e}")

    async def create_subscription(
        self,
        name: str,
        price_amount: float,
        currency_code: str = "USD",
        interval: BillingInterval = BillingInterval.EVERY_30_DAYS,
        return_url: str = None,
        trial_days: int = 0,
        test: bool = False,
        replacement_behavior: str = "APPLY_IMMEDIATELY"
    ) -> CreateSubscriptionResult:
        """
        Create a new recurring app subscription.

        This creates a charge that the merchant must approve in Shopify admin.
        After approval, the subscription becomes active.

        Args:
            name: Subscription name (displayed to merchant)
            price_amount: Price in currency units (e.g., 9.99)
            currency_code: ISO 4217 currency code (default: USD)
            interval: Billing interval (EVERY_30_DAYS or ANNUAL)
            return_url: URL to redirect merchant after approval/decline
            trial_days: Number of trial days (0 for no trial)
            test: Whether this is a test charge (won't charge real money)
            replacement_behavior: How to handle existing subscriptions

        Returns:
            CreateSubscriptionResult with confirmation_url for merchant redirect

        Raises:
            ShopifyAPIError: If the API call fails
        """
        if not return_url:
            return_url = os.getenv("SHOPIFY_BILLING_RETURN_URL", f"https://{self.shop_domain}/admin/apps")

        mutation = """
        mutation appSubscriptionCreate($name: String!, $returnUrl: URL!, $lineItems: [AppSubscriptionLineItemInput!]!, $trialDays: Int, $test: Boolean, $replacementBehavior: AppSubscriptionReplacementBehavior) {
            appSubscriptionCreate(
                name: $name
                returnUrl: $returnUrl
                lineItems: $lineItems
                trialDays: $trialDays
                test: $test
                replacementBehavior: $replacementBehavior
            ) {
                appSubscription {
                    id
                    name
                    status
                    createdAt
                    currentPeriodEnd
                    trialDays
                    test
                    lineItems(first: 10) {
                        edges {
                            node {
                                id
                                plan {
                                    pricingDetails {
                                        ... on AppRecurringPricing {
                                            price {
                                                amount
                                                currencyCode
                                            }
                                            interval
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                confirmationUrl
                userErrors {
                    field
                    message
                }
            }
        }
        """

        variables = {
            "name": name,
            "returnUrl": return_url,
            "lineItems": [
                {
                    "plan": {
                        "appRecurringPricingDetails": {
                            "price": {
                                "amount": price_amount,
                                "currencyCode": currency_code
                            },
                            "interval": interval.value
                        }
                    }
                }
            ],
            "trialDays": trial_days,
            "test": test,
            "replacementBehavior": replacement_behavior
        }

        logger.info("Creating Shopify subscription", extra={
            "shop_domain": self.shop_domain,
            "name": name,
            "price_amount": price_amount,
            "interval": interval.value,
            "trial_days": trial_days,
            "test": test
        })

        data = await self._execute_graphql(mutation, variables)
        result = data.get("appSubscriptionCreate", {})

        user_errors = result.get("userErrors", [])
        if user_errors:
            logger.warning("Subscription creation had user errors", extra={
                "shop_domain": self.shop_domain,
                "user_errors": user_errors
            })

        app_subscription = None
        if result.get("appSubscription"):
            sub_data = result["appSubscription"]
            app_subscription = ShopifySubscription(
                id=sub_data["id"],
                name=sub_data["name"],
                status=sub_data["status"],
                created_at=datetime.fromisoformat(sub_data["createdAt"].replace("Z", "+00:00")) if sub_data.get("createdAt") else None,
                current_period_end=datetime.fromisoformat(sub_data["currentPeriodEnd"].replace("Z", "+00:00")) if sub_data.get("currentPeriodEnd") else None,
                trial_days=sub_data.get("trialDays", 0),
                test=sub_data.get("test", False)
            )

        return CreateSubscriptionResult(
            confirmation_url=result.get("confirmationUrl", ""),
            app_subscription=app_subscription,
            user_errors=user_errors
        )

    async def get_subscription(self, subscription_gid: str) -> Optional[ShopifySubscription]:
        """
        Get subscription details by GraphQL ID.

        Args:
            subscription_gid: Shopify GraphQL ID (e.g., 'gid://shopify/AppSubscription/12345')

        Returns:
            ShopifySubscription if found, None otherwise
        """
        query = """
        query getSubscription($id: ID!) {
            node(id: $id) {
                ... on AppSubscription {
                    id
                    name
                    status
                    createdAt
                    currentPeriodEnd
                    trialDays
                    test
                    lineItems(first: 10) {
                        edges {
                            node {
                                id
                                plan {
                                    pricingDetails {
                                        ... on AppRecurringPricing {
                                            price {
                                                amount
                                                currencyCode
                                            }
                                            interval
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        data = await self._execute_graphql(query, {"id": subscription_gid})
        node = data.get("node")

        if not node or node.get("__typename") != "AppSubscription":
            return None

        return ShopifySubscription(
            id=node["id"],
            name=node["name"],
            status=node["status"],
            created_at=datetime.fromisoformat(node["createdAt"].replace("Z", "+00:00")) if node.get("createdAt") else None,
            current_period_end=datetime.fromisoformat(node["currentPeriodEnd"].replace("Z", "+00:00")) if node.get("currentPeriodEnd") else None,
            trial_days=node.get("trialDays", 0),
            test=node.get("test", False)
        )

    async def get_active_subscriptions(self) -> list[ShopifySubscription]:
        """
        Get all active subscriptions for the current app.

        Returns:
            List of active ShopifySubscription objects
        """
        query = """
        query getActiveSubscriptions {
            currentAppInstallation {
                activeSubscriptions {
                    id
                    name
                    status
                    createdAt
                    currentPeriodEnd
                    trialDays
                    test
                    lineItems(first: 10) {
                        edges {
                            node {
                                id
                                plan {
                                    pricingDetails {
                                        ... on AppRecurringPricing {
                                            price {
                                                amount
                                                currencyCode
                                            }
                                            interval
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """

        data = await self._execute_graphql(query)
        subscriptions_data = data.get("currentAppInstallation", {}).get("activeSubscriptions", [])

        subscriptions = []
        for sub_data in subscriptions_data:
            subscriptions.append(ShopifySubscription(
                id=sub_data["id"],
                name=sub_data["name"],
                status=sub_data["status"],
                created_at=datetime.fromisoformat(sub_data["createdAt"].replace("Z", "+00:00")) if sub_data.get("createdAt") else None,
                current_period_end=datetime.fromisoformat(sub_data["currentPeriodEnd"].replace("Z", "+00:00")) if sub_data.get("currentPeriodEnd") else None,
                trial_days=sub_data.get("trialDays", 0),
                test=sub_data.get("test", False)
            ))

        return subscriptions

    async def cancel_subscription(self, subscription_gid: str) -> bool:
        """
        Cancel an app subscription.

        Args:
            subscription_gid: Shopify GraphQL ID of the subscription

        Returns:
            True if cancelled successfully, False otherwise
        """
        mutation = """
        mutation appSubscriptionCancel($id: ID!) {
            appSubscriptionCancel(id: $id) {
                appSubscription {
                    id
                    status
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        logger.info("Cancelling Shopify subscription", extra={
            "shop_domain": self.shop_domain,
            "subscription_gid": subscription_gid
        })

        data = await self._execute_graphql(mutation, {"id": subscription_gid})
        result = data.get("appSubscriptionCancel", {})

        user_errors = result.get("userErrors", [])
        if user_errors:
            logger.warning("Subscription cancellation had user errors", extra={
                "shop_domain": self.shop_domain,
                "subscription_gid": subscription_gid,
                "user_errors": user_errors
            })
            return False

        app_subscription = result.get("appSubscription")
        if app_subscription and app_subscription.get("status") == "CANCELLED":
            logger.info("Subscription cancelled successfully", extra={
                "shop_domain": self.shop_domain,
                "subscription_gid": subscription_gid
            })
            return True

        return False


def get_billing_client(shop_domain: str, access_token: str) -> ShopifyBillingClient:
    """
    Factory function to create a ShopifyBillingClient.

    Args:
        shop_domain: Shopify store domain
        access_token: Decrypted access token

    Returns:
        Configured ShopifyBillingClient instance
    """
    return ShopifyBillingClient(shop_domain, access_token)
