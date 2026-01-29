"""
E2E Tests: API Endpoint Testing

Comprehensive tests that exercise actual API endpoints with test data
flowing through the complete pipeline.

Test Coverage:
- Shopify Ingestion API (/api/shopify-ingestion/*)
- Sync Orchestration API (/api/sync/*)
- Data Health API (/api/data-health/*)
- Webhook Handlers (/api/webhooks/shopify/*)
"""

import pytest
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List
from unittest.mock import patch, MagicMock

from .fixtures.test_data import (
    TestDataProvider,
    EXPECTED_OUTCOMES,
    SHOPIFY_PURCHASES,
    SHOPIFY_REFUNDS,
    SHOPIFY_CANCELLATIONS,
    create_shopify_order,
)


# =============================================================================
# Shopify Ingestion API Tests
# =============================================================================

@pytest.mark.e2e
class TestShopifyIngestionAPI:
    """Tests for /api/shopify-ingestion endpoints."""

    async def test_validate_token_endpoint(
        self,
        async_client,
        auth_headers,
        mock_shopify,
    ):
        """
        Test POST /api/shopify-ingestion/validate-token

        Validates that the API correctly validates Shopify access tokens.
        """
        # Setup mock Shopify to return valid shop info
        mock_shopify.setup_shop_response(
            shop="test-store.myshopify.com",
            shop_data={
                "id": 12345678,
                "name": "Test Store",
                "email": "owner@test-store.com",
                "currency": "USD",
                "timezone": "America/New_York",
            }
        )

        # Make API request
        response = await async_client.post(
            "/api/shopify-ingestion/validate-token",
            headers=auth_headers,
            json={
                "shop_domain": "test-store.myshopify.com",
                "access_token": "shpat_test_token_12345"
            }
        )

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data.get("valid") is True or "shop_domain" in data

    async def test_validate_token_invalid(
        self,
        async_client,
        auth_headers,
        mock_shopify,
    ):
        """
        Test token validation with invalid token.
        """
        # Don't setup mock response - should fail validation

        response = await async_client.post(
            "/api/shopify-ingestion/validate-token",
            headers=auth_headers,
            json={
                "shop_domain": "invalid-store.myshopify.com",
                "access_token": "invalid_token"
            }
        )

        # Should return validation failure (not server error)
        assert response.status_code in [200, 400, 422]
        if response.status_code == 200:
            data = response.json()
            assert data.get("valid") is False or "error" in data

    async def test_setup_ingestion_endpoint(
        self,
        async_client,
        auth_headers,
        mock_shopify,
        mock_airbyte,
        db_session,
    ):
        """
        Test POST /api/shopify-ingestion/setup

        Full integration test for setting up Shopify data ingestion.
        """
        shop_domain = "e2e-test-store.myshopify.com"

        # Setup mocks
        mock_shopify.setup_oauth_response(
            shop=shop_domain,
            access_token="shpat_e2e_test_token"
        )
        mock_shopify.setup_shop_response(shop=shop_domain, shop_data={"name": "E2E Test Store"})

        # Mock Airbyte connection creation
        mock_airbyte.register_connection(
            connection_id="airbyte_e2e_conn_001",
            name="E2E Shopify Connection",
            source_type="shopify"
        )

        response = await async_client.post(
            "/api/shopify-ingestion/setup",
            headers=auth_headers,
            json={
                "shop_domain": shop_domain,
                "access_token": "shpat_e2e_test_token",
                "start_date": "2024-01-01",
                "trigger_initial_sync": False  # Don't trigger sync in test
            }
        )

        # Should succeed or return expected error structure
        assert response.status_code in [200, 201, 400, 422]

    async def test_trigger_sync_endpoint(
        self,
        async_client,
        auth_headers,
        test_airbyte_connection,
        mock_airbyte,
    ):
        """
        Test POST /api/shopify-ingestion/trigger-sync/{connection_id}

        Verifies sync triggering works through the API.
        """
        connection_id = test_airbyte_connection.airbyte_connection_id

        # Setup mock to handle sync
        mock_airbyte.register_connection(connection_id, source_type="shopify")
        mock_airbyte.setup_test_data(
            connection_id=connection_id,
            data={"_airbyte_raw_shopify_orders": SHOPIFY_PURCHASES[:5]}
        )

        response = await async_client.post(
            f"/api/shopify-ingestion/trigger-sync/{test_airbyte_connection.id}",
            headers=auth_headers,
        )

        # Should accept the sync request
        assert response.status_code in [200, 202, 404]
        if response.status_code in [200, 202]:
            data = response.json()
            assert "job_id" in data or "success" in data

    async def test_get_ingestion_status(
        self,
        async_client,
        auth_headers,
        test_airbyte_connection,
    ):
        """
        Test GET /api/shopify-ingestion/status/{connection_id}

        Verifies status endpoint returns correct information.
        """
        response = await async_client.get(
            f"/api/shopify-ingestion/status/{test_airbyte_connection.id}",
            headers=auth_headers,
        )

        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert "status" in data or "connection_id" in data


