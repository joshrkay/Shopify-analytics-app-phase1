"""
Mock Shopify API server for E2E testing.

Simulates:
- OAuth token exchange
- Admin API endpoints (orders, customers, products)
- GraphQL API
- Webhook delivery with HMAC signing
"""

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import httpx


class MockShopifyServer:
    """
    Mock Shopify Admin API server.

    Usage:
        mock = MockShopifyServer(api_secret="test-secret")
        mock.setup_oauth_response(shop="test.myshopify.com", access_token="shpat_xxx")
        mock.setup_orders_response(orders=[...])
    """

    def __init__(self, api_secret: str = "test-webhook-secret"):
        self.api_secret = api_secret
        self._oauth_responses: Dict[str, Dict] = {}
        self._shop_responses: Dict[str, Dict] = {}
        self._orders_responses: Dict[str, List[Dict]] = {}
        self._customers_responses: Dict[str, List[Dict]] = {}
        self._products_responses: Dict[str, List[Dict]] = {}
        self._graphql_responses: Dict[str, Dict] = {}
        self._billing_responses: Dict[str, Dict] = {}
        self._product_update_responses: Dict[str, Dict] = {}

    def setup_oauth_response(
        self,
        shop: str,
        access_token: str,
        scope: str = "read_products,write_products,read_orders,read_customers"
    ) -> None:
        """Configure OAuth token exchange response for a shop."""
        self._oauth_responses[shop] = {
            "access_token": access_token,
            "scope": scope,
        }

    def setup_shop_response(self, shop: str, shop_data: Dict) -> None:
        """Configure shop info response."""
        self._shop_responses[shop] = {
            "shop": {
                "id": shop_data.get("id", 12345678),
                "name": shop_data.get("name", "Test Store"),
                "email": shop_data.get("email", "owner@example.com"),
                "domain": shop,
                "currency": shop_data.get("currency", "USD"),
                "timezone": shop_data.get("timezone", "America/New_York"),
                "plan_name": shop_data.get("plan_name", "basic"),
                **shop_data,
            }
        }

    def setup_orders_response(self, shop: str, orders: List[Dict]) -> None:
        """Configure orders API response."""
        self._orders_responses[shop] = orders

    def setup_customers_response(self, shop: str, customers: List[Dict]) -> None:
        """Configure customers API response."""
        self._customers_responses[shop] = customers

    def setup_products_response(self, shop: str, products: List[Dict]) -> None:
        """Configure products API response."""
        self._products_responses[shop] = products

    def setup_graphql_response(self, shop: str, query_hash: str, response: Dict) -> None:
        """Configure GraphQL query response."""
        key = f"{shop}:{query_hash}"
        self._graphql_responses[key] = response

    def setup_billing_response(self, shop: str, response: Dict) -> None:
        """Configure billing API response."""
        self._billing_responses[shop] = response

    def setup_product_update_response(
        self,
        product_id: str,
        success: bool = True,
        updated_product: Optional[Dict] = None
    ) -> None:
        """Configure product update response."""
        self._product_update_responses[product_id] = {
            "success": success,
            "product": updated_product or {"id": product_id, "title": "Updated Product"},
        }

    # Response handlers (called by test HTTP client interceptor)

    def handle_oauth_token(self, shop: str, code: str) -> Dict:
        """Handle POST /admin/oauth/access_token"""
        if shop in self._oauth_responses:
            return self._oauth_responses[shop]
        raise ValueError(f"No OAuth response configured for shop: {shop}")

    def handle_shop_info(self, shop: str) -> Dict:
        """Handle GET /admin/api/2024-01/shop.json"""
        if shop in self._shop_responses:
            return self._shop_responses[shop]
        # Return default shop info
        return {
            "shop": {
                "id": 12345678,
                "name": "Test Store",
                "domain": shop,
                "currency": "USD",
            }
        }

    def handle_orders(self, shop: str, params: Dict) -> Dict:
        """Handle GET /admin/api/2024-01/orders.json"""
        orders = self._orders_responses.get(shop, [])
        return {"orders": orders}

    def handle_customers(self, shop: str, params: Dict) -> Dict:
        """Handle GET /admin/api/2024-01/customers.json"""
        customers = self._customers_responses.get(shop, [])
        return {"customers": customers}

    def handle_graphql(self, shop: str, query: str, variables: Dict) -> Dict:
        """Handle POST /admin/api/2024-01/graphql.json"""
        # Try to find a matching configured response
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        key = f"{shop}:{query_hash}"

        if key in self._graphql_responses:
            return self._graphql_responses[key]

        # Return empty data by default
        return {"data": {}, "extensions": {}}

    def handle_product_update(self, shop: str, product_id: str, data: Dict) -> Dict:
        """Handle PUT /admin/api/2024-01/products/{id}.json"""
        if product_id in self._product_update_responses:
            response = self._product_update_responses[product_id]
            if response["success"]:
                return {"product": response["product"]}
            raise ValueError(f"Product update failed: {product_id}")

        return {"product": {"id": product_id, **data}}

    def get_mock_transport(self) -> httpx.MockTransport:
        """
        Create an httpx MockTransport that routes requests to this mock server.

        Usage:
            client = httpx.AsyncClient(transport=mock.get_mock_transport())
        """
        def handle_request(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            shop = request.url.host.replace(".myshopify.com", "") + ".myshopify.com"

            try:
                if "oauth/access_token" in path:
                    data = json.loads(request.content)
                    result = self.handle_oauth_token(shop, data.get("code", ""))
                elif path.endswith("/shop.json"):
                    result = self.handle_shop_info(shop)
                elif path.endswith("/orders.json"):
                    params = dict(request.url.params)
                    result = self.handle_orders(shop, params)
                elif path.endswith("/customers.json"):
                    params = dict(request.url.params)
                    result = self.handle_customers(shop, params)
                elif "/graphql" in path:
                    data = json.loads(request.content)
                    result = self.handle_graphql(
                        shop,
                        data.get("query", ""),
                        data.get("variables", {})
                    )
                elif "/products/" in path and request.method == "PUT":
                    product_id = path.split("/products/")[1].split(".")[0]
                    data = json.loads(request.content)
                    result = self.handle_product_update(shop, product_id, data.get("product", {}))
                else:
                    return httpx.Response(404, json={"error": "Not found"})

                return httpx.Response(200, json=result)

            except Exception as e:
                return httpx.Response(500, json={"error": str(e)})

        return httpx.MockTransport(handle_request)


class ShopifyWebhookSimulator:
    """
    Simulates Shopify webhook delivery with proper HMAC signing.

    Usage:
        simulator = ShopifyWebhookSimulator(
            api_secret="test-secret",
            base_url="http://localhost:8000"
        )
        response = simulator.send_webhook(
            topic="orders/create",
            payload=order_data,
            shop_domain="test.myshopify.com"
        )
    """

    def __init__(self, api_secret: str, base_url: str):
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")

    def compute_hmac(self, body: bytes) -> str:
        """Compute Shopify HMAC-SHA256 signature."""
        digest = hmac.new(
            self.api_secret.encode("utf-8"),
            body,
            hashlib.sha256
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def send_webhook(
        self,
        topic: str,
        payload: Dict[str, Any],
        shop_domain: str,
        webhook_id: Optional[str] = None,
    ) -> httpx.Response:
        """
        Send a signed webhook to the application.

        Args:
            topic: Shopify webhook topic (e.g., "orders/create", "app/uninstalled")
            payload: Webhook payload data
            shop_domain: Shop domain (e.g., "test.myshopify.com")
            webhook_id: Optional webhook ID for idempotency

        Returns:
            HTTP response from the application
        """
        body = json.dumps(payload).encode("utf-8")
        hmac_signature = self.compute_hmac(body)

        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Topic": topic,
            "X-Shopify-Hmac-Sha256": hmac_signature,
            "X-Shopify-Shop-Domain": shop_domain,
            "X-Shopify-Webhook-Id": webhook_id or str(uuid.uuid4()),
            "X-Shopify-Api-Version": "2024-01",
        }

        with httpx.Client() as client:
            return client.post(
                f"{self.base_url}/api/webhooks/shopify",
                content=body,
                headers=headers,
            )

    async def send_webhook_async(
        self,
        topic: str,
        payload: Dict[str, Any],
        shop_domain: str,
        webhook_id: Optional[str] = None,
    ) -> httpx.Response:
        """Async version of send_webhook."""
        body = json.dumps(payload).encode("utf-8")
        hmac_signature = self.compute_hmac(body)

        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Topic": topic,
            "X-Shopify-Hmac-Sha256": hmac_signature,
            "X-Shopify-Shop-Domain": shop_domain,
            "X-Shopify-Webhook-Id": webhook_id or str(uuid.uuid4()),
            "X-Shopify-Api-Version": "2024-01",
        }

        async with httpx.AsyncClient() as client:
            return await client.post(
                f"{self.base_url}/api/webhooks/shopify",
                content=body,
                headers=headers,
            )

    # Convenience methods for common webhook types

    def send_order_create(self, order: Dict, shop_domain: str) -> httpx.Response:
        """Send orders/create webhook."""
        return self.send_webhook("orders/create", order, shop_domain)

    def send_order_updated(self, order: Dict, shop_domain: str) -> httpx.Response:
        """Send orders/updated webhook."""
        return self.send_webhook("orders/updated", order, shop_domain)

    def send_app_uninstalled(self, shop_domain: str) -> httpx.Response:
        """Send app/uninstalled webhook."""
        return self.send_webhook(
            "app/uninstalled",
            {"shop_domain": shop_domain},
            shop_domain
        )

    def send_subscription_update(
        self,
        subscription: Dict,
        shop_domain: str
    ) -> httpx.Response:
        """Send app_subscriptions/update webhook."""
        return self.send_webhook(
            "app_subscriptions/update",
            {"app_subscription": subscription},
            shop_domain
        )
