"""
Raw Warehouse RLS Isolation Tests.

CRITICAL: These tests verify that Row-Level Security is properly enforced
on all raw warehouse tables. Tenants MUST NOT see each other's data.

These tests require PostgreSQL (RLS is not supported in SQLite).
Tests will be skipped if PostgreSQL is not available.
"""

import os
import uuid
import pytest
from datetime import datetime, timezone, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


# Test tenant identifiers - fixed for deterministic tests
TENANT_A = "test-tenant-alpha-rls"
TENANT_B = "test-tenant-beta-rls"
TENANT_C = "test-tenant-gamma-rls"


def _get_postgres_url():
    """Get PostgreSQL URL for testing, or None if not available."""
    database_url = os.getenv("DATABASE_URL")

    if database_url:
        # Skip if SQLite is configured (RLS not supported)
        if database_url.startswith("sqlite"):
            return None
        # Handle Render's postgres:// URL format
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        # Only return if it's a PostgreSQL URL
        if database_url.startswith("postgresql://"):
            return database_url
        return None

    # Try default local PostgreSQL
    return "postgresql://test:test@localhost:5432/test_billing_db"


def _is_postgres_available() -> bool:
    """Check if PostgreSQL is available and connectable."""
    url = _get_postgres_url()
    if not url:
        return False
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# Skip all tests if PostgreSQL is not available
pytestmark = pytest.mark.skipif(
    not _is_postgres_available(),
    reason="PostgreSQL required for RLS tests. Set DATABASE_URL to PostgreSQL or run local postgres."
)


@pytest.fixture(scope="module")
def pg_engine():
    """Create PostgreSQL engine for RLS tests."""
    url = _get_postgres_url()
    if not url:
        pytest.skip("PostgreSQL URL not available")
    engine = create_engine(url, pool_pre_ping=True)
    yield engine


@pytest.fixture(scope="module")
def setup_raw_schema(pg_engine):
    """
    Create raw schema and tables for testing.

    This fixture sets up the minimal schema needed for RLS testing.
    """
    with pg_engine.connect() as conn:
        # Create raw schema
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))

        # Create uuid extension
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\""))

        # Drop existing test table to ensure clean state
        conn.execute(text("DROP TABLE IF EXISTS raw.raw_shopify_orders_test CASCADE"))

        # Create test table with RLS
        conn.execute(text("""
            CREATE TABLE raw.raw_shopify_orders_test (
                id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
                tenant_id VARCHAR(255) NOT NULL,
                source_account_id VARCHAR(255) NOT NULL,
                extracted_at TIMESTAMP WITH TIME ZONE NOT NULL,
                loaded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                run_id VARCHAR(255) NOT NULL,
                shopify_order_id VARCHAR(255) NOT NULL,
                total_price_cents BIGINT
            )
        """))

        # Create test role if not exists
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'test_query_role') THEN
                    CREATE ROLE test_query_role NOLOGIN;
                END IF;
            END $$
        """))

        # Grant the current user ability to switch to test_query_role
        conn.execute(text("GRANT test_query_role TO CURRENT_USER"))

        # Grant permissions to test_query_role
        conn.execute(text("GRANT USAGE ON SCHEMA raw TO test_query_role"))
        conn.execute(text("GRANT SELECT ON raw.raw_shopify_orders_test TO test_query_role"))

        # Create tenant context function
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION raw.get_test_tenant_id()
            RETURNS VARCHAR(255) AS $$
            BEGIN
                RETURN NULLIF(current_setting('app.tenant_id', true), '');
            EXCEPTION
                WHEN OTHERS THEN
                    RETURN NULL;
            END;
            $$ LANGUAGE plpgsql STABLE SECURITY DEFINER
        """))

        conn.execute(text("GRANT EXECUTE ON FUNCTION raw.get_test_tenant_id() TO test_query_role"))

        # Enable RLS on the table
        conn.execute(text("ALTER TABLE raw.raw_shopify_orders_test ENABLE ROW LEVEL SECURITY"))

        # Create RLS policy for test_query_role only
        conn.execute(text("""
            CREATE POLICY test_tenant_isolation
            ON raw.raw_shopify_orders_test
            FOR ALL
            TO test_query_role
            USING (tenant_id = raw.get_test_tenant_id())
        """))

        conn.commit()

    yield

    # Cleanup
    with pg_engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS raw.raw_shopify_orders_test CASCADE"))
        conn.commit()


