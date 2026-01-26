"""
Integration tests for Shopify Billing API functionality.

Tests cover:
- Checkout URL creation
- Webhook handling with HMAC verification
- Subscription status updates
- Grace period enforcement
- Reconciliation job
"""

import os
import json
import hmac
import hashlib
import base64
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Test fixtures and helpers


@pytest.fixture
def test_tenant_id():
    """Generate a unique tenant ID for testing."""
    return f"test-tenant-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def test_shop_domain():
    """Test shop domain."""
    return "test-store.myshopify.com"


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock()
    session.query = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.close = MagicMock()
    return session


@pytest.fixture
def mock_store(test_tenant_id, test_shop_domain):
    """Create a mock ShopifyStore."""
    store = MagicMock()
    store.id = str(uuid.uuid4())
    store.tenant_id = test_tenant_id
    store.shop_domain = test_shop_domain
    store.access_token_encrypted = "mock-access-token"
    store.currency = "USD"
    store.status = "active"
    return store


@pytest.fixture
def mock_plan():
    """Create a mock Plan."""
    plan = MagicMock()
    plan.id = "plan_growth"
    plan.name = "growth"
    plan.display_name = "Growth"
    plan.description = "For growing businesses"
    plan.price_monthly_cents = 2900
    plan.price_yearly_cents = 29000
    plan.is_active = True
    return plan


@pytest.fixture
def mock_subscription(test_tenant_id, mock_store, mock_plan):
    """Create a mock Subscription."""
    subscription = MagicMock()
    subscription.id = str(uuid.uuid4())
    subscription.tenant_id = test_tenant_id
    subscription.store_id = mock_store.id
    subscription.plan_id = mock_plan.id
    subscription.shopify_subscription_id = f"gid://shopify/AppSubscription/{uuid.uuid4().hex[:12]}"
    subscription.status = "active"
    subscription.current_period_start = datetime.now(timezone.utc)
    subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)
    return subscription


class TestShopifyBillingClient:
    """Tests for ShopifyBillingClient."""

    @pytest.mark.asyncio
    async def test_create_subscription_success(self, test_shop_domain):
        """Test successful subscription creation."""
        from src.integrations.shopify.billing_client import (
            ShopifyBillingClient,
            BillingInterval,
            CreateSubscriptionResult
        )

        # Mock the HTTP response
        mock_response = {
            "data": {
                "appSubscriptionCreate": {
                    "appSubscription": {
                        "id": "gid://shopify/AppSubscription/12345",
                        "name": "AI Growth Analytics - Growth",
                        "status": "PENDING",
                        "createdAt": "2024-01-15T10:00:00Z",
                        "currentPeriodEnd": None,
                        "trialDays": 0,
                        "test": True
                    },
                    "confirmationUrl": "https://test-store.myshopify.com/admin/charges/confirm",
                    "userErrors": []
                }
            }
        }

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response
            )

            client = ShopifyBillingClient(test_shop_domain, "mock-token")

            result = await client.create_subscription(
                name="AI Growth Analytics - Growth",
                price_amount=29.00,
                interval=BillingInterval.EVERY_30_DAYS,
                return_url="https://app.example.com/billing/callback",
                test=True
            )

            assert result.success
            assert result.confirmation_url == "https://test-store.myshopify.com/admin/charges/confirm"
            assert result.app_subscription is not None
            assert result.app_subscription.id == "gid://shopify/AppSubscription/12345"

            await client.close()

    @pytest.mark.asyncio
    async def test_create_subscription_with_user_errors(self, test_shop_domain):
        """Test subscription creation with user errors."""
        from src.integrations.shopify.billing_client import ShopifyBillingClient

        mock_response = {
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

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response
            )

            client = ShopifyBillingClient(test_shop_domain, "mock-token")

            result = await client.create_subscription(
                name="Test",
                price_amount=-10,
                return_url="https://example.com"
            )

            assert not result.success
            assert len(result.user_errors) == 1
            assert result.user_errors[0]["field"] == "price"

            await client.close()

    @pytest.mark.asyncio
    async def test_get_active_subscriptions(self, test_shop_domain):
        """Test getting active subscriptions."""
        from src.integrations.shopify.billing_client import ShopifyBillingClient

        mock_response = {
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

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_response
            )

            client = ShopifyBillingClient(test_shop_domain, "mock-token")
            subscriptions = await client.get_active_subscriptions()

            assert len(subscriptions) == 1
            assert subscriptions[0].status == "ACTIVE"
            assert subscriptions[0].name == "Growth Plan"

            await client.close()


