"""
Regression test fixtures and configuration.

Provides:
- Ephemeral database (SQLite or Postgres via testcontainers)
- Test FastAPI app with dependency overrides
- Mock Shopify billing client
- Webhook payload fixtures with HMAC signing
- Pre-seeded test data (tenants, stores, plans, subscriptions)
"""

import os
import uuid
import json
import pytest
from datetime import datetime, timezone, timedelta
from typing import Generator, Optional
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

# Set test environment before importing app modules
os.environ["ENV"] = "test"
os.environ["SHOPIFY_API_SECRET"] = "test-webhook-secret-for-hmac"
os.environ["SHOPIFY_BILLING_TEST_MODE"] = "true"

# Fixed test webhook secret - used for HMAC computation
TEST_WEBHOOK_SECRET = "test-webhook-secret-for-hmac"


# =============================================================================
# Database Fixtures
# =============================================================================

def _get_test_database_url():
    """
    Get database URL for testing.

    Models use PostgreSQL-specific features (JSONB, DEFERRABLE constraints),
    so we require PostgreSQL for regression tests.

    For CI: Set DATABASE_URL to PostgreSQL connection string
    For local: Run PostgreSQL via Docker:
        docker run -d --name test-pg -e POSTGRES_PASSWORD=test -p 5432:5432 postgres:15
        export DATABASE_URL="postgresql://postgres:test@localhost:5432/postgres"
    """
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        # Try default local PostgreSQL
        database_url = "postgresql://postgres:test@localhost:5432/postgres"

    return database_url


@pytest.fixture(scope="session")
def db_engine():
    """
    Create PostgreSQL database engine for tests.

    Models use PostgreSQL-specific features (JSONB, DEFERRABLE constraints),
    so we require PostgreSQL for these regression tests.
    """
    database_url = _get_test_database_url()

    # Handle Render's postgres:// URL format
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(
            f"PostgreSQL required for regression tests. "
            f"Set DATABASE_URL or run: docker run -d --name test-pg "
            f"-e POSTGRES_PASSWORD=test -p 5432:5432 postgres:15. "
            f"Error: {e}"
        )

    # Import Base from db_base
    from src.db_base import Base

    # Import all models to ensure they're registered with Base
    from src.models import subscription, plan, store, billing_event, airbyte_connection

    # Create all tables
    Base.metadata.create_all(bind=engine)

    yield engine

    # Cleanup
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(db_engine) -> Generator[Session, None, None]:
    """
    Create a new database session for each test.

    Uses transaction rollback to isolate tests.
    """
    connection = db_engine.connect()
    transaction = connection.begin()

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = SessionLocal()

    # Begin a nested transaction for the test
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(session, transaction):
        nonlocal nested
        if transaction.nested and not transaction._parent.nested:
            nested = connection.begin_nested()

    yield session

    # Rollback everything
    session.close()
    transaction.rollback()
    connection.close()


# =============================================================================
# Test Identity Fixtures
# =============================================================================

@pytest.fixture
def test_tenant_id() -> str:
    """Generate unique tenant ID for test isolation."""
    return f"test-tenant-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def test_tenant_id_b() -> str:
    """Second tenant ID for multi-tenant isolation tests."""
    return f"test-tenant-b-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def test_shop_domain() -> str:
    """Test shop domain."""
    return "test-store.myshopify.com"


@pytest.fixture
def test_shop_domain_b() -> str:
    """Second test shop domain for isolation tests."""
    return "test-store-b.myshopify.com"


@pytest.fixture
def webhook_secret() -> str:
    """Webhook secret for HMAC signing in tests."""
    return TEST_WEBHOOK_SECRET


# =============================================================================
# Database Entity Fixtures
# =============================================================================

@pytest.fixture
def test_plan_free(db_session):
    """Create a free plan in the database."""
    # Late import to avoid circular import
    from src.models.plan import Plan

    plan = Plan(
        id="plan_free",
        name="free",
        display_name="Free",
        description="Free tier with limited features",
        price_monthly_cents=0,
        price_yearly_cents=0,
        is_active=True
    )
    db_session.add(plan)
    db_session.flush()
    return plan


@pytest.fixture
def test_plan_growth(db_session):
    """Create a Growth plan in the database."""
    from src.models.plan import Plan

    plan = Plan(
        id="plan_growth",
        name="growth",
        display_name="Growth",
        description="For growing businesses",
        price_monthly_cents=2900,
        price_yearly_cents=29000,
        is_active=True
    )
    db_session.add(plan)
    db_session.flush()
    return plan


