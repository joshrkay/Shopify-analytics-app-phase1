# OAuth TIER 1 Mitigations - Deployment Guide

**Version:** 1.0.0
**Date:** 2026-01-31
**Criticality:** BLOCKING (Must deploy before OAuth launch)

---

## Executive Summary

This package implements **TIER 1 security mitigations** to prevent data leakage via duplicate `shop_domain` mappings in the OAuth/Airbyte integration.

### The Problem

- DBT derives `tenant_id` by JOINing Airbyte data on `shop_domain`
- If two tenants connect the same `shop_domain`, the JOIN returns duplicate rows
- **Result**: Cross-tenant data leakage (Tenant B sees Tenant A's orders)

### The Solution

Three-layer defense:
1. **Database constraint** - Blocks duplicates at strongest layer
2. **Application validation** - Early detection with user-friendly errors
3. **Audit logging** - Security monitoring and compliance

**Risk Reduction:** HIGH → LOW

---

## Files Deployed

### 1. Database Migration
```
backend/migrations/oauth_shop_domain_unique_constraint.sql
```
- Creates unique index on normalized `shop_domain`
- Validates no existing duplicates before deployment
- **Run time:** ~5 seconds (depends on table size)

### 2. Application Logic
```
backend/src/services/airbyte_service.py
```
**Changes:**
- Added `_normalize_shop_domain()` method
- Added `_validate_shop_domain_unique()` method
- Updated `register_connection()` to validate before insert

### 3. Audit Events
```
backend/src/platform/audit_events.py
```
**New events:**
- `oauth.flow_started`
- `oauth.callback_received`
- `oauth.token_exchanged`
- `oauth.connection_created`
- `oauth.connection_failed`
- `oauth.duplicate_shop_detected` (CRITICAL severity)
- `oauth.connection_disconnected`
- `credentials.refreshed`
- `credentials.refresh_failed`
- `credentials.revoked_by_provider`

### 4. Integration Tests
```
backend/src/tests/services/test_shop_domain_validation.py
```
**Coverage:**
- Normalization logic (protocol, case, trailing slash)
- Application validation (different tenant, same tenant, inactive)
- Database constraint enforcement
- End-to-end OAuth flows
- Performance tests

---

## Pre-Deployment Checklist

### ✅ Step 1: Review Existing Data

Run this query to check for existing duplicates:

```sql
SELECT
    lower(
        trim(
            trailing '/' from
            regexp_replace(
                coalesce(configuration->>'shop_domain', ''),
                '^https?://',
                '',
                'i'
            )
        )
    ) as shop_domain,
    array_agg(tenant_id ORDER BY tenant_id) as tenant_ids,
    array_agg(connection_name ORDER BY connection_name) as connection_names,
    COUNT(*) as tenant_count
FROM platform.tenant_airbyte_connections
WHERE source_type IN ('shopify', 'source-shopify')
  AND status = 'active'
  AND is_enabled = true
  AND configuration->>'shop_domain' IS NOT NULL
  AND configuration->>'shop_domain' != ''
GROUP BY 1
HAVING COUNT(*) > 1;
```

**If duplicates found:**
1. Investigate which tenant legitimately owns each shop
2. Disable or delete duplicate connections:
   ```sql
   UPDATE platform.tenant_airbyte_connections
   SET is_enabled = false
   WHERE id = '<connection_id_to_disable>';
   ```
3. Document decision in audit log

### ✅ Step 2: Test in Staging

```bash
# Run migration in staging
psql $STAGING_DATABASE_URL -f backend/migrations/oauth_shop_domain_unique_constraint.sql

# Run integration tests
pytest backend/src/tests/services/test_shop_domain_validation.py -v

# Verify constraint exists
psql $STAGING_DATABASE_URL -c "
    SELECT indexname, indexdef
    FROM pg_indexes
    WHERE schemaname = 'platform'
      AND tablename = 'tenant_airbyte_connections'
      AND indexname = 'ix_tenant_airbyte_connections_shop_domain_unique';
"
```

### ✅ Step 3: Coordinate Deployment

**Deployment order (CRITICAL):**
1. Deploy database migration
2. Deploy application code
3. Restart backend services
4. Monitor for errors

**DO NOT:**
- Deploy application code before migration (will fail on duplicates)
- Deploy migration without clearing duplicates first

---

## Deployment Instructions

### Production Deployment

#### Part 1: Database Migration (5 minutes)

```bash
# 1. Connect to production database (read-write user)
psql $PRODUCTION_DATABASE_URL

# 2. Run migration
\i backend/migrations/oauth_shop_domain_unique_constraint.sql

# Expected output:
# ✓ No duplicate shop_domains found
# ✓ Unique index created successfully
# ✓ Index verified: ix_tenant_airbyte_connections_shop_domain_unique
# ✓ Active Shopify connections protected: <count>
# Migration completed successfully
```

**Rollback (if needed):**
```sql
DROP INDEX IF EXISTS platform.ix_tenant_airbyte_connections_shop_domain_unique;
```

#### Part 2: Application Deployment (10 minutes)

```bash
# 1. Deploy backend code
git checkout <your-branch>
git pull origin <your-branch>

# 2. Build and deploy (adjust for your deployment method)
# Example for Docker:
docker build -t shopify-analytics-backend:oauth-tier1 .
docker push shopify-analytics-backend:oauth-tier1

# Example for Render:
git push origin <your-branch>
# (Render auto-deploys from branch)

# 3. Restart services
# (Automatic on Render, manual for other platforms)

# 4. Verify deployment
curl https://your-api.com/health
```

#### Part 3: Post-Deployment Verification (5 minutes)

```bash
# 1. Verify database constraint active
psql $PRODUCTION_DATABASE_URL -c "
    SELECT
        schemaname,
        tablename,
        indexname,
        indexdef
    FROM pg_indexes
    WHERE indexname = 'ix_tenant_airbyte_connections_shop_domain_unique';
"

# 2. Test application validation
# Try creating duplicate connection (should fail gracefully)
curl -X POST https://your-api.com/api/airbyte/connections \
  -H "Authorization: Bearer <tenant-a-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "airbyte_connection_id": "test-duplicate",
    "connection_name": "Duplicate Test",
    "source_type": "shopify",
    "configuration": {"shop_domain": "<existing-shop-domain>"}
  }'

# Expected: 400 Bad Request with user-friendly error message
# "This Shopify store is already connected to another account..."

# 3. Check logs for validation events
# Look for: "SECURITY: Duplicate shop_domain attempted by different tenant"

# 4. Verify audit events captured
psql $PRODUCTION_DATABASE_URL -c "
    SELECT event_type, COUNT(*)
    FROM audit_logs
    WHERE event_type LIKE 'oauth.%'
      AND created_at > NOW() - INTERVAL '1 hour'
    GROUP BY event_type
    ORDER BY COUNT(*) DESC;
"
```

---

## Testing the Mitigations

### Manual Test Cases

#### Test 1: Duplicate shop_domain (different tenant) - SHOULD FAIL

```bash
# Terminal 1: Tenant A creates connection
curl -X POST https://your-api.com/api/airbyte/connections \
  -H "Authorization: Bearer <tenant-a-token>" \
  -d '{
    "airbyte_connection_id": "conn-tenant-a",
    "connection_name": "My Shop",
    "source_type": "shopify",
    "configuration": {"shop_domain": "test-duplicate.myshopify.com"}
  }'

# Expected: 200 OK, connection created

# Terminal 2: Tenant B tries same shop
curl -X POST https://your-api.com/api/airbyte/connections \
  -H "Authorization: Bearer <tenant-b-token>" \
  -d '{
    "airbyte_connection_id": "conn-tenant-b",
    "connection_name": "Duplicate Attempt",
    "source_type": "shopify",
    "configuration": {"shop_domain": "test-duplicate.myshopify.com"}
  }'

# Expected: 400 Bad Request
# Error: "This Shopify store is already connected to another account..."
```

#### Test 2: Case/protocol variations - SHOULD FAIL

```bash
# Tenant A has: "store.myshopify.com"

# Try with different case
curl ... -d '{"shop_domain": "STORE.myshopify.com"}'
# Expected: FAIL

# Try with protocol
curl ... -d '{"shop_domain": "https://store.myshopify.com"}'
# Expected: FAIL

# Try with trailing slash
curl ... -d '{"shop_domain": "store.myshopify.com/"}'
# Expected: FAIL
```

#### Test 3: Inactive connection - SHOULD SUCCEED

```bash
# 1. Disable existing connection
psql $DATABASE_URL -c "
    UPDATE platform.tenant_airbyte_connections
    SET status = 'inactive'
    WHERE configuration->>'shop_domain' = 'test-inactive.myshopify.com';
"

# 2. New tenant connects
curl -X POST ... -d '{
  "shop_domain": "test-inactive.myshopify.com"
}'

# Expected: 200 OK (can reconnect after previous tenant disconnected)
```

### Automated Test Suite

```bash
# Run full test suite
pytest backend/src/tests/services/test_shop_domain_validation.py -v

# Run specific test categories
pytest backend/src/tests/services/test_shop_domain_validation.py::TestShopDomainNormalization -v
pytest backend/src/tests/services/test_shop_domain_validation.py::TestShopDomainValidation -v
pytest backend/src/tests/services/test_shop_domain_validation.py::TestDatabaseConstraintEnforcement -v
pytest backend/src/tests/services/test_shop_domain_validation.py::TestEndToEndOAuthFlow -v

# Run with coverage
pytest backend/src/tests/services/test_shop_domain_validation.py \
  --cov=src.services.airbyte_service \
  --cov-report=html \
  --cov-report=term-missing

# Expected coverage: > 95% for airbyte_service.py
```

---

## Monitoring & Alerts

### Metrics to Monitor

1. **Duplicate Detection Rate**
   ```sql
   SELECT COUNT(*)
   FROM audit_logs
   WHERE event_type = 'oauth.duplicate_shop_detected'
     AND created_at > NOW() - INTERVAL '24 hours';
   ```
   - **Alert threshold:** > 0 (investigate immediately)
   - **Severity:** CRITICAL

2. **OAuth Connection Success Rate**
   ```sql
   SELECT
       COUNT(*) FILTER (WHERE event_type = 'oauth.connection_created') as success,
       COUNT(*) FILTER (WHERE event_type = 'oauth.connection_failed') as failed,
       ROUND(
           100.0 * COUNT(*) FILTER (WHERE event_type = 'oauth.connection_created') /
           NULLIF(COUNT(*), 0),
           2
       ) as success_rate_pct
   FROM audit_logs
   WHERE event_type IN ('oauth.connection_created', 'oauth.connection_failed')
     AND created_at > NOW() - INTERVAL '24 hours';
   ```
   - **Alert threshold:** < 95% success rate
   - **Severity:** HIGH

3. **Validation Query Performance**
   - Monitor `_validate_shop_domain_unique()` execution time
   - **Alert threshold:** > 100ms (check if index is being used)
   - **Severity:** MEDIUM

### Alert Configuration

Add to your monitoring system (Datadog, CloudWatch, etc.):

```yaml
# Datadog alert example
alerts:
  - name: "Critical: Duplicate shop_domain detected"
    query: 'sum(last_1h):sum:audit.event{event_type:oauth.duplicate_shop_detected} > 0'
    message: |
      CRITICAL: A duplicate shop_domain connection was attempted!
      This indicates a potential data leakage attack or configuration error.

      Review audit logs immediately:
      SELECT * FROM audit_logs
      WHERE event_type = 'oauth.duplicate_shop_detected'
      ORDER BY created_at DESC LIMIT 10;

      Notify: @slack-security @pagerduty-oncall
    severity: critical
    notify:
      - slack: "#security-alerts"
      - pagerduty: "oncall-engineering"
      - email: ["security@company.com", "engineering@company.com"]

  - name: "High: OAuth connection failure rate elevated"
    query: 'sum(last_1h):sum:audit.event{event_type:oauth.connection_failed} > 10'
    message: |
      OAuth connections are failing at elevated rate.
      This may indicate:
      - Provider API issues
      - Network connectivity problems
      - Validation too strict

      Review recent failures for patterns.
    severity: high
    notify:
      - slack: "#engineering-alerts"
```

---

## Troubleshooting

### Issue 1: Migration fails with "duplicate shop_domains found"

**Symptoms:**
```
ERROR: Cannot create unique index with 3 existing duplicates. Resolve conflicts first.
Shop: store.myshopify.com
  Tenant IDs: ['tenant-a', 'tenant-b']
```

**Resolution:**
1. Review duplicate shop_domains listed
2. Determine legitimate owner for each shop
3. Disable or delete duplicate connections:
   ```sql
   -- Disable (keeps audit trail)
   UPDATE platform.tenant_airbyte_connections
   SET is_enabled = false
   WHERE id = '<connection-id-to-remove>';

   -- OR delete (permanent)
   DELETE FROM platform.tenant_airbyte_connections
   WHERE id = '<connection-id-to-remove>';
   ```
4. Document decision (which tenant owned shop, why other was duplicate)
5. Re-run migration

### Issue 2: Application returns "already connected" for legitimate new shop

**Symptoms:**
User tries to connect new shop but gets error:
```
This Shopify store is already connected to another account.
```

**Diagnosis:**
```sql
-- Check if shop_domain exists
SELECT
    tenant_id,
    connection_name,
    status,
    is_enabled,
    configuration->>'shop_domain' as shop_domain
FROM platform.tenant_airbyte_connections
WHERE lower(
        trim(
            trailing '/' from
            regexp_replace(
                coalesce(configuration->>'shop_domain', ''),
                '^https?://',
                '',
                'i'
            )
        )
    ) = '<normalized-shop-domain>';
```

**Possible causes:**
1. Previous tenant still has active connection
   - **Fix:** Previous tenant must disconnect first
2. Normalization issue (edge case not covered)
   - **Fix:** Report bug with exact shop_domain value
3. Stale connection (tenant deleted but connection remains)
   - **Fix:** Clean up orphaned connections

### Issue 3: Performance degradation on validation

**Symptoms:**
OAuth flows taking > 5 seconds to complete

**Diagnosis:**
```sql
-- Check if index is being used
EXPLAIN ANALYZE
SELECT tenant_id
FROM platform.tenant_airbyte_connections
WHERE lower(
        trim(
            trailing '/' from
            regexp_replace(
                coalesce(configuration->>'shop_domain', ''),
                '^https?://',
                '',
                'i'
            )
        )
    ) = 'test-shop.myshopify.com'
  AND source_type IN ('shopify', 'source-shopify')
  AND status = 'active'
  AND is_enabled = true;

-- Look for: "Index Scan using ix_tenant_airbyte_connections_shop_domain_unique"
```

**Resolution:**
- If index NOT being used: Rebuild index
  ```sql
  REINDEX INDEX CONCURRENTLY ix_tenant_airbyte_connections_shop_domain_unique;
  ```
- If table has > 10,000 rows: Consider partitioning by tenant_id

---

## Rollback Plan

If critical issues discovered post-deployment:

### Emergency Rollback (< 5 minutes)

```bash
# 1. Drop database constraint
psql $PRODUCTION_DATABASE_URL -c "
    DROP INDEX IF EXISTS platform.ix_tenant_airbyte_connections_shop_domain_unique;
"

# 2. Revert application code
git revert <commit-hash>
git push origin <branch>

# 3. Restart services
# (depends on deployment platform)

# 4. Verify rollback
curl https://your-api.com/health

# 5. Document rollback reason
# - What issue was encountered?
# - What needs to be fixed before retry?
# - ETA for fix?
```

### Post-Rollback Investigation

1. Review logs for errors
2. Check audit_logs for unexpected events
3. Verify no data corruption occurred
4. Identify root cause
5. Fix and re-test in staging
6. Schedule re-deployment

---

## Success Criteria

Deployment is considered successful when:

- ✅ Database constraint created without errors
- ✅ Application validation blocking duplicate shop_domains
- ✅ Audit events capturing OAuth flows
- ✅ Integration tests passing (100%)
- ✅ Manual test cases validated
- ✅ No production errors in first 24 hours
- ✅ OAuth connection success rate > 95%
- ✅ Validation query performance < 100ms

---

## Next Steps (TIER 2 & 3)

After successful TIER 1 deployment:

1. **Week 1:** Deploy TIER 2 monitoring
   - DBT tests for duplicate detection
   - Hourly reconciliation job
   - Alerting dashboard

2. **Month 2:** Implement TIER 3 architectural improvements
   - Extract shop_domain to dedicated column
   - Implement token refresh automation
   - Add provider webhook handlers

---

## Support & Escalation

**Issues during deployment:**
- Slack: #engineering-support
- PagerDuty: On-call engineer
- Email: engineering@company.com

**Security concerns:**
- Slack: #security-incidents
- Email: security@company.com
- Emergency: Page security on-call

**Documentation updates:**
- Update this README with lessons learned
- Document any edge cases discovered
- Share in team retrospective

---

## Changelog

### v1.0.0 (2026-01-31)
- Initial TIER 1 mitigations
- Database unique constraint
- Application validation
- OAuth audit events
- Integration test suite