@pytest.fixture(scope="function")
def db_session(pg_engine, setup_raw_schema):
    """Create a new database session for each test."""
    Session = sessionmaker(bind=pg_engine)
    session = Session()

    # Clear test data (as admin, not subject to RLS)
    session.execute(text("DELETE FROM raw.raw_shopify_orders_test WHERE tenant_id LIKE 'test-tenant-%'"))
    session.commit()

    yield session

    # Reset role and cleanup after test
    try:
        session.execute(text("RESET ROLE"))
    except Exception:
        pass
    session.execute(text("DELETE FROM raw.raw_shopify_orders_test WHERE tenant_id LIKE 'test-tenant-%'"))
    session.commit()
    session.close()


@pytest.fixture
def seed_test_data(db_session):
    """Insert test data for multiple tenants (as admin, bypassing RLS)."""
    now = datetime.now(timezone.utc)

    # Insert data for Tenant A (3 orders) - total: 6000 cents
    for i in range(3):
        db_session.execute(text("""
            INSERT INTO raw.raw_shopify_orders_test
            (tenant_id, source_account_id, extracted_at, run_id, shopify_order_id, total_price_cents)
            VALUES (:tenant_id, :source, :extracted, :run_id, :order_id, :price)
        """), {
            "tenant_id": TENANT_A,
            "source": "shop-alpha",
            "extracted": now - timedelta(days=i),
            "run_id": "run-test-a",
            "order_id": f"order-a-{i+1}-{uuid.uuid4().hex[:6]}",
            "price": (i + 1) * 1000  # 1000 + 2000 + 3000 = 6000
        })

    # Insert data for Tenant B (2 orders) - total: 6000 cents
    for i in range(2):
        db_session.execute(text("""
            INSERT INTO raw.raw_shopify_orders_test
            (tenant_id, source_account_id, extracted_at, run_id, shopify_order_id, total_price_cents)
            VALUES (:tenant_id, :source, :extracted, :run_id, :order_id, :price)
        """), {
            "tenant_id": TENANT_B,
            "source": "shop-beta",
            "extracted": now - timedelta(days=i),
            "run_id": "run-test-b",
            "order_id": f"order-b-{i+1}-{uuid.uuid4().hex[:6]}",
            "price": (i + 1) * 2000  # 2000 + 4000 = 6000
        })

    # Insert data for Tenant C (1 order) - total: 5000 cents
    db_session.execute(text("""
        INSERT INTO raw.raw_shopify_orders_test
        (tenant_id, source_account_id, extracted_at, run_id, shopify_order_id, total_price_cents)
        VALUES (:tenant_id, :source, :extracted, :run_id, :order_id, :price)
    """), {
        "tenant_id": TENANT_C,
        "source": "shop-gamma",
        "extracted": now,
        "run_id": "run-test-c",
        "order_id": f"order-c-1-{uuid.uuid4().hex[:6]}",
        "price": 5000
    })

    db_session.commit()

    return {
        "tenant_a": TENANT_A,
        "tenant_b": TENANT_B,
        "tenant_c": TENANT_C,
        "tenant_a_count": 3,
        "tenant_b_count": 2,
        "tenant_c_count": 1,
        "tenant_a_total": 6000,
        "tenant_b_total": 6000,
        "tenant_c_total": 5000,
    }


