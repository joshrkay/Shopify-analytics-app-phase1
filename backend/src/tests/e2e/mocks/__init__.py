"""
Mock service implementations for E2E testing.

Provides mock servers for:
- Shopify API (OAuth, Admin API, Webhooks)
- Airbyte Cloud API (sync orchestration)
- OpenRouter API (LLM responses)
- Clerk API (authentication)
"""

from .mock_shopify import MockShopifyServer, ShopifyWebhookSimulator
from .mock_airbyte import MockAirbyteServer
from .mock_openrouter import MockOpenRouterServer
from .mock_clerk import MockClerkServer, MockFronteggServer  # MockFronteggServer is alias for backwards compat

__all__ = [
    "MockShopifyServer",
    "ShopifyWebhookSimulator",
    "MockAirbyteServer",
    "MockOpenRouterServer",
    "MockClerkServer",
    "MockFronteggServer",  # Backwards compatibility alias
]
