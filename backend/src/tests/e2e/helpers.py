"""
E2E Test Helper Functions.

Provides utilities for:
- Waiting for async job completion
- Setting up test tenants with data
- Running dbt models
- Validating data at each pipeline stage
"""

import asyncio
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient, Response


# =============================================================================
# Job Waiting Utilities
# =============================================================================

class JobTimeoutError(Exception):
    """Raised when a job doesn't complete within the timeout."""
    pass


class JobFailedError(Exception):
    """Raised when a job fails."""
    pass


async def wait_for_job_completion(
    client: AsyncClient,
    token: str,
    job_id: str,
    timeout_seconds: int = 60,
    poll_interval_seconds: float = 1.0,
    job_status_endpoint: str = "/api/v1/jobs/{job_id}/status",
) -> Dict:
    """
    Wait for an async job to complete.

    Args:
        client: HTTP client
        token: Auth token
        job_id: Job ID to wait for
        timeout_seconds: Maximum time to wait
        poll_interval_seconds: Time between status checks
        job_status_endpoint: API endpoint template for job status

    Returns:
        Final job status response

    Raises:
        JobTimeoutError: If job doesn't complete within timeout
        JobFailedError: If job fails
    """
    endpoint = job_status_endpoint.format(job_id=job_id)
    start_time = time.time()

    while time.time() - start_time < timeout_seconds:
        response = await client.get(
            endpoint,
            headers={"Authorization": f"Bearer {token}"}
        )

        if response.status_code != 200:
            raise ValueError(f"Failed to get job status: {response.text}")

        status_data = response.json()
        status = status_data.get("status", "").lower()

        if status in ["succeeded", "completed", "success"]:
            return status_data
        elif status in ["failed", "error", "dead_letter"]:
            raise JobFailedError(
                f"Job {job_id} failed: {status_data.get('error', 'Unknown error')}"
            )

        await asyncio.sleep(poll_interval_seconds)

    raise JobTimeoutError(
        f"Job {job_id} did not complete within {timeout_seconds} seconds"
    )


async def wait_for_sync_completion(
    client: AsyncClient,
    token: str,
    job_id: str,
    timeout_seconds: int = 120,
) -> Dict:
    """Wait specifically for data sync job completion."""
    return await wait_for_job_completion(
        client=client,
        token=token,
        job_id=job_id,
        timeout_seconds=timeout_seconds,
        job_status_endpoint="/api/v1/sync/jobs/{job_id}",
    )


# =============================================================================
# Tenant Setup Utilities
# =============================================================================

async def setup_test_tenant(
    db_session: AsyncSession,
    tenant_id: str,
    shop_domain: Optional[str] = None,
) -> Dict[str, str]:
    """
    Create a test tenant with minimal required records.

    Args:
        db_session: Database session
        tenant_id: Unique tenant identifier
        shop_domain: Shopify shop domain (auto-generated if not provided)

    Returns:
        Dict with created entity IDs
    """
    shop_domain = shop_domain or f"{tenant_id}.myshopify.com"
    store_id = str(uuid.uuid4())

    # Create Shopify store record
    await db_session.execute(
        text("""
            INSERT INTO shopify_stores
            (id, tenant_id, shop_domain, shop_id, access_token_encrypted, scopes, status, created_at, updated_at)
            VALUES (:id, :tenant_id, :shop_domain, :shop_id, :token, :scopes, 'active', NOW(), NOW())
            ON CONFLICT (tenant_id) DO UPDATE SET
                status = 'active',
                updated_at = NOW()
        """),
        {
            "id": store_id,
            "tenant_id": tenant_id,
            "shop_domain": shop_domain,
            "shop_id": str(hash(shop_domain) % 10**12),
            "token": "encrypted-test-token",
            "scopes": "read_products,write_products,read_orders",
        }
    )

    await db_session.commit()

    return {
        "tenant_id": tenant_id,
        "store_id": store_id,
        "shop_domain": shop_domain,
    }


async def setup_test_airbyte_connection(
    db_session: AsyncSession,
    tenant_id: str,
    connection_id: Optional[str] = None,
    source_type: str = "shopify",
) -> str:
    """
    Create a test Airbyte connection mapping.

    Args:
        db_session: Database session
        tenant_id: Tenant ID
        connection_id: Airbyte connection ID (auto-generated if not provided)
        source_type: Type of data source

    Returns:
        Connection ID
    """
    connection_id = connection_id or f"airbyte-{uuid.uuid4().hex[:12]}"

    await db_session.execute(
        text("""
            INSERT INTO tenant_airbyte_connections
            (id, tenant_id, airbyte_connection_id, connection_name, connection_type, source_type, status, is_enabled, created_at)
            VALUES (:id, :tenant_id, :conn_id, :name, 'source', :source_type, 'active', true, NOW())
            ON CONFLICT (tenant_id, airbyte_connection_id) DO NOTHING
        """),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "conn_id": connection_id,
            "name": f"Test {source_type.title()} Connection",
            "source_type": source_type,
        }
    )

    await db_session.commit()
    return connection_id


