"""
Unit tests for ShopifyBillingClient retry and rate limiting.

Tests cover:
- Exponential backoff retry
- Rate limit handling with Retry-After header
- Timeout handling
- Error classification
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

from src.integrations.shopify.billing_client import (
    ShopifyBillingClient,
    ShopifyAPIError,
    RetryConfig,
    BillingInterval,
    CreateSubscriptionResult,
    ShopifySubscription
)


@pytest.fixture
def billing_client():
    """Create a billing client for testing."""
    return ShopifyBillingClient(
        shop_domain="test-store.myshopify.com",
        access_token="test-token"
    )


@pytest.fixture
def retry_config():
    """Create a retry config for testing."""
    return RetryConfig(
        max_retries=3,
        initial_delay=0.1,
        max_delay=1.0,
        backoff_multiplier=2.0
    )


class TestRetryConfig:
    """Tests for RetryConfig dataclass."""

    def test_default_values(self):
        """Test default retry config values."""
        config = RetryConfig()

        assert config.max_retries == 3
        assert config.initial_delay == 1.0
        assert config.max_delay == 30.0
        assert config.backoff_multiplier == 2.0
        assert 429 in config.retryable_status_codes
        assert 500 in config.retryable_status_codes
        assert 503 in config.retryable_status_codes

    def test_custom_values(self):
        """Test custom retry config values."""
        config = RetryConfig(
            max_retries=5,
            initial_delay=0.5,
            max_delay=10.0,
            backoff_multiplier=3.0
        )

        assert config.max_retries == 5
        assert config.initial_delay == 0.5
        assert config.max_delay == 10.0
        assert config.backoff_multiplier == 3.0


class TestShopifyAPIError:
    """Tests for ShopifyAPIError exception."""

    def test_error_with_all_fields(self):
        """Test error with all fields populated."""
        error = ShopifyAPIError(
            message="Rate limited",
            status_code=429,
            code="RATE_LIMITED",
            response={"error": "Too many requests"},
            retry_after=5.0
        )

        assert str(error) == "Rate limited"
        assert error.status_code == 429
        assert error.code == "RATE_LIMITED"
        assert error.response == {"error": "Too many requests"}
        assert error.retry_after == 5.0

    def test_error_minimal_fields(self):
        """Test error with minimal fields."""
        error = ShopifyAPIError("Something went wrong")

        assert str(error) == "Something went wrong"
        assert error.status_code is None
        assert error.retry_after is None


class TestClientInitialization:
    """Tests for client initialization."""

    def test_init_with_valid_params(self):
        """Test initialization with valid parameters."""
        client = ShopifyBillingClient(
            shop_domain="test.myshopify.com",
            access_token="test-token"
        )

        assert client.shop_domain == "test.myshopify.com"
        assert client.access_token == "test-token"
        assert "2024-01" in client.api_version

    def test_init_strips_protocol(self):
        """Test that protocol is stripped from domain."""
        client = ShopifyBillingClient(
            shop_domain="https://test.myshopify.com",
            access_token="test-token"
        )

        assert client.shop_domain == "test.myshopify.com"

    def test_init_requires_shop_domain(self):
        """Test that shop_domain is required."""
        with pytest.raises(ValueError, match="shop_domain is required"):
            ShopifyBillingClient(shop_domain="", access_token="token")

    def test_init_requires_access_token(self):
        """Test that access_token is required."""
        with pytest.raises(ValueError, match="access_token is required"):
            ShopifyBillingClient(shop_domain="test.myshopify.com", access_token="")

    def test_init_with_custom_retry_config(self, retry_config):
        """Test initialization with custom retry config."""
        client = ShopifyBillingClient(
            shop_domain="test.myshopify.com",
            access_token="test-token",
            retry_config=retry_config
        )

        assert client.retry_config.max_retries == 3
        assert client.retry_config.initial_delay == 0.1


class TestRateLimitHandling:
    """Tests for rate limit handling."""

    @pytest.mark.asyncio
    async def test_rate_limit_extracts_retry_after(self, billing_client):
        """Test that Retry-After header is extracted."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "5.0"}

        with patch.object(billing_client._client, 'post', return_value=mock_response):
            with pytest.raises(ShopifyAPIError) as exc_info:
                await billing_client._execute_graphql_raw("query { test }")

            assert exc_info.value.status_code == 429
            assert exc_info.value.retry_after == 5.0

    @pytest.mark.asyncio
    async def test_rate_limit_default_retry_after(self, billing_client):
        """Test default Retry-After when header is invalid."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "invalid"}

        with patch.object(billing_client._client, 'post', return_value=mock_response):
            with pytest.raises(ShopifyAPIError) as exc_info:
                await billing_client._execute_graphql_raw("query { test }")

            assert exc_info.value.status_code == 429
            assert exc_info.value.retry_after == 2.0  # Default fallback


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_authentication_error(self, billing_client):
        """Test 401 authentication error."""
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch.object(billing_client._client, 'post', return_value=mock_response):
            with pytest.raises(ShopifyAPIError) as exc_info:
                await billing_client._execute_graphql_raw("query { test }")

            assert exc_info.value.status_code == 401
            assert "Authentication failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_store_frozen_error(self, billing_client):
        """Test 402 store frozen error."""
        mock_response = MagicMock()
        mock_response.status_code = 402

        with patch.object(billing_client._client, 'post', return_value=mock_response):
            with pytest.raises(ShopifyAPIError) as exc_info:
                await billing_client._execute_graphql_raw("query { test }")

            assert exc_info.value.status_code == 402
            assert "frozen" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_graphql_errors(self, billing_client):
        """Test GraphQL error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "errors": [{"message": "Field not found"}]
        }

        with patch.object(billing_client._client, 'post', return_value=mock_response):
            with pytest.raises(ShopifyAPIError) as exc_info:
                await billing_client._execute_graphql_raw("query { test }")

            assert "GraphQL errors" in str(exc_info.value)


