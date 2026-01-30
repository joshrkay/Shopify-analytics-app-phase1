# E2E Testing Implementation Prompts

Use these prompts with Claude Code (or claude cowork for parallel execution) to implement the complete E2E testing infrastructure.

---

## Troubleshooting Guide: When Tests Fail Due to Third-Party Services

When E2E tests fail due to missing API keys or third-party service configuration, use these steps to diagnose and fix:

### Step 1: Identify the Failing Service
```bash
# Run tests with verbose output to see which service is failing
pytest src/tests/e2e/ -v --tb=long 2>&1 | grep -E "Error|Failed|Missing|required"
```

### Step 2: Look Up API Documentation

**Frontegg (Authentication)**
- Documentation: https://docs.frontegg.com/
- API Reference: https://docs.frontegg.com/reference/getting-started-with-your-api
- Required env vars: `FRONTEGG_CLIENT_ID`, `FRONTEGG_CLIENT_SECRET`, `FRONTEGG_BASE_URL`
- Get credentials: Frontegg Portal → Settings → API Tokens

**Airbyte (Data Ingestion)**
- Documentation: https://docs.airbyte.com/
- API Reference: https://reference.airbyte.com/reference/start
- Required env vars: `AIRBYTE_API_TOKEN`, `AIRBYTE_WORKSPACE_ID`, `AIRBYTE_BASE_URL`
- Get credentials: Airbyte Cloud → Settings → API Keys

**Shopify (E-commerce)**
- Documentation: https://shopify.dev/docs/api
- Admin API Reference: https://shopify.dev/docs/api/admin-rest
- Webhooks Guide: https://shopify.dev/docs/apps/webhooks
- Required env vars: `SHOPIFY_API_KEY`, `SHOPIFY_API_SECRET`
- Get credentials: Shopify Partners → Apps → Your App → API credentials

**OpenRouter (LLM/AI)**
- Documentation: https://openrouter.ai/docs
- API Reference: https://openrouter.ai/docs/api-reference
- Required env vars: `OPENROUTER_API_KEY`
- Get credentials: https://openrouter.ai/keys

### Step 3: Verify Configuration
```bash
# Check what env vars are currently set
env | grep -E "FRONTEGG|AIRBYTE|SHOPIFY|OPENROUTER|ENCRYPTION"

# Verify the app can load with current config
cd backend && PYTHONPATH=. python -c "from main import app; print('App loaded successfully')"
```

### Step 4: Update Mock Configuration
If the real service isn't available, ensure mocks are properly configured:
1. Check `backend/src/tests/e2e/mocks/` for the relevant mock
2. Verify the mock handles the endpoints being called
3. Ensure the mock is injected via `conftest.py` dependency overrides

---

## Prompt 1: Fix Authentication Mocking (P0 - Blocking)

```
Fix the E2E test authentication mocking so JWT validation works without calling real Frontegg servers.

Changes needed:

1. In `backend/src/tests/e2e/mocks/mock_frontegg.py`:
   - Change line 122 from `"iss": "https://test.frontegg.com"` to `"iss": "https://api.frontegg.com"`
   - Change line 123 to `"aud": "test-client-id"` (must match FRONTEGG_CLIENT_ID env var)

2. In `backend/src/tests/e2e/conftest.py`:
   - Update the `test_app` fixture to patch `TenantContextMiddleware._get_jwks_client`
   - Create a MockJWKSClient class that returns the mock_frontegg's public key
   - The mock should have a `client_id` attribute set to "test-client-id"
   - The `get_signing_key(token)` method should return an object with a `key` attribute containing the mock's public key

After changes, run: `cd backend && PYTHONPATH=. ENV=test FRONTEGG_CLIENT_ID=test-client-id pytest src/tests/e2e/test_api_endpoints.py::TestShopifyIngestionAPI::test_validate_token_endpoint -v`
```

---

## Prompt 2: Add Airbyte Client Dependency Injection (P1 - Core)

