# Billing Schema Tests and Assertions

This document contains SQL assertions and test queries to verify the billing and entitlements schema is correctly implemented with tenant isolation.

## Prerequisites

1. Migration `0001_billing_entitlements.sql` has been applied
2. Seed script `seed_plans.sql` has been run
3. Test database is available

## Test Data Setup

```sql
-- Create test tenants (simulating JWT org_ids)
-- In production, tenant_id comes from JWT, never inserted directly
-- For testing, we'll insert directly but document this is NOT production pattern

-- Test tenant A
\set tenant_a 'test-tenant-a-org-id'

-- Test tenant B  
\set tenant_b 'test-tenant-b-org-id'
```

## 1. Schema Constraint Tests

### 1.1 Plans Table Constraints

```sql
-- Test: Plan name must be unique
INSERT INTO plans (id, name, display_name, is_active)
VALUES ('test1', 'free', 'Test Free', true);
-- Should fail: duplicate name 'free'

-- Test: Plan can be created
INSERT INTO plans (id, name, display_name, is_active)
VALUES ('test_plan', 'test', 'Test Plan', true);
-- Should succeed

-- Cleanup
DELETE FROM plans WHERE id = 'test_plan';
```

### 1.2 Plan Features Constraints

```sql
-- Test: Unique constraint on (plan_id, feature_key)
INSERT INTO plan_features (id, plan_id, feature_key, is_enabled)
VALUES ('test1', 'plan_free', 'basic_reports', true);
-- Should fail: duplicate (plan_free, basic_reports)

-- Test: Foreign key constraint
INSERT INTO plan_features (id, plan_id, feature_key, is_enabled)
VALUES ('test2', 'nonexistent_plan', 'basic_reports', true);
-- Should fail: foreign key violation

-- Test: Cascade delete
DELETE FROM plans WHERE id = 'plan_free';
-- Should cascade delete all plan_features for plan_free
-- (Restore with seed script after test)
```

### 1.3 Tenant Subscriptions Constraints

```sql
-- Test: Unique constraint on (tenant_id, plan_id, status)
-- Using test tenant IDs
INSERT INTO tenant_subscriptions (id, tenant_id, plan_id, status)
VALUES ('sub1', 'tenant-a', 'plan_free', 'active');
-- Should succeed

INSERT INTO tenant_subscriptions (id, tenant_id, plan_id, status)
VALUES ('sub2', 'tenant-a', 'plan_free', 'active');
-- Should fail: duplicate (tenant-a, plan_free, active)

-- Test: Can have multiple subscriptions with different status
INSERT INTO tenant_subscriptions (id, tenant_id, plan_id, status)
VALUES ('sub3', 'tenant-a', 'plan_free', 'cancelled');
-- Should succeed (different status)

-- Test: Foreign key constraint
INSERT INTO tenant_subscriptions (id, tenant_id, plan_id, status)
VALUES ('sub4', 'tenant-a', 'nonexistent_plan', 'active');
-- Should fail: foreign key violation

-- Cleanup
DELETE FROM tenant_subscriptions WHERE id IN ('sub1', 'sub3');
```

### 1.4 Usage Meters Constraints

```sql
-- Test: Unique constraint on (tenant_id, feature_key, period_type)
INSERT INTO usage_meters (id, tenant_id, feature_key, meter_type, period_type, current_value)
VALUES ('meter1', 'tenant-a', 'ai_insights', 'counter', 'monthly', 0);
-- Should succeed

INSERT INTO usage_meters (id, tenant_id, feature_key, meter_type, period_type, current_value)
VALUES ('meter2', 'tenant-a', 'ai_insights', 'counter', 'monthly', 0);
-- Should fail: duplicate (tenant-a, ai_insights, monthly)

-- Test: Can have same feature with different period_type
INSERT INTO usage_meters (id, tenant_id, feature_key, meter_type, period_type, current_value)
VALUES ('meter3', 'tenant-a', 'ai_insights', 'counter', 'yearly', 0);
-- Should succeed (different period_type)

-- Cleanup
DELETE FROM usage_meters WHERE id IN ('meter1', 'meter3');
```

### 1.5 Usage Events Constraints

```sql
-- Test: Foreign key constraint (optional, can be NULL)
INSERT INTO usage_events (id, tenant_id, feature_key, event_type, value, period_type, meter_id)
VALUES ('event1', 'tenant-a', 'ai_insights', 'increment', 1, 'monthly', 'nonexistent_meter');
-- Should fail: foreign key violation (if meter_id is provided, must exist)

-- Test: Can insert without meter_id
INSERT INTO usage_events (id, tenant_id, feature_key, event_type, value, period_type)
VALUES ('event2', 'tenant-a', 'ai_insights', 'increment', 1, 'monthly');
-- Should succeed

-- Cleanup
DELETE FROM usage_events WHERE id = 'event2';
```