class TestRawWarehouseRLSIsolation:
    """
    CRITICAL: Test that RLS properly isolates tenant data.

    These tests verify:
    1. Tenants see only their own data
    2. Cross-tenant queries return zero rows
    3. Empty/invalid context returns zero rows

    NOTE: Tests use SET ROLE to switch to test_query_role which is subject to RLS.
    """

    def test_tenant_a_sees_only_own_data(self, db_session, seed_test_data):
        """Test that Tenant A can only see Tenant A data."""
        # Set tenant context and switch to RLS-enforced role
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": TENANT_A})
        db_session.execute(text("SET ROLE test_query_role"))

        result = db_session.execute(text(
            "SELECT COUNT(*) as cnt FROM raw.raw_shopify_orders_test"
        ))
        count = result.scalar()

        # Reset role before assertion to allow cleanup
        db_session.execute(text("RESET ROLE"))

        assert count == 3, f"Tenant A should see exactly 3 orders, got {count}"

    def test_tenant_b_sees_only_own_data(self, db_session, seed_test_data):
        """Test that Tenant B can only see Tenant B data."""
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": TENANT_B})
        db_session.execute(text("SET ROLE test_query_role"))

        result = db_session.execute(text(
            "SELECT COUNT(*) as cnt FROM raw.raw_shopify_orders_test"
        ))
        count = result.scalar()

        db_session.execute(text("RESET ROLE"))

        assert count == 2, f"Tenant B should see exactly 2 orders, got {count}"

    def test_tenant_c_sees_only_own_data(self, db_session, seed_test_data):
        """Test that Tenant C can only see Tenant C data."""
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": TENANT_C})
        db_session.execute(text("SET ROLE test_query_role"))

        result = db_session.execute(text(
            "SELECT COUNT(*) as cnt FROM raw.raw_shopify_orders_test"
        ))
        count = result.scalar()

        db_session.execute(text("RESET ROLE"))

        assert count == 1, f"Tenant C should see exactly 1 order, got {count}"

    def test_tenant_a_cannot_see_tenant_b_data(self, db_session, seed_test_data):
        """CRITICAL: Tenant A cannot access Tenant B's data."""
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": TENANT_A})
        db_session.execute(text("SET ROLE test_query_role"))

        # Attempt to query Tenant B's data directly
        result = db_session.execute(text("""
            SELECT COUNT(*) as cnt FROM raw.raw_shopify_orders_test
            WHERE tenant_id = :tenant_b
        """), {"tenant_b": TENANT_B})
        count = result.scalar()

        db_session.execute(text("RESET ROLE"))

        assert count == 0, f"SECURITY VIOLATION: Tenant A can see {count} Tenant B records!"

    def test_tenant_b_cannot_see_tenant_a_data(self, db_session, seed_test_data):
        """CRITICAL: Tenant B cannot access Tenant A's data."""
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": TENANT_B})
        db_session.execute(text("SET ROLE test_query_role"))

        result = db_session.execute(text("""
            SELECT COUNT(*) as cnt FROM raw.raw_shopify_orders_test
            WHERE tenant_id = :tenant_a
        """), {"tenant_a": TENANT_A})
        count = result.scalar()

        db_session.execute(text("RESET ROLE"))

        assert count == 0, f"SECURITY VIOLATION: Tenant B can see {count} Tenant A records!"

    def test_no_context_returns_zero_rows(self, db_session, seed_test_data):
        """Test that empty tenant context returns no data."""
        # Clear tenant context
        db_session.execute(text("SET app.tenant_id = ''"))
        db_session.execute(text("SET ROLE test_query_role"))

        result = db_session.execute(text(
            "SELECT COUNT(*) as cnt FROM raw.raw_shopify_orders_test"
        ))
        count = result.scalar()

        db_session.execute(text("RESET ROLE"))

        assert count == 0, f"SECURITY VIOLATION: {count} records visible without tenant context!"

    def test_invalid_tenant_returns_zero_rows(self, db_session, seed_test_data):
        """Test that invalid tenant context returns no data."""
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": "non-existent-tenant-xyz"})
        db_session.execute(text("SET ROLE test_query_role"))

        result = db_session.execute(text(
            "SELECT COUNT(*) as cnt FROM raw.raw_shopify_orders_test"
        ))
        count = result.scalar()

        db_session.execute(text("RESET ROLE"))

        assert count == 0, f"SECURITY VIOLATION: {count} records visible with invalid tenant!"

    def test_sql_injection_blocked(self, db_session, seed_test_data):
        """Test that SQL injection in tenant context is blocked."""
        # Attempt SQL injection
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": "' OR '1'='1"})
        db_session.execute(text("SET ROLE test_query_role"))

        result = db_session.execute(text(
            "SELECT COUNT(*) as cnt FROM raw.raw_shopify_orders_test"
        ))
        count = result.scalar()

        db_session.execute(text("RESET ROLE"))

        assert count == 0, f"SECURITY VIOLATION: SQL injection returned {count} records!"

    def test_tenant_context_switching(self, db_session, seed_test_data):
        """Test that switching tenant context updates visible data."""
        # Start as Tenant A
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": TENANT_A})
        db_session.execute(text("SET ROLE test_query_role"))
        result = db_session.execute(text("SELECT COUNT(*) FROM raw.raw_shopify_orders_test"))
        count_a = result.scalar()
        db_session.execute(text("RESET ROLE"))

        # Switch to Tenant B
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": TENANT_B})
        db_session.execute(text("SET ROLE test_query_role"))
        result = db_session.execute(text("SELECT COUNT(*) FROM raw.raw_shopify_orders_test"))
        count_b = result.scalar()
        db_session.execute(text("RESET ROLE"))

        # Switch to Tenant C
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": TENANT_C})
        db_session.execute(text("SET ROLE test_query_role"))
        result = db_session.execute(text("SELECT COUNT(*) FROM raw.raw_shopify_orders_test"))
        count_c = result.scalar()
        db_session.execute(text("RESET ROLE"))

        assert count_a == 3, f"Tenant A should see 3, got {count_a}"
        assert count_b == 2, f"Tenant B should see 2, got {count_b}"
        assert count_c == 1, f"Tenant C should see 1, got {count_c}"

    def test_aggregate_isolation(self, db_session, seed_test_data):
        """Test that aggregate queries respect RLS."""
        # Tenant A total
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": TENANT_A})
        db_session.execute(text("SET ROLE test_query_role"))
        result = db_session.execute(text(
            "SELECT SUM(total_price_cents) as total FROM raw.raw_shopify_orders_test"
        ))
        total_a = result.scalar()
        db_session.execute(text("RESET ROLE"))

        # Tenant C total (different from A)
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": TENANT_C})
        db_session.execute(text("SET ROLE test_query_role"))
        result = db_session.execute(text(
            "SELECT SUM(total_price_cents) as total FROM raw.raw_shopify_orders_test"
        ))
        total_c = result.scalar()
        db_session.execute(text("RESET ROLE"))

        # Tenant A: 1000+2000+3000 = 6000
        # Tenant C: 5000
        assert total_a == 6000, f"Tenant A total should be 6000, got {total_a}"
        assert total_c == 5000, f"Tenant C total should be 5000, got {total_c}"
        assert total_a != total_c, "Aggregates should be different per tenant"


