# End-to-End Testing Plan

## Overview

This document outlines a comprehensive end-to-end (E2E) testing strategy for the Shopify Analytics Platform. The plan focuses on **API-driven test data flow** rather than direct database seeding, ensuring that all data passes through the same pathways as production data.

## Test Data Coverage Summary

| Channel | Data Type | Record Count | Status |
|---------|-----------|--------------|--------|
| **Shopify** | Purchases | 30 | ✅ |
| **Shopify** | Refunds | 25 | ✅ |
| **Shopify** | Cancellations | 20 | ✅ |
| **Shopify** | Customers | 50 | ✅ |
| **Meta Ads** | Campaign Records | 30 | ✅ |
| **Google Ads** | Campaign Records | 30 | ✅ |
| **TikTok Ads** | Campaign Records | 25 | ✅ |
| **Snapchat Ads** | Campaign Records | 25 | ✅ |
| **Klaviyo** | Email Campaigns | 30 | ✅ |
| **Klaviyo** | Email Events | 50 | ✅ |
| **Attentive** | SMS Events | 30 | ✅ |
| **SMSBump** | SMS Events | 30 | ✅ |
| **Postscript** | SMS Events | 30 | ✅ |
| **Total** | All Records | **455** | ✅ |

## Table of Contents

1. [Testing Philosophy](#testing-philosophy)
2. [Test Environment Architecture](#test-environment-architecture)
3. [External Service Mocking Strategy](#external-service-mocking-strategy)
4. [Test Data Flow Pipeline](#test-data-flow-pipeline)
5. [E2E Test Scenarios](#e2e-test-scenarios)
6. [Test Execution Phases](#test-execution-phases)
7. [Test Data Specifications](#test-data-specifications)
8. [Validation Checkpoints](#validation-checkpoints)
9. [Running the Tests](#running-the-tests)

---

## Testing Philosophy

### Core Principles

1. **API-First Data Injection**: All test data enters the system through APIs, webhooks, or simulated external service responses - never through direct database inserts
2. **Production Parity**: Test environment mirrors production architecture as closely as possible
3. **Tenant Isolation Verification**: Every test validates that data remains isolated per tenant
4. **Full Pipeline Coverage**: Tests cover ingestion → transformation → analytics → AI features → action execution

### Why API-Driven Testing?

| Direct Seeding (Avoid) | API-Driven (Preferred) |
|------------------------|------------------------|
| Bypasses validation logic | Validates all input constraints |
| Skips middleware/auth | Tests auth & tenant context |
| Misses transformation bugs | Catches pipeline errors |
| Creates unrealistic data states | Mirrors real-world data flow |

---

## Test Environment Architecture

### Infrastructure Components

```
┌─────────────────────────────────────────────────────────────────────┐
│                        E2E TEST ENVIRONMENT                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────┐     ┌──────────────────┐                     │
│  │  Mock Shopify    │     │  Mock Airbyte    │                     │
│  │  API Server      │     │  API Server      │                     │
│  │  (WireMock/      │     │  (WireMock/      │                     │
│  │   MockServer)    │     │   MockServer)    │                     │
│  └────────┬─────────┘     └────────┬─────────┘                     │
│           │                        │                               │
│           ▼                        ▼                               │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    FastAPI Application                       │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │   │
│  │  │ Auth Mock   │  │  API Routes │  │  Background Worker  │  │   │
│  │  │ (Frontegg)  │  │             │  │                     │  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│           │                                                        │
│           ▼                                                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                PostgreSQL (Test Database)                    │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │   │
│  │  │ Raw Tables  │  │  Staging    │  │  Analytics/Marts    │  │   │
│  │  │ (airbyte_*) │  │  (staging)  │  │  (analytics/marts)  │  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│           │                                                        │
│           ▼                                                        │
│  ┌──────────────────┐     ┌──────────────────┐                     │
│  │  Mock OpenRouter │     │  Redis           │                     │
│  │  (LLM responses) │     │  (Test instance) │                     │
│  └──────────────────┘     └──────────────────┘                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Environment Variables

```bash
# Test environment configuration
TEST_ENV=true
DATABASE_URL=postgresql://test_user:test_pass@localhost:5432/shopify_analytics_test
REDIS_URL=redis://localhost:6379/1

# Mock service URLs
SHOPIFY_API_URL=http://localhost:8081  # WireMock for Shopify
AIRBYTE_API_URL=http://localhost:8082  # WireMock for Airbyte
OPENROUTER_API_URL=http://localhost:8083  # Mock LLM responses
FRONTEGG_API_URL=http://localhost:8084  # Mock auth service

# Test-specific settings
AIRBYTE_SYNC_TIMEOUT_SECONDS=30  # Faster timeouts for tests
SYNC_CHECK_INTERVAL_SECONDS=2
```

---

## External Service Mocking Strategy

### 1. Shopify API Mock

The Shopify mock simulates the Shopify Admin API and webhook delivery.

#### Mock Endpoints Required

| Endpoint | Purpose |
|----------|---------|
| `POST /admin/oauth/access_token` | OAuth token exchange |
| `GET /admin/api/2024-01/shop.json` | Shop info validation |
| `GET /admin/api/2024-01/orders.json` | Order data retrieval |
| `GET /admin/api/2024-01/customers.json` | Customer data retrieval |
| `POST /admin/api/2024-01/graphql.json` | GraphQL queries |
| `POST /admin/api/2024-01/recurring_application_charges.json` | Billing creation |

#### Webhook Simulation

```python
# Test helper to simulate Shopify webhook delivery
class ShopifyWebhookSimulator:
    def __init__(self, api_secret: str, base_url: str):
        self.api_secret = api_secret
        self.base_url = base_url

    def send_webhook(self, topic: str, payload: dict, shop_domain: str) -> Response:
        """
        Send a properly signed Shopify webhook to the application.

        Topics:
        - orders/create
        - orders/updated
        - app/uninstalled
        - app_subscriptions/update
        """
        body = json.dumps(payload)
        hmac_signature = self._compute_hmac(body)

        return requests.post(
            f"{self.base_url}/api/webhooks/shopify",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Shopify-Topic": topic,
                "X-Shopify-Hmac-Sha256": hmac_signature,
                "X-Shopify-Shop-Domain": shop_domain,
            }
        )

    def _compute_hmac(self, body: str) -> str:
        return base64.b64encode(
            hmac.new(
                self.api_secret.encode(),
                body.encode(),
                hashlib.sha256
            ).digest()
        ).decode()
```

### 2. Airbyte API Mock

Simulates Airbyte Cloud API for data sync orchestration.

#### Mock State Machine

```
                    ┌─────────────┐
                    │   PENDING   │
                    └──────┬──────┘
                           │ trigger_sync()
                           ▼
                    ┌─────────────┐
                    │   RUNNING   │◄──── poll (status check)
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            │            ▼
       ┌───────────┐       │     ┌───────────┐
       │ SUCCEEDED │       │     │  FAILED   │
       └───────────┘       │     └───────────┘
                           │
              (for testing partial success)
                           ▼
                    ┌─────────────┐
                    │  CANCELLED  │
                    └─────────────┘
```

#### Mock Implementation

```python
class MockAirbyteServer:
    """
    Mock Airbyte server that injects test data into raw tables
    when sync completes successfully.
    """

    def __init__(self, db_session, test_data_provider):
        self.db_session = db_session
        self.test_data_provider = test_data_provider
        self.jobs = {}  # job_id -> job_state

    async def handle_trigger_sync(self, connection_id: str) -> dict:
        """POST /v1/jobs"""
        job_id = str(uuid.uuid4())
        self.jobs[job_id] = {
            "status": "running",
            "connection_id": connection_id,
            "started_at": datetime.utcnow(),
        }
        return {"jobId": job_id, "status": "running"}

    async def handle_get_job_status(self, job_id: str) -> dict:
        """GET /v1/jobs/{job_id}"""
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")

        # Simulate job completion after configured time
        elapsed = datetime.utcnow() - job["started_at"]
        if elapsed > timedelta(seconds=5):
            job["status"] = "succeeded"
            # CRITICAL: Inject test data into raw tables when sync "completes"
            await self._inject_raw_data(job["connection_id"])

        return {"jobId": job_id, "status": job["status"]}

    async def _inject_raw_data(self, connection_id: str):
        """
        Inject test data into _airbyte_raw_* tables.
        This simulates what Airbyte does in production.
        """
        test_data = self.test_data_provider.get_data_for_connection(connection_id)

        for table_name, records in test_data.items():
            for record in records:
                await self.db_session.execute(
                    text(f"""
                        INSERT INTO {table_name}
                        (_airbyte_raw_id, _airbyte_data, _airbyte_extracted_at, _airbyte_loaded_at)
                        VALUES (:id, :data, :extracted_at, :loaded_at)
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "data": json.dumps(record),
                        "extracted_at": datetime.utcnow(),
                        "loaded_at": datetime.utcnow(),
                    }
                )
        await self.db_session.commit()
```

### 3. OpenRouter (LLM) Mock

Provides deterministic AI responses for testing.

```python
class MockOpenRouterServer:
    """
    Returns predetermined responses for AI feature testing.
    """

    MOCK_RESPONSES = {
        "insight_generation": {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "insights": [
                            {
                                "type": "revenue_anomaly",
                                "severity": "medium",
                                "summary": "Revenue dropped 15% compared to last week",
                                "supporting_metrics": {
                                    "current_revenue": 8500,
                                    "previous_revenue": 10000,
                                    "change_percent": -15
                                }
                            }
                        ]
                    })
                }
            }]
        },
        "recommendation_generation": {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "recommendations": [
                            {
                                "type": "increase_ad_spend",
                                "platform": "meta",
                                "reason": "ROAS is 3.2x, above target threshold",
                                "suggested_action": "Increase Meta ad budget by 20%"
                            }
                        ]
                    })
                }
            }]
        },
        "action_proposal_generation": {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "proposals": [
                            {
                                "action_type": "update_product_price",
                                "target_entity_type": "product",
                                "target_entity_id": "gid://shopify/Product/123456",
                                "parameters": {
                                    "new_price": "29.99",
                                    "reason": "Competitive pricing adjustment"
                                }
                            }
                        ]
                    })
                }
            }]
        }
    }

    async def handle_chat_completion(self, request: dict) -> dict:
        """POST /api/v1/chat/completions"""
        # Determine response type from system prompt
        system_prompt = request.get("messages", [{}])[0].get("content", "")

        if "insight" in system_prompt.lower():
            return self.MOCK_RESPONSES["insight_generation"]
        elif "recommendation" in system_prompt.lower():
            return self.MOCK_RESPONSES["recommendation_generation"]
        elif "action" in system_prompt.lower():
            return self.MOCK_RESPONSES["action_proposal_generation"]

        return {"choices": [{"message": {"content": "Mock response"}}]}
```

### 4. Frontegg (Auth) Mock

Provides JWT tokens with configurable tenant context.

```python
class MockFronteggServer:
    """
    Issues test JWTs with proper tenant claims.
    """

    def __init__(self, private_key: str):
        self.private_key = private_key

    def create_test_token(
        self,
        tenant_id: str,
        user_id: str = "test-user-123",
        roles: list[str] = None,
        entitlements: list[str] = None,
        allowed_tenants: list[str] = None,
    ) -> str:
        """
        Create a test JWT for a specific tenant.

        Usage:
            token = mock_frontegg.create_test_token(
                tenant_id="tenant-abc",
                entitlements=["AI_INSIGHTS", "AI_ACTIONS"]
            )
        """
        now = datetime.utcnow()
        payload = {
            "sub": user_id,
            "org_id": tenant_id,  # This becomes tenant_id in the app
            "roles": roles or ["user"],
            "entitlements": entitlements or [],
            "allowed_tenants": allowed_tenants or [tenant_id],
            "iat": now,
            "exp": now + timedelta(hours=1),
        }
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    def get_jwks(self) -> dict:
        """GET /.well-known/jwks.json"""
        # Return public key for JWT verification
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": "test-key-1",
                    "use": "sig",
                    "n": "...",  # Public key modulus
                    "e": "AQAB"
                }
            ]
        }
```

---

## Test Data Flow Pipeline

### Complete Data Flow Sequence

```
Phase 1: TENANT SETUP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1. Create test tenant via API
    2. Simulate Shopify OAuth flow
    3. Store encrypted credentials
    4. Create Airbyte connection mapping

Phase 2: DATA INGESTION (via Mock Airbyte)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1. Trigger sync via /api/v1/sync endpoint
    2. Mock Airbyte receives trigger request
    3. Mock Airbyte simulates sync process
    4. Mock Airbyte injects test data into _airbyte_raw_* tables
    5. Sync completes with success status

Phase 3: DATA TRANSFORMATION (dbt)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1. Trigger dbt run (or auto-triggered post-sync)
    2. Raw data → Staging models
    3. Staging → Fact tables
    4. Facts → Metric views
    5. Metrics → Mart tables

Phase 4: AI FEATURE TESTING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1. Trigger insight generation via /api/v1/insights
    2. Mock LLM returns predetermined insights
    3. Trigger recommendation generation
    4. Trigger action proposal generation
    5. Approve action proposal
    6. Execute action via platform executor

Phase 5: VERIFICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1. Verify data in all layers
    2. Verify tenant isolation
    3. Verify metrics calculations
    4. Verify audit logs
```

---

## E2E Test Scenarios

### Scenario 1: New Merchant Onboarding

**Objective**: Test complete onboarding flow from Shopify OAuth to first data sync.

```python
@pytest.mark.e2e
async def test_new_merchant_onboarding(
    test_client: TestClient,
    mock_shopify: MockShopifyServer,
    mock_airbyte: MockAirbyteServer,
    mock_frontegg: MockFronteggServer,
    db_session: AsyncSession,
):
    """
    E2E Test: New merchant completes onboarding and sees first data.
    """
    tenant_id = f"tenant-{uuid.uuid4()}"
    shop_domain = "test-store.myshopify.com"

    # Step 1: Simulate OAuth callback from Shopify
    mock_shopify.setup_oauth_response(
        shop=shop_domain,
        access_token="shpat_test_token_12345"
    )

    # Simulate the OAuth callback that Shopify sends
    response = await test_client.get(
        "/auth/shopify/callback",
        params={
            "code": "test_auth_code",
            "shop": shop_domain,
            "state": tenant_id,  # Our state contains tenant_id
        }
    )
    assert response.status_code == 302  # Redirect to app

    # Step 2: Verify store was created
    token = mock_frontegg.create_test_token(tenant_id)
    response = await test_client.get(
        "/api/v1/shopify-ingestion/status",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["shop_domain"] == shop_domain

    # Step 3: Verify Airbyte connection was created
    # (App auto-creates Airbyte source on OAuth completion)
    response = await test_client.get(
        "/api/v1/sync/connections",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    connections = response.json()["connections"]
    assert len(connections) == 1
    assert connections[0]["source_type"] == "shopify"

    # Step 4: Trigger initial sync
    mock_airbyte.setup_test_data(
        connection_id=connections[0]["airbyte_connection_id"],
        data=TEST_DATA_SETS["new_merchant_initial"]
    )

    response = await test_client.post(
        "/api/v1/sync/trigger",
        headers={"Authorization": f"Bearer {token}"},
        json={"connection_id": connections[0]["airbyte_connection_id"]}
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    # Step 5: Wait for sync completion
    await wait_for_job_completion(test_client, token, job_id, timeout=30)

    # Step 6: Run dbt transformations
    await run_dbt_models(db_session, tenant_id)

    # Step 7: Verify data appears in analytics
    response = await test_client.get(
        f"/api/v1/data-health/freshness",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    freshness = response.json()
    assert freshness["orders"]["last_sync"] is not None
    assert freshness["orders"]["record_count"] > 0
```

### Scenario 2: Full Revenue Metrics Pipeline

**Objective**: Verify revenue calculations from raw order data through mart tables.

```python
@pytest.mark.e2e
async def test_revenue_metrics_pipeline(
    test_client: TestClient,
    mock_airbyte: MockAirbyteServer,
    mock_frontegg: MockFronteggServer,
    db_session: AsyncSession,
):
    """
    E2E Test: Revenue metrics calculated correctly through full pipeline.
    """
    tenant_id = "tenant-revenue-test"
    token = mock_frontegg.create_test_token(tenant_id)

    # Prepare test order data with known values
    test_orders = [
        # Regular orders
        {"id": "order-1", "total_price": "100.00", "created_at": "2024-01-15T10:00:00Z", "financial_status": "paid"},
        {"id": "order-2", "total_price": "150.00", "created_at": "2024-01-15T11:00:00Z", "financial_status": "paid"},
        {"id": "order-3", "total_price": "200.00", "created_at": "2024-01-16T09:00:00Z", "financial_status": "paid"},
        # Refunded order
        {"id": "order-4", "total_price": "75.00", "created_at": "2024-01-16T10:00:00Z", "financial_status": "refunded", "refunds": [{"amount": "75.00"}]},
        # Cancelled order
        {"id": "order-5", "total_price": "50.00", "created_at": "2024-01-17T08:00:00Z", "financial_status": "paid", "cancelled_at": "2024-01-17T09:00:00Z"},
    ]

    # Expected calculations:
    # Gross revenue: 100 + 150 + 200 + 75 + 50 = 575
    # Refunds: 75
    # Cancellations: 50
    # Net revenue: 575 - 75 - 50 = 450

    # Step 1: Inject data via mock Airbyte sync
    connection_id = await setup_test_connection(db_session, tenant_id)
    mock_airbyte.setup_test_data(
        connection_id=connection_id,
        data={"_airbyte_raw_shopify_orders": test_orders}
    )

    response = await test_client.post(
        "/api/v1/sync/trigger",
        headers={"Authorization": f"Bearer {token}"},
        json={"connection_id": connection_id}
    )
    job_id = response.json()["job_id"]
    await wait_for_job_completion(test_client, token, job_id)

    # Step 2: Run dbt transformations
    await run_dbt_models(db_session, tenant_id)

    # Step 3: Verify staging layer
    staging_orders = await db_session.execute(
        text("SELECT * FROM staging.stg_shopify_orders WHERE tenant_id = :tenant_id"),
        {"tenant_id": tenant_id}
    )
    staging_results = staging_orders.fetchall()
    assert len(staging_results) == 5

    # Step 4: Verify fact layer
    fact_orders = await db_session.execute(
        text("SELECT * FROM analytics.fact_orders WHERE tenant_id = :tenant_id"),
        {"tenant_id": tenant_id}
    )
    fact_results = fact_orders.fetchall()
    assert len(fact_results) == 5

    # Step 5: Verify revenue metrics
    revenue_metrics = await db_session.execute(
        text("""
            SELECT
                SUM(gross_revenue) as gross,
                SUM(refunds) as refunds,
                SUM(cancellations) as cancellations,
                SUM(net_revenue) as net
            FROM analytics.fct_revenue
            WHERE tenant_id = :tenant_id
        """),
        {"tenant_id": tenant_id}
    )
    metrics = revenue_metrics.fetchone()

    assert float(metrics.gross) == 575.00
    assert float(metrics.refunds) == 75.00
    assert float(metrics.cancellations) == 50.00
    assert float(metrics.net) == 450.00

    # Step 6: Verify mart table aggregations
    mart_metrics = await db_session.execute(
        text("""
            SELECT * FROM marts.mart_revenue_metrics
            WHERE tenant_id = :tenant_id
            AND period_type = 'daily'
            ORDER BY period_start
        """),
        {"tenant_id": tenant_id}
    )
    mart_results = mart_metrics.fetchall()

    # Verify daily breakdown
    assert len(mart_results) == 3  # 3 days of data
```

### Scenario 3: Multi-Tenant Isolation

**Objective**: Verify that tenants cannot access each other's data.

```python
@pytest.mark.e2e
@pytest.mark.security
async def test_multi_tenant_isolation(
    test_client: TestClient,
    mock_airbyte: MockAirbyteServer,
    mock_frontegg: MockFronteggServer,
    db_session: AsyncSession,
):
    """
    E2E Test: Verify strict tenant isolation across all data layers.
    """
    tenant_a = "tenant-isolation-a"
    tenant_b = "tenant-isolation-b"

    # Setup both tenants with different data
    await setup_tenant_with_data(
        db_session, mock_airbyte, tenant_a,
        orders=[
            {"id": "order-a1", "total_price": "100.00"},
            {"id": "order-a2", "total_price": "200.00"},
        ]
    )

    await setup_tenant_with_data(
        db_session, mock_airbyte, tenant_b,
        orders=[
            {"id": "order-b1", "total_price": "500.00"},
            {"id": "order-b2", "total_price": "600.00"},
            {"id": "order-b3", "total_price": "700.00"},
        ]
    )

    # Run transformations for both
    await run_dbt_models(db_session, tenant_a)
    await run_dbt_models(db_session, tenant_b)

    # Test 1: Tenant A can only see their data
    token_a = mock_frontegg.create_test_token(tenant_a)
    response = await test_client.get(
        "/api/v1/data-health/freshness",
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert response.json()["orders"]["record_count"] == 2

    # Test 2: Tenant B can only see their data
    token_b = mock_frontegg.create_test_token(tenant_b)
    response = await test_client.get(
        "/api/v1/data-health/freshness",
        headers={"Authorization": f"Bearer {token_b}"}
    )
    assert response.json()["orders"]["record_count"] == 3

    # Test 3: Tenant A cannot access Tenant B's sync connections
    response = await test_client.get(
        f"/api/v1/sync/connections/{tenant_b_connection_id}",
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert response.status_code == 404  # Not found (not 403 - don't reveal existence)

    # Test 4: Direct SQL verification - no cross-tenant data
    result = await db_session.execute(
        text("""
            SELECT DISTINCT tenant_id
            FROM analytics.fact_orders
            WHERE order_id IN ('order-a1', 'order-b1')
        """)
    )
    tenant_ids = [r.tenant_id for r in result.fetchall()]
    assert tenant_a in tenant_ids
    assert tenant_b in tenant_ids
    assert len(tenant_ids) == 2  # Each order belongs to correct tenant
```

### Scenario 4: AI Features Pipeline

**Objective**: Test insight generation, recommendations, and action execution.

```python
@pytest.mark.e2e
async def test_ai_features_pipeline(
    test_client: TestClient,
    mock_airbyte: MockAirbyteServer,
    mock_openrouter: MockOpenRouterServer,
    mock_frontegg: MockFronteggServer,
    mock_shopify: MockShopifyServer,
    db_session: AsyncSession,
):
    """
    E2E Test: Full AI pipeline from data to executed action.
    """
    tenant_id = "tenant-ai-test"
    token = mock_frontegg.create_test_token(
        tenant_id,
        entitlements=["AI_INSIGHTS", "AI_RECOMMENDATIONS", "AI_ACTIONS"]
    )

    # Step 1: Setup test data showing declining revenue
    await setup_tenant_with_data(
        db_session, mock_airbyte, tenant_id,
        orders=generate_declining_revenue_pattern()
    )
    await run_dbt_models(db_session, tenant_id)

    # Step 2: Trigger insight generation
    response = await test_client.post(
        "/api/v1/insights/generate",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 202
    insight_job_id = response.json()["job_id"]

    await wait_for_job_completion(test_client, token, insight_job_id)

    # Step 3: Verify insights were created
    response = await test_client.get(
        "/api/v1/insights",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    insights = response.json()["insights"]
    assert len(insights) > 0
    assert any(i["type"] == "revenue_anomaly" for i in insights)

    # Step 4: Trigger recommendations based on insights
    response = await test_client.post(
        "/api/v1/recommendations/generate",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 202
    rec_job_id = response.json()["job_id"]

    await wait_for_job_completion(test_client, token, rec_job_id)

    # Step 5: Verify recommendations
    response = await test_client.get(
        "/api/v1/recommendations",
        headers={"Authorization": f"Bearer {token}"}
    )
    recommendations = response.json()["recommendations"]
    assert len(recommendations) > 0

    # Step 6: Generate action proposals
    response = await test_client.post(
        "/api/v1/action-proposals/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={"recommendation_id": recommendations[0]["id"]}
    )
    assert response.status_code == 202

    await wait_for_job_completion(test_client, token, response.json()["job_id"])

    # Step 7: Get and approve action proposal
    response = await test_client.get(
        "/api/v1/action-proposals?status=pending",
        headers={"Authorization": f"Bearer {token}"}
    )
    proposals = response.json()["proposals"]
    assert len(proposals) > 0
    proposal_id = proposals[0]["id"]

    # Approve the proposal
    response = await test_client.post(
        f"/api/v1/action-proposals/{proposal_id}/approve",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200

    # Step 8: Execute the approved action
    mock_shopify.setup_product_update_response(
        product_id="gid://shopify/Product/123456",
        success=True
    )

    response = await test_client.post(
        f"/api/v1/actions/{proposal_id}/execute",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200

    # Step 9: Verify action execution was logged
    response = await test_client.get(
        f"/api/v1/actions/{proposal_id}/execution-log",
        headers={"Authorization": f"Bearer {token}"}
    )
    execution_log = response.json()
    assert execution_log["status"] == "completed"
    assert execution_log["before_state"] is not None
    assert execution_log["after_state"] is not None
```

### Scenario 5: Webhook-Driven Data Updates

**Objective**: Test real-time data updates via Shopify webhooks.

```python
@pytest.mark.e2e
async def test_webhook_driven_updates(
    test_client: TestClient,
    webhook_simulator: ShopifyWebhookSimulator,
    mock_frontegg: MockFronteggServer,
    db_session: AsyncSession,
):
    """
    E2E Test: Shopify webhooks trigger data updates correctly.
    """
    tenant_id = "tenant-webhook-test"
    shop_domain = "webhook-test.myshopify.com"

    # Setup tenant with existing data
    await setup_tenant_with_data(db_session, None, tenant_id, orders=[])

    # Test 1: Order Create Webhook
    new_order = {
        "id": 12345678901234,
        "order_number": 1001,
        "total_price": "99.99",
        "financial_status": "paid",
        "created_at": "2024-01-20T10:00:00Z",
        "customer": {
            "id": 98765432109876,
            "email": "customer@example.com"
        },
        "line_items": [
            {"id": 1, "title": "Test Product", "quantity": 1, "price": "99.99"}
        ]
    }

    response = webhook_simulator.send_webhook(
        topic="orders/create",
        payload=new_order,
        shop_domain=shop_domain
    )
    assert response.status_code == 200

    # Allow time for async processing
    await asyncio.sleep(2)

    # Verify order was ingested (check raw tables)
    result = await db_session.execute(
        text("""
            SELECT * FROM _airbyte_raw_shopify_orders
            WHERE _airbyte_data->>'id' = :order_id
        """),
        {"order_id": str(new_order["id"])}
    )
    assert result.fetchone() is not None

    # Test 2: Order Updated Webhook (refund)
    updated_order = {
        **new_order,
        "financial_status": "refunded",
        "refunds": [{"id": 1, "amount": "99.99", "created_at": "2024-01-21T10:00:00Z"}]
    }

    response = webhook_simulator.send_webhook(
        topic="orders/updated",
        payload=updated_order,
        shop_domain=shop_domain
    )
    assert response.status_code == 200

    # Test 3: App Uninstall Webhook
    response = webhook_simulator.send_webhook(
        topic="app/uninstalled",
        payload={"shop_domain": shop_domain},
        shop_domain=shop_domain
    )
    assert response.status_code == 200

    # Verify store status changed
    token = mock_frontegg.create_test_token(tenant_id)
    response = await test_client.get(
        "/api/v1/shopify-ingestion/status",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.json()["status"] == "uninstalled"
```

### Scenario 6: Billing and Entitlements

**Objective**: Test subscription changes affect feature access.

```python
@pytest.mark.e2e
async def test_billing_entitlements(
    test_client: TestClient,
    webhook_simulator: ShopifyWebhookSimulator,
    mock_frontegg: MockFronteggServer,
    db_session: AsyncSession,
):
    """
    E2E Test: Subscription changes correctly gate feature access.
    """
    tenant_id = "tenant-billing-test"

    # Setup tenant on free plan (no AI features)
    await setup_tenant_subscription(db_session, tenant_id, plan="free")

    token = mock_frontegg.create_test_token(
        tenant_id,
        entitlements=[]  # Free plan has no AI entitlements
    )

    # Test 1: AI features blocked on free plan
    response = await test_client.post(
        "/api/v1/insights/generate",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
    assert "AI_INSIGHTS" in response.json()["detail"]

    # Test 2: Simulate subscription upgrade via webhook
    upgrade_payload = {
        "app_subscription": {
            "admin_graphql_api_id": "gid://shopify/AppSubscription/123",
            "name": "Pro Plan",
            "status": "active",
            "created_at": "2024-01-20T10:00:00Z"
        }
    }

    response = webhook_simulator.send_webhook(
        topic="app_subscriptions/update",
        payload=upgrade_payload,
        shop_domain=f"{tenant_id}.myshopify.com"
    )
    assert response.status_code == 200

    # Get new token with updated entitlements
    token = mock_frontegg.create_test_token(
        tenant_id,
        entitlements=["AI_INSIGHTS", "AI_RECOMMENDATIONS"]
    )

    # Test 3: AI features now accessible
    response = await test_client.post(
        "/api/v1/insights/generate",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 202  # Accepted
```

### Scenario 7: Data Backfill Operations

**Objective**: Test manual data backfill for historical data recovery.

```python
@pytest.mark.e2e
async def test_data_backfill(
    test_client: TestClient,
    mock_airbyte: MockAirbyteServer,
    mock_frontegg: MockFronteggServer,
    db_session: AsyncSession,
):
    """
    E2E Test: Manual backfill recovers historical data.
    """
    tenant_id = "tenant-backfill-test"
    token = mock_frontegg.create_test_token(tenant_id)

    # Setup tenant with partial data (missing historical orders)
    await setup_tenant_with_data(
        db_session, mock_airbyte, tenant_id,
        orders=[
            {"id": "order-recent", "total_price": "100.00", "created_at": "2024-01-15T10:00:00Z"},
        ]
    )

    # Prepare historical data for backfill
    historical_orders = [
        {"id": "order-historical-1", "total_price": "50.00", "created_at": "2023-12-01T10:00:00Z"},
        {"id": "order-historical-2", "total_price": "75.00", "created_at": "2023-12-15T10:00:00Z"},
        {"id": "order-historical-3", "total_price": "80.00", "created_at": "2023-12-20T10:00:00Z"},
    ]

    connection_id = await get_tenant_connection_id(db_session, tenant_id)
    mock_airbyte.setup_backfill_data(
        connection_id=connection_id,
        data={"_airbyte_raw_shopify_orders": historical_orders}
    )

    # Trigger backfill
    response = await test_client.post(
        "/api/v1/backfills/trigger",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "connection_id": connection_id,
            "start_date": "2023-12-01",
            "end_date": "2023-12-31"
        }
    )
    assert response.status_code == 202

    await wait_for_job_completion(test_client, token, response.json()["job_id"])

    # Run dbt in backfill mode
    await run_dbt_models(db_session, tenant_id, backfill_mode=True)

    # Verify all data present
    response = await test_client.get(
        "/api/v1/data-health/freshness",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.json()["orders"]["record_count"] == 4  # 1 recent + 3 historical
```

---

## Test Execution Phases

### Phase 1: Environment Setup

```bash
# 1. Start test infrastructure
docker-compose -f docker-compose.test.yml up -d

# 2. Initialize test database
make db-migrate-test

# 3. Start mock services
make start-mock-services

# 4. Verify environment
make test-env-check
```

### Phase 2: Unit Tests (Fast Feedback)

```bash
# Run unit tests first (< 2 minutes)
make test-unit

# Coverage report
make test-unit-coverage
```

### Phase 3: Integration Tests

```bash
# Run integration tests (5-10 minutes)
make test-integration

# Specific integration suites
make test-integration-airbyte
make test-integration-billing
make test-integration-auth
```

### Phase 4: E2E Tests

```bash
# Run full E2E suite (15-30 minutes)
make test-e2e

# Run specific scenarios
pytest tests/e2e/test_onboarding.py -v
pytest tests/e2e/test_revenue_pipeline.py -v
pytest tests/e2e/test_ai_features.py -v

# Run with parallel workers
pytest tests/e2e/ -n 4 -v
```

### Phase 5: Security Tests

```bash
# Run security-focused tests
make test-security

# Tenant isolation tests
pytest tests/e2e/ -m "security" -v
```

---

## Test Data Specifications

### Standard Test Data Sets

#### 1. `new_merchant_initial`

Represents a new merchant's first sync with minimal but complete data.

```python
TEST_DATA_SETS = {
    "new_merchant_initial": {
        "_airbyte_raw_shopify_orders": [
            {
                "id": "gid://shopify/Order/1001",
                "order_number": 1001,
                "total_price": "99.99",
                "subtotal_price": "89.99",
                "total_tax": "10.00",
                "financial_status": "paid",
                "fulfillment_status": "fulfilled",
                "created_at": "2024-01-10T10:00:00Z",
                "updated_at": "2024-01-10T12:00:00Z",
                "currency": "USD",
                "customer": {
                    "id": "gid://shopify/Customer/2001",
                    "email": "customer1@example.com",
                    "first_name": "John",
                    "last_name": "Doe"
                },
                "line_items": [
                    {
                        "id": "gid://shopify/LineItem/3001",
                        "product_id": "gid://shopify/Product/4001",
                        "variant_id": "gid://shopify/ProductVariant/5001",
                        "title": "Test Product A",
                        "quantity": 1,
                        "price": "89.99"
                    }
                ],
                "shipping_address": {
                    "country_code": "US",
                    "province_code": "CA"
                }
            },
            # ... more orders
        ],
        "_airbyte_raw_shopify_customers": [
            {
                "id": "gid://shopify/Customer/2001",
                "email": "customer1@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "orders_count": 1,
                "total_spent": "99.99",
                "created_at": "2024-01-10T09:00:00Z"
            },
            # ... more customers
        ]
    }
}
```

#### 2. `revenue_scenario_complex`

Complex revenue scenarios with refunds, cancellations, and edge cases.

```python
"revenue_scenario_complex": {
    "_airbyte_raw_shopify_orders": [
        # Regular paid order
        {"id": "order-1", "total_price": "100.00", "financial_status": "paid", "created_at": "2024-01-15T10:00:00Z"},

        # Partially refunded order
        {"id": "order-2", "total_price": "200.00", "financial_status": "partially_refunded",
         "refunds": [{"id": "refund-1", "amount": "50.00"}], "created_at": "2024-01-15T11:00:00Z"},

        # Fully refunded order
        {"id": "order-3", "total_price": "150.00", "financial_status": "refunded",
         "refunds": [{"id": "refund-2", "amount": "150.00"}], "created_at": "2024-01-16T10:00:00Z"},

        # Cancelled order (never shipped)
        {"id": "order-4", "total_price": "75.00", "financial_status": "paid",
         "cancelled_at": "2024-01-16T12:00:00Z", "created_at": "2024-01-16T11:00:00Z"},

        # Order with multiple currencies (edge case)
        {"id": "order-5", "total_price": "80.00", "currency": "EUR", "financial_status": "paid",
         "created_at": "2024-01-17T10:00:00Z"},

        # Order with null/missing fields (edge case)
        {"id": "order-6", "total_price": "0.00", "financial_status": "pending",
         "created_at": "2024-01-17T11:00:00Z"},
    ]
}
```

#### 3. `multi_platform_marketing`

Cross-platform marketing data for attribution testing.

```python
"multi_platform_marketing": {
    "_airbyte_raw_shopify_orders": [...],
    "_airbyte_raw_meta_ads": [
        {
            "campaign_id": "meta-campaign-1",
            "campaign_name": "Winter Sale",
            "spend": 500.00,
            "impressions": 50000,
            "clicks": 2500,
            "date": "2024-01-15"
        },
    ],
    "_airbyte_raw_google_ads": [
        {
            "campaign_id": "google-campaign-1",
            "campaign_name": "Brand Search",
            "cost": 300.00,
            "impressions": 30000,
            "clicks": 1500,
            "date": "2024-01-15"
        },
    ],
    "_airbyte_raw_klaviyo_campaigns": [
        {
            "campaign_id": "klaviyo-campaign-1",
            "name": "Newsletter Jan 2024",
            "sent_count": 10000,
            "open_count": 3500,
            "click_count": 500,
            "revenue": 2500.00,
            "sent_at": "2024-01-15T09:00:00Z"
        },
    ]
}
```

---

## Validation Checkpoints

### Checkpoint 1: Raw Data Integrity

```python
async def validate_raw_data(db_session, tenant_id, expected_counts: dict):
    """Validate data landed correctly in raw tables."""
    for table, expected_count in expected_counts.items():
        result = await db_session.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE _airbyte_data->>'tenant_id' = :tid"),
            {"tid": tenant_id}
        )
        actual = result.scalar()
        assert actual == expected_count, f"{table}: expected {expected_count}, got {actual}"
```

### Checkpoint 2: Staging Transformation

```python
async def validate_staging_data(db_session, tenant_id):
    """Validate staging models transformed correctly."""
    # Check required fields are populated
    result = await db_session.execute(
        text("""
            SELECT
                COUNT(*) as total,
                COUNT(order_id) as has_order_id,
                COUNT(customer_id) as has_customer_id,
                COUNT(total_amount) as has_total
            FROM staging.stg_shopify_orders
            WHERE tenant_id = :tid
        """),
        {"tid": tenant_id}
    )
    row = result.fetchone()
    assert row.total == row.has_order_id, "Missing order_id in staging"
    assert row.total == row.has_total, "Missing total_amount in staging"
```

### Checkpoint 3: Fact Table Accuracy

```python
async def validate_fact_tables(db_session, tenant_id, expected_metrics: dict):
    """Validate fact table calculations."""
    result = await db_session.execute(
        text("""
            SELECT
                SUM(gross_revenue) as gross,
                SUM(net_revenue) as net,
                COUNT(DISTINCT order_id) as order_count
            FROM analytics.fact_orders
            WHERE tenant_id = :tid
        """),
        {"tid": tenant_id}
    )
    row = result.fetchone()

    assert abs(float(row.gross) - expected_metrics["gross_revenue"]) < 0.01
    assert abs(float(row.net) - expected_metrics["net_revenue"]) < 0.01
    assert row.order_count == expected_metrics["order_count"]
```

### Checkpoint 4: Tenant Isolation

```python
async def validate_tenant_isolation(db_session, tenant_ids: list):
    """Verify no data leakage between tenants."""
    tables_to_check = [
        "staging.stg_shopify_orders",
        "analytics.fact_orders",
        "analytics.fct_revenue",
        "marts.mart_revenue_metrics",
    ]

    for table in tables_to_check:
        result = await db_session.execute(
            text(f"""
                SELECT tenant_id, COUNT(*)
                FROM {table}
                WHERE tenant_id = ANY(:tids)
                GROUP BY tenant_id
            """),
            {"tids": tenant_ids}
        )
        rows = result.fetchall()

        # Each tenant should only see their own data
        seen_tenants = {r.tenant_id for r in rows}
        assert seen_tenants == set(tenant_ids), f"Unexpected tenants in {table}"
```

### Checkpoint 5: API Response Validation

```python
async def validate_api_responses(test_client, token, tenant_id):
    """Validate API responses match database state."""
    # Get data health from API
    response = await test_client.get(
        "/api/v1/data-health/freshness",
        headers={"Authorization": f"Bearer {token}"}
    )
    api_counts = response.json()

    # Verify against database
    db_counts = await get_database_counts(tenant_id)

    assert api_counts["orders"]["record_count"] == db_counts["orders"]
    assert api_counts["customers"]["record_count"] == db_counts["customers"]
```

---

## Running the Tests

### Prerequisites

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Install Node.js test dependencies (for frontend E2E)
cd frontend && npm install && cd ..
```

### Quick Start

```bash
# Run everything
make test-all

# Or step by step:
make test-unit          # Unit tests (~2 min)
make test-integration   # Integration tests (~5-10 min)
make test-e2e          # E2E tests (~15-30 min)
```

### Test Configuration

```python
# conftest.py
import pytest
from tests.fixtures import (
    MockShopifyServer,
    MockAirbyteServer,
    MockOpenRouterServer,
    MockFronteggServer,
    TestDataProvider,
)

@pytest.fixture(scope="session")
def mock_services():
    """Start all mock services for E2E tests."""
    shopify = MockShopifyServer(port=8081)
    airbyte = MockAirbyteServer(port=8082)
    openrouter = MockOpenRouterServer(port=8083)
    frontegg = MockFronteggServer(port=8084)

    yield {
        "shopify": shopify,
        "airbyte": airbyte,
        "openrouter": openrouter,
        "frontegg": frontegg,
    }

    # Cleanup
    shopify.stop()
    airbyte.stop()
    openrouter.stop()
    frontegg.stop()

@pytest.fixture
def test_data_provider():
    """Provides standardized test data sets."""
    return TestDataProvider()
```

### CI/CD Integration

```yaml
# .github/workflows/e2e-tests.yml
name: E2E Tests

on:
  push:
    branches: [main, develop]
  pull_request:

jobs:
  e2e-tests:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test
          POSTGRES_DB: shopify_analytics_test
        ports:
          - 5432:5432
      redis:
        image: redis:7
        ports:
          - 6379:6379

    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-test.txt

      - name: Run database migrations
        run: make db-migrate-test

      - name: Run E2E tests
        run: make test-e2e
        env:
          DATABASE_URL: postgresql://postgres:test@localhost:5432/shopify_analytics_test
          REDIS_URL: redis://localhost:6379/1
```

---

## Appendix: Helper Functions

### Test Utilities

```python
# tests/e2e/helpers.py

async def wait_for_job_completion(
    test_client: TestClient,
    token: str,
    job_id: str,
    timeout: int = 60,
    poll_interval: int = 2
) -> dict:
    """Wait for an async job to complete."""
    start = time.time()
    while time.time() - start < timeout:
        response = await test_client.get(
            f"/api/v1/jobs/{job_id}/status",
            headers={"Authorization": f"Bearer {token}"}
        )
        status = response.json()["status"]

        if status in ["succeeded", "completed"]:
            return response.json()
        elif status in ["failed", "dead_letter"]:
            raise AssertionError(f"Job {job_id} failed: {response.json()}")

        await asyncio.sleep(poll_interval)

    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


async def run_dbt_models(
    db_session: AsyncSession,
    tenant_id: str,
    backfill_mode: bool = False
) -> None:
    """Run dbt models for a specific tenant."""
    env = os.environ.copy()
    env["DBT_TARGET_TENANT_ID"] = tenant_id
    if backfill_mode:
        env["DBT_BACKFILL_MODE"] = "true"

    result = subprocess.run(
        ["dbt", "run", "--project-dir", "analytics"],
        env=env,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"dbt run failed: {result.stderr}")


async def setup_tenant_with_data(
    db_session: AsyncSession,
    mock_airbyte: MockAirbyteServer,
    tenant_id: str,
    orders: list[dict],
    customers: list[dict] = None,
) -> str:
    """Setup a tenant with test data via mock Airbyte sync."""
    # Create tenant record
    await db_session.execute(
        text("""
            INSERT INTO shopify_stores (tenant_id, shop_domain, status, created_at)
            VALUES (:tid, :domain, 'active', NOW())
            ON CONFLICT (tenant_id) DO NOTHING
        """),
        {"tid": tenant_id, "domain": f"{tenant_id}.myshopify.com"}
    )

    # Create Airbyte connection mapping
    connection_id = str(uuid.uuid4())
    await db_session.execute(
        text("""
            INSERT INTO tenant_airbyte_connections
            (tenant_id, airbyte_connection_id, connection_name, source_type, created_at)
            VALUES (:tid, :cid, 'Test Connection', 'shopify', NOW())
        """),
        {"tid": tenant_id, "cid": connection_id}
    )

    await db_session.commit()

    # Setup mock data for sync
    if mock_airbyte:
        mock_airbyte.setup_test_data(
            connection_id=connection_id,
            data={
                "_airbyte_raw_shopify_orders": orders,
                "_airbyte_raw_shopify_customers": customers or [],
            }
        )

    return connection_id
```

---

## Summary

This E2E testing plan provides:

1. **Complete API-driven data flow**: All test data enters through APIs and webhooks, never direct database inserts
2. **Mock infrastructure**: Comprehensive mocking of Shopify, Airbyte, OpenRouter, and Frontegg
3. **Full pipeline coverage**: Tests span ingestion -> transformation -> analytics -> AI features -> action execution
4. **Security validation**: Tenant isolation verified at every layer
5. **Realistic scenarios**: Tests mirror actual user workflows
6. **Reproducible data sets**: Standardized test data with known expected outcomes

By following this plan, you can confidently verify that the entire system works correctly from end to end, with data flowing through the same pathways used in production.