## 2. Tenant Isolation Tests

### 2.1 Cross-Tenant Access Prevention

```sql
-- Setup: Create subscriptions for two tenants
INSERT INTO tenant_subscriptions (id, tenant_id, plan_id, status)
VALUES 
    ('sub-tenant-a', 'tenant-a', 'plan_growth', 'active'),
    ('sub-tenant-b', 'tenant-b', 'plan_pro', 'active');

-- Test: Tenant A should only see their own subscription
SELECT id, tenant_id, plan_id, status
FROM tenant_subscriptions
WHERE tenant_id = 'tenant-a';
-- Should return only sub-tenant-a

-- Test: Tenant B should only see their own subscription
SELECT id, tenant_id, plan_id, status
FROM tenant_subscriptions
WHERE tenant_id = 'tenant-b';
-- Should return only sub-tenant-b

-- Test: Query without tenant_id filter (WRONG - should never happen in code)
SELECT id, tenant_id, plan_id, status
FROM tenant_subscriptions;
-- Returns both - this is why repository MUST enforce tenant_id filter

-- Cleanup
DELETE FROM tenant_subscriptions WHERE id IN ('sub-tenant-a', 'sub-tenant-b');
```

### 2.2 Composite Key Tenant Isolation

```sql
-- Test: Same feature key, different tenants
INSERT INTO usage_meters (id, tenant_id, feature_key, meter_type, period_type, current_value)
VALUES 
    ('meter-tenant-a', 'tenant-a', 'ai_insights', 'counter', 'monthly', 10),
    ('meter-tenant-b', 'tenant-b', 'ai_insights', 'counter', 'monthly', 20);
-- Should succeed (different tenant_id)

-- Test: Tenant A can only access their meter
SELECT id, tenant_id, feature_key, current_value
FROM usage_meters
WHERE tenant_id = 'tenant-a' AND feature_key = 'ai_insights';
-- Should return only meter-tenant-a with value 10

-- Cleanup
DELETE FROM usage_meters WHERE id IN ('meter-tenant-a', 'meter-tenant-b');
```

## 3. Index Verification

```sql
-- Verify all tenant_id indexes exist
SELECT 
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname LIKE '%tenant_id%'
ORDER BY tablename, indexname;

-- Expected indexes:
-- - idx_tenant_subscriptions_tenant_id
-- - idx_tenant_subscriptions_tenant_status (partial)
-- - idx_usage_meters_tenant_id
-- - idx_usage_meters_tenant_feature
-- - idx_usage_events_tenant_id
-- - idx_usage_events_tenant_feature_created
-- - idx_usage_events_period (partial)
```

## 4. Trigger Tests

```sql
-- Test: updated_at trigger on plans
INSERT INTO plans (id, name, display_name, is_active)
VALUES ('trigger_test', 'trigger', 'Trigger Test', true);

SELECT created_at, updated_at FROM plans WHERE id = 'trigger_test';
-- created_at and updated_at should be equal

-- Wait a moment, then update
UPDATE plans SET display_name = 'Updated' WHERE id = 'trigger_test';

SELECT created_at, updated_at FROM plans WHERE id = 'trigger_test';
-- updated_at should be newer than created_at

-- Cleanup
DELETE FROM plans WHERE id = 'trigger_test';
```

## 5. Seed Data Verification

```sql
-- Verify all plans exist
SELECT id, name, display_name, is_active
FROM plans
ORDER BY name;
-- Should return: plan_enterprise, plan_free, plan_growth, plan_pro

-- Verify plan features are seeded
SELECT 
    p.name as plan_name,
    COUNT(pf.feature_key) as feature_count
FROM plans p
LEFT JOIN plan_features pf ON p.id = pf.plan_id AND pf.is_enabled = true
GROUP BY p.id, p.name
ORDER BY p.name;

-- Expected:
-- free: 2 features (basic_reports, data_export)
-- growth: 5 features
-- pro: 8 features
-- enterprise: 8 features

-- Verify feature keys match requirements
SELECT DISTINCT feature_key
FROM plan_features
ORDER BY feature_key;
-- Should include: ai_actions, ai_insights, agency_mode, basic_reports, 
--                 custom_reports, data_export, openrouter_byollm, robyn_mmm
```