```
Add dependency injection support to the Airbyte client so it can be mocked in E2E tests.

Changes needed:

1. In `backend/src/integrations/airbyte/client.py`:
   - Add a `get_airbyte_client()` dependency function that returns an AirbyteClient instance
   - Export this function in the module

2. In `backend/src/tests/e2e/mocks/mock_airbyte.py`:
   - Add a `handle_request(self, request: httpx.Request) -> httpx.Response` method
   - Handle these endpoints:
     - POST /v1/connections/{id}/sync -> return job trigger response
     - GET /v1/jobs/{id} -> return job status
     - GET /v1/connections/{id} -> return connection details
   - Return 404 for unhandled paths

3. In `backend/src/tests/e2e/conftest.py`:
   - Add a `mock_airbyte_client` fixture that creates an httpx.AsyncClient with MockTransport
   - The transport should route requests to mock_airbyte.handle_request()
   - In `test_app` fixture, add dependency override: `app.dependency_overrides[get_airbyte_client] = lambda: mock_airbyte_client`

After changes, verify mock is injected by adding a debug print in the mock handler.
```

---

## Prompt 3: Add Shopify Client Dependency Injection (P1 - Core)

```
Add dependency injection support to the Shopify client so it can be mocked in E2E tests.

Changes needed:

1. Check if `backend/src/integrations/shopify/client.py` exists. If not, find where Shopify API calls are made.

2. Create or update the Shopify client:
   - Add a `get_shopify_client()` dependency function
   - The client should handle: token validation, shop info retrieval, GraphQL queries

3. In `backend/src/tests/e2e/mocks/mock_shopify.py`:
   - Add a `handle_request(self, request: httpx.Request) -> httpx.Response` method
   - Handle these endpoints:
     - GET /admin/api/2024-01/shop.json -> return mock shop info
     - POST /admin/api/2024-01/graphql.json -> return mock GraphQL response
     - GET /admin/api/2024-01/orders.json -> return mock orders
   - Include proper Shopify API response structure

4. In `backend/src/tests/e2e/conftest.py`:
   - Add `mock_shopify_client` fixture similar to mock_airbyte_client
   - Add dependency override in test_app fixture

After changes, ensure the mock handles the token validation endpoint used in tests.
```

---

## Prompt 4: Update Services for Dependency Injection (P1 - Core)

```
Update service classes to accept injected clients for testability.

Changes needed:

1. In `backend/src/services/sync_orchestrator.py` (or wherever SyncOrchestrator is defined):
   - Update __init__ to accept optional `airbyte_client` parameter
   - Default to creating AirbyteClient() if not provided
   - Store as self._airbyte or similar

2. In `backend/src/services/shopify_ingestion.py` (or wherever ShopifyIngestionService is defined):
   - Update __init__ to accept optional `airbyte_client` and `shopify_client` parameters
   - Default to creating real clients if not provided

3. Find all API routes that instantiate these services and update them:
   - Use FastAPI's Depends() to inject the clients
   - Pass injected clients to service constructors

Example pattern:
```python
@router.post("/trigger/{connection_id}")
async def trigger_sync(
    connection_id: str,
    request: Request,
    airbyte_client: AirbyteClient = Depends(get_airbyte_client),
):
    service = SyncOrchestrator(
        db_session=get_db(request),
        tenant_id=get_tenant_context(request).tenant_id,
        airbyte_client=airbyte_client,
    )
```

After changes, run the E2E tests to verify services receive mock clients.
```

---

## Prompt 5: Add Webhook Simulator HTTP Handler (P1 - Core)

```
Update the webhook simulator to properly send webhooks through the test client.

Changes needed:

1. In `backend/src/tests/e2e/mocks/mock_shopify.py`:
   - Ensure `ShopifyWebhookSimulator` class can send webhooks to the test app
   - The `send_order_create()` method should:
     - Generate proper HMAC signature using SHOPIFY_API_SECRET
     - Send POST request to /api/webhooks/shopify/orders-create
     - Include headers: X-Shopify-Hmac-Sha256, X-Shopify-Topic, X-Shopify-Shop-Domain
   - Add similar methods for: send_order_updated(), send_app_uninstalled(), send_subscription_update()

2. In `backend/src/tests/e2e/conftest.py`:
   - Update `webhook_simulator` fixture to use the test client
   - Pass the async_client or client to the simulator so it can make real HTTP calls

3. Ensure the HMAC calculation matches what the webhook handler expects:
   - Read `backend/src/api/routes/webhooks_shopify.py` to understand signature verification
   - Match the exact signing algorithm (HMAC-SHA256, base64 encoded)

After changes, run: `pytest src/tests/e2e/test_api_endpoints.py::TestWebhookHandlers -v`
```