@pytest.fixture
def test_plan_pro(db_session):
    """Create a Pro plan in the database."""
    from src.models.plan import Plan

    plan = Plan(
        id="plan_pro",
        name="pro",
        display_name="Pro",
        description="Professional tier with all features",
        price_monthly_cents=7900,
        price_yearly_cents=79000,
        is_active=True
    )
    db_session.add(plan)
    db_session.flush()
    return plan


@pytest.fixture
def test_store(db_session, test_tenant_id, test_shop_domain):
    """Create a test Shopify store in the database."""
    from src.models.store import ShopifyStore

    store = ShopifyStore(
        id=str(uuid.uuid4()),
        tenant_id=test_tenant_id,
        shop_domain=test_shop_domain,
        shop_id="12345678",
        access_token_encrypted="test-access-token-encrypted",
        scopes="read_products,write_products",
        currency="USD",
        timezone="America/New_York",
        status="active"
    )
    db_session.add(store)
    db_session.flush()
    return store


@pytest.fixture
def test_store_b(db_session, test_tenant_id_b, test_shop_domain_b):
    """Create a second test store for isolation tests."""
    from src.models.store import ShopifyStore

    store = ShopifyStore(
        id=str(uuid.uuid4()),
        tenant_id=test_tenant_id_b,
        shop_domain=test_shop_domain_b,
        shop_id="87654321",
        access_token_encrypted="test-access-token-b-encrypted",
        scopes="read_products,write_products",
        currency="USD",
        timezone="America/Los_Angeles",
        status="active"
    )
    db_session.add(store)
    db_session.flush()
    return store


@pytest.fixture
def pending_subscription(
    db_session, test_tenant_id, test_store, test_plan_growth
):
    """Create a subscription in PENDING status."""
    from src.models.subscription import Subscription, SubscriptionStatus

    subscription = Subscription(
        id=str(uuid.uuid4()),
        tenant_id=test_tenant_id,
        store_id=test_store.id,
        plan_id=test_plan_growth.id,
        shopify_subscription_id=f"gid://shopify/AppSubscription/{uuid.uuid4().hex[:12]}",
        status=SubscriptionStatus.PENDING.value,
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
    )
    db_session.add(subscription)
    db_session.flush()
    return subscription


@pytest.fixture
def active_subscription(
    db_session, test_tenant_id, test_store, test_plan_growth
):
    """Create a subscription in ACTIVE status on Growth plan."""
    from src.models.subscription import Subscription, SubscriptionStatus

    subscription = Subscription(
        id=str(uuid.uuid4()),
        tenant_id=test_tenant_id,
        store_id=test_store.id,
        plan_id=test_plan_growth.id,
        shopify_subscription_id=f"gid://shopify/AppSubscription/{uuid.uuid4().hex[:12]}",
        status=SubscriptionStatus.ACTIVE.value,
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
    )
    db_session.add(subscription)
    db_session.flush()
    return subscription


@pytest.fixture
def active_subscription_pro(
    db_session, test_tenant_id, test_store, test_plan_pro
):
    """Create a subscription in ACTIVE status on Pro plan."""
    from src.models.subscription import Subscription, SubscriptionStatus

    subscription = Subscription(
        id=str(uuid.uuid4()),
        tenant_id=test_tenant_id,
        store_id=test_store.id,
        plan_id=test_plan_pro.id,
        shopify_subscription_id=f"gid://shopify/AppSubscription/{uuid.uuid4().hex[:12]}",
        status=SubscriptionStatus.ACTIVE.value,
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
    )
    db_session.add(subscription)
    db_session.flush()
    return subscription


@pytest.fixture
def active_subscription_b(
    db_session, test_tenant_id_b, test_store_b, test_plan_growth
):
    """Create a second active subscription for tenant B (isolation tests)."""
    from src.models.subscription import Subscription, SubscriptionStatus

    subscription = Subscription(
        id=str(uuid.uuid4()),
        tenant_id=test_tenant_id_b,
        store_id=test_store_b.id,
        plan_id=test_plan_growth.id,
        shopify_subscription_id=f"gid://shopify/AppSubscription/{uuid.uuid4().hex[:12]}",
        status=SubscriptionStatus.ACTIVE.value,
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30)
    )
    db_session.add(subscription)
    db_session.flush()
    return subscription


# =============================================================================
# Mock Billing Client Fixture
# =============================================================================

@pytest.fixture
def mock_billing_client():
    """
    Mock Shopify billing client for testing without API calls.

    The mock can be configured per-test to return specific responses.
    """
    from src.tests.regression.helpers.mock_billing_client import MockShopifyBillingClient
    return MockShopifyBillingClient()