## 6. Usage Flow Tests

```sql
-- Setup: Create subscription and meter for tenant
INSERT INTO tenant_subscriptions (id, tenant_id, plan_id, status)
VALUES ('usage-test-sub', 'tenant-a', 'plan_pro', 'active');

INSERT INTO usage_meters (id, tenant_id, feature_key, meter_type, period_type, current_value, limit_value)
VALUES ('usage-test-meter', 'tenant-a', 'ai_insights', 'counter', 'monthly', 0, 500);

-- Test: Increment usage via event
INSERT INTO usage_events (id, tenant_id, feature_key, event_type, value, previous_value, period_type, meter_id)
VALUES ('usage-event-1', 'tenant-a', 'ai_insights', 'increment', 1, 0, 'monthly', 'usage-test-meter');

-- Update meter
UPDATE usage_meters 
SET current_value = current_value + 1
WHERE id = 'usage-test-meter';

-- Verify
SELECT current_value, limit_value 
FROM usage_meters 
WHERE id = 'usage-test-meter';
-- current_value should be 1

-- Test: Check entitlement (should pass - 1 < 500)
SELECT 
    um.current_value,
    um.limit_value,
    CASE 
        WHEN um.limit_value IS NULL THEN true
        WHEN um.current_value < um.limit_value THEN true
        ELSE false
    END as can_access
FROM usage_meters um
WHERE um.tenant_id = 'tenant-a' AND um.feature_key = 'ai_insights';
-- can_access should be true

-- Cleanup
DELETE FROM usage_events WHERE id = 'usage-event-1';
DELETE FROM usage_meters WHERE id = 'usage-test-meter';
DELETE FROM tenant_subscriptions WHERE id = 'usage-test-sub';
```

## 7. Performance Tests

```sql
-- Test: Query performance with indexes
EXPLAIN ANALYZE
SELECT ts.*
FROM tenant_subscriptions ts
WHERE ts.tenant_id = 'tenant-a' AND ts.status = 'active';
-- Should use idx_tenant_subscriptions_tenant_status (partial index)

EXPLAIN ANALYZE
SELECT um.*
FROM usage_meters um
WHERE um.tenant_id = 'tenant-a' AND um.feature_key = 'ai_insights';
-- Should use idx_usage_meters_tenant_feature (composite index)
```

## 8. Security Assertions

```sql
-- Assertion 1: No table allows tenant_id to be NULL for tenant-scoped tables
SELECT 
    table_name,
    column_name,
    is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('tenant_subscriptions', 'usage_meters', 'usage_events')
  AND column_name = 'tenant_id'
  AND is_nullable = 'YES';
-- Should return 0 rows (all tenant_id columns must be NOT NULL)

-- Assertion 2: All tenant-scoped tables have tenant_id index
SELECT 
    t.table_name,
    COUNT(i.indexname) as tenant_id_index_count
FROM information_schema.tables t
LEFT JOIN pg_indexes i ON i.tablename = t.table_name 
    AND i.indexname LIKE '%tenant_id%'
WHERE t.table_schema = 'public'
  AND t.table_name IN ('tenant_subscriptions', 'usage_meters', 'usage_events')
GROUP BY t.table_name;
-- Each table should have at least 1 tenant_id index

-- Assertion 3: Composite unique keys include tenant_id
SELECT 
    tc.table_name,
    tc.constraint_name,
    string_agg(kcu.column_name, ', ' ORDER BY kcu.ordinal_position) as columns
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu 
    ON tc.constraint_name = kcu.constraint_name
WHERE tc.constraint_type = 'UNIQUE'
  AND tc.table_schema = 'public'
  AND tc.table_name IN ('tenant_subscriptions', 'usage_meters')
GROUP BY tc.table_name, tc.constraint_name
HAVING 'tenant_id' = ANY(array_agg(kcu.column_name));
-- Should return constraints that include tenant_id
```

## Running All Tests

Create a test script:

```bash
#!/bin/bash
# backend/scripts/test_billing_schema.sh

set -e

DATABASE_URL="${DATABASE_URL:-postgresql://user:pass@localhost:5432/testdb}"

echo "Running billing schema tests..."

psql "$DATABASE_URL" <<EOF
\set ON_ERROR_STOP on

-- Run all test queries above
-- (Copy test queries from sections 1-8)

\echo 'All tests passed!'
EOF
```

## Expected Results

All tests should pass. If any test fails:
1. Verify migration was applied correctly
2. Check that seed script ran successfully
3. Verify indexes were created
4. Check constraint definitions match expected behavior