---

## Prompt 6: Add API-Based Test Data Injection Helpers (P2 - Enhancement)

```
Create helper functions to inject test data through APIs instead of direct database access.

Changes needed:

1. In `backend/src/tests/e2e/helpers.py`:
   - Add `async def inject_orders_via_webhooks(webhook_simulator, orders, shop_domain)`:
     - Loops through orders and sends each via webhook
     - Returns list of responses for assertion

   - Add `async def trigger_and_wait_for_sync(client, connection_id, headers, timeout=30)`:
     - POST to /api/sync/trigger/{connection_id}
     - Poll /api/sync/state/{connection_id} until status is "succeeded" or timeout
     - Return final status

   - Add `async def setup_tenant_via_api(client, headers, shop_domain, access_token)`:
     - POST to /api/shopify-ingestion/validate-token
     - POST to /api/shopify-ingestion/setup
     - Return connection_id

2. Update existing helper functions to clearly document whether they use DB or API:
   - Prefix DB-only helpers with `db_` (e.g., `db_setup_test_tenant`)
   - Keep API helpers without prefix

After changes, update one test in test_api_endpoints.py to use the new API-based helpers instead of direct DB injection.
```

---

## Prompt 7: Add Data Verification Assertions (P2 - Enhancement)

```
Add proper data verification to E2E tests - not just HTTP status checks.

Changes needed:

1. In `backend/src/tests/e2e/fixtures/test_data.py`:
   - Add `EXPECTED_OUTCOMES` dictionary mapping test data to expected results:
   ```python
   EXPECTED_OUTCOMES = {
       "shopify_purchases": {
           "count": 30,
           "total_revenue": sum(float(o["total_price"]) for o in SHOPIFY_PURCHASES),
       },
       "shopify_refunds": {
           "count": 25,
           "total_refunded": ...,
       },
       # Add for all channels
   }
   ```

2. In `backend/src/tests/e2e/test_api_endpoints.py`:
   - Update `TestFullPipelineE2E` tests to verify:
     - Data actually exists in database after webhook/sync
     - Record counts match expected
     - Key fields (amounts, dates, IDs) are correct

   - Add assertions like:
   ```python
   # After sending webhooks
   result = await db_session.execute(
       text("SELECT COUNT(*) FROM webhook_events WHERE shop_domain = :domain"),
       {"domain": shop_domain}
   )
   assert result.scalar() == len(orders_sent)
   ```

3. Create a new test class `TestDataIntegrity`:
   - Test that refund amounts are parsed correctly
   - Test that cancellation timestamps are stored
   - Test that multi-currency orders are handled

After changes, run: `pytest src/tests/e2e/ -v -k "integrity or pipeline"`
```

---

## Prompt 8: Add OpenRouter/LLM Client Mocking (P1 - Core)

```
Add dependency injection for the OpenRouter LLM client used in AI features.

Changes needed:

1. Find where OpenRouter API calls are made (likely in `backend/src/services/` or `backend/src/integrations/`).

2. Create or update the LLM client:
   - Add a `get_openrouter_client()` dependency function
   - The client should have methods like `generate_insights()`, `generate_recommendations()`

3. In `backend/src/tests/e2e/mocks/mock_openrouter.py`:
   - Add `handle_request(self, request: httpx.Request) -> httpx.Response` method
   - Handle POST /api/v1/chat/completions:
     - Parse the prompt from request body
     - Return deterministic mock responses based on prompt content
     - Return proper OpenAI-compatible response format

4. In `backend/src/tests/e2e/conftest.py`:
   - Add `mock_openrouter_client` fixture
   - Add dependency override in test_app

5. Update any AI-related tests to verify:
   - Mock is being used (not real API)
   - Responses are processed correctly

After changes, run any AI feature tests to verify mocking works.
```

---

## Prompt 9: Create Integration Test for Full Data Pipeline (P2 - Enhancement)

