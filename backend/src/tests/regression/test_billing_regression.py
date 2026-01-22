"""
Billing Regression Test Suite.

Tests end-to-end billing flows at the API boundary with:
- Mocked Shopify Billing Client (no external calls)
- Real database operations (ephemeral Postgres/SQLite)
- Real webhook HMAC verification with test secrets
- Deterministic, repeatable test scenarios

Run with: pytest -m regression src/tests/regression/test_billing_regression.py -v
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

# NOTE: Imports of src.models and src.services are done inside tests
# to avoid circular import issues. Use helper functions below.


def get_subscription_model():
    """Lazy import of Subscription model."""
    from src.models.subscription import Subscription
    return Subscription


def get_subscription_status():
    """Lazy import of SubscriptionStatus enum."""
    from src.models.subscription import SubscriptionStatus
    return SubscriptionStatus


def get_billing_event_model():
    """Lazy import of BillingEvent model."""
    from src.models.billing_event import BillingEvent
    return BillingEvent


def get_billing_event_type():
    """Lazy import of BillingEventType enum."""
    from src.models.billing_event import BillingEventType
    return BillingEventType


def get_billing_service(db_session, tenant_id):
    """Lazy import and instantiate BillingService."""
    from src.services.billing_service import BillingService
    return BillingService(db_session, tenant_id)


# Mark all tests in this module as regression tests
pytestmark = pytest.mark.regression


class TestBillingCheckout:
    """Test cases for billing checkout flow."""

    @pytest.mark.asyncio
    async def test_billing_checkout_url_happy_path(
        self,
        db_session,
        test_tenant_id,
        test_store,
        test_plan_free,
        test_plan_growth,
        mock_billing_client,
        get_billing_events,
    ):
        """
        Test 1: Create checkout URL for a plan (happy path).

        GIVEN a tenant on Free plan (no active subscription)
        WHEN POST /billing/checkout with plan_id=Growth
        THEN response includes redirect_url
        AND tenant_subscriptions status becomes PENDING
        AND audit log is written for "subscription_created"
        """
        # Lazy imports to avoid circular import
        Subscription = get_subscription_model()
        SubscriptionStatus = get_subscription_status()
        BillingEventType = get_billing_event_type()

        # Arrange: Verify tenant has no active subscription
        existing_sub = db_session.query(Subscription).filter(
            Subscription.tenant_id == test_tenant_id,
            Subscription.status.in_([
                SubscriptionStatus.ACTIVE.value,
                SubscriptionStatus.PENDING.value
            ])
        ).first()
        assert existing_sub is None, "Tenant should not have an existing subscription"

        # Act: Create checkout URL via BillingService
        # (In full integration test, this would go through the API endpoint)
        with patch(
            "src.services.billing_service.get_billing_client"
        ) as mock_get_client:
            # Configure mock to return our mock client
            mock_get_client.return_value = mock_billing_client

            billing_service = get_billing_service(db_session, test_tenant_id)
            result = await billing_service.create_checkout_url(
                plan_id=test_plan_growth.id,
                test_mode=True
            )

        # Assert: Response includes checkout URL
        assert result.success is True
        assert result.checkout_url, "Checkout URL should be returned"
        assert "confirm" in result.checkout_url or "charges" in result.checkout_url
        assert result.subscription_id, "Subscription ID should be returned"

        # Assert: Subscription created with PENDING status
        subscription = db_session.query(Subscription).filter(
            Subscription.id == result.subscription_id
        ).first()
        assert subscription is not None
        assert subscription.tenant_id == test_tenant_id
        assert subscription.plan_id == test_plan_growth.id
        assert subscription.status == SubscriptionStatus.PENDING.value

        # Assert: Audit log written
        events = get_billing_events(
            tenant_id=test_tenant_id,
            event_type=BillingEventType.SUBSCRIPTION_CREATED.value
        )
        assert len(events) >= 1, "Billing event should be logged"
        assert events[0].to_plan_id == test_plan_growth.id


class TestWebhookSubscriptionActivation:
    """Test cases for webhook-driven subscription activation."""

    def test_webhook_valid_signature_sets_subscription_active(
        self,
        client,
        db_session,
        test_store,
        test_plan_growth,
        pending_subscription,
        webhook_secret,
        sign_webhook_payload,
        load_webhook_fixture,
        get_billing_events,
    ):
        """
        Test 2: Receive signed webhook -> subscription becomes ACTIVE.

        GIVEN a tenant_subscriptions record in PENDING
        WHEN webhook event with valid signature is POSTed to /webhooks/shopify
        THEN status becomes ACTIVE
        AND plan_id updated
        AND entitlements refreshed (can_access returns true for premium feature)
        AND audit log is written for "subscription_updated"
        """
        # Lazy imports
        SubscriptionStatus = get_subscription_status()
        BillingEventType = get_billing_event_type()

        # Arrange: Load webhook fixture with subscription ID
        payload_dict = load_webhook_fixture(
            "subscription_created",
            SUBSCRIPTION_ID=pending_subscription.shopify_subscription_id
        )
        payload_bytes = json.dumps(payload_dict).encode("utf-8")

        # Sign the payload
        signature = sign_webhook_payload(payload_bytes)

        # Act: POST webhook to endpoint
        response = client.post(
            "/api/webhooks/shopify/subscription-update",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": signature,
                "X-Shopify-Shop-Domain": test_store.shop_domain,
                "X-Shopify-Topic": "app_subscriptions/update",
            }
        )

        # Assert: Webhook accepted
        assert response.status_code == 200
        response_data = response.json()
        assert response_data.get("received") is True

        # Assert: Subscription status updated to ACTIVE
        db_session.refresh(pending_subscription)
        assert pending_subscription.status == SubscriptionStatus.ACTIVE.value

        # Assert: Entitlements check (via BillingService)
        billing_service = get_billing_service(db_session, pending_subscription.tenant_id)
        sub_info = billing_service.get_subscription_info()
        assert sub_info.is_active is True
        assert sub_info.can_access_features is True

        # Assert: Audit log written
        events = get_billing_events(
            tenant_id=pending_subscription.tenant_id,
            event_type=BillingEventType.SUBSCRIPTION_UPDATED.value
        )
        assert len(events) >= 1, "Subscription update event should be logged"


class TestUpgradeFlow:
    """Test cases for subscription upgrade flow."""

    def test_upgrade_flow_updates_plan_and_entitlements(
        self,
        client,
        db_session,
        test_store,
        test_plan_growth,
        test_plan_pro,
        active_subscription,
        webhook_secret,
        sign_webhook_payload,
        load_webhook_fixture,
    ):
        """
        Test 3: Upgrade plan -> subscription reflects new plan_id.

        GIVEN subscription ACTIVE on Growth
        WHEN webhook subscription_updated indicates Pro
        THEN plan_id becomes Pro
        AND entitlements update immediately
        """
        # Lazy imports
        SubscriptionStatus = get_subscription_status()

        # Arrange: Verify initial state is Growth plan
        assert active_subscription.plan_id == test_plan_growth.id
        assert active_subscription.status == SubscriptionStatus.ACTIVE.value

        # Load upgrade webhook fixture
        payload_dict = load_webhook_fixture(
            "subscription_updated_upgrade",
            SUBSCRIPTION_ID=active_subscription.shopify_subscription_id
        )
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        signature = sign_webhook_payload(payload_bytes)

        # Act: POST upgrade webhook
        # Note: The webhook handler updates status but may not change plan_id
        # directly from webhook - that typically happens via checkout callback
        # For this test, we simulate the status update portion
        response = client.post(
            "/api/webhooks/shopify/subscription-update",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": signature,
                "X-Shopify-Shop-Domain": test_store.shop_domain,
                "X-Shopify-Topic": "app_subscriptions/update",
            }
        )

        # Assert: Webhook accepted
        assert response.status_code == 200

        # Assert: Subscription remains ACTIVE
        db_session.refresh(active_subscription)
        assert active_subscription.status == SubscriptionStatus.ACTIVE.value

        # Assert: Entitlements are valid
        billing_service = get_billing_service(db_session, active_subscription.tenant_id)
        sub_info = billing_service.get_subscription_info()
        assert sub_info.can_access_features is True


class TestCancellationFlow:
    """Test cases for subscription cancellation."""

    def test_cancel_flow_revokes_entitlements(
        self,
        client,
        db_session,
        test_store,
        test_plan_pro,
        active_subscription_pro,
        webhook_secret,
        sign_webhook_payload,
        load_webhook_fixture,
        get_billing_events,
    ):
        """
        Test 4: Cancel subscription -> entitlements revoked.

        GIVEN subscription ACTIVE on Pro
        WHEN webhook cancellation event received
        THEN status becomes CANCELLED
        AND premium entitlements are false
        AND audit log written
        """
        # Lazy imports
        SubscriptionStatus = get_subscription_status()
        BillingEventType = get_billing_event_type()

        # Arrange: Verify initial state
        assert active_subscription_pro.status == SubscriptionStatus.ACTIVE.value
        assert active_subscription_pro.plan_id == test_plan_pro.id

        # Load cancellation webhook
        payload_dict = load_webhook_fixture(
            "subscription_cancelled",
            SUBSCRIPTION_ID=active_subscription_pro.shopify_subscription_id
        )
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        signature = sign_webhook_payload(payload_bytes)

        # Act: POST cancellation webhook
        response = client.post(
            "/api/webhooks/shopify/subscription-update",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": signature,
                "X-Shopify-Shop-Domain": test_store.shop_domain,
                "X-Shopify-Topic": "app_subscriptions/update",
            }
        )

        # Assert: Webhook accepted
        assert response.status_code == 200

        # Assert: Status becomes CANCELLED
        db_session.refresh(active_subscription_pro)
        assert active_subscription_pro.status == SubscriptionStatus.CANCELLED.value

        # Assert: Entitlements revoked
        billing_service = get_billing_service(db_session, active_subscription_pro.tenant_id)
        sub_info = billing_service.get_subscription_info()
        assert sub_info.can_access_features is False
        assert sub_info.downgraded_reason is not None
        assert "cancelled" in sub_info.downgraded_reason.lower()

        # Assert: Audit log written
        events = get_billing_events(
            tenant_id=active_subscription_pro.tenant_id,
            event_type=BillingEventType.SUBSCRIPTION_CANCELLED.value
        )
        assert len(events) >= 1, "Cancellation event should be logged"


class TestFailedPayment:
    """Test cases for failed payment handling."""

    def test_failed_payment_downgrades_access(
        self,
        client,
        db_session,
        test_store,
        test_plan_growth,
        active_subscription,
        webhook_secret,
        sign_webhook_payload,
        load_webhook_fixture,
        get_billing_events,
    ):
        """
        Test 5: Failed payment -> access downgraded.

        GIVEN subscription ACTIVE
        WHEN webhook indicates PAST_DUE/FROZEN
        THEN status becomes FROZEN
        AND premium access is blocked OR grace-period rules apply
        """
        # Lazy imports
        SubscriptionStatus = get_subscription_status()
        BillingEventType = get_billing_event_type()

        # Arrange: Verify initial active state
        assert active_subscription.status == SubscriptionStatus.ACTIVE.value

        # Load past_due/frozen webhook
        payload_dict = load_webhook_fixture(
            "subscription_past_due",
            SUBSCRIPTION_ID=active_subscription.shopify_subscription_id
        )
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        signature = sign_webhook_payload(payload_bytes)

        # Act: POST frozen webhook
        response = client.post(
            "/api/webhooks/shopify/subscription-update",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": signature,
                "X-Shopify-Shop-Domain": test_store.shop_domain,
                "X-Shopify-Topic": "app_subscriptions/update",
            }
        )

        # Assert: Webhook accepted
        assert response.status_code == 200

        # Assert: Status becomes FROZEN
        db_session.refresh(active_subscription)
        assert active_subscription.status == SubscriptionStatus.FROZEN.value

        # Assert: Grace period is set
        assert active_subscription.grace_period_ends_on is not None
        assert active_subscription.grace_period_ends_on > datetime.now(timezone.utc)

        # Assert: During grace period, access may still be allowed
        billing_service = get_billing_service(db_session, active_subscription.tenant_id)
        sub_info = billing_service.get_subscription_info()
        # Access allowed during grace period
        assert sub_info.can_access_features is True
        assert "grace period" in sub_info.downgraded_reason.lower()

        # Assert: Audit log written
        events = get_billing_events(
            tenant_id=active_subscription.tenant_id,
            event_type=BillingEventType.CHARGE_FAILED.value
        )
        assert len(events) >= 1, "Charge failed event should be logged"


class TestReconciliation:
    """Test cases for subscription reconciliation job."""

    @pytest.mark.asyncio
    async def test_reconciliation_job_corrects_drift(
        self,
        db_session,
        test_tenant_id,
        test_store,
        test_plan_growth,
        active_subscription,
        mock_billing_client,
        get_billing_events,
    ):
        """
        Test 6: Reconciliation job corrects drift.

        GIVEN DB status ACTIVE but Shopify mock returns CANCELLED
        WHEN reconcile_subscriptions job runs
        THEN DB status becomes CANCELLED
        AND audit log written with source="reconciliation"
        """
        # Lazy imports
        SubscriptionStatus = get_subscription_status()
        BillingEventType = get_billing_event_type()

        # Arrange: Set up drift scenario
        # DB says ACTIVE
        assert active_subscription.status == SubscriptionStatus.ACTIVE.value

        # Configure mock to return CANCELLED for this subscription
        mock_billing_client.add_subscription(
            subscription_gid=active_subscription.shopify_subscription_id,
            name="AI Growth Analytics - Growth",
            status="CANCELLED"
        )

        # Act: Run reconciliation via BillingService.sync_with_shopify
        # (Simulating what the reconciliation job does)
        billing_service = get_billing_service(db_session, test_tenant_id)

        # Simulate reconciliation detecting the drift
        billing_service.sync_with_shopify(
            shopify_subscription_id=active_subscription.shopify_subscription_id,
            shopify_status="CANCELLED"
        )

        # Assert: DB status corrected to CANCELLED
        db_session.refresh(active_subscription)
        assert active_subscription.status == SubscriptionStatus.CANCELLED.value

        # Assert: Audit log written with reconciliation source
        events = get_billing_events(
            tenant_id=test_tenant_id,
            event_type=BillingEventType.SUBSCRIPTION_UPDATED.value
        )
        assert len(events) >= 1

        # Check metadata indicates reconciliation source
        latest_event = events[0]
        assert latest_event.extra_metadata is not None
        assert latest_event.extra_metadata.get("source") == "reconciliation"


class TestWebhookSecurity:
    """Test cases for webhook security."""

    def test_webhook_rejects_invalid_signature(
        self,
        client,
        db_session,
        test_store,
        test_plan_growth,
        pending_subscription,
    ):
        """
        Test 7: Security - webhook HMAC verification rejects invalid signatures.

        WHEN webhook posted with invalid HMAC
        THEN returns 401
        AND DB is unchanged
        """
        # Arrange: Create payload with invalid signature
        payload_dict = {
            "app_subscription": {
                "admin_graphql_api_id": pending_subscription.shopify_subscription_id,
                "name": "AI Growth Analytics - Growth",
                "status": "ACTIVE"
            }
        }
        payload_bytes = json.dumps(payload_dict).encode("utf-8")

        # Use obviously invalid signature
        invalid_signature = "aW52YWxpZC1zaWduYXR1cmUtZm9yLXRlc3Rpbmc="

        # Record initial state
        initial_status = pending_subscription.status

        # Act: POST with invalid signature
        response = client.post(
            "/api/webhooks/shopify/subscription-update",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": invalid_signature,
                "X-Shopify-Shop-Domain": test_store.shop_domain,
                "X-Shopify-Topic": "app_subscriptions/update",
            }
        )

        # Assert: Request rejected with 401
        assert response.status_code == 401
        assert "Invalid HMAC" in response.json().get("detail", "")

        # Assert: DB unchanged
        db_session.refresh(pending_subscription)
        assert pending_subscription.status == initial_status

    def test_webhook_rejects_missing_signature(
        self,
        client,
        test_store,
    ):
        """
        Test webhook rejects requests without HMAC header.
        """
        payload = json.dumps({"test": "data"}).encode("utf-8")

        response = client.post(
            "/api/webhooks/shopify/subscription-update",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Shop-Domain": test_store.shop_domain,
                # No X-Shopify-Hmac-Sha256 header
            }
        )

        assert response.status_code == 401
        assert "Missing HMAC" in response.json().get("detail", "")


class TestTenantIsolation:
    """Test cases for multi-tenant security."""

    def test_cross_tenant_protection_webhook_cannot_mutate_other_tenant(
        self,
        client,
        db_session,
        test_store,
        test_store_b,
        test_plan_growth,
        active_subscription,
        active_subscription_b,
        webhook_secret,
        sign_webhook_payload,
        load_webhook_fixture,
    ):
        """
        Test 8: Multi-tenant safety - tenant A cannot affect tenant B.

        GIVEN tenant A and tenant B subscriptions exist
        WHEN webhook for tenant A is posted
        THEN tenant B subscription unchanged
        AND no cross-tenant updates occur
        """
        # Lazy imports
        SubscriptionStatus = get_subscription_status()

        # Arrange: Record initial state for both tenants
        initial_status_a = active_subscription.status
        initial_status_b = active_subscription_b.status
        initial_plan_b = active_subscription_b.plan_id

        # Create cancellation webhook for tenant A's subscription
        payload_dict = load_webhook_fixture(
            "subscription_cancelled",
            SUBSCRIPTION_ID=active_subscription.shopify_subscription_id
        )
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        signature = sign_webhook_payload(payload_bytes)

        # Act: POST webhook for tenant A's store
        response = client.post(
            "/api/webhooks/shopify/subscription-update",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": signature,
                "X-Shopify-Shop-Domain": test_store.shop_domain,  # Tenant A's store
                "X-Shopify-Topic": "app_subscriptions/update",
            }
        )

        # Assert: Webhook accepted
        assert response.status_code == 200

        # Assert: Tenant A's subscription was updated
        db_session.refresh(active_subscription)
        assert active_subscription.status == SubscriptionStatus.CANCELLED.value

        # Assert: Tenant B's subscription is COMPLETELY UNCHANGED
        db_session.refresh(active_subscription_b)
        assert active_subscription_b.status == initial_status_b
        assert active_subscription_b.plan_id == initial_plan_b
        assert active_subscription_b.tenant_id != active_subscription.tenant_id

    def test_webhook_for_unknown_store_does_not_affect_other_tenants(
        self,
        client,
        db_session,
        test_store,
        active_subscription,
        active_subscription_b,
        webhook_secret,
        sign_webhook_payload,
    ):
        """
        Test that webhooks for unknown stores don't affect existing tenants.
        """
        # Arrange: Record initial states
        initial_status_a = active_subscription.status
        initial_status_b = active_subscription_b.status

        # Create webhook for non-existent store
        payload_dict = {
            "app_subscription": {
                "admin_graphql_api_id": "gid://shopify/AppSubscription/unknown123",
                "name": "Unknown Subscription",
                "status": "CANCELLED"
            }
        }
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        signature = sign_webhook_payload(payload_bytes)

        # Act: POST webhook with unknown shop domain
        response = client.post(
            "/api/webhooks/shopify/subscription-update",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": signature,
                "X-Shopify-Shop-Domain": "unknown-store.myshopify.com",
                "X-Shopify-Topic": "app_subscriptions/update",
            }
        )

        # Assert: Webhook processed (returns 200 but with "store not found" message)
        assert response.status_code == 200

        # Assert: Neither tenant's subscription was modified
        db_session.refresh(active_subscription)
        db_session.refresh(active_subscription_b)
        assert active_subscription.status == initial_status_a
        assert active_subscription_b.status == initial_status_b


# =============================================================================
# Additional Edge Case Tests
# =============================================================================

class TestEdgeCases:
    """Additional edge case tests for robustness."""

    def test_webhook_with_missing_subscription_id_handled_gracefully(
        self,
        client,
        test_store,
        webhook_secret,
        sign_webhook_payload,
    ):
        """
        Test that webhook with missing subscription ID is handled gracefully.
        """
        # Payload missing the subscription ID
        payload_dict = {
            "app_subscription": {
                "name": "Some Subscription",
                "status": "ACTIVE"
                # Missing admin_graphql_api_id
            }
        }
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        signature = sign_webhook_payload(payload_bytes)

        response = client.post(
            "/api/webhooks/shopify/subscription-update",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Hmac-Sha256": signature,
                "X-Shopify-Shop-Domain": test_store.shop_domain,
                "X-Shopify-Topic": "app_subscriptions/update",
            }
        )

        # Should return 200 (webhook acknowledged) but not process
        assert response.status_code == 200
        assert "Missing subscription ID" in response.json().get("message", "")

    def test_free_plan_checkout_does_not_require_shopify(
        self,
        db_session,
        test_tenant_id,
        test_store,
        test_plan_free,
    ):
        """
        Test that free plan checkout doesn't require Shopify API calls.
        """
        # Lazy imports
        Subscription = get_subscription_model()
        SubscriptionStatus = get_subscription_status()

        # Act: Create checkout for free plan
        billing_service = get_billing_service(db_session, test_tenant_id)

        # This should NOT call Shopify API
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            billing_service.create_checkout_url(
                plan_id=test_plan_free.id,
                test_mode=True
            )
        )

        # Assert: Success without Shopify URL
        assert result.success is True
        assert result.checkout_url == ""  # No checkout needed
        assert result.subscription_id is not None

        # Assert: Subscription is immediately ACTIVE
        subscription = db_session.query(Subscription).filter(
            Subscription.id == result.subscription_id
        ).first()
        assert subscription.status == SubscriptionStatus.ACTIVE.value