class TestWebhookHMACVerification:
    """Tests for webhook HMAC signature verification."""

    def test_valid_hmac_verification(self):
        """Test HMAC verification with valid signature."""
        from src.api.routes.webhooks_shopify import verify_shopify_webhook

        api_secret = "test-secret-key"
        body = b'{"test": "data"}'

        # Compute expected HMAC
        expected_hmac = hmac.new(
            api_secret.encode("utf-8"),
            body,
            hashlib.sha256
        )
        expected_digest = base64.b64encode(expected_hmac.digest()).decode("utf-8")

        assert verify_shopify_webhook(body, expected_digest, api_secret)

    def test_invalid_hmac_verification(self):
        """Test HMAC verification with invalid signature."""
        from src.api.routes.webhooks_shopify import verify_shopify_webhook

        api_secret = "test-secret-key"
        body = b'{"test": "data"}'
        invalid_signature = "invalid-signature"

        assert not verify_shopify_webhook(body, invalid_signature, api_secret)

    def test_hmac_with_tampered_body(self):
        """Test HMAC verification fails when body is tampered."""
        from src.api.routes.webhooks_shopify import verify_shopify_webhook

        api_secret = "test-secret-key"
        original_body = b'{"test": "data"}'
        tampered_body = b'{"test": "tampered"}'

        # Sign with original body
        signature = hmac.new(
            api_secret.encode("utf-8"),
            original_body,
            hashlib.sha256
        )
        signature_digest = base64.b64encode(signature.digest()).decode("utf-8")

        # Verify fails with tampered body
        assert not verify_shopify_webhook(tampered_body, signature_digest, api_secret)

    def test_hmac_empty_values(self):
        """Test HMAC verification with empty values."""
        from src.api.routes.webhooks_shopify import verify_shopify_webhook

        assert not verify_shopify_webhook(b"data", "", "secret")
        assert not verify_shopify_webhook(b"data", "signature", "")
        assert not verify_shopify_webhook(b"data", None, "secret")