```
Create a comprehensive integration test that exercises the complete data flow from ingestion to analytics.

Create new file: `backend/src/tests/e2e/test_full_pipeline.py`

The test should:

1. Setup Phase:
   - Create a test tenant via mock Frontegg token
   - Setup Airbyte connection via /api/shopify-ingestion/setup
   - Verify connection is created in database

2. Data Ingestion Phase:
   - Send 10 order webhooks via webhook simulator
   - Send 3 refund webhooks
   - Send 2 cancellation webhooks
   - Verify webhook_events table has 15 records

3. Sync Phase:
   - Trigger Airbyte sync via /api/sync/trigger/{connection_id}
   - Wait for sync completion (mock should inject data)
   - Verify _airbyte_raw_shopify_orders has records

4. Analytics Phase (if dbt transformation is testable):
   - Trigger transformation or verify staging tables
   - Check fact tables have correct aggregations

5. AI Phase (if applicable):
   - Trigger insight generation
   - Verify mock LLM was called
   - Check insights are stored

6. Cleanup Phase:
   - Test app uninstall webhook
   - Verify data is marked for deletion

Use fixtures from conftest.py and helpers from helpers.py.
Mark the test with @pytest.mark.e2e and @pytest.mark.slow.

After creating, run: `pytest src/tests/e2e/test_full_pipeline.py -v --tb=long`
```

---

## Prompt 10: Verify and Fix All Missing Environment Variables (P0 - Blocking)

```
Audit the codebase for all required environment variables and ensure E2E tests have proper defaults or mocks.

Steps:

1. Search the codebase for all os.getenv() and os.environ calls:
   - `grep -r "os.getenv\|os.environ" backend/src/`
   - List all environment variables found

2. Categorize them:
   - Authentication: FRONTEGG_CLIENT_ID, FRONTEGG_CLIENT_SECRET, FRONTEGG_BASE_URL
   - Database: DATABASE_URL, DATABASE_URL_ASYNC
   - External Services: AIRBYTE_API_TOKEN, AIRBYTE_WORKSPACE_ID, OPENROUTER_API_KEY
   - Shopify: SHOPIFY_API_KEY, SHOPIFY_API_SECRET
   - Security: ENCRYPTION_KEY
   - Feature Flags: ENV, DEBUG, etc.

3. In `backend/src/tests/e2e/conftest.py`:
   - Ensure all required env vars are set at the top of the file:
   ```python
   os.environ.setdefault("ENV", "test")
   os.environ.setdefault("FRONTEGG_CLIENT_ID", "test-client-id")
   os.environ.setdefault("FRONTEGG_CLIENT_SECRET", "test-secret")
   os.environ.setdefault("SHOPIFY_API_SECRET", "test-webhook-secret")
   os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS0zMi1ieXRlcw==")
   # ... add all others
   ```

4. For any env var that gates functionality (like OPENROUTER_API_KEY for AI features):
   - Either set a test value OR
   - Add conditional skip in tests: `@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="No API key")`

5. Create a test that verifies all required env vars are set:
   ```python
   def test_required_env_vars_set():
       required = ["DATABASE_URL", "SHOPIFY_API_SECRET", "FRONTEGG_CLIENT_ID"]
       missing = [v for v in required if not os.getenv(v)]
       assert not missing, f"Missing env vars: {missing}"
   ```

After changes, run: `pytest src/tests/e2e/ -v --collect-only` to verify tests can be collected.
```

---

## Execution Order

For sequential execution, run prompts in this order:

1. **Prompt 10** - Fix environment variables (unblocks everything)
2. **Prompt 1** - Fix authentication (unblocks all authenticated endpoints)
3. **Prompt 2** - Airbyte client injection
4. **Prompt 3** - Shopify client injection
5. **Prompt 4** - Service dependency injection
6. **Prompt 5** - Webhook simulator
7. **Prompt 12** - Add missing webhook endpoints (if needed)
8. **Prompt 8** - OpenRouter mocking
9. **Prompt 6** - API-based helpers
10. **Prompt 7** - Data verification
11. **Prompt 9** - Full pipeline test
12. **Prompt 11** - Use for any remaining failures (troubleshooting)

For parallel execution with `claude cowork`:
- Group 1 (can run together): Prompts 1, 2, 3, 8
- Group 2 (after Group 1): Prompts 4, 5, 12
- Group 3 (after Group 2): Prompts 6, 7, 9
- On-demand: Prompt 11 (troubleshooting)

---

## Prompt 11: Diagnose and Fix Third-Party Service Failures (Troubleshooting)

