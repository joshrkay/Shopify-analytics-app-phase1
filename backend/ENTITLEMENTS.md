# Entitlements Enforcement System

This document describes the entitlements enforcement system for billing-based feature access control.

## Overview

The entitlements system ensures that:
1. Feature access is based on the tenant's billing plan
2. Access rules vary by billing state (active, past_due, grace_period, etc.)
3. All access denials are audit-logged for compliance
4. Billing state changes immediately invalidate cached entitlements

## Architecture

```
+------------------+     +---------------+     +------------------+
|  plans.json      |---->| Loader        |---->| PlanEntitlements |
| (Source of Truth)|     | (Singleton)   |     | (Features/Limits)|
+------------------+     +---------------+     +------------------+
                                |
                                v
+------------------+     +---------------+     +------------------+
| Subscription DB  |---->| AccessRules   |---->| AccessDecision   |
| (Billing State)  |     | (Evaluator)   |     | (Allow/Deny)     |
+------------------+     +---------------+     +------------------+
                                |
                                v
+------------------+     +---------------+     +------------------+
| Redis/Memory     |<--->| Cache         |     | Middleware       |
| (TTL-based)      |     | (Invalidation)|---->| (Enforcement)    |
+------------------+     +---------------+     +------------------+
                                |
                                v
                         +---------------+
                         | Audit Logger  |
                         | (Compliance)  |
                         +---------------+
```

## Configuration

### plans.json Structure

```json
{
  "plans": [
    {
      "id": "plan_growth",
      "name": "growth",
      "display_name": "Growth",
      "tier": 1,
      "features": {
        "ai_insights": true,
        "data_export_csv": true,
        "api_access": "limited"
      },
      "limits": {
        "max_dashboards": 10,
        "max_users": 5,
        "api_calls_per_month": 10000
      }
    }
  ],
  "billing_rules": {
    "grace_period_days": 3,
    "retry_strategy": "exponential_backoff",
    "max_retries": 5
  },
  "access_rules": {
    "active": { "access_level": "full", "restrictions": [] },
    "grace_period": { "access_level": "full", "warnings": ["payment_grace_period"] },
    "expired": { "access_level": "read_only_analytics", "restrictions": ["ai_insights"] }
  }
}
```

### Grace Period

The grace period is **3 days** (configurable via `billing_rules.grace_period_days`).

During the grace period:
- Full feature access is maintained
- Warning banners are shown to the user
- Cache TTL is shortened to 60 seconds for volatile states

## Billing States

| State | Access Level | Description |
|-------|--------------|-------------|
| `active` | Full | Normal subscription, all features available |
| `trialing` | Full | Trial period, all plan features available |
| `grace_period` | Full | Payment failed, 3-day grace period active |
| `past_due` | Read-Only | Payment past due, write operations blocked |
| `frozen` | Limited | After grace period, most features restricted |
| `canceled` | Full Until Period End | User canceled, access until billing period ends |
| `expired` | Read-Only Analytics | Subscription expired, only basic analytics |

## Usage

### API Endpoints

Use the `@require_entitlement` decorator:

```python
from src.entitlements.middleware import require_entitlement, require_billing_state
from src.entitlements.rules import BillingState

@router.get("/api/ai/insights")
@require_entitlement("ai_insights")
async def get_ai_insights(request: Request):
    # Only accessible if plan has ai_insights enabled
    return {"insights": [...]}

@router.post("/api/exports")
@require_billing_state([BillingState.ACTIVE, BillingState.TRIALING])
async def create_export(request: Request):
    # Only accessible with active billing
    return {"export_id": "..."}
```

### Background Jobs

Use the `BackgroundJobEntitlementChecker`:

```python
from src.entitlements.middleware import BackgroundJobEntitlementChecker

def run_scheduled_report_job(tenant_id: str, db_session):
    checker = BackgroundJobEntitlementChecker(tenant_id, db_session)

    if not checker.can_execute("scheduled_reports", job_name="daily_report"):
        logger.info(f"Skipping job for {tenant_id} - no entitlement")
        return

    # Execute the job
    generate_report(tenant_id)
```

### Manual Feature Checks