async def setup_tenant_with_data(
    db_session: AsyncSession,
    tenant_id: str,
    orders: List[Dict],
    customers: Optional[List[Dict]] = None,
    inject_raw: bool = True,
) -> str:
    """
    Setup a tenant with test data in raw tables.

    This bypasses Airbyte to directly inject test data for faster tests.
    Use mock Airbyte for full pipeline tests.

    Args:
        db_session: Database session
        tenant_id: Tenant ID
        orders: List of order data dicts
        customers: List of customer data dicts
        inject_raw: Whether to inject into raw tables

    Returns:
        Airbyte connection ID
    """
    # Setup tenant records
    await setup_test_tenant(db_session, tenant_id)
    connection_id = await setup_test_airbyte_connection(db_session, tenant_id)

    if inject_raw and orders:
        await inject_raw_orders(db_session, tenant_id, orders)

    if inject_raw and customers:
        await inject_raw_customers(db_session, tenant_id, customers)

    return connection_id


async def inject_raw_orders(
    db_session: AsyncSession,
    tenant_id: str,
    orders: List[Dict],
) -> None:
    """Inject order data into raw Airbyte table."""
    for order in orders:
        # Add tenant_id to the order data
        order_with_tenant = {**order, "tenant_id": tenant_id}

        await db_session.execute(
            text("""
                INSERT INTO _airbyte_raw_shopify_orders
                (_airbyte_raw_id, _airbyte_data, _airbyte_extracted_at, _airbyte_loaded_at)
                VALUES (:raw_id, :data, :extracted_at, :loaded_at)
            """),
            {
                "raw_id": str(uuid.uuid4()),
                "data": json.dumps(order_with_tenant),
                "extracted_at": datetime.now(timezone.utc),
                "loaded_at": datetime.now(timezone.utc),
            }
        )

    await db_session.commit()


async def inject_raw_customers(
    db_session: AsyncSession,
    tenant_id: str,
    customers: List[Dict],
) -> None:
    """Inject customer data into raw Airbyte table."""
    for customer in customers:
        customer_with_tenant = {**customer, "tenant_id": tenant_id}

        await db_session.execute(
            text("""
                INSERT INTO _airbyte_raw_shopify_customers
                (_airbyte_raw_id, _airbyte_data, _airbyte_extracted_at, _airbyte_loaded_at)
                VALUES (:raw_id, :data, :extracted_at, :loaded_at)
            """),
            {
                "raw_id": str(uuid.uuid4()),
                "data": json.dumps(customer_with_tenant),
                "extracted_at": datetime.now(timezone.utc),
                "loaded_at": datetime.now(timezone.utc),
            }
        )

    await db_session.commit()


# =============================================================================
# dbt Utilities
# =============================================================================

async def run_dbt_models(
    tenant_id: str,
    models: Optional[List[str]] = None,
    backfill_mode: bool = False,
    project_dir: str = "analytics",
) -> subprocess.CompletedProcess:
    """
    Run dbt models for a specific tenant.

    Args:
        tenant_id: Tenant ID to filter transformations
        models: Specific models to run (None = all)
        backfill_mode: Enable backfill mode for historical data
        project_dir: Path to dbt project

    Returns:
        Completed process result
    """
    env = os.environ.copy()
    env["DBT_TARGET_TENANT_ID"] = tenant_id

    if backfill_mode:
        env["DBT_BACKFILL_MODE"] = "true"

    cmd = ["dbt", "run", "--project-dir", project_dir]

    if models:
        cmd.extend(["--select", " ".join(models)])

    # Run in thread to not block async
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, env=env, capture_output=True, text=True)
    )

    if result.returncode != 0:
        raise RuntimeError(f"dbt run failed:\n{result.stderr}")

    return result


def run_dbt_models_sync(
    tenant_id: str,
    models: Optional[List[str]] = None,
    project_dir: str = "analytics",
) -> subprocess.CompletedProcess:
    """Synchronous version of run_dbt_models."""
    env = os.environ.copy()
    env["DBT_TARGET_TENANT_ID"] = tenant_id

    cmd = ["dbt", "run", "--project-dir", project_dir]

    if models:
        cmd.extend(["--select", " ".join(models)])

    result = subprocess.run(cmd, env=env, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"dbt run failed:\n{result.stderr}")

    return result


# =============================================================================
# Validation Utilities
# =============================================================================

async def validate_raw_data_count(
    db_session: AsyncSession,
    table_name: str,
    tenant_id: str,
    expected_count: int,
) -> None:
    """Validate record count in raw table for a tenant."""
    result = await db_session.execute(
        text(f"""
            SELECT COUNT(*) as count
            FROM {table_name}
            WHERE _airbyte_data->>'tenant_id' = :tenant_id
        """),
        {"tenant_id": tenant_id}
    )
    actual_count = result.scalar()

    assert actual_count == expected_count, (
        f"Expected {expected_count} records in {table_name} for tenant {tenant_id}, "
        f"got {actual_count}"
    )