class TestBillingService:
    """Tests for BillingService."""

    def test_billing_service_requires_tenant_id(self, mock_db_session):
        """Test that BillingService requires tenant_id."""
        from src.services.billing_service import BillingService

        with pytest.raises(ValueError, match="tenant_id is required"):
            BillingService(mock_db_session, "")

        with pytest.raises(ValueError, match="tenant_id is required"):
            BillingService(mock_db_session, None)

    def test_get_subscription_info_no_subscription(
        self, mock_db_session, test_tenant_id
    ):
        """Test getting subscription info when no subscription exists."""
        from src.services.billing_service import BillingService
        from src.models.plan import Plan

        # Create a mock free plan
        mock_free_plan = MagicMock(spec=Plan)
        mock_free_plan.id = "plan_free"
        mock_free_plan.name = "free"
        mock_free_plan.display_name = "Free"

        # The service makes 3 queries:
        # 1. _get_active_subscription(): filter().first() -> None
        # 2. Check cancelled/declined/expired: filter().order_by().first() -> None
        # 3. Get free plan: filter().first() -> mock_free_plan

        # Query 1: _get_active_subscription
        mock_active_sub_query = MagicMock()
        mock_active_sub_query.filter.return_value.first.return_value = None

        # Query 2: cancelled/declined/expired subscriptions
        mock_old_sub_query = MagicMock()
        mock_old_sub_query.filter.return_value.order_by.return_value.first.return_value = None

        # Query 3: free plan lookup
        mock_plan_query = MagicMock()
        mock_plan_query.filter.return_value.first.return_value = mock_free_plan

        mock_db_session.query.side_effect = [
            mock_active_sub_query,
            mock_old_sub_query,
            mock_plan_query
        ]

        service = BillingService(mock_db_session, test_tenant_id)
        info = service.get_subscription_info()

        assert info.subscription_id is None
        assert info.plan_id == "plan_free"
        assert info.can_access_features  # Free tier is accessible
        assert info.downgraded_reason == "No active subscription"

    def test_get_subscription_info_active(
        self, mock_db_session, test_tenant_id, mock_subscription, mock_plan
    ):
        """Test getting subscription info for active subscription."""
        from src.services.billing_service import BillingService

        # Mock active subscription
        mock_subscription.status = "active"

        mock_sub_query = MagicMock()
        mock_sub_query.filter.return_value.first.return_value = mock_subscription
        mock_plan_query = MagicMock()
        mock_plan_query.filter.return_value.first.return_value = mock_plan

        mock_db_session.query.side_effect = [mock_sub_query, mock_plan_query]

        service = BillingService(mock_db_session, test_tenant_id)
        info = service.get_subscription_info()

        assert info.subscription_id == mock_subscription.id
        assert info.is_active
        assert info.can_access_features
        assert info.downgraded_reason is None

    def test_get_subscription_info_frozen_in_grace_period(
        self, mock_db_session, test_tenant_id, mock_subscription, mock_plan
    ):
        """Test subscription info for frozen subscription in grace period."""
        from src.services.billing_service import BillingService

        # Mock frozen subscription with future grace period end
        mock_subscription.status = "frozen"
        mock_subscription.grace_period_ends_on = datetime.now(timezone.utc) + timedelta(days=2)

        mock_sub_query = MagicMock()
        mock_sub_query.filter.return_value.first.return_value = mock_subscription
        mock_plan_query = MagicMock()
        mock_plan_query.filter.return_value.first.return_value = mock_plan

        mock_db_session.query.side_effect = [mock_sub_query, mock_plan_query]

        service = BillingService(mock_db_session, test_tenant_id)
        info = service.get_subscription_info()

        assert info.status == "frozen"
        assert info.can_access_features  # Still in grace period
        assert "grace period" in info.downgraded_reason.lower()

    def test_get_subscription_info_frozen_grace_period_expired(
        self, mock_db_session, test_tenant_id, mock_subscription, mock_plan
    ):
        """Test subscription info for frozen subscription with expired grace period."""
        from src.services.billing_service import BillingService

        # Mock frozen subscription with past grace period end
        mock_subscription.status = "frozen"
        mock_subscription.grace_period_ends_on = datetime.now(timezone.utc) - timedelta(days=1)

        mock_sub_query = MagicMock()
        mock_sub_query.filter.return_value.first.return_value = mock_subscription
        mock_plan_query = MagicMock()
        mock_plan_query.filter.return_value.first.return_value = mock_plan

        mock_db_session.query.side_effect = [mock_sub_query, mock_plan_query]

        service = BillingService(mock_db_session, test_tenant_id)
        info = service.get_subscription_info()

        assert info.status == "frozen"
        assert not info.can_access_features  # Grace period expired
        assert "expired" in info.downgraded_reason.lower()

    def test_activate_subscription(
        self, mock_db_session, test_tenant_id, mock_subscription
    ):
        """Test subscription activation."""
        from src.services.billing_service import BillingService

        mock_subscription.status = "pending"
        shopify_sub_id = mock_subscription.shopify_subscription_id

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_subscription
        mock_db_session.query.return_value = mock_query

        service = BillingService(mock_db_session, test_tenant_id)
        result = service.activate_subscription(
            shopify_subscription_id=shopify_sub_id,
            current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )

        assert result is not None
        assert result.status == "active"
        mock_db_session.commit.assert_called()

    def test_cancel_subscription(
        self, mock_db_session, test_tenant_id, mock_subscription
    ):
        """Test subscription cancellation."""
        from src.services.billing_service import BillingService

        mock_subscription.status = "active"
        shopify_sub_id = mock_subscription.shopify_subscription_id

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_subscription
        mock_db_session.query.return_value = mock_query

        service = BillingService(mock_db_session, test_tenant_id)
        result = service.cancel_subscription(shopify_subscription_id=shopify_sub_id)

        assert result is not None
        assert result.status == "cancelled"
        assert result.cancelled_at is not None
        mock_db_session.commit.assert_called()

    def test_freeze_subscription(
        self, mock_db_session, test_tenant_id, mock_subscription
    ):
        """Test subscription freeze (payment failure)."""
        from src.services.billing_service import BillingService

        mock_subscription.status = "active"
        shopify_sub_id = mock_subscription.shopify_subscription_id

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_subscription
        mock_db_session.query.return_value = mock_query

        service = BillingService(mock_db_session, test_tenant_id)
        result = service.freeze_subscription(
            shopify_subscription_id=shopify_sub_id,
            reason="payment_failed"
        )

        assert result is not None
        assert result.status == "frozen"
        assert result.grace_period_ends_on is not None
        # Grace period should be in the future
        assert result.grace_period_ends_on > datetime.now(timezone.utc)
        mock_db_session.commit.assert_called()