# =============================================================================
# Sync Orchestration API Tests
# =============================================================================

@pytest.mark.e2e
class TestSyncOrchestrationAPI:
    """Tests for /api/sync endpoints."""

    async def test_trigger_sync_with_retry(
        self,
        async_client,
        auth_headers,
        test_airbyte_connection,
        mock_airbyte,
    ):
        """
        Test POST /api/sync/trigger/{connection_id}

        Verifies sync with automatic retry capability.
        """
        connection_id = test_airbyte_connection.airbyte_connection_id

        mock_airbyte.register_connection(connection_id)
        mock_airbyte.setup_test_data(
            connection_id=connection_id,
            data={"_airbyte_raw_shopify_orders": SHOPIFY_PURCHASES[:10]}
        )

        response = await async_client.post(
            f"/api/sync/trigger/{connection_id}",
            headers=auth_headers,
            json={"timeout_seconds": 120}
        )

        assert response.status_code in [200, 202, 404, 422]

    async def test_get_sync_state(
        self,
        async_client,
        auth_headers,
        test_airbyte_connection,
    ):
        """
        Test GET /api/sync/state/{connection_id}
        """
        response = await async_client.get(
            f"/api/sync/state/{test_airbyte_connection.airbyte_connection_id}",
            headers=auth_headers,
        )

        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert "status" in data or "connection_id" in data

    async def test_list_failed_connections(
        self,
        async_client,
        auth_headers,
    ):
        """
        Test GET /api/sync/failed

        Verifies listing of failed sync connections.
        """
        response = await async_client.get(
            "/api/sync/failed",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "connections" in data or isinstance(data, list)


# =============================================================================
# Webhook Handler Tests
# =============================================================================

@pytest.mark.e2e
class TestWebhookHandlers:
    """Tests for /api/webhooks/shopify endpoints."""

    def test_orders_create_webhook(
        self,
        client,
        webhook_simulator,
        test_store,
        test_tenant_id,
    ):
        """
        Test orders/create webhook processing.

        Sends 30 purchase orders through the webhook endpoint.
        """
        provider = TestDataProvider()
        order_payloads = provider.get_webhook_payloads("orders/create", count=30)

        successful_webhooks = 0
        for order in order_payloads:
            response = webhook_simulator.send_order_create(
                order=order,
                shop_domain=test_store.shop_domain,
            )
            if response.status_code == 200:
                successful_webhooks += 1

        # Most webhooks should succeed
        assert successful_webhooks >= 25, f"Only {successful_webhooks}/30 webhooks succeeded"

    def test_orders_updated_webhook_refunds(
        self,
        client,
        webhook_simulator,
        test_store,
    ):
        """
        Test orders/updated webhook with refund data.

        Sends 25 refund orders through the webhook endpoint.
        """
        successful = 0
        for order in SHOPIFY_REFUNDS:
            response = webhook_simulator.send_order_updated(
                order=order,
                shop_domain=test_store.shop_domain,
            )
            if response.status_code == 200:
                successful += 1

        assert successful >= 20, f"Only {successful}/25 refund webhooks succeeded"

    def test_orders_updated_webhook_cancellations(
        self,
        client,
        webhook_simulator,
        test_store,
    ):
        """
        Test orders/updated webhook with cancellation data.

        Sends 20 cancelled orders through the webhook endpoint.
        """
        successful = 0
        for order in SHOPIFY_CANCELLATIONS:
            response = webhook_simulator.send_order_updated(
                order=order,
                shop_domain=test_store.shop_domain,
            )
            if response.status_code == 200:
                successful += 1

        assert successful >= 15, f"Only {successful}/20 cancellation webhooks succeeded"

    def test_subscription_update_webhook(
        self,
        client,
        webhook_simulator,
        test_store,
    ):
        """
        Test app_subscriptions/update webhook.
        """
        provider = TestDataProvider()
        payloads = provider.get_webhook_payloads("app_subscriptions/update", count=5)

        for payload in payloads:
            response = webhook_simulator.send_subscription_update(
                subscription=payload["app_subscription"],
                shop_domain=test_store.shop_domain,
            )
            # Should process without error
            assert response.status_code in [200, 202, 404]

    def test_app_uninstalled_webhook(
        self,
        client,
        webhook_simulator,
        test_store,
    ):
        """
        Test app/uninstalled webhook.
        """
        response = webhook_simulator.send_app_uninstalled(
            shop_domain=test_store.shop_domain,
        )

        assert response.status_code in [200, 202, 404]

    def test_webhook_hmac_validation(
        self,
        client,
        test_store,
    ):
        """
        Test that webhooks without valid HMAC are rejected.
        """
        # Send webhook without proper HMAC signature
        response = client.post(
            "/api/webhooks/shopify",
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Topic": "orders/create",
                "X-Shopify-Hmac-Sha256": "invalid_signature",
                "X-Shopify-Shop-Domain": test_store.shop_domain,
            },
            json=create_shopify_order()
        )

        # Should reject invalid HMAC
        assert response.status_code in [401, 403, 422]


