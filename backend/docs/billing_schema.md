# Billing and Entitlements Schema

## Overview

This document describes the database schema for billing, subscriptions, and entitlements in the AI Growth Analytics Platform.

**Security Requirement**: All tenant-scoped tables include `tenant_id` which is **ONLY** extracted from JWT (`org_id`). `tenant_id` is **NEVER** accepted from client input (body/query/path).

## Schema Design Principles

1. **Tenant Isolation**: All tenant-owned tables include `tenant_id` with composite unique keys and foreign keys
2. **Append-Only Audit**: `usage_events` is append-only for audit trail
3. **Global Plans**: Plans and plan_features are global (no tenant_id) - they define what's available
4. **Tenant Subscriptions**: Each tenant can have active subscriptions linking to Shopify Billing API
5. **Usage Tracking**: Usage meters track current usage, usage_events provide audit trail

## Tables

### 1. `plans` (Global)

Global plan definitions. Not tenant-specific.

**Columns:**
- `id` (VARCHAR): Primary key (e.g., 'plan_free', 'plan_growth')
- `name` (VARCHAR): Unique plan name (e.g., 'free', 'growth')
- `display_name` (VARCHAR): Human-readable name (e.g., 'Free', 'Growth')
- `description` (TEXT): Plan description
- `shopify_plan_id` (VARCHAR): Shopify Billing API plan ID (NULL until configured)
- `price_monthly_cents` (INTEGER): Monthly price in cents (NULL for free/enterprise)
- `price_yearly_cents` (INTEGER): Yearly price in cents (NULL for free/enterprise)
- `is_active` (BOOLEAN): Whether plan is available for new subscriptions
- `created_at`, `updated_at` (TIMESTAMP): Audit timestamps

**Indexes:**
- Primary key on `id`
- Unique on `name`
- Index on `shopify_plan_id`
- Index on `is_active`

### 2. `plan_features` (Global)

Junction table linking plans to enabled features with optional limits.

**Columns:**
- `id` (VARCHAR): Primary key
- `plan_id` (VARCHAR): Foreign key to `plans.id`
- `feature_key` (VARCHAR): Feature identifier (e.g., 'ai_insights', 'custom_reports')
- `is_enabled` (BOOLEAN): Whether feature is enabled for this plan
- `limits` (JSONB): Optional limits object (e.g., `{"ai_insights_per_month": 100}`)
- `created_at`, `updated_at` (TIMESTAMP): Audit timestamps

**Constraints:**
- Unique on (`plan_id`, `feature_key`)
- Foreign key to `plans(id)` ON DELETE CASCADE

**Indexes:**
- Composite unique index on (`plan_id`, `feature_key`)
- Index on `plan_id`
- Index on `feature_key`

**Feature Keys:**
- `basic_reports`: Basic reporting features
- `custom_reports`: Custom report creation
- `data_export`: Data export functionality
- `ai_insights`: AI-powered insights
- `ai_actions`: AI write-back actions (requires kill switch)
- `agency_mode`: Multi-client agency features
- `openrouter_byollm`: Bring-your-own-LLM via OpenRouter
- `robyn_mmm`: Robyn MMM (Media Mix Modeling) features

### 3. `tenant_subscriptions` (Tenant-Scoped)

Active subscriptions per tenant. Links to Shopify Billing API.

**Columns:**
- `id` (VARCHAR): Primary key (UUID recommended)
- `tenant_id` (VARCHAR): **From JWT org_id, NEVER from client input**
- `plan_id` (VARCHAR): Foreign key to `plans.id`
- `shopify_subscription_id` (VARCHAR): Shopify Billing API subscription ID (unique)
- `shopify_charge_id` (VARCHAR): Shopify charge ID for one-time charges
- `status` (VARCHAR): Subscription status ('active', 'cancelled', 'expired', 'trialing')
- `current_period_start` (TIMESTAMP): Start of current billing period
- `current_period_end` (TIMESTAMP): End of current billing period
- `trial_end` (TIMESTAMP): Trial expiration (if applicable)
- `cancelled_at` (TIMESTAMP): When subscription was cancelled
- `metadata` (JSONB): Additional subscription metadata
- `created_at`, `updated_at` (TIMESTAMP): Audit timestamps

**Constraints:**
- Unique on (`tenant_id`, `plan_id`, `status`) - allows multiple subscriptions if status differs
- Foreign key to `plans(id)`
- Unique on `shopify_subscription_id`

**Indexes:**
- Index on `tenant_id` (critical for tenant isolation)
- Index on `plan_id`
- Index on `status`
- Index on `shopify_subscription_id`
- Partial index on (`tenant_id`, `status`) WHERE `status = 'active'` (optimized for common query)

**Security:**
- All queries MUST filter by `tenant_id` from JWT context
- Repository methods MUST enforce tenant scope

### 4. `usage_meters` (Tenant-Scoped)

Current usage counters per tenant per feature. Updated from `usage_events`.

