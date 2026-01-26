# Entitlement Middleware

Runtime enforcement of feature entitlements based on billing state and plan features.

## Usage

### 1. Add Middleware to FastAPI App

```python
from src.entitlements.middleware import EntitlementMiddleware

# Add after TenantContextMiddleware
app.add_middleware(
    EntitlementMiddleware,
    db_session_factory=lambda: get_db_session()  # Your DB session factory
)
```

### 2. Mark Routes with Required Features

```python
from src.entitlements.middleware import require_feature

@router.get("/premium-analytics")
@require_feature("premium_analytics")
async def get_premium_analytics(request: Request, db: Session = Depends(get_db_session)):
    # This endpoint requires "premium_analytics" feature
    # Middleware will check billing_state and plan features
    return {"data": "premium analytics"}
```

### 3. Billing States

The middleware evaluates the following billing states:

- **active**: Subscription is active → Check plan features
- **grace_period**: Payment failed but within grace period (3 days) → Allow with warning header
- **past_due**: Grace period expired → Hard block (402)
- **canceled**: Subscription canceled → Hard block (402) or end-of-period based on config
- **expired**: Subscription expired → Hard block (402)

### 4. Configuration

Edit `config/plans.json` to configure:
- Grace period duration
- Canceled behavior (immediate vs end-of-period)
- Feature-to-plan mappings (optional, primary source is PlanFeature table)

### 5. Audit Logging

All entitlement checks emit audit events:
- `entitlement.allowed` - Feature access granted
- `entitlement.denied` - Feature access denied

Events include:
- tenant_id
- feature
- billing_state
- plan_id
- reason

## Error Responses

When access is denied, the API returns:

```json
{
  "detail": {
    "error": "entitlement_denied",
    "feature": "premium_analytics",
    "reason": "Subscription has expired",
    "billing_state": "expired",
    "plan_id": "plan_growth",
    "machine_readable": {
      "code": "subscription_expired",
      "billing_state": "expired",
      "feature": "premium_analytics"
    }
  }
}
```

HTTP Status: `402 Payment Required`

## Grace Period Warnings

When in grace period, responses include headers:

```
X-Billing-Warning: payment_grace_period
X-Grace-Period-Ends: 2026-01-29T12:00:00Z
```