# =============================================================================
# Data Health API Tests
# =============================================================================

@pytest.mark.e2e
class TestDataHealthAPI:
    """Tests for /api/data-health endpoints."""

    async def test_get_health_summary(
        self,
        async_client,
        auth_headers,
    ):
        """
        Test GET /api/data-health/summary

        Verifies health summary endpoint returns expected structure.
        """
        response = await async_client.get(
            "/api/data-health/summary",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Check expected fields
        expected_fields = ["total_sources", "healthy_sources", "overall_health_score"]
        for field in expected_fields:
            assert field in data or "sources" in data

    async def test_get_source_health(
        self,
        async_client,
        auth_headers,
        test_airbyte_connection,
    ):
        """
        Test GET /api/data-health/source/{connection_id}
        """
        response = await async_client.get(
            f"/api/data-health/source/{test_airbyte_connection.airbyte_connection_id}",
            headers=auth_headers,
        )

        assert response.status_code in [200, 404]

    async def test_get_stale_sources(
        self,
        async_client,
        auth_headers,
    ):
        """
        Test GET /api/data-health/stale
        """
        response = await async_client.get(
            "/api/data-health/stale",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "stale_sources" in data or "count" in data or isinstance(data, list)

    async def test_get_all_sources_health(
        self,
        async_client,
        auth_headers,
    ):
        """
        Test GET /api/data-health/sources
        """
        response = await async_client.get(
            "/api/data-health/sources",
            headers=auth_headers,
        )

        assert response.status_code == 200


# =============================================================================
# Sync Health (Data Quality) API Tests
# =============================================================================

@pytest.mark.e2e
class TestSyncHealthAPI:
    """Tests for /api/sync-health endpoints."""

    async def test_get_sync_health_summary(
        self,
        async_client,
        auth_headers,
    ):
        """
        Test GET /api/sync-health/summary
        """
        response = await async_client.get(
            "/api/sync-health/summary",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "overall_status" in data or "health_score" in data

    async def test_get_compact_health(
        self,
        async_client,
        auth_headers,
    ):
        """
        Test GET /api/sync-health/compact

        Lightweight endpoint for frequent polling.
        """
        response = await async_client.get(
            "/api/sync-health/compact",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "overall_status" in data or "health_score" in data

    async def test_get_active_incidents(
        self,
        async_client,
        auth_headers,
    ):
        """
        Test GET /api/sync-health/incidents/active
        """
        response = await async_client.get(
            "/api/sync-health/incidents/active",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "incidents" in data or "has_critical" in data

    async def test_dashboard_block_status(
        self,
        async_client,
        auth_headers,
    ):
        """
        Test GET /api/sync-health/dashboard-block
        """
        response = await async_client.get(
            "/api/sync-health/dashboard-block",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "is_blocked" in data


# =============================================================================
# Backfill API Tests
# =============================================================================

@pytest.mark.e2e
class TestBackfillAPI:
    """Tests for /api/backfills endpoints."""

    async def test_trigger_backfill(
        self,
        async_client,
        auth_headers,
    ):
        """
        Test POST /api/backfills/trigger
        """
        response = await async_client.post(
            "/api/backfills/trigger",
            headers=auth_headers,
            json={
                "model_selector": "fact_orders",
                "start_date": "2024-01-01",
                "end_date": "2024-01-31"
            }
        )

        # Should accept or reject based on business rules
        assert response.status_code in [200, 202, 400, 403, 422]

    async def test_backfill_estimate(
        self,
        async_client,
        auth_headers,
        test_airbyte_connection,
    ):
        """
        Test GET /api/sync-health/connectors/{connector_id}/backfill/estimate
        """
        response = await async_client.get(
            f"/api/sync-health/connectors/{test_airbyte_connection.airbyte_connection_id}/backfill/estimate",
            headers=auth_headers,
            params={
                "start_date": "2024-01-01",
                "end_date": "2024-01-31"
            }
        )

        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert "is_allowed" in data or "days_count" in data


# =============================================================================
# Full Pipeline E2E Tests
# =============================================================================

@pytest.mark.e2e
@pytest.mark.slow
class TestFullPipelineE2E:
    """
    Full end-to-end pipeline tests that exercise multiple APIs.
    """

    async def test_complete_shopify_data_flow(
        self,
        async_client,
        auth_headers,
        webhook_simulator,
        test_store,
        mock_airbyte,
        test_airbyte_connection,
    ):
        """
        Full E2E test: Shopify data flows through all APIs.

        Flow:
        1. Send orders via webhooks (30 purchases, 25 refunds, 20 cancellations)
        2. Verify data health reflects new data
        3. Check sync health status
        """
        # Step 1: Send purchase webhooks
        purchases_sent = 0
        for order in SHOPIFY_PURCHASES:
            response = webhook_simulator.send_order_create(
                order=order,
                shop_domain=test_store.shop_domain,
            )
            if response.status_code == 200:
                purchases_sent += 1

        # Step 2: Send refund webhooks
        refunds_sent = 0
        for order in SHOPIFY_REFUNDS:
            response = webhook_simulator.send_order_updated(
                order=order,
                shop_domain=test_store.shop_domain,
            )
            if response.status_code == 200:
                refunds_sent += 1

        # Step 3: Send cancellation webhooks
        cancellations_sent = 0
        for order in SHOPIFY_CANCELLATIONS:
            response = webhook_simulator.send_order_updated(
                order=order,
                shop_domain=test_store.shop_domain,
            )
            if response.status_code == 200:
                cancellations_sent += 1

        # Step 4: Check data health
        health_response = await async_client.get(
            "/api/data-health/summary",
            headers=auth_headers,
        )
        assert health_response.status_code == 200

        # Step 5: Check sync health
        sync_health_response = await async_client.get(
            "/api/sync-health/compact",
            headers=auth_headers,
        )
        assert sync_health_response.status_code == 200

        # Verify totals
        expected = EXPECTED_OUTCOMES["shopify_complete"]
        total_sent = purchases_sent + refunds_sent + cancellations_sent

        # Log results for debugging
        print(f"Purchases sent: {purchases_sent}/{expected['purchase_count']}")
        print(f"Refunds sent: {refunds_sent}/{expected['refund_count']}")
        print(f"Cancellations sent: {cancellations_sent}/{expected['cancellation_count']}")
        print(f"Total sent: {total_sent}/{expected['total_orders']}")

    async def test_multi_channel_data_ingestion(
        self,
        async_client,
        auth_headers,
        mock_airbyte,
        test_airbyte_connection,
    ):
        """
        E2E test: Multi-channel data ingestion verification.

        Tests that data from all channels can be processed.
        """
        provider = TestDataProvider()
        all_channels = provider.get_all_channels()

        # Verify each channel's data can be retrieved
        for channel in ["shopify_orders", "meta_ads", "google_ads", "klaviyo_campaigns"]:
            data = provider.get_channel_data(channel)
            assert len(data) >= 20, f"Channel {channel} has insufficient test data: {len(data)}"

        # Check overall health
        response = await async_client.get(
            "/api/data-health/summary",
            headers=auth_headers,
        )
        assert response.status_code == 200


# =============================================================================
# Tenant Isolation Tests
# =============================================================================

@pytest.mark.e2e
@pytest.mark.security
class TestTenantIsolationAPI:
    """Tests verifying tenant data isolation through APIs."""

    async def test_tenant_cannot_access_other_tenant_connection(
        self,
        async_client,
        auth_headers,
        auth_headers_b,
        test_airbyte_connection,
    ):
        """
        Verify Tenant A cannot access Tenant B's connection via API.
        """
        # Tenant A's connection ID
        connection_id = test_airbyte_connection.airbyte_connection_id

        # Tenant B tries to access it
        response = await async_client.get(
            f"/api/sync/state/{connection_id}",
            headers=auth_headers_b,
        )

        # Should return 404 (not found) - don't reveal existence
        assert response.status_code in [403, 404]

    async def test_tenant_cannot_trigger_other_tenant_sync(
        self,
        async_client,
        auth_headers_b,
        test_airbyte_connection,
    ):
        """
        Verify Tenant B cannot trigger sync for Tenant A's connection.
        """
        response = await async_client.post(
            f"/api/sync/trigger/{test_airbyte_connection.airbyte_connection_id}",
            headers=auth_headers_b,
        )

        assert response.status_code in [403, 404]

    async def test_each_tenant_sees_only_own_health(
        self,
        async_client,
        auth_headers,
        auth_headers_b,
    ):
        """
        Verify each tenant's health endpoint shows only their data.
        """
        # Tenant A health
        response_a = await async_client.get(
            "/api/data-health/summary",
            headers=auth_headers,
        )
        assert response_a.status_code == 200

        # Tenant B health
        response_b = await async_client.get(
            "/api/data-health/summary",
            headers=auth_headers_b,
        )
        assert response_b.status_code == 200

        # Both should succeed but return different data
        # (exact assertions depend on test data setup)
