"""
Unit tests for BillingWebhookHandler with idempotency.

Tests cover:
- Webhook deduplication
- State transition validation
- Out-of-order event handling
- Error recovery
"""

import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock

from src.services.billing_webhook_handler import (
    BillingWebhookHandler,
    WebhookProcessingResult,
    get_webhook_handler
)
from src.models.subscription import SubscriptionStatus


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock()
    session.query = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    return session


@pytest.fixture
def webhook_handler(mock_db_session):
    """Create a webhook handler instance."""
    return BillingWebhookHandler(mock_db_session)


@pytest.fixture
def sample_subscription_payload():
    """Sample Shopify subscription webhook payload."""
    return {
        "app_subscription": {
            "admin_graphql_api_id": "gid://shopify/AppSubscription/12345",
            "name": "AI Growth Analytics - Growth",
            "status": "ACTIVE",
            "current_period_end": "2024-02-15T00:00:00Z"
        }
    }


@pytest.fixture
def mock_store():
    """Create a mock ShopifyStore."""
    store = MagicMock()
    store.id = str(uuid.uuid4())
    store.tenant_id = f"test-tenant-{uuid.uuid4().hex[:8]}"
    store.shop_domain = "test-store.myshopify.com"
    store.access_token_encrypted = "mock-token"
    return store


@pytest.fixture
def mock_subscription():
    """Create a mock Subscription."""
    subscription = MagicMock()
    subscription.id = str(uuid.uuid4())
    subscription.tenant_id = f"test-tenant-{uuid.uuid4().hex[:8]}"
    subscription.shopify_subscription_id = "gid://shopify/AppSubscription/12345"
    subscription.status = SubscriptionStatus.PENDING.value
    subscription.store_id = str(uuid.uuid4())
    return subscription


class TestWebhookDeduplication:
    """Tests for webhook deduplication."""

    def test_duplicate_webhook_is_skipped(self, webhook_handler, mock_db_session):
        """Test that duplicate webhooks are skipped."""
        event_id = f"shopify-event-{uuid.uuid4().hex}"

        # Mock existing webhook event
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = MagicMock()  # Event exists
        mock_db_session.query.return_value = mock_query

        result = webhook_handler._is_duplicate(event_id)

        assert result is True

    def test_new_webhook_is_not_duplicate(self, webhook_handler, mock_db_session):
        """Test that new webhooks are not marked as duplicate."""
        event_id = f"shopify-event-{uuid.uuid4().hex}"

        # Mock no existing webhook event
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db_session.query.return_value = mock_query

        result = webhook_handler._is_duplicate(event_id)

        assert result is False

    def test_event_is_recorded_after_processing(self, webhook_handler, mock_db_session):
        """Test that processed events are recorded."""
        event_id = f"shopify-event-{uuid.uuid4().hex}"
        topic = "app_subscriptions/update"
        shop_domain = "test-store.myshopify.com"
        payload = {"test": "data"}

        webhook_handler._record_event(event_id, topic, shop_domain, payload)

        mock_db_session.add.assert_called_once()


class TestStateTransitionValidation:
    """Tests for state transition validation."""

    @pytest.mark.parametrize("current,new,expected", [
        # Valid transitions from PENDING
        (SubscriptionStatus.PENDING.value, SubscriptionStatus.ACTIVE.value, True),
        (SubscriptionStatus.PENDING.value, SubscriptionStatus.DECLINED.value, True),
        (SubscriptionStatus.PENDING.value, SubscriptionStatus.EXPIRED.value, True),

        # Valid transitions from ACTIVE
        (SubscriptionStatus.ACTIVE.value, SubscriptionStatus.FROZEN.value, True),
        (SubscriptionStatus.ACTIVE.value, SubscriptionStatus.CANCELLED.value, True),
        (SubscriptionStatus.ACTIVE.value, SubscriptionStatus.ACTIVE.value, True),

        # Valid transitions from FROZEN
        (SubscriptionStatus.FROZEN.value, SubscriptionStatus.ACTIVE.value, True),
        (SubscriptionStatus.FROZEN.value, SubscriptionStatus.CANCELLED.value, True),

        # Invalid transitions
        (SubscriptionStatus.CANCELLED.value, SubscriptionStatus.ACTIVE.value, False),
        (SubscriptionStatus.DECLINED.value, SubscriptionStatus.ACTIVE.value, False),
        (SubscriptionStatus.PENDING.value, SubscriptionStatus.FROZEN.value, False),
    ])
    def test_state_transition_validation(self, webhook_handler, current, new, expected):
        """Test state transition validation."""
        result = webhook_handler._is_valid_transition(current, new)
        assert result == expected


