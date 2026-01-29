"""
E2E Test Configuration and Fixtures.

Provides:
- Test database setup with PostgreSQL
- Mock service instances (Shopify, Airbyte, OpenRouter, Frontegg)
- Test client with dependency overrides
- Test data providers
"""

import os
import uuid
import json
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Generator, AsyncGenerator, Dict, Any
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from fastapi.testclient import TestClient
from httpx import AsyncClient

# Set test environment before importing app modules
os.environ["ENV"] = "test"
os.environ["SHOPIFY_API_SECRET"] = "test-webhook-secret-for-hmac"
os.environ["SHOPIFY_BILLING_TEST_MODE"] = "true"

# Import mocks
from .mocks import (
    MockShopifyServer,
    ShopifyWebhookSimulator,
    MockAirbyteServer,
    MockOpenRouterServer,
    MockFronteggServer,
)

# Import helpers
from .helpers import (
    setup_test_tenant,
    setup_test_airbyte_connection,
    setup_tenant_with_data,
    generate_test_orders,
)

# Test constants
TEST_WEBHOOK_SECRET = "test-webhook-secret-for-hmac"


# =============================================================================
# Database Configuration
# =============================================================================

def _get_test_database_url() -> str:
    """Get PostgreSQL database URL for E2E tests."""
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        database_url = "postgresql://postgres:test@localhost:5432/shopify_analytics_test"

    # Handle Render's postgres:// URL format
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    return database_url


def _get_async_database_url() -> str:
    """Get async PostgreSQL URL."""
    url = _get_test_database_url()
    return url.replace("postgresql://", "postgresql+asyncpg://")


# =============================================================================
# Database Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def db_engine():
    """Create PostgreSQL database engine for E2E tests."""
    database_url = _get_test_database_url()

    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(
            f"PostgreSQL required for E2E tests. "
            f"Set DATABASE_URL or run: docker run -d --name test-pg "
            f"-e POSTGRES_PASSWORD=test -p 5432:5432 postgres:15. "
            f"Error: {e}"
        )

    # Import and create all tables
    from src.db_base import Base
    from src.models import subscription, plan, store, billing_event, airbyte_connection
    from src.ingestion.jobs import models as ingestion_job_models

    Base.metadata.create_all(bind=engine)

    yield engine

    # Cleanup
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(db_engine) -> Generator[Session, None, None]:
    """Create database session with transaction rollback for test isolation."""
    connection = db_engine.connect()
    transaction = connection.begin()

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = SessionLocal()

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(session, transaction):
        nonlocal nested
        if transaction.nested and not transaction._parent.nested:
            nested = connection.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="session")
def async_db_engine():
    """Create async PostgreSQL engine for E2E tests."""
    database_url = _get_async_database_url()

    try:
        engine = create_async_engine(database_url, pool_pre_ping=True)
    except Exception as e:
        pytest.skip(f"Async PostgreSQL connection failed: {e}")

    yield engine