# =============================================================================
# FastAPI Test Client Fixture
# =============================================================================

@pytest.fixture
def test_app(db_session, mock_billing_client, test_tenant_id):
    """
    Create FastAPI test application with dependency overrides.

    Injects:
    - Test database session
    - Mock billing client
    - Test tenant context
    """
    from main import app
    from src.api.routes.webhooks_shopify import get_db_session

    # Store original dependency overrides
    original_overrides = app.dependency_overrides.copy()

    # Override database session dependency to use test session
    def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    yield app

    # Restore original overrides
    app.dependency_overrides = original_overrides


@pytest.fixture
def client(test_app) -> TestClient:
    """Create FastAPI test client."""
    return TestClient(test_app)


# =============================================================================
# Webhook Helper Fixtures
# =============================================================================

@pytest.fixture
def load_webhook_fixture():
    """
    Factory fixture to load webhook JSON fixtures.

    Usage:
        payload = load_webhook_fixture("subscription_created", subscription_id="gid://...")
    """
    def _load(fixture_name: str, **substitutions) -> dict:
        fixture_path = os.path.join(
            os.path.dirname(__file__),
            "fixtures",
            "webhooks",
            f"{fixture_name}.json"
        )

        with open(fixture_path, "r") as f:
            content = f.read()

        # Apply substitutions (e.g., {{SUBSCRIPTION_ID}} -> actual value)
        for key, value in substitutions.items():
            content = content.replace(f"{{{{{key}}}}}", str(value))

        return json.loads(content)

    return _load


@pytest.fixture
def sign_webhook_payload(webhook_secret):
    """
    Factory fixture to sign webhook payloads with HMAC.

    Usage:
        signature = sign_webhook_payload(payload_bytes)
    """
    from src.tests.regression.helpers.hmac_signing import compute_shopify_hmac

    def _sign(payload: bytes) -> str:
        return compute_shopify_hmac(payload, webhook_secret)

    return _sign


# =============================================================================
# Audit Log Helpers
# =============================================================================

@pytest.fixture
def get_billing_events(db_session):
    """
    Factory fixture to query billing events for assertions.

    Usage:
        events = get_billing_events(tenant_id=..., event_type="subscription_created")
    """
    from src.models.billing_event import BillingEvent

    def _get_events(
        tenant_id: Optional[str] = None,
        event_type: Optional[str] = None,
        subscription_id: Optional[str] = None
    ) -> list:
        query = db_session.query(BillingEvent)

        if tenant_id:
            query = query.filter(BillingEvent.tenant_id == tenant_id)
        if event_type:
            query = query.filter(BillingEvent.event_type == event_type)
        if subscription_id:
            query = query.filter(BillingEvent.subscription_id == subscription_id)

        return query.order_by(BillingEvent.created_at.desc()).all()

    return _get_events


# =============================================================================
# Airbyte Connection Fixtures
# =============================================================================

@pytest.fixture
def test_airbyte_connection(db_session, test_tenant_id):
    """Create a test Airbyte connection for tenant A."""
    from src.models.airbyte_connection import (
        TenantAirbyteConnection,
        ConnectionStatus,
        ConnectionType,
    )

    connection = TenantAirbyteConnection(
        id=str(uuid.uuid4()),
        tenant_id=test_tenant_id,
        airbyte_connection_id=f"airbyte-{uuid.uuid4().hex[:12]}",
        connection_name="Test Shopify Connection",
        connection_type=ConnectionType.SOURCE,
        source_type="shopify",
        status=ConnectionStatus.ACTIVE,
        is_enabled=True,
        configuration={"shop": "test-store.myshopify.com"}
    )
    db_session.add(connection)
    db_session.flush()
    return connection


@pytest.fixture
def test_airbyte_connection_b(db_session, test_tenant_id_b):
    """Create a test Airbyte connection for tenant B (isolation tests)."""
    from src.models.airbyte_connection import (
        TenantAirbyteConnection,
        ConnectionStatus,
        ConnectionType,
    )

    connection = TenantAirbyteConnection(
        id=str(uuid.uuid4()),
        tenant_id=test_tenant_id_b,
        airbyte_connection_id=f"airbyte-b-{uuid.uuid4().hex[:12]}",
        connection_name="Test Postgres Connection",
        connection_type=ConnectionType.SOURCE,
        source_type="postgres",
        status=ConnectionStatus.ACTIVE,
        is_enabled=True,
        configuration={"host": "db.example.com"}
    )
    db_session.add(connection)
    db_session.flush()
    return connection