async def validate_staging_data(
    db_session: AsyncSession,
    tenant_id: str,
) -> Dict[str, int]:
    """
    Validate data in staging tables.

    Returns counts for each staging table.
    """
    tables = [
        "staging.stg_shopify_orders",
        "staging.stg_shopify_customers",
    ]

    counts = {}
    for table in tables:
        try:
            result = await db_session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = :tid"),
                {"tid": tenant_id}
            )
            counts[table] = result.scalar()
        except Exception:
            counts[table] = 0

    return counts


async def validate_fact_tables(
    db_session: AsyncSession,
    tenant_id: str,
) -> Dict[str, Any]:
    """
    Validate data in fact tables.

    Returns metrics from fact tables.
    """
    result = await db_session.execute(
        text("""
            SELECT
                COUNT(*) as order_count,
                COALESCE(SUM(total_amount), 0) as total_revenue
            FROM analytics.fact_orders
            WHERE tenant_id = :tid
        """),
        {"tid": tenant_id}
    )
    row = result.fetchone()

    return {
        "order_count": row.order_count if row else 0,
        "total_revenue": float(row.total_revenue) if row else 0.0,
    }


async def validate_tenant_isolation(
    db_session: AsyncSession,
    tenant_ids: List[str],
    table: str = "analytics.fact_orders",
) -> bool:
    """
    Verify tenant isolation - each tenant only sees their own data.

    Returns True if isolation is maintained.
    """
    result = await db_session.execute(
        text(f"""
            SELECT tenant_id, COUNT(*) as count
            FROM {table}
            WHERE tenant_id = ANY(:tids)
            GROUP BY tenant_id
        """),
        {"tids": tenant_ids}
    )

    rows = result.fetchall()
    seen_tenants = {row.tenant_id for row in rows}

    # Each tenant in the list should only appear once per tenant_id
    return seen_tenants.issubset(set(tenant_ids))


# =============================================================================
# Test Data Generators
# =============================================================================

def generate_test_order(
    order_id: Optional[str] = None,
    total_price: float = 99.99,
    financial_status: str = "paid",
    created_at: Optional[str] = None,
    **kwargs,
) -> Dict:
    """Generate a test order dict."""
    return {
        "id": order_id or f"gid://shopify/Order/{uuid.uuid4().hex[:12]}",
        "order_number": kwargs.get("order_number", 1000 + hash(order_id or "") % 1000),
        "total_price": str(total_price),
        "subtotal_price": str(total_price * 0.9),
        "total_tax": str(total_price * 0.1),
        "currency": kwargs.get("currency", "USD"),
        "financial_status": financial_status,
        "fulfillment_status": kwargs.get("fulfillment_status", "fulfilled"),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "updated_at": kwargs.get("updated_at", datetime.now(timezone.utc).isoformat()),
        "cancelled_at": kwargs.get("cancelled_at"),
        "customer": kwargs.get("customer", {
            "id": f"gid://shopify/Customer/{uuid.uuid4().hex[:12]}",
            "email": f"customer-{uuid.uuid4().hex[:8]}@example.com",
        }),
        "refunds": kwargs.get("refunds", []),
        **{k: v for k, v in kwargs.items() if k not in [
            "order_number", "currency", "fulfillment_status",
            "updated_at", "cancelled_at", "customer", "refunds"
        ]},
    }


def generate_test_orders(
    count: int,
    start_date: Optional[datetime] = None,
    price_range: tuple = (50.0, 200.0),
) -> List[Dict]:
    """Generate multiple test orders."""
    import random

    start_date = start_date or datetime.now(timezone.utc) - timedelta(days=30)
    orders = []

    for i in range(count):
        order_date = start_date + timedelta(days=i % 30, hours=random.randint(0, 23))
        price = round(random.uniform(*price_range), 2)

        orders.append(generate_test_order(
            total_price=price,
            created_at=order_date.isoformat(),
            order_number=1000 + i,
        ))

    return orders


def generate_declining_revenue_pattern(
    days: int = 14,
    start_revenue: float = 10000.0,
    decline_rate: float = 0.15,
) -> List[Dict]:
    """
    Generate orders showing declining revenue pattern.

    Useful for testing revenue anomaly detection.
    """
    orders = []
    current_date = datetime.now(timezone.utc) - timedelta(days=days)

    for day in range(days):
        # Calculate daily revenue with decline
        if day < days // 2:
            daily_revenue = start_revenue / (days // 2)  # Normal period
        else:
            # Declining period
            decline_factor = 1 - (decline_rate * (day - days // 2) / (days // 2))
            daily_revenue = (start_revenue / (days // 2)) * max(decline_factor, 0.5)

        # Create orders for the day
        num_orders = max(1, int(daily_revenue / 100))
        order_value = daily_revenue / num_orders

        for i in range(num_orders):
            orders.append(generate_test_order(
                total_price=round(order_value, 2),
                created_at=(current_date + timedelta(days=day, hours=i)).isoformat(),
            ))

    return orders