**Columns:**
- `id` (VARCHAR): Primary key (UUID recommended)
- `tenant_id` (VARCHAR): **From JWT org_id, NEVER from client input**
- `feature_key` (VARCHAR): Feature identifier (e.g., 'ai_insights')
- `meter_type` (VARCHAR): 'counter' (increments), 'gauge' (current value), 'cumulative' (never resets)
- `period_type` (VARCHAR): 'monthly', 'yearly', 'lifetime'
- `current_value` (NUMERIC): Current usage value
- `limit_value` (NUMERIC): Usage limit (NULL means unlimited)
- `reset_at` (TIMESTAMP): When meter resets (for monthly/yearly)
- `metadata` (JSONB): Additional meter configuration
- `created_at`, `updated_at` (TIMESTAMP): Audit timestamps

**Constraints:**
- Unique on (`tenant_id`, `feature_key`, `period_type`)

**Indexes:**
- Index on `tenant_id` (critical for tenant isolation)
- Index on `feature_key`
- Composite index on (`tenant_id`, `feature_key`)
- Index on `reset_at` WHERE `reset_at IS NOT NULL`

**Security:**
- All queries MUST filter by `tenant_id` from JWT context
- Repository methods MUST enforce tenant scope

### 5. `usage_events` (Tenant-Scoped)

Append-only audit log of usage events. Used for reconciliation and analytics.

**Columns:**
- `id` (VARCHAR): Primary key (UUID recommended)
- `tenant_id` (VARCHAR): **From JWT org_id, NEVER from client input**
- `feature_key` (VARCHAR): Feature identifier
- `meter_id` (VARCHAR): Optional foreign key to `usage_meters.id`
- `event_type` (VARCHAR): 'increment', 'set', 'reset'
- `value` (NUMERIC): Event value
- `previous_value` (NUMERIC): Value before this event
- `period_type` (VARCHAR): 'monthly', 'yearly', 'lifetime'
- `period_start` (TIMESTAMP): Start of billing period
- `metadata` (JSONB): Additional event context (user_id, request_id, etc.)
- `created_at` (TIMESTAMP): Event timestamp (no updated_at - append-only)

**Constraints:**
- Foreign key to `usage_meters(id)` ON DELETE SET NULL

**Indexes:**
- Index on `tenant_id` (critical for tenant isolation)
- Index on `feature_key`
- Index on `meter_id`
- Index on `created_at`
- Composite index on (`tenant_id`, `feature_key`, `created_at DESC`) for time-series queries
- Composite index on (`tenant_id`, `period_type`, `period_start`) WHERE `period_start IS NOT NULL`

**Security:**
- All queries MUST filter by `tenant_id` from JWT context
- Repository methods MUST enforce tenant scope
- **Append-only**: No UPDATE or DELETE operations allowed

## Tenant Isolation Enforcement

### Repository Pattern

All repository methods MUST:
1. Accept `tenant_id` from JWT context (via `TenantContext`)
2. Apply `WHERE tenant_id = ?` to all queries
3. Reject any `tenant_id` provided in entity data
4. Use composite unique keys that include `tenant_id`

### Example Query Pattern

```python
# CORRECT: tenant_id from JWT context
tenant_ctx = get_tenant_context(request)
subscription = db.query(TenantSubscription).filter(
    TenantSubscription.tenant_id == tenant_ctx.tenant_id,
    TenantSubscription.status == 'active'
).first()

# WRONG: tenant_id from request body
subscription = db.query(TenantSubscription).filter(
    TenantSubscription.tenant_id == request_body['tenant_id']  # NEVER DO THIS
).first()
```

## Usage Flow

1. **Subscription Created**: Insert into `tenant_subscriptions` with `status = 'active'`
2. **Feature Check**: Query `plan_features` for tenant's plan to check if feature is enabled
3. **Usage Increment**: 
   - Insert into `usage_events` (append-only)
   - Update `usage_meters.current_value`
4. **Entitlement Check**: Compare `usage_meters.current_value` to `plan_features.limits`
5. **Meter Reset**: For monthly/yearly meters, reset `current_value` when `reset_at` passes

## Migration and Seed

### Apply Migration

```bash
psql $DATABASE_URL -f backend/migrations/0001_billing_entitlements.sql
```

### Seed Plans and Features

```bash
psql $DATABASE_URL -f backend/seeds/seed_plans.sql
```

### Verify

```sql
-- Check plans
SELECT name, display_name, price_monthly_cents FROM plans WHERE is_active = true;

-- Check plan features
SELECT p.name, pf.feature_key, pf.is_enabled, pf.limits
FROM plans p
JOIN plan_features pf ON p.id = pf.plan_id
ORDER BY p.name, pf.feature_key;
```

## Integration with Shopify Billing API

1. **Plan Creation**: Create plan in Shopify Billing API, store `shopify_plan_id` in `plans` table
2. **Subscription Webhook**: On Shopify subscription webhook:
   - Upsert `tenant_subscriptions` with `shopify_subscription_id`
   - Update `status`, `current_period_start`, `current_period_end`
3. **Charge Webhook**: On Shopify charge webhook:
   - Update `shopify_charge_id` for one-time charges
   - Update subscription status if charge fails

## Entitlement Engine

The entitlement engine (to be implemented in `/backend/src/platform/entitlements.py`) will:

1. Get tenant's active subscription from `tenant_subscriptions`
2. Get plan features from `plan_features` for that plan
3. Check `usage_meters` for current usage
4. Compare usage to `plan_features.limits`
5. Return `can_access(tenant_id, feature_key)` boolean

## Testing

See `backend/docs/billing_schema_tests.md` for SQL assertions and test queries.