class TestSubscriptionOperations:
    """Tests for subscription operations."""

    @pytest.mark.asyncio
    async def test_create_subscription_success(self, billing_client):
        """Test successful subscription creation."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "appSubscriptionCreate": {
                    "appSubscription": {
                        "id": "gid://shopify/AppSubscription/12345",
                        "name": "Test Plan",
                        "status": "PENDING",
                        "createdAt": "2024-01-15T00:00:00Z",
                        "currentPeriodEnd": None,
                        "trialDays": 0,
                        "test": True
                    },
                    "confirmationUrl": "https://test.myshopify.com/admin/charges/confirm",
                    "userErrors": []
                }
            }
        }

        with patch.object(billing_client._client, 'post', return_value=mock_response):
            result = await billing_client.create_subscription(
                name="Test Plan",
                price_amount=29.00,
                interval=BillingInterval.EVERY_30_DAYS,
                return_url="https://app.example.com/callback",
                test=True
            )

        assert result.success
        assert result.confirmation_url == "https://test.myshopify.com/admin/charges/confirm"
        assert result.app_subscription.id == "gid://shopify/AppSubscription/12345"

    @pytest.mark.asyncio
    async def test_create_subscription_user_errors(self, billing_client):
        """Test subscription creation with user errors."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "appSubscriptionCreate": {
                    "appSubscription": None,
                    "confirmationUrl": None,
                    "userErrors": [
                        {"field": "price", "message": "Price must be positive"}
                    ]
                }
            }
        }

        with patch.object(billing_client._client, 'post', return_value=mock_response):
            result = await billing_client.create_subscription(
                name="Test",
                price_amount=-10,
                return_url="https://example.com"
            )

        assert not result.success
        assert len(result.user_errors) == 1

    @pytest.mark.asyncio
    async def test_get_active_subscriptions(self, billing_client):
        """Test getting active subscriptions."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "currentAppInstallation": {
                    "activeSubscriptions": [
                        {
                            "id": "gid://shopify/AppSubscription/12345",
                            "name": "Growth Plan",
                            "status": "ACTIVE",
                            "createdAt": "2024-01-01T00:00:00Z",
                            "currentPeriodEnd": "2024-02-01T00:00:00Z",
                            "trialDays": 0,
                            "test": False
                        }
                    ]
                }
            }
        }

        with patch.object(billing_client._client, 'post', return_value=mock_response):
            subscriptions = await billing_client.get_active_subscriptions()

        assert len(subscriptions) == 1
        assert subscriptions[0].status == "ACTIVE"
        assert subscriptions[0].name == "Growth Plan"

    @pytest.mark.asyncio
    async def test_cancel_subscription_success(self, billing_client):
        """Test successful subscription cancellation."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "appSubscriptionCancel": {
                    "appSubscription": {
                        "id": "gid://shopify/AppSubscription/12345",
                        "status": "CANCELLED"
                    },
                    "userErrors": []
                }
            }
        }

        with patch.object(billing_client._client, 'post', return_value=mock_response):
            result = await billing_client.cancel_subscription(
                "gid://shopify/AppSubscription/12345"
            )

        assert result is True


class TestClientCleanup:
    """Tests for client cleanup."""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test client as context manager."""
        async with ShopifyBillingClient("test.myshopify.com", "token") as client:
            assert client is not None
            assert client.shop_domain == "test.myshopify.com"

    @pytest.mark.asyncio
    async def test_close_method(self, billing_client):
        """Test close method."""
        with patch.object(billing_client._client, 'aclose', new_callable=AsyncMock) as mock_close:
            await billing_client.close()
            mock_close.assert_called_once()