```python
from src.entitlements.rules import AccessRules, BillingState

rules = AccessRules(
    tenant_id="tenant_123",
    plan_id="plan_growth",
    billing_state=BillingState.ACTIVE,
)

# Check feature access
if rules.can_access_feature("ai_insights"):
    # Feature is available
    pass

# Check usage limits
decision = rules.check_limit("max_dashboards", current_count=5)
if not decision.allowed:
    # Limit exceeded - show upgrade prompt
    pass
```

## Cache Invalidation

The entitlement cache is automatically invalidated when billing state changes.

**Webhook handlers MUST call:**

```python
from src.entitlements.cache import on_billing_state_change

# In webhook handler after processing subscription update
on_billing_state_change(
    tenant_id=tenant_id,
    old_state="active",
    new_state="frozen",
    plan_id=plan_id,
)
```

**Cache TTLs:**
- Normal states: 5 minutes (300 seconds)
- Volatile states (grace_period, past_due, frozen): 1 minute (60 seconds)

## Audit Logging

All access denials are logged with:
- `tenant_id`
- `feature_name`
- `billing_state`
- `plan_id`
- `reason`
- `endpoint`
- `timestamp`

Logs are written to:
1. Structured logger (`entitlements.audit`)
2. Database (`billing_events` table) - if enabled

Example log entry:
```json
{
  "event_type": "access_denied",
  "tenant_id": "tenant_123",
  "feature_name": "ai_insights",
  "billing_state": "expired",
  "plan_id": "plan_free",
  "reason": "Feature requires Growth plan",
  "endpoint": "/api/ai/insights"
}
```

## Feature Flags (Emergency Overrides)

Admin-only emergency overrides can enable/disable features:

```python
from src.entitlements.cache import get_entitlement_cache

cache = get_entitlement_cache()

# Enable feature for a tenant (24-hour TTL)
cache.set_feature_flag_override(
    tenant_id="tenant_123",
    feature_key="ai_insights",
    enabled=True,
    ttl_seconds=86400,
)

# Clear override
cache.clear_feature_flag_override(
    tenant_id="tenant_123",
    feature_key="ai_insights",
)
```

## Error Responses

Access denials return HTTP 402 (Payment Required):

```json
{
  "error": "entitlement_required",
  "error_code": "PAYMENT_REQUIRED",
  "message": "Feature 'ai_insights' requires plan upgrade",
  "feature": "ai_insights",
  "billing_state": "active",
  "current_plan": "Free",
  "required_plan": "Growth",
  "upgrade_url": "/billing/upgrade?to=Growth"
}
```

## Enforcement Points

| Location | Mechanism | Notes |
|----------|-----------|-------|
| API Endpoints | `@require_entitlement` decorator | Returns HTTP 402 |
| Background Jobs | `BackgroundJobEntitlementChecker` | Skips job execution |
| Dashboard Embeds | Check `request.state.entitlements` | Return empty state |
| Data Exports | `@require_entitlement("data_export_*")` | Block with upgrade prompt |

## Middleware Setup

Add the middleware to your FastAPI app:

```python
from fastapi import FastAPI
from src.entitlements.middleware import EntitlementMiddleware

app = FastAPI()

app.add_middleware(
    EntitlementMiddleware,
    excluded_paths=["/health", "/api/webhooks"],
    enforce_active_billing=False,  # Set True for strict enforcement
)
```

## Testing

Run entitlement tests:

```bash
cd backend
pytest src/tests/test_entitlements.py -v --cov=src.entitlements --cov-report=term-missing
```

Target: >= 90% code coverage

## Files

| File | Purpose |
|------|---------|
| `src/entitlements/__init__.py` | Module exports |
| `src/entitlements/loader.py` | Load plans from config/plans.json |
| `src/entitlements/rules.py` | Access rules by billing state |
| `src/entitlements/cache.py` | Redis/memory cache with invalidation |
| `src/entitlements/middleware.py` | FastAPI middleware and decorators |
| `src/entitlements/audit.py` | Audit logging for compliance |
| `config/plans.json` | Plan definitions (source of truth) |

## Security Considerations

1. **Never trust client input for entitlement checks** - always use server-side validation
2. **Cache invalidation is critical** - billing state changes must immediately reflect in access
3. **Audit all denials** - required for SOC2 and Shopify compliance
4. **Feature flags are admin-only** - emergency overrides need proper authorization

## Compliance

This system supports:
- **SOC2**: Complete audit trail of access denials
- **Shopify App Review**: Proper billing enforcement
- **GDPR/CCPA**: No PII in entitlement logs (only tenant/user IDs)