class TestSubscriptionUpdateWebhook:
    """Tests for subscription update webhook handling."""

    @pytest.mark.asyncio
    async def test_handle_activation_webhook(
        self,
        webhook_handler,
        mock_db_session,
        sample_subscription_payload,
        mock_store,
        mock_subscription
    ):
        """Test handling subscription activation webhook."""
        event_id = f"shopify-event-{uuid.uuid4().hex}"
        shop_domain = mock_store.shop_domain

        # Mock: No duplicate
        mock_webhook_query = MagicMock()
        mock_webhook_query.filter.return_value.first.return_value = None

        # Mock: Store found
        mock_store_query = MagicMock()
        mock_store_query.filter.return_value.first.return_value = mock_store

        # Mock: Subscription found
        mock_sub_query = MagicMock()
        mock_sub_query.filter.return_value.first.return_value = mock_subscription

        def query_side_effect(model):
            if hasattr(model, '__tablename__'):
                if model.__tablename__ == 'webhook_events':
                    return mock_webhook_query
                elif model.__tablename__ == 'shopify_stores':
                    return mock_store_query
                elif model.__tablename__ == 'tenant_subscriptions':
                    return mock_sub_query
            return MagicMock()

        mock_db_session.query.side_effect = query_side_effect

        with patch('src.services.billing_webhook_handler.BillingService') as mock_billing:
            mock_billing_instance = MagicMock()
            mock_billing.return_value = mock_billing_instance

            result = await webhook_handler.handle_subscription_update(
                shopify_event_id=event_id,
                shop_domain=shop_domain,
                payload=sample_subscription_payload
            )

        assert result.processed is True
        assert "activated" in result.message.lower() or "status" in result.message.lower()

    @pytest.mark.asyncio
    async def test_handle_duplicate_webhook_returns_skipped(
        self,
        webhook_handler,
        mock_db_session,
        sample_subscription_payload
    ):
        """Test that duplicate webhooks are skipped."""
        event_id = f"shopify-event-{uuid.uuid4().hex}"

        # Mock: Duplicate found
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = MagicMock()
        mock_db_session.query.return_value = mock_query

        result = await webhook_handler.handle_subscription_update(
            shopify_event_id=event_id,
            shop_domain="test-store.myshopify.com",
            payload=sample_subscription_payload
        )

        assert result.processed is False
        assert result.skipped_reason == "duplicate"

    @pytest.mark.asyncio
    async def test_handle_missing_subscription_id(self, webhook_handler, mock_db_session):
        """Test handling webhook with missing subscription ID."""
        event_id = f"shopify-event-{uuid.uuid4().hex}"
        payload = {
            "app_subscription": {
                "name": "Test",
                "status": "ACTIVE"
                # Missing admin_graphql_api_id
            }
        }

        # Mock: No duplicate
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db_session.query.return_value = mock_query

        result = await webhook_handler.handle_subscription_update(
            shopify_event_id=event_id,
            shop_domain="test-store.myshopify.com",
            payload=payload
        )

        assert result.processed is False
        assert result.error == "missing_subscription_id"

    @pytest.mark.asyncio
    async def test_handle_store_not_found(
        self,
        webhook_handler,
        mock_db_session,
        sample_subscription_payload
    ):
        """Test handling webhook when store is not found."""
        event_id = f"shopify-event-{uuid.uuid4().hex}"

        # Mock: No duplicate
        mock_webhook_query = MagicMock()
        mock_webhook_query.filter.return_value.first.return_value = None

        # Mock: Store not found
        mock_store_query = MagicMock()
        mock_store_query.filter.return_value.first.return_value = None

        def query_side_effect(model):
            if hasattr(model, '__tablename__'):
                if model.__tablename__ == 'webhook_events':
                    return mock_webhook_query
                elif model.__tablename__ == 'shopify_stores':
                    return mock_store_query
            return MagicMock()

        mock_db_session.query.side_effect = query_side_effect

        result = await webhook_handler.handle_subscription_update(
            shopify_event_id=event_id,
            shop_domain="unknown-store.myshopify.com",
            payload=sample_subscription_payload
        )

        assert result.processed is False
        assert result.error == "store_not_found"


class TestAppUninstalledWebhook:
    """Tests for app uninstalled webhook handling."""

    @pytest.mark.asyncio
    async def test_handle_uninstall_cancels_subscriptions(
        self,
        webhook_handler,
        mock_db_session,
        mock_store,
        mock_subscription
    ):
        """Test that uninstall webhook cancels subscriptions."""
        event_id = f"shopify-event-{uuid.uuid4().hex}"

        # Mock: No duplicate
        mock_webhook_query = MagicMock()
        mock_webhook_query.filter.return_value.first.return_value = None

        # Mock: Store found with active subscription
        mock_store_query = MagicMock()
        mock_store_query.filter.return_value.first.return_value = mock_store

        mock_sub_query = MagicMock()
        mock_sub_query.filter.return_value.all.return_value = [mock_subscription]

        def query_side_effect(model):
            if hasattr(model, '__tablename__'):
                if model.__tablename__ == 'webhook_events':
                    return mock_webhook_query
                elif model.__tablename__ == 'shopify_stores':
                    return mock_store_query
                elif model.__tablename__ == 'tenant_subscriptions':
                    return mock_sub_query
            return MagicMock()

        mock_db_session.query.side_effect = query_side_effect

        result = await webhook_handler.handle_app_uninstalled(
            shopify_event_id=event_id,
            shop_domain=mock_store.shop_domain,
            payload={}
        )

        assert result.processed is True
        assert mock_store.status == "uninstalled"
        assert mock_subscription.status == SubscriptionStatus.CANCELLED.value


class TestFactoryFunction:
    """Tests for factory function."""

    def test_get_webhook_handler_returns_instance(self, mock_db_session):
        """Test that factory function returns handler instance."""
        handler = get_webhook_handler(mock_db_session)

        assert isinstance(handler, BillingWebhookHandler)
        assert handler.db == mock_db_session
