# Billing Regression Testing Guide

This document describes how to run and maintain the billing regression test suite for AI Growth Analytics.

## Overview

The billing regression tests validate end-to-end billing flows at the API boundary without making real Shopify API calls. Tests use:

- **Mocked Shopify Billing Client** - Deterministic responses without network calls
- **PostgreSQL Database** - Required (models use JSONB and DEFERRABLE constraints)
- **Real HMAC Verification** - Uses test secrets for webhook signature validation
- **Transaction Isolation** - Each test runs in a rolled-back transaction

**Note:** Tests will automatically skip with a helpful message if PostgreSQL isn't available.

## Test Coverage

The regression suite covers these critical flows:

| Test | Description |
|------|-------------|
| `test_billing_checkout_url_happy_path` | Create checkout URL for a plan |
| `test_webhook_valid_signature_sets_subscription_active` | Webhook activates pending subscription |
| `test_upgrade_flow_updates_plan_and_entitlements` | Plan upgrade via webhook |
| `test_cancel_flow_revokes_entitlements` | Cancellation revokes access |
| `test_failed_payment_downgrades_access` | Payment failure triggers grace period |
| `test_reconciliation_job_corrects_drift` | Reconciliation corrects DB/Shopify drift |
| `test_webhook_rejects_invalid_signature` | Invalid HMAC rejected with 401 |
| `test_cross_tenant_protection_webhook_cannot_mutate_other_tenant` | Tenant isolation verified |

## Running Tests Locally

### Prerequisites

```bash
cd backend
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-mock pytest-cov pytest-timeout
```

### Start PostgreSQL (Required)

```bash
# Start Postgres container
docker run -d \
  --name test-postgres \
  -e POSTGRES_USER=test \
  -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=test_billing_db \
  -p 5432:5432 \
  postgres:15

# Wait for it to be ready
sleep 3
```

### Run Tests

```bash
# Run regression tests
DATABASE_URL="postgresql://test:test@localhost:5432/test_billing_db" \
make test-regression

# Or directly with pytest
DATABASE_URL="postgresql://test:test@localhost:5432/test_billing_db" \
PYTHONPATH=. pytest src/tests/regression/test_billing_regression.py -v -m regression
```

### Cleanup

```bash
docker stop test-postgres && docker rm test-postgres
```

### Run All Billing Tests

```bash
make test-billing
```

## CI Pipeline

The regression tests run automatically in the GitHub Actions CI pipeline:

1. **quality-gates** - Must pass first
2. **billing-regression-tests** - Uses Postgres service container
3. **pr-check** - Blocks merge if regression tests fail

See `.github/workflows/ci.yml` for configuration.

### CI Environment Variables

| Variable | Value in CI |
|----------|-------------|
| `DATABASE_URL` | `postgresql://test:test@localhost:5432/test_billing_db` |
| `SHOPIFY_API_SECRET` | `test-webhook-secret-for-hmac` |
| `SHOPIFY_BILLING_TEST_MODE` | `true` |
| `ENV` | `test` |

## Adding New Test Cases

### 1. Create a fixture if needed

Add to `src/tests/regression/conftest.py`:

```python
@pytest.fixture
def my_new_fixture(db_session, test_tenant_id):
    # Setup test data
    yield data
    # Cleanup (optional - transaction rollback handles most cases)
```

### 2. Add webhook fixtures if needed

Create JSON files in `src/tests/regression/fixtures/webhooks/`:

```json
{
  "app_subscription": {
    "admin_graphql_api_id": "{{SUBSCRIPTION_ID}}",
    "name": "AI Growth Analytics - Growth",
    "status": "ACTIVE"
  }
}
```

### 3. Write the test

Add to `src/tests/regression/test_billing_regression.py`:

```python
class TestNewFeature:
    def test_new_billing_flow(
        self,
        client,
        db_session,
        test_store,
        webhook_secret,
        sign_webhook_payload,
    ):
        """
        GIVEN ...
        WHEN ...
        THEN ...
        """
        # Arrange

        # Act

        # Assert
```

### 4. Mark as regression test

All tests in the regression module are automatically marked with `@pytest.mark.regression` via the module-level `pytestmark`.

## Troubleshooting

### Tests fail with import errors

```bash
# Ensure PYTHONPATH is set
PYTHONPATH=. pytest ...
```

### Tests skipped - PostgreSQL required

```bash
# Tests require PostgreSQL. Start a container:
docker run -d --name test-pg -e POSTGRES_PASSWORD=test -p 5432:5432 postgres:15

# Set DATABASE_URL
export DATABASE_URL="postgresql://postgres:test@localhost:5432/postgres"
```

### Database connection errors

```bash
# Check if DATABASE_URL is set correctly
echo $DATABASE_URL

# Verify PostgreSQL is running
docker ps | grep postgres
```

### HMAC verification fails

Ensure `SHOPIFY_API_SECRET` matches the test secret:

```bash
export SHOPIFY_API_SECRET="test-webhook-secret-for-hmac"
```

### Tests hang or timeout

```bash
# Increase timeout
pytest --timeout=600 ...
```

## Test Architecture

```
src/tests/regression/
├── __init__.py
├── conftest.py              # Shared fixtures
├── test_billing_regression.py   # All 8 regression tests
├── fixtures/
│   └── webhooks/            # Webhook JSON payloads
│       ├── subscription_created.json
│       ├── subscription_updated_upgrade.json
│       ├── subscription_cancelled.json
│       └── subscription_past_due.json
└── helpers/
    ├── __init__.py
    ├── hmac_signing.py      # HMAC computation helper
    └── mock_billing_client.py   # Mock Shopify client
```

## Mock Billing Client

The `MockShopifyBillingClient` provides deterministic responses:

```python
# Configure mock state for specific test scenarios
mock_billing_client.add_subscription(
    subscription_gid="gid://shopify/AppSubscription/123",
    status="CANCELLED"
)

# Simulate API failures
mock_billing_client.configure_failure("API unavailable")
```

## Performance

Tests should complete in under 10 minutes in CI. Current benchmarks:

- Local (PostgreSQL): ~1-2 minutes
- CI (PostgreSQL service): ~2-3 minutes

If tests become slow, consider:
- Reducing database fixtures
- Parallelizing independent tests
- Using session-scoped fixtures where safe