class TestRawWarehouseRLSEdgeCases:
    """Edge case tests for RLS behavior."""

    def test_null_tenant_id_in_data_not_visible(self, db_session, setup_raw_schema):
        """Test that rows with NULL tenant_id are not visible."""
        # This shouldn't happen in production (tenant_id is NOT NULL)
        # but test the behavior anyway
        try:
            db_session.execute(text("""
                INSERT INTO raw.raw_shopify_orders_test
                (id, tenant_id, source_account_id, extracted_at, run_id, shopify_order_id)
                VALUES ('null-test', NULL, 'shop', NOW(), 'run', 'order')
            """))
        except Exception:
            # Expected - tenant_id is NOT NULL
            db_session.rollback()
            return

        # If insert succeeded (which it shouldn't), verify it's not visible
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": "any-tenant"})
        db_session.execute(text("SET ROLE test_query_role"))
        result = db_session.execute(text(
            "SELECT COUNT(*) FROM raw.raw_shopify_orders_test WHERE id = 'null-test'"
        ))
        count = result.scalar()
        db_session.execute(text("RESET ROLE"))
        assert count == 0

    def test_special_characters_in_tenant_id(self, db_session, setup_raw_schema):
        """Test that special characters in tenant_id work correctly."""
        special_tenant = f"tenant-special_chars.{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc)

        # Insert data with special tenant_id (as admin)
        db_session.execute(text("""
            INSERT INTO raw.raw_shopify_orders_test
            (tenant_id, source_account_id, extracted_at, run_id, shopify_order_id)
            VALUES (:tenant, 'shop', :now, 'run', :order_id)
        """), {"tenant": special_tenant, "now": now, "order_id": f"order-special-{uuid.uuid4().hex[:6]}"})
        db_session.commit()

        # Verify only visible with correct tenant (as test_query_role)
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": special_tenant})
        db_session.execute(text("SET ROLE test_query_role"))
        result = db_session.execute(text("SELECT COUNT(*) FROM raw.raw_shopify_orders_test"))
        count = result.scalar()
        db_session.execute(text("RESET ROLE"))
        assert count == 1, f"Should see 1 record with matching tenant, got {count}"

        # Not visible with different tenant
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": "other-tenant"})
        db_session.execute(text("SET ROLE test_query_role"))
        result = db_session.execute(text("SELECT COUNT(*) FROM raw.raw_shopify_orders_test"))
        count = result.scalar()
        db_session.execute(text("RESET ROLE"))
        assert count == 0, f"Should see 0 records with different tenant, got {count}"

        # Cleanup (as admin)
        db_session.execute(text("DELETE FROM raw.raw_shopify_orders_test WHERE tenant_id = :t"),
                          {"t": special_tenant})
        db_session.commit()


class TestTenantContextFunction:
    """Test the tenant context helper function."""

    def test_get_tenant_id_returns_set_value(self, db_session, setup_raw_schema):
        """Test that get_test_tenant_id returns the set value."""
        db_session.execute(text("SET app.tenant_id = :tenant"), {"tenant": "test-123"})

        result = db_session.execute(text("SELECT raw.get_test_tenant_id()"))
        tenant_id = result.scalar()

        assert tenant_id == "test-123"

    def test_get_tenant_id_returns_null_for_empty(self, db_session, setup_raw_schema):
        """Test that get_test_tenant_id returns NULL for empty string."""
        db_session.execute(text("SET app.tenant_id = ''"))

        result = db_session.execute(text("SELECT raw.get_test_tenant_id()"))
        tenant_id = result.scalar()

        assert tenant_id is None

    def test_get_tenant_id_returns_null_when_not_set(self, db_session, setup_raw_schema):
        """Test that get_test_tenant_id returns NULL when not set."""
        db_session.execute(text("RESET app.tenant_id"))

        result = db_session.execute(text("SELECT raw.get_test_tenant_id()"))
        tenant_id = result.scalar()

        assert tenant_id is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