class TestReconciliationJob:
    """Tests for the reconciliation job."""

    @pytest.mark.asyncio
    async def test_grace_period_expiration_check(self, mock_db_session):
        """Test that expired grace periods are processed."""
        from src.jobs.reconcile_subscriptions import (
            check_grace_period_expirations,
            ReconciliationStats
        )
        from src.models.subscription import SubscriptionStatus

        # Create mock expired subscription
        expired_sub = MagicMock()
        expired_sub.id = str(uuid.uuid4())
        expired_sub.tenant_id = "test-tenant"
        expired_sub.status = SubscriptionStatus.FROZEN.value
        expired_sub.grace_period_ends_on = datetime.now(timezone.utc) - timedelta(hours=1)

        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = [expired_sub]
        mock_db_session.query.return_value = mock_query

        stats = ReconciliationStats()

        with patch("src.services.billing_service.BillingService"):
            await check_grace_period_expirations(mock_db_session, stats)

        assert stats.subscriptions_updated == 1
        assert expired_sub.status == SubscriptionStatus.CANCELLED.value
        mock_db_session.commit.assert_called()


class TestEntitlementEnforcement:
    """Tests for entitlement enforcement based on subscription status."""

    def test_cancelled_subscription_no_access(
        self, mock_db_session, test_tenant_id, mock_subscription, mock_plan
    ):
        """Test that cancelled subscriptions have no feature access."""
        from src.services.billing_service import BillingService

        mock_subscription.status = "cancelled"
        mock_subscription.cancelled_at = datetime.now(timezone.utc)

        mock_sub_query = MagicMock()
        mock_sub_query.filter.return_value.first.return_value = mock_subscription
        mock_plan_query = MagicMock()
        mock_plan_query.filter.return_value.first.return_value = mock_plan

        mock_db_session.query.side_effect = [mock_sub_query, mock_plan_query]

        service = BillingService(mock_db_session, test_tenant_id)
        info = service.get_subscription_info()

        assert not info.can_access_features
        assert info.downgraded_reason == "Subscription cancelled"

    def test_declined_subscription_no_access(
        self, mock_db_session, test_tenant_id, mock_subscription, mock_plan
    ):
        """Test that declined subscriptions have no feature access."""
        from src.services.billing_service import BillingService

        mock_subscription.status = "declined"

        mock_sub_query = MagicMock()
        mock_sub_query.filter.return_value.first.return_value = mock_subscription
        mock_plan_query = MagicMock()
        mock_plan_query.filter.return_value.first.return_value = mock_plan

        mock_db_session.query.side_effect = [mock_sub_query, mock_plan_query]

        service = BillingService(mock_db_session, test_tenant_id)
        info = service.get_subscription_info()

        assert not info.can_access_features
        assert info.downgraded_reason == "Subscription declined"

    def test_active_subscription_has_access(
        self, mock_db_session, test_tenant_id, mock_subscription, mock_plan
    ):
        """Test that active subscriptions have feature access."""
        from src.services.billing_service import BillingService

        mock_subscription.status = "active"

        mock_sub_query = MagicMock()
        mock_sub_query.filter.return_value.first.return_value = mock_subscription
        mock_plan_query = MagicMock()
        mock_plan_query.filter.return_value.first.return_value = mock_plan

        mock_db_session.query.side_effect = [mock_sub_query, mock_plan_query]

        service = BillingService(mock_db_session, test_tenant_id)
        info = service.get_subscription_info()

        assert info.can_access_features
        assert info.downgraded_reason is None


# Run tests with: pytest -v src/tests/integration/test_billing.py