@pytest.fixture
async def async_db_session(async_db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create async database session."""
    async_session_maker = async_sessionmaker(
        async_db_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

    async with async_session_maker() as session:
        yield session


# =============================================================================
# Mock Service Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def mock_frontegg() -> MockFronteggServer:
    """Create mock Frontegg auth server (session-scoped for key consistency)."""
    return MockFronteggServer()


@pytest.fixture
def mock_shopify() -> MockShopifyServer:
    """Create mock Shopify API server."""
    return MockShopifyServer(api_secret=TEST_WEBHOOK_SECRET)


@pytest.fixture
def mock_airbyte() -> MockAirbyteServer:
    """Create mock Airbyte API server."""
    return MockAirbyteServer(sync_delay_seconds=0.1)


@pytest.fixture
def mock_openrouter() -> MockOpenRouterServer:
    """Create mock OpenRouter LLM server."""
    return MockOpenRouterServer()


@pytest.fixture
def webhook_simulator(mock_frontegg) -> ShopifyWebhookSimulator:
    """Create webhook simulator for sending signed webhooks."""
    base_url = os.getenv("TEST_API_BASE_URL", "http://localhost:8000")
    return ShopifyWebhookSimulator(
        api_secret=TEST_WEBHOOK_SECRET,
        base_url=base_url
    )


# =============================================================================
# Test Identity Fixtures
# =============================================================================

@pytest.fixture
def test_tenant_id() -> str:
    """Generate unique tenant ID."""
    return f"e2e-tenant-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def test_tenant_id_b() -> str:
    """Second tenant ID for isolation tests."""
    return f"e2e-tenant-b-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def test_shop_domain(test_tenant_id) -> str:
    """Test shop domain."""
    return f"{test_tenant_id}.myshopify.com"


@pytest.fixture
def test_shop_domain_b(test_tenant_id_b) -> str:
    """Second shop domain."""
    return f"{test_tenant_id_b}.myshopify.com"


# =============================================================================
# Auth Token Fixtures
# =============================================================================

@pytest.fixture
def test_token(mock_frontegg, test_tenant_id) -> str:
    """Create test JWT token for primary tenant."""
    return mock_frontegg.create_test_token(
        tenant_id=test_tenant_id,
        entitlements=["AI_INSIGHTS", "AI_RECOMMENDATIONS", "AI_ACTIONS"],
    )


@pytest.fixture
def test_token_b(mock_frontegg, test_tenant_id_b) -> str:
    """Create test JWT token for second tenant."""
    return mock_frontegg.create_test_token(
        tenant_id=test_tenant_id_b,
        entitlements=["AI_INSIGHTS"],
    )


@pytest.fixture
def free_tier_token(mock_frontegg, test_tenant_id) -> str:
    """Create token for free tier user (no AI entitlements)."""
    return mock_frontegg.create_free_tier_token(test_tenant_id)


@pytest.fixture
def admin_token(mock_frontegg, test_tenant_id) -> str:
    """Create admin token."""
    return mock_frontegg.create_admin_token(test_tenant_id)


# =============================================================================
# FastAPI Test Client Fixtures
# =============================================================================

@pytest.fixture
def test_app(db_session, mock_frontegg, mock_shopify, mock_airbyte, mock_openrouter):
    """
    Create FastAPI test application with all dependencies mocked.
    """
    from main import app
    from src.api.routes.webhooks_shopify import get_db_session

    original_overrides = app.dependency_overrides.copy()

    # Override database session
    def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    # Store mock references for access in tests
    app.state.mock_frontegg = mock_frontegg
    app.state.mock_shopify = mock_shopify
    app.state.mock_airbyte = mock_airbyte
    app.state.mock_openrouter = mock_openrouter

    yield app

    app.dependency_overrides = original_overrides


@pytest.fixture
def client(test_app) -> TestClient:
    """Create synchronous test client."""
    return TestClient(test_app)


@pytest.fixture
async def async_client(test_app) -> AsyncGenerator[AsyncClient, None]:
    """Create async test client."""
    async with AsyncClient(app=test_app, base_url="http://test") as ac:
        yield ac


# =============================================================================
# Test Data Fixtures
# =============================================================================

@pytest.fixture
def test_orders() -> list:
    """Generate standard test orders."""
    return generate_test_orders(count=10)


@pytest.fixture
def test_orders_with_refunds() -> list:
    """Generate orders including refunds and cancellations."""
    from .helpers import generate_test_order

    orders = [
        generate_test_order(total_price=100.0, financial_status="paid"),
        generate_test_order(total_price=150.0, financial_status="paid"),
        generate_test_order(total_price=200.0, financial_status="refunded", refunds=[{"amount": "200.00"}]),
        generate_test_order(total_price=75.0, financial_status="partially_refunded", refunds=[{"amount": "25.00"}]),
        generate_test_order(total_price=50.0, financial_status="paid", cancelled_at=datetime.now(timezone.utc).isoformat()),
    ]
    return orders


@pytest.fixture
def declining_revenue_orders() -> list:
    """Generate orders showing declining revenue pattern."""
    from .helpers import generate_declining_revenue_pattern
    return generate_declining_revenue_pattern(days=14, start_revenue=10000.0, decline_rate=0.2)


# =============================================================================
# Database Entity Fixtures
# =============================================================================

@pytest.fixture
def test_plan_free(db_session):
    """Create free plan."""
    from src.models.plan import Plan

    plan = Plan(
        id="plan_free_e2e",
        name="free",
        display_name="Free",
        description="Free tier",
        price_monthly_cents=0,
        price_yearly_cents=0,
        is_active=True
    )
    db_session.add(plan)
    db_session.flush()
    return plan


@pytest.fixture
def test_plan_pro(db_session):
    """Create pro plan with AI features."""
    from src.models.plan import Plan

    plan = Plan(
        id="plan_pro_e2e",
        name="pro",
        display_name="Pro",
        description="Pro tier with AI features",
        price_monthly_cents=7900,
        price_yearly_cents=79000,
        is_active=True
    )
    db_session.add(plan)
    db_session.flush()
    return plan


@pytest.fixture
def test_store(db_session, test_tenant_id, test_shop_domain):
    """Create test Shopify store."""
    from src.models.store import ShopifyStore

    store = ShopifyStore(
        id=str(uuid.uuid4()),
        tenant_id=test_tenant_id,
        shop_domain=test_shop_domain,
        shop_id=str(hash(test_shop_domain) % 10**12),
        access_token_encrypted="encrypted-test-token",
        scopes="read_products,write_products,read_orders",
        currency="USD",
        timezone="America/New_York",
        status="active"
    )
    db_session.add(store)
    db_session.flush()
    return store


@pytest.fixture
def test_airbyte_connection(db_session, test_tenant_id):
    """Create test Airbyte connection."""
    from src.models.airbyte_connection import (
        TenantAirbyteConnection,
        ConnectionStatus,
        ConnectionType,
    )

    connection = TenantAirbyteConnection(
        id=str(uuid.uuid4()),
        tenant_id=test_tenant_id,
        airbyte_connection_id=f"airbyte-e2e-{uuid.uuid4().hex[:12]}",
        connection_name="E2E Test Shopify Connection",
        connection_type=ConnectionType.SOURCE,
        source_type="shopify",
        status=ConnectionStatus.ACTIVE,
        is_enabled=True,
        configuration={"shop": "test-store.myshopify.com"}
    )
    db_session.add(connection)
    db_session.flush()
    return connection


# =============================================================================
# Utility Fixtures
# =============================================================================

@pytest.fixture
def auth_headers(test_token) -> Dict[str, str]:
    """Standard auth headers for API requests."""
    return {"Authorization": f"Bearer {test_token}"}


@pytest.fixture
def auth_headers_b(test_token_b) -> Dict[str, str]:
    """Auth headers for second tenant."""
    return {"Authorization": f"Bearer {test_token_b}"}


@pytest.fixture
def webhook_secret() -> str:
    """Webhook secret for HMAC signing."""
    return TEST_WEBHOOK_SECRET


# =============================================================================
# Markers
# =============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "e2e: mark test as end-to-end test")
    config.addinivalue_line("markers", "security: mark test as security-focused")
    config.addinivalue_line("markers", "slow: mark test as slow-running")
    config.addinivalue_line("markers", "ai_features: mark test as testing AI features")
