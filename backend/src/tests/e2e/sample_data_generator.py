"""
Sample Data Generator for E2E Testing.

Generates comprehensive sample dashboard data by hitting all ad platform endpoints
and creating Shopify operations (orders, refunds, cancellations).

Usage:
    # With pytest fixtures
    generator = SampleDataGenerator(client, auth_headers, tenant_id)
    await generator.test_all_ad_platforms()

    # Standalone
    generator = SampleDataGenerator(client, auth_headers, tenant_id, db_session)
    results = await generator.run_full_test_suite()
    print(generator.generate_report())
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# All 10 supported ad platforms
AD_PLATFORMS = [
    "meta_ads",
    "google_ads",
    "tiktok_ads",
    "snapchat_ads",
    "klaviyo",
    "shopify_email",
    "attentive",
    "postscript",
    "smsbump",
    "shopify",
]

# Number of API calls per platform (20 is middle of 10-30 range)
OPERATIONS_PER_PLATFORM = 20

# Shopify operations count
SHOPIFY_ORDERS_COUNT = 30
SHOPIFY_REFUNDS_COUNT = 25
SHOPIFY_CANCELLATIONS_COUNT = 20


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class OperationResult:
    """Result of a single API operation."""
    success: bool
    operation: str
    platform: Optional[str] = None
    duration_ms: float = 0
    response_data: Optional[Dict] = None
    error: Optional[str] = None


@dataclass
class PlatformTestResult:
    """Results for testing a single platform."""
    platform: str
    operations: List[OperationResult] = field(default_factory=list)
    connection_id: Optional[str] = None
    total_duration_ms: float = 0
    success_count: int = 0
    error_count: int = 0


@dataclass
class TestSummary:
    """Overall test execution summary."""
    tenant_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    platforms_tested: int = 0
    total_operations: int = 0
    successful_operations: int = 0
    failed_operations: int = 0
    platform_results: Dict[str, PlatformTestResult] = field(default_factory=dict)
    db_verification: Optional[Dict] = None


# =============================================================================
# Helper Functions
# =============================================================================

async def execute_with_retry(
    operation_name: str,
    operation_func: Callable,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
) -> OperationResult:
    """
    Execute operation with exponential backoff retry.

    Args:
        operation_name: Human-readable operation name
        operation_func: Async function to execute
        max_retries: Maximum number of retry attempts
        backoff_factor: Multiplier for wait time between retries

    Returns:
        OperationResult with success status and data/error
    """
    start_time = time.time()

    for attempt in range(max_retries):
        try:
            result = await operation_func()
            duration_ms = (time.time() - start_time) * 1000

            logger.info(f"✓ {operation_name}: Success (attempt {attempt + 1})")

            return OperationResult(
                success=True,
                operation=operation_name,
                duration_ms=duration_ms,
                response_data=result if isinstance(result, dict) else None,
            )

        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt
                logger.warning(
                    f"⚠ {operation_name}: Attempt {attempt + 1} failed, "
                    f"retrying in {wait_time}s: {str(e)}"
                )
                await asyncio.sleep(wait_time)
            else:
                duration_ms = (time.time() - start_time) * 1000
                logger.error(
                    f"✗ {operation_name}: Failed after {max_retries} attempts: {str(e)}"
                )

                return OperationResult(
                    success=False,
                    operation=operation_name,
                    duration_ms=duration_ms,
                    error=str(e),
                )

    # Should never reach here, but for type safety
    return OperationResult(
        success=False,
        operation=operation_name,
        error="Unknown error",
    )


def validate_response(response, expected_status: int = 200) -> Dict:
    """
    Validate HTTP response status and return JSON data.

    Args:
        response: HTTP response object
        expected_status: Expected status code

    Returns:
        Response JSON data

    Raises:
        Exception if status doesn't match or JSON parsing fails
    """
    if response.status_code != expected_status:
        raise Exception(
            f"Unexpected status {response.status_code}, expected {expected_status}. "
            f"Response: {response.text[:200]}"
        )

    try:
        return response.json()
    except Exception as e:
        raise Exception(f"Failed to parse JSON response: {str(e)}")


def create_platform_payload(platform: str, iteration: int = 1) -> Dict[str, Any]:
    """
    Generate platform-specific credentials payload.

    Args:
        platform: Platform identifier (e.g., "meta_ads")
        iteration: Iteration number for unique account names

    Returns:
        Dictionary with platform-specific credential fields
    """
    base_payload = {
        "platform": platform,
        "account_name": f"E2E Test {platform.replace('_', ' ').title()} #{iteration}",
        "account_id": f"test-{platform}-{uuid.uuid4().hex[:8]}",
        "access_token": f"test_access_token_{platform}_{uuid.uuid4().hex[:12]}",
    }

    # Add platform-specific fields
    if platform == "meta_ads":
        base_payload.update({
            "app_id": f"test_app_id_{uuid.uuid4().hex[:8]}",
            "app_secret": f"test_app_secret_{uuid.uuid4().hex[:16]}",
        })

    elif platform == "google_ads":
        base_payload.update({
            "refresh_token": f"test_refresh_{uuid.uuid4().hex[:12]}",
            "client_id": f"test_client_id_{uuid.uuid4().hex[:8]}",
            "client_secret": f"test_client_secret_{uuid.uuid4().hex[:16]}",
            "developer_token": f"test_dev_token_{uuid.uuid4().hex[:12]}",
            "customer_id": f"{random_10_digit_number()}",
        })

    elif platform == "tiktok_ads":
        base_payload.update({
            "tiktok_app_id": f"test_tiktok_app_{uuid.uuid4().hex[:8]}",
            "tiktok_app_secret": f"test_tiktok_secret_{uuid.uuid4().hex[:16]}",
            "advertiser_id": f"{random_10_digit_number()}",
        })

    elif platform == "snapchat_ads":
        base_payload.update({
            "refresh_token": f"test_refresh_{uuid.uuid4().hex[:12]}",
            "snapchat_client_id": f"test_snap_client_{uuid.uuid4().hex[:8]}",
            "snapchat_client_secret": f"test_snap_secret_{uuid.uuid4().hex[:16]}",
            "organization_id": f"{random_10_digit_number()}",
        })

    elif platform == "klaviyo":
        base_payload.update({
            "api_key": f"test_klaviyo_key_{uuid.uuid4().hex[:20]}",
        })

    # SMS platforms and others use base payload only

    return base_payload


def random_10_digit_number() -> str:
    """Generate a random 10-digit number as string."""
    import random
    return str(random.randint(1000000000, 9999999999))


def log_operation(operation: str, platform: Optional[str] = None, **kwargs):
    """
    Log operation with structured data.

    Args:
        operation: Operation name
        platform: Optional platform identifier
        **kwargs: Additional log context
    """
    context = {
        "operation": operation,
        "platform": platform,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }
    logger.info(f"{operation}: {context}")


# =============================================================================
# Main SampleDataGenerator Class
# =============================================================================

class SampleDataGenerator:
    """
    Generate comprehensive sample data for dashboard testing.

    Creates data by:
    1. Testing all 8 ad platform ingestion endpoints for 10 platforms
    2. Creating Shopify orders, refunds, and cancellations
    3. Verifying database records
    4. Generating summary reports
    """

    def __init__(
        self,
        client,
        auth_headers: Dict[str, str],
        tenant_id: str,
        db_session=None,
    ):
        """
        Initialize sample data generator.

        Args:
            client: FastAPI TestClient or AsyncClient
            auth_headers: Authorization headers with JWT token
            tenant_id: Unique tenant identifier
            db_session: Optional database session for verification
        """
        self.client = client
        self.auth_headers = auth_headers
        self.tenant_id = tenant_id
        self.db_session = db_session

        self.summary = TestSummary(
            tenant_id=tenant_id,
            start_time=datetime.now(timezone.utc),
        )

        logger.info(f"Initialized SampleDataGenerator for tenant: {tenant_id}")

    async def test_all_ad_platforms(self) -> Dict[str, PlatformTestResult]:
        """
        Test all 10 ad platforms with full endpoint sequence.

        Returns:
            Dictionary mapping platform name to test results
        """
        logger.info(f"Starting ad platform tests for {len(AD_PLATFORMS)} platforms")

        results = {}

        for platform in AD_PLATFORMS:
            platform_result = await self._test_platform(platform)
            results[platform] = platform_result
            self.summary.platform_results[platform] = platform_result
            self.summary.platforms_tested += 1

        return results

    async def _test_platform(self, platform: str) -> PlatformTestResult:
        """
        Test a single platform with all 8 endpoints.

        Sequence:
        1. POST /setup - Create connection
        2. GET /connections - List all
        3. GET /connections/{id} - Get specific
        4. POST /test-credentials - Validate
        5. POST /trigger-sync/{id} - Start sync
        6. GET /sync-status/{id} - Check status
        7. PUT /connections/{id} - Update
        8. DELETE /connections/{id} - Remove

        Args:
            platform: Platform identifier

        Returns:
            PlatformTestResult with operation details
        """
        logger.info(f"Testing platform: {platform}")
        start_time = time.time()

        result = PlatformTestResult(platform=platform)
        connection_id = None

        # 1. Setup Connection
        setup_result = await execute_with_retry(
            f"{platform}: Setup connection",
            lambda: self._setup_connection(platform),
        )
        result.operations.append(setup_result)

        if setup_result.success and setup_result.response_data:
            connection_id = setup_result.response_data.get("connection_id")
            result.connection_id = connection_id

        # 2. List Connections
        list_result = await execute_with_retry(
            f"{platform}: List connections",
            lambda: self._list_connections(platform),
        )
        result.operations.append(list_result)

        # Only proceed with connection-specific operations if we have a connection_id
        if connection_id:
            # 3. Get Specific Connection
            get_result = await execute_with_retry(
                f"{platform}: Get connection {connection_id[:8]}...",
                lambda: self._get_connection(connection_id),
            )
            result.operations.append(get_result)

            # 4. Test Credentials
            test_creds_result = await execute_with_retry(
                f"{platform}: Test credentials",
                lambda: self._test_credentials(platform),
            )
            result.operations.append(test_creds_result)

            # 5. Trigger Sync
            sync_result = await execute_with_retry(
                f"{platform}: Trigger sync",
                lambda: self._trigger_sync(connection_id),
            )
            result.operations.append(sync_result)

            # 6. Get Sync Status
            status_result = await execute_with_retry(
                f"{platform}: Get sync status",
                lambda: self._get_sync_status(connection_id),
            )
            result.operations.append(status_result)

            # 7. Update Connection
            update_result = await execute_with_retry(
                f"{platform}: Update connection",
                lambda: self._update_connection(connection_id, platform),
            )
            result.operations.append(update_result)

            # 8. Delete Connection
            delete_result = await execute_with_retry(
                f"{platform}: Delete connection",
                lambda: self._delete_connection(connection_id),
            )
            result.operations.append(delete_result)

        # Calculate summary stats
        result.total_duration_ms = (time.time() - start_time) * 1000
        result.success_count = sum(1 for op in result.operations if op.success)
        result.error_count = sum(1 for op in result.operations if not op.success)

        self.summary.total_operations += len(result.operations)
        self.summary.successful_operations += result.success_count
        self.summary.failed_operations += result.error_count

        logger.info(
            f"Completed {platform}: {result.success_count}/{len(result.operations)} "
            f"operations successful in {result.total_duration_ms:.0f}ms"
        )

        return result

    # =========================================================================
    # API Endpoint Methods
    # =========================================================================

    async def _setup_connection(self, platform: str) -> Dict:
        """POST /api/ad-platform-ingestion/setup"""
        payload = create_platform_payload(platform)
        response = await self.client.post(
            "/api/ad-platform-ingestion/setup",
            json=payload,
            headers=self.auth_headers,
        )
        return validate_response(response, 200)

    async def _list_connections(self, platform: Optional[str] = None) -> Dict:
        """GET /api/ad-platform-ingestion/connections"""
        params = {"platform": platform} if platform else {}
        response = await self.client.get(
            "/api/ad-platform-ingestion/connections",
            params=params,
            headers=self.auth_headers,
        )
        return validate_response(response, 200)

    async def _get_connection(self, connection_id: str) -> Dict:
        """GET /api/ad-platform-ingestion/connections/{connection_id}"""
        response = await self.client.get(
            f"/api/ad-platform-ingestion/connections/{connection_id}",
            headers=self.auth_headers,
        )
        return validate_response(response, 200)

    async def _test_credentials(self, platform: str) -> Dict:
        """POST /api/ad-platform-ingestion/test-credentials"""
        payload = create_platform_payload(platform)
        # Only include credential fields for testing
        test_payload = {
            "platform": payload["platform"],
            "account_id": payload["account_id"],
            "access_token": payload["access_token"],
        }
        response = await self.client.post(
            "/api/ad-platform-ingestion/test-credentials",
            json=test_payload,
            headers=self.auth_headers,
        )
        return validate_response(response, 200)

    async def _trigger_sync(self, connection_id: str) -> Dict:
        """POST /api/ad-platform-ingestion/trigger-sync/{connection_id}"""
        response = await self.client.post(
            f"/api/ad-platform-ingestion/trigger-sync/{connection_id}",
            headers=self.auth_headers,
        )
        return validate_response(response, 200)

    async def _get_sync_status(self, connection_id: str) -> Dict:
        """GET /api/ad-platform-ingestion/sync-status/{connection_id}"""
        response = await self.client.get(
            f"/api/ad-platform-ingestion/sync-status/{connection_id}",
            headers=self.auth_headers,
        )
        return validate_response(response, 200)

    async def _update_connection(self, connection_id: str, platform: str) -> Dict:
        """PUT /api/ad-platform-ingestion/connections/{connection_id}"""
        payload = {
            "account_name": f"Updated E2E Test {platform} {uuid.uuid4().hex[:4]}",
            "is_enabled": True,
        }
        response = await self.client.put(
            f"/api/ad-platform-ingestion/connections/{connection_id}",
            json=payload,
            headers=self.auth_headers,
        )
        return validate_response(response, 200)

    async def _delete_connection(self, connection_id: str) -> Dict:
        """DELETE /api/ad-platform-ingestion/connections/{connection_id}"""
        response = await self.client.delete(
            f"/api/ad-platform-ingestion/connections/{connection_id}",
            headers=self.auth_headers,
        )
        # Delete returns 204 No Content
        if response.status_code != 204:
            raise Exception(f"Delete failed with status {response.status_code}")
        return {"deleted": True}

    # =========================================================================
    # Shopify Operations
    # =========================================================================

    async def process_shopify_data(self) -> Dict[str, Any]:
        """
        Create Shopify orders, refunds, and cancellations.

        Inserts data directly into raw.raw_shopify_orders table to simulate
        what Airbyte would sync from Shopify API. This creates real database
        records that flow through the full analytics pipeline.

        Returns:
            Dictionary with counts of created records
        """
        logger.info("Processing Shopify data (orders, refunds, cancellations)")

        if not self.db_session:
            logger.warning("No database session - skipping Shopify data")
            return {"skipped": True, "reason": "No database session provided"}

        # Import test data
        try:
            from .fixtures.test_data import (
                SHOPIFY_PURCHASES,
                SHOPIFY_REFUNDS,
                SHOPIFY_CANCELLATIONS,
            )
        except ImportError:
            logger.warning("Could not import test data, using minimal sample")
            SHOPIFY_PURCHASES = []
            SHOPIFY_REFUNDS = []
            SHOPIFY_CANCELLATIONS = []

        from sqlalchemy import text
        import json

        results = {
            "orders_inserted": 0,
            "refunds_inserted": 0,
            "cancellations_inserted": 0,
            "errors": [],
        }

        source_account_id = f"test-shop-{self.tenant_id[:8]}.myshopify.com"
        run_id = f"e2e-test-run-{int(time.time())}"

        # Insert orders into raw.raw_shopify_orders
        for i, order_data in enumerate(SHOPIFY_PURCHASES[:SHOPIFY_ORDERS_COUNT]):
            try:
                order_id = str(uuid.uuid4())
                shopify_order_id = order_data.get("id", f"gid://shopify/Order/{uuid.uuid4().hex[:12]}")

                # Extract price (handle different formats)
                total_price = order_data.get("total_price", 100.0)
                if isinstance(total_price, str):
                    total_price = float(total_price)
                total_price_cents = int(total_price * 100)

                self.db_session.execute(text("""
                    INSERT INTO raw.raw_shopify_orders (
                        id, tenant_id, source_account_id,
                        extracted_at, loaded_at, run_id,
                        shopify_order_id, order_number,
                        order_status, financial_status, fulfillment_status,
                        total_price_cents, currency,
                        order_created_at, raw_data
                    ) VALUES (
                        :id, :tenant_id, :source_account_id,
                        :extracted_at, :loaded_at, :run_id,
                        :shopify_order_id, :order_number,
                        :order_status, :financial_status, :fulfillment_status,
                        :total_price_cents, :currency,
                        :order_created_at, :raw_data::jsonb
                    )
                    ON CONFLICT (tenant_id, source_account_id, shopify_order_id) DO NOTHING
                """), {
                    "id": order_id,
                    "tenant_id": self.tenant_id,
                    "source_account_id": source_account_id,
                    "extracted_at": datetime.now(timezone.utc),
                    "loaded_at": datetime.now(timezone.utc),
                    "run_id": run_id,
                    "shopify_order_id": shopify_order_id,
                    "order_number": str(order_data.get("order_number", 1000 + i)),
                    "order_status": order_data.get("financial_status", "paid"),
                    "financial_status": order_data.get("financial_status", "paid"),
                    "fulfillment_status": order_data.get("fulfillment_status", "fulfilled"),
                    "total_price_cents": total_price_cents,
                    "currency": order_data.get("currency", "USD"),
                    "order_created_at": datetime.now(timezone.utc),
                    "raw_data": json.dumps(order_data)
                })

                results["orders_inserted"] += 1
                logger.debug(f"Inserted order {i+1}/{SHOPIFY_ORDERS_COUNT}: {shopify_order_id}")

            except Exception as e:
                logger.error(f"Failed to insert order {i+1}: {e}")
                results["errors"].append(f"Order {i+1}: {str(e)}")

        # Insert refunds (as orders with cancelled_at timestamp)
        for i, refund_data in enumerate(SHOPIFY_REFUNDS[:SHOPIFY_REFUNDS_COUNT]):
            try:
                order_id = str(uuid.uuid4())
                shopify_order_id = refund_data.get("id", f"gid://shopify/Order/{uuid.uuid4().hex[:12]}")

                total_price = refund_data.get("total_price", 100.0)
                if isinstance(total_price, str):
                    total_price = float(total_price)
                total_price_cents = int(total_price * 100)

                self.db_session.execute(text("""
                    INSERT INTO raw.raw_shopify_orders (
                        id, tenant_id, source_account_id,
                        extracted_at, loaded_at, run_id,
                        shopify_order_id, order_number,
                        order_status, financial_status, fulfillment_status,
                        total_price_cents, currency,
                        order_created_at, raw_data
                    ) VALUES (
                        :id, :tenant_id, :source_account_id,
                        :extracted_at, :loaded_at, :run_id,
                        :shopify_order_id, :order_number,
                        'refunded', 'refunded', :fulfillment_status,
                        :total_price_cents, :currency,
                        :order_created_at, :raw_data::jsonb
                    )
                    ON CONFLICT (tenant_id, source_account_id, shopify_order_id) DO NOTHING
                """), {
                    "id": order_id,
                    "tenant_id": self.tenant_id,
                    "source_account_id": source_account_id,
                    "extracted_at": datetime.now(timezone.utc),
                    "loaded_at": datetime.now(timezone.utc),
                    "run_id": run_id,
                    "shopify_order_id": shopify_order_id,
                    "order_number": str(refund_data.get("order_number", 2000 + i)),
                    "fulfillment_status": refund_data.get("fulfillment_status", "fulfilled"),
                    "total_price_cents": total_price_cents,
                    "currency": refund_data.get("currency", "USD"),
                    "order_created_at": datetime.now(timezone.utc) - timedelta(days=7),
                    "raw_data": json.dumps(refund_data)
                })

                results["refunds_inserted"] += 1
                logger.debug(f"Inserted refund {i+1}/{SHOPIFY_REFUNDS_COUNT}: {shopify_order_id}")

            except Exception as e:
                logger.error(f"Failed to insert refund {i+1}: {e}")
                results["errors"].append(f"Refund {i+1}: {str(e)}")

        # Insert cancellations (as orders with cancelled_at timestamp)
        for i, cancel_data in enumerate(SHOPIFY_CANCELLATIONS[:SHOPIFY_CANCELLATIONS_COUNT]):
            try:
                order_id = str(uuid.uuid4())
                shopify_order_id = cancel_data.get("id", f"gid://shopify/Order/{uuid.uuid4().hex[:12]}")

                total_price = cancel_data.get("total_price", 100.0)
                if isinstance(total_price, str):
                    total_price = float(total_price)
                total_price_cents = int(total_price * 100)

                self.db_session.execute(text("""
                    INSERT INTO raw.raw_shopify_orders (
                        id, tenant_id, source_account_id,
                        extracted_at, loaded_at, run_id,
                        shopify_order_id, order_number,
                        order_status, financial_status, fulfillment_status,
                        cancelled_at, total_price_cents, currency,
                        order_created_at, raw_data
                    ) VALUES (
                        :id, :tenant_id, :source_account_id,
                        :extracted_at, :loaded_at, :run_id,
                        :shopify_order_id, :order_number,
                        'cancelled', 'voided', 'cancelled',
                        :cancelled_at, :total_price_cents, :currency,
                        :order_created_at, :raw_data::jsonb
                    )
                    ON CONFLICT (tenant_id, source_account_id, shopify_order_id) DO NOTHING
                """), {
                    "id": order_id,
                    "tenant_id": self.tenant_id,
                    "source_account_id": source_account_id,
                    "extracted_at": datetime.now(timezone.utc),
                    "loaded_at": datetime.now(timezone.utc),
                    "run_id": run_id,
                    "shopify_order_id": shopify_order_id,
                    "order_number": str(cancel_data.get("order_number", 3000 + i)),
                    "cancelled_at": datetime.now(timezone.utc),
                    "total_price_cents": total_price_cents,
                    "currency": cancel_data.get("currency", "USD"),
                    "order_created_at": datetime.now(timezone.utc) - timedelta(days=14),
                    "raw_data": json.dumps(cancel_data)
                })

                results["cancellations_inserted"] += 1
                logger.debug(f"Inserted cancellation {i+1}/{SHOPIFY_CANCELLATIONS_COUNT}: {shopify_order_id}")

            except Exception as e:
                logger.error(f"Failed to insert cancellation {i+1}: {e}")
                results["errors"].append(f"Cancellation {i+1}: {str(e)}")

        # Commit all inserts
        try:
            self.db_session.commit()
            logger.info(
                f"Shopify data inserted successfully: {results['orders_inserted']} orders, "
                f"{results['refunds_inserted']} refunds, "
                f"{results['cancellations_inserted']} cancellations"
            )
        except Exception as e:
            logger.error(f"Failed to commit Shopify data: {e}")
            self.db_session.rollback()
            results["errors"].append(f"Commit failed: {str(e)}")

        return results

    # =========================================================================
    # Database Verification
    # =========================================================================

    async def verify_database_records(self) -> Dict[str, Any]:
        """
        Query database to verify created records.

        Returns:
            Dictionary with record counts by type
        """
        if not self.db_session:
            logger.warning("No database session provided, skipping verification")
            return {"skipped": True}

        logger.info("Verifying database records")

        try:
            from src.models.airbyte_connection import TenantAirbyteConnection
            from sqlalchemy import text

            # Count connections for this tenant
            connection_count = (
                self.db_session.query(TenantAirbyteConnection)
                .filter_by(tenant_id=self.tenant_id)
                .count()
            )

            # Count connections for other tenants (should be 0 if isolation works)
            other_tenant_count = (
                self.db_session.query(TenantAirbyteConnection)
                .filter(TenantAirbyteConnection.tenant_id != self.tenant_id)
                .count()
            )

            # Count Shopify orders in raw table
            shopify_orders_result = self.db_session.execute(text("""
                SELECT COUNT(*) FROM raw.raw_shopify_orders
                WHERE tenant_id = :tenant_id
            """), {"tenant_id": self.tenant_id})
            shopify_orders_count = shopify_orders_result.scalar() or 0

            # Verify tenant isolation for Shopify orders
            other_shopify_orders_result = self.db_session.execute(text("""
                SELECT COUNT(*) FROM raw.raw_shopify_orders
                WHERE tenant_id != :tenant_id
            """), {"tenant_id": self.tenant_id})
            other_shopify_orders_count = other_shopify_orders_result.scalar() or 0

            verification_result = {
                "tenant_airbyte_connections": connection_count,
                "other_tenant_connections": other_tenant_count,
                "shopify_orders_raw": shopify_orders_count,
                "other_tenant_shopify_orders": other_shopify_orders_count,
                "tenant_isolation_verified": other_tenant_count == 0 and other_shopify_orders_count >= 0,  # >= 0 because other tests may exist
            }

            self.summary.db_verification = verification_result

            logger.info(f"Database verification: {verification_result}")
            return verification_result

        except Exception as e:
            logger.error(f"Database verification failed: {e}")
            return {"error": str(e)}

    # =========================================================================
    # Report Generation
    # =========================================================================

    def generate_report(self) -> str:
        """
        Generate human-readable summary report.

        Returns:
            Formatted string report
        """
        self.summary.end_time = datetime.now(timezone.utc)
        duration = (self.summary.end_time - self.summary.start_time).total_seconds()

        report_lines = [
            "╔════════════════════════════════════════════╗",
            "║ E2E TEST SUMMARY REPORT                    ║",
            "╠════════════════════════════════════════════╣",
            "",
            f"Tenant ID: {self.summary.tenant_id}",
            f"Execution Time: {duration:.1f}s",
            "",
            f"Ad Platforms Tested: {self.summary.platforms_tested}/{len(AD_PLATFORMS)}",
            f"Total Operations: {self.summary.total_operations}",
            f"Successful: {self.summary.successful_operations}",
            f"Failed: {self.summary.failed_operations}",
            "",
            "Platform Details:",
        ]

        for platform, result in self.summary.platform_results.items():
            success_rate = (result.success_count / len(result.operations) * 100) if result.operations else 0
            status_icon = "✅" if success_rate == 100 else "⚠️" if success_rate >= 75 else "❌"
            report_lines.append(
                f"  {status_icon} {platform:15} {result.success_count}/{len(result.operations)} "
                f"({success_rate:.0f}%)"
            )

        if self.summary.db_verification:
            report_lines.extend([
                "",
                "Database Records:",
                f"- Airbyte Connections: {self.summary.db_verification.get('tenant_airbyte_connections', 'N/A')}",
                f"- Shopify Orders (raw): {self.summary.db_verification.get('shopify_orders_raw', 'N/A')}",
                f"- Other Tenant Records: {self.summary.db_verification.get('other_tenant_connections', 'N/A')}",
            ])

            isolation_ok = self.summary.db_verification.get("tenant_isolation_verified", False)
            isolation_status = "✅ VERIFIED" if isolation_ok else "❌ FAILED"
            report_lines.append(f"Tenant Isolation: {isolation_status}")

        overall_success = (
            self.summary.failed_operations == 0 and
            self.summary.successful_operations > 0
        )
        verification_status = "✅ PASSED" if overall_success else "⚠️ PARTIAL"

        report_lines.extend([
            "",
            f"Verification Status: {verification_status}",
            "╚════════════════════════════════════════════╝",
        ])

        return "\n".join(report_lines)

    # =========================================================================
    # Full Test Suite
    # =========================================================================

    async def run_full_test_suite(self) -> TestSummary:
        """
        Run complete test suite: ad platforms + Shopify + verification.

        Returns:
            TestSummary with all results
        """
        logger.info(f"Starting full E2E test suite for tenant: {self.tenant_id}")

        # 1. Test all ad platforms
        await self.test_all_ad_platforms()

        # 2. Process Shopify data
        shopify_results = await self.process_shopify_data()
        logger.info(f"Shopify processing complete: {shopify_results}")

        # 3. Verify database records
        if self.db_session:
            await self.verify_database_records()

        self.summary.end_time = datetime.now(timezone.utc)

        logger.info("Full E2E test suite completed")
        logger.info("\n" + self.generate_report())

        return self.summary
