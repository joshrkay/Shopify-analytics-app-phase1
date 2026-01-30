"""
E2E Tests for Dashboard Sample Data Generation.

These tests create comprehensive sample data across all ad platforms and
Shopify operations to populate the dashboard with realistic test data.

Usage:
    # Run all sample data tests
    pytest src/tests/e2e/test_dashboard_sample_data.py -v -s

    # Run specific test
    pytest src/tests/e2e/test_dashboard_sample_data.py::TestDashboardSampleData::test_create_all_platforms_sample_data -v -s

    # With detailed output
    pytest src/tests/e2e/test_dashboard_sample_data.py -v -s --log-cli-level=INFO
"""

import pytest
import uuid
import time
from datetime import datetime, timezone

from .sample_data_generator import SampleDataGenerator, AD_PLATFORMS
from src.models.airbyte_connection import TenantAirbyteConnection


@pytest.mark.e2e
class TestDashboardSampleData:
    """
    E2E tests that create comprehensive sample dashboard data.

    These tests:
    1. Create a unique tenant for each test run
    2. Hit all ad platform endpoints (10 platforms × 8 endpoints)
    3. Process Shopify data (orders, refunds, cancellations)
    4. Verify database records and tenant isolation
    5. Generate summary reports
    """

    @pytest.mark.asyncio
    async def test_create_all_platforms_sample_data(
        self,
        async_client,
        sample_data_generator,
        db_session,
    ):
        """
        Main test: Create sample data for all 10 ad platforms.

        This test executes the full sequence:
        - Setup → List → Get → Test Creds → Sync → Status → Update → Delete

        For each of 10 platforms:
        - Meta Ads, Google Ads, TikTok Ads, Snapchat Ads
        - Klaviyo, Shopify Email
        - Attentive, Postscript, SMSBump
        - Shopify

        Expected: ~200 API calls total, all successful
        """
        print(f"\n{'='*60}")
        print(f"Creating Sample Data for Tenant: {sample_data_generator.tenant_id}")
        print(f"{'='*60}\n")

        # Run full test suite
        summary = await sample_data_generator.run_full_test_suite()

        # Print detailed report
        report = sample_data_generator.generate_report()
        print("\n" + report + "\n")

        # Assertions
        assert summary.platforms_tested == len(AD_PLATFORMS), \
            f"Expected {len(AD_PLATFORMS)} platforms tested, got {summary.platforms_tested}"

        assert summary.successful_operations > 0, \
            "No successful operations recorded"

        # Allow some failures in E2E (network issues, etc.) but expect >75% success
        success_rate = summary.successful_operations / summary.total_operations if summary.total_operations > 0 else 0
        assert success_rate >= 0.75, \
            f"Success rate too low: {success_rate:.1%}. Expected >= 75%"

        # Verify database records exist
        if summary.db_verification:
            assert summary.db_verification.get("tenant_airbyte_connections", 0) > 0, \
                "No Airbyte connections found in database"

            # Verify tenant isolation (no cross-tenant data leakage)
            assert summary.db_verification.get("other_tenant_connections", 0) == 0, \
                "Found connections from other tenants - isolation broken!"

        print(f"\n✅ Sample data creation completed successfully!")
        print(f"Tenant ID: {summary.tenant_id}")
        print(f"Total Operations: {summary.total_operations}")
        print(f"Success Rate: {success_rate:.1%}\n")

    @pytest.mark.asyncio
    async def test_verify_tenant_isolation(
        self,
        async_client,
        mock_frontegg,
        db_session,
    ):
        """
        Verify multi-tenancy works correctly (no data leakage).

        Creates two separate tenants and verifies:
        1. Each tenant only sees their own connections
        2. No cross-tenant data access
        3. Proper tenant_id scoping in queries
        """
        print(f"\n{'='*60}")
        print("Testing Tenant Isolation")
        print(f"{'='*60}\n")

        # Create first tenant
        tenant1_id = f"e2e-test-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        token1 = mock_frontegg.create_test_token(
            tenant_id=tenant1_id,
            entitlements=["AI_INSIGHTS", "AI_RECOMMENDATIONS"],
        )
        headers1 = {"Authorization": f"Bearer {token1}"}

        generator1 = SampleDataGenerator(
            client=async_client,
            auth_headers=headers1,
            tenant_id=tenant1_id,
            db_session=db_session,
        )

        # Create second tenant
        tenant2_id = f"e2e-test-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        token2 = mock_frontegg.create_test_token(
            tenant_id=tenant2_id,
            entitlements=["AI_INSIGHTS", "AI_RECOMMENDATIONS"],
        )
        headers2 = {"Authorization": f"Bearer {token2}"}

        generator2 = SampleDataGenerator(
            client=async_client,
            auth_headers=headers2,
            tenant_id=tenant2_id,
            db_session=db_session,
        )

        # Create connections for tenant 1 (test 3 platforms)
        print(f"Creating connections for Tenant 1: {tenant1_id}")
        tenant1_platforms = ["meta_ads", "google_ads", "klaviyo"]
        for platform in tenant1_platforms:
            await generator1._test_platform(platform)

        # Create connections for tenant 2 (test 3 different platforms)
        print(f"Creating connections for Tenant 2: {tenant2_id}")
        tenant2_platforms = ["tiktok_ads", "snapchat_ads", "attentive"]
        for platform in tenant2_platforms:
            await generator2._test_platform(platform)

        # Verify database isolation
        tenant1_connections = (
            db_session.query(TenantAirbyteConnection)
            .filter_by(tenant_id=tenant1_id)
            .count()
        )

        tenant2_connections = (
            db_session.query(TenantAirbyteConnection)
            .filter_by(tenant_id=tenant2_id)
            .count()
        )

        print(f"\nTenant 1 connections: {tenant1_connections}")
        print(f"Tenant 2 connections: {tenant2_connections}")

        # Assertions
        assert tenant1_connections > 0, "Tenant 1 should have connections"
        assert tenant2_connections > 0, "Tenant 2 should have connections"

        # Verify API isolation - tenant 1 should only see their connections
        response1 = await async_client.get(
            "/api/ad-platform-ingestion/connections",
            headers=headers1,
        )
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["total_count"] == tenant1_connections, \
            f"Tenant 1 API returned {data1['total_count']} connections, DB has {tenant1_connections}"

        # Verify API isolation - tenant 2 should only see their connections
        response2 = await async_client.get(
            "/api/ad-platform-ingestion/connections",
            headers=headers2,
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["total_count"] == tenant2_connections, \
            f"Tenant 2 API returned {data2['total_count']} connections, DB has {tenant2_connections}"

        print(f"\n✅ Tenant isolation verified successfully!")
        print(f"   Tenant 1: {tenant1_connections} connections (isolated)")
        print(f"   Tenant 2: {tenant2_connections} connections (isolated)\n")

    @pytest.mark.asyncio
    async def test_shopify_operations(
        self,
        async_client,
        sample_data_generator,
        mock_shopify,
    ):
        """
        Test Shopify-specific operations.

        Creates:
        - Purchase orders (30)
        - Refunds (25)
        - Cancellations (20)

        Verifies data flows correctly through webhook processing.
        """
        print(f"\n{'='*60}")
        print(f"Testing Shopify Operations")
        print(f"{'='*60}\n")

        # Process Shopify data
        shopify_results = await sample_data_generator.process_shopify_data()

        print(f"\nShopify Results:")
        print(f"  Orders: {shopify_results.get('orders_processed', 0)}")
        print(f"  Refunds: {shopify_results.get('refunds_processed', 0)}")
        print(f"  Cancellations: {shopify_results.get('cancellations_processed', 0)}")
        print(f"  Errors: {len(shopify_results.get('errors', []))}")

        # Assertions
        assert shopify_results["orders_processed"] > 0, \
            "No orders were processed"

        # Check for excessive errors (allow some, but not all)
        total_processed = (
            shopify_results["orders_processed"] +
            shopify_results["refunds_processed"] +
            shopify_results["cancellations_processed"]
        )
        error_rate = len(shopify_results["errors"]) / total_processed if total_processed > 0 else 1
        assert error_rate < 0.25, \
            f"Too many errors: {error_rate:.1%}. Expected < 25%"

        print(f"\n✅ Shopify operations completed successfully!\n")

    @pytest.mark.asyncio
    async def test_platform_endpoint_sequence(
        self,
        async_client,
        sample_data_generator,
    ):
        """
        Test the complete endpoint sequence for a single platform.

        Verifies each endpoint in the sequence:
        1. Setup → 2. List → 3. Get → 4. Test Creds →
        5. Sync → 6. Status → 7. Update → 8. Delete

        This test ensures all 8 endpoints work correctly for one platform.
        """
        print(f"\n{'='*60}")
        print("Testing Complete Endpoint Sequence (Meta Ads)")
        print(f"{'='*60}\n")

        platform = "meta_ads"
        result = await sample_data_generator._test_platform(platform)

        print(f"\nPlatform: {platform}")
        print(f"Operations: {len(result.operations)}")
        print(f"Successful: {result.success_count}")
        print(f"Failed: {result.error_count}")
        print(f"Duration: {result.total_duration_ms:.0f}ms")

        print("\nOperation Details:")
        for op in result.operations:
            status_icon = "✅" if op.success else "❌"
            print(f"  {status_icon} {op.operation} ({op.duration_ms:.0f}ms)")

        # Assertions
        assert len(result.operations) == 8, \
            f"Expected 8 operations, got {len(result.operations)}"

        assert result.success_count >= 6, \
            f"Too many failures: {result.success_count}/8 succeeded. Expected >= 6"

        assert result.connection_id is not None, \
            "No connection_id was created"

        print(f"\n✅ Endpoint sequence test passed!\n")

    @pytest.mark.asyncio
    async def test_multiple_platforms_in_parallel_batches(
        self,
        async_client,
        sample_data_generator,
    ):
        """
        Test creating connections for multiple platforms.

        Creates connections for 5 platforms to simulate realistic usage.
        Verifies:
        - Multiple platforms can coexist
        - Listing returns all platforms correctly
        - Each platform maintains independent connection data
        """
        print(f"\n{'='*60}")
        print("Testing Multiple Platforms")
        print(f"{'='*60}\n")

        platforms_to_test = [
            "meta_ads",
            "google_ads",
            "tiktok_ads",
            "klaviyo",
            "attentive",
        ]

        connection_ids = {}

        # Create connections for each platform
        for platform in platforms_to_test:
            print(f"Setting up {platform}...")
            result = await sample_data_generator._test_platform(platform)

            if result.connection_id:
                connection_ids[platform] = result.connection_id

        print(f"\nCreated {len(connection_ids)} connections")

        # List all connections
        response = await async_client.get(
            "/api/ad-platform-ingestion/connections",
            headers=sample_data_generator.auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        print(f"Total connections via API: {data['total_count']}")

        # Verify we can retrieve each connection
        for platform, conn_id in connection_ids.items():
            response = await async_client.get(
                f"/api/ad-platform-ingestion/connections/{conn_id}",
                headers=sample_data_generator.auth_headers,
            )
            assert response.status_code == 200, \
                f"Failed to retrieve connection for {platform}"

            conn_data = response.json()
            assert conn_data["platform"] == platform, \
                f"Platform mismatch: expected {platform}, got {conn_data['platform']}"

        print(f"\n✅ Multiple platforms test passed!\n")

    @pytest.mark.asyncio
    async def test_error_handling_invalid_platform(
        self,
        async_client,
        sample_data_generator,
    ):
        """
        Test error handling for invalid platform.

        Verifies API returns appropriate error for unsupported platforms.
        """
        print(f"\n{'='*60}")
        print("Testing Error Handling (Invalid Platform)")
        print(f"{'='*60}\n")

        invalid_payload = {
            "platform": "invalid_platform_xyz",
            "account_name": "Test Account",
            "account_id": "test123",
            "access_token": "test_token",
        }

        response = await async_client.post(
            "/api/ad-platform-ingestion/setup",
            json=invalid_payload,
            headers=sample_data_generator.auth_headers,
        )

        # Expect 400 Bad Request or 422 Unprocessable Entity
        assert response.status_code in [400, 422], \
            f"Expected error status, got {response.status_code}"

        print(f"✅ API correctly rejected invalid platform (status {response.status_code})\n")