```
A test is failing due to a third-party service issue. Diagnose and fix it.

Steps:

1. Run the failing test with full output:
   ```bash
   cd backend && PYTHONPATH=. pytest src/tests/e2e/<test_file>::<test_name> -v --tb=long 2>&1
   ```

2. Identify which service is failing by looking for:
   - Connection errors (service not mocked)
   - Authentication errors (missing/invalid credentials)
   - 404 errors (endpoint not mocked)
   - Timeout errors (mock not responding)

3. Based on the error, take action:

   **If Frontegg/Auth error:**
   - Check `mock_frontegg.py` issuer matches middleware expectation
   - Verify `conftest.py` patches `TenantContextMiddleware._get_jwks_client`
   - Ensure token audience matches `FRONTEGG_CLIENT_ID`
   - Documentation: https://docs.frontegg.com/reference/getting-started-with-your-api

   **If Airbyte error:**
   - Check `mock_airbyte.py` has `handle_request()` method
   - Verify it handles: POST /v1/connections/*/sync, GET /v1/jobs/*
   - Ensure mock is injected via dependency override
   - Documentation: https://reference.airbyte.com/reference/start

   **If Shopify error:**
   - Check `mock_shopify.py` handles the endpoint being called
   - For webhooks: verify HMAC calculation matches
   - For API calls: ensure mock returns correct response structure
   - Documentation: https://shopify.dev/docs/api/admin-rest

   **If OpenRouter/LLM error:**
   - Check `mock_openrouter.py` handles POST /api/v1/chat/completions
   - Ensure response format matches OpenAI spec
   - Documentation: https://openrouter.ai/docs/api-reference

4. If the service needs real credentials (not mocked):
   - Search for where credentials are loaded: `grep -r "os.getenv.*<SERVICE>" backend/src/`
   - Check the service's documentation for how to obtain API keys
   - Add credentials to `.env` file or environment
   - For tests, prefer mocking over real credentials

5. Verify the fix:
   ```bash
   pytest src/tests/e2e/<test_file>::<test_name> -v --tb=short
   ```

Common issues and solutions:
- "Connection refused" → Mock not injected, real HTTP call being made
- "401 Unauthorized" → Token issuer/audience mismatch, or JWKS not mocked
- "404 Not Found" → Endpoint path doesn't exist or mock doesn't handle it
- "Missing env var" → Add to conftest.py os.environ.setdefault()
```

---

## Prompt 12: Add Missing Webhook Endpoints (Feature Gap)

```
The E2E tests expect webhook endpoints that don't exist. Add them.

Current state:
- App has: /subscription-update, /app-uninstalled, /customers-redact, /shop-redact
- Tests expect: /orders-create, /orders-updated (for orders/create, orders/updated topics)

Steps:

1. Read existing webhook handlers:
   ```bash
   cat backend/src/api/routes/webhooks_shopify.py
   ```

2. Add new webhook endpoint for orders:
   ```python
   @router.post("/orders-create", response_model=WebhookResponse)
   async def handle_orders_create(
       request: Request,
       x_shopify_hmac_sha256: str = Header(...),
       x_shopify_shop_domain: str = Header(...),
       x_shopify_topic: str = Header(...),
   ):
       """Handle orders/create webhook from Shopify."""
       body, shop_domain = await get_verified_webhook_body(request)

       # Process the order data
       order = body
       logger.info(f"Received order {order.get('id')} from {shop_domain}")

       # Store in database or queue for processing
       # ... implementation depends on business logic

       return WebhookResponse(message="Order received")
   ```

3. Add similar endpoint for orders/updated:
   - Handle refunds (check for refunds array in payload)
   - Handle cancellations (check cancelled_at field)

4. Update the webhook simulator path:
   - In `mock_shopify.py`, change `/api/webhooks/shopify` to `/api/webhooks/shopify/orders-create`
   - Or add a topic-based router

5. Verify:
   ```bash
   pytest src/tests/e2e/test_api_endpoints.py::TestWebhookHandlers -v
   ```

Shopify webhook payload reference: https://shopify.dev/docs/api/admin-rest/2024-01/resources/webhook
```

---

## Verification Command

After all prompts are complete, run:

```bash
cd backend
export PYTHONPATH=.
export DATABASE_URL="postgresql://test_user:test@localhost:5432/shopify_analytics_test"
export ENV=test
export FRONTEGG_CLIENT_ID=test-client-id

pytest src/tests/e2e/ -v --tb=short

# Expected: All 36+ tests pass
```
