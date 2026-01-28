# Implementation Plan: User Story 7.7.1 — Build Canonical Fact Tables

## Executive Summary

The canonical fact tables are **largely implemented** with excellent patterns. This plan identifies 8 specific gaps that need to be addressed to fully comply with the user story requirements.

---

## Current State Assessment

### What Already Exists ✅

| Model | Location | Status |
|-------|----------|--------|
| `fact_orders` | `analytics/models/facts/fact_orders.sql` | ✅ Implemented |
| `fact_ad_spend` | `analytics/models/facts/fact_ad_spend.sql` | ✅ Implemented (equivalent to `fact_marketing_spend`) |
| `fact_campaign_performance` | `analytics/models/facts/fact_campaign_performance.sql` | ✅ Implemented |
| `schema.yml` | `analytics/models/facts/schema.yml` | ✅ Comprehensive tests |

### Existing Capabilities ✅

- **Incremental models** with time-based tracking (`airbyte_emitted_at > max(ingested_at)`)
- **Tenant isolation** via `tenant_id` in all models with relationship tests
- **Surrogate keys** using MD5 hash including `tenant_id`
- **Multi-platform unification** (Meta Ads + Google Ads)
- **Calculated metrics** (CTR, CPC, CPA in campaign performance)
- **ROAS calculation** with both gross and net variants (in `fct_roas.sql`)
- **Backfill support** via macro variables
- **Freshness tests** and volume anomaly detection

---

## Gap Analysis: What's Left to Do

### Gap 1: PII in `fact_orders` ❌ **CRITICAL**

**User Story Requirement:** "No PII columns"

**Current State:** `fact_orders` contains:
- `customer_email` (line 75) — **PII**
- `customer_id_raw` (line 76) — Potentially identifiable

**Required Change:**
- Remove `customer_email` from `fact_orders.sql`
- Consider removing or hashing `customer_id_raw`
- Update `schema.yml` to remove these column definitions

**Files to Modify:**
- `analytics/models/facts/fact_orders.sql` (lines 23-24, 75-77)
- `analytics/models/facts/schema.yml` (lines 42-47)

---

### Gap 2: Missing Timezone Normalization ❌ **HIGH PRIORITY**

**User Story Requirement:** "Normalize timestamps to tenant local date"

**Current State:**
- All timestamps are UTC
- No tenant timezone storage or dimension table exists
- No timezone conversion in fact models

**Required Changes:**

1. **Create tenant timezone dimension** (new model or extend existing):
   ```sql
   -- Option A: Add timezone to _tenant_airbyte_connections
   -- Option B: Create dim_tenant.sql with timezone column
   ```

2. **Add timezone conversion macro**:
   ```sql
   -- macros/convert_to_tenant_local.sql
   {% macro convert_to_tenant_local(timestamp_col, tenant_timezone) %}
       {{ timestamp_col }} AT TIME ZONE 'UTC' AT TIME ZONE {{ tenant_timezone }}
   {% endmacro %}
   ```

3. **Add `date_local` column** to all fact tables:
   - `fact_orders`: `order_created_at` → `date` (tenant local)
   - `fact_ad_spend`: `spend_date` → already DATE, may need timezone-aware source
   - `fact_campaign_performance`: `performance_date` → already DATE

**Files to Create:**
- `analytics/models/staging/dim_tenant.sql` (or modify `_tenant_airbyte_connections`)
- `analytics/macros/convert_to_tenant_local.sql`

**Files to Modify:**
- `analytics/models/facts/fact_orders.sql`
- `analytics/models/facts/fact_ad_spend.sql`
- `analytics/models/facts/fact_campaign_performance.sql`
- `analytics/models/facts/schema.yml`

---

### Gap 3: Missing `source_platform` in `fact_orders` ❌ **MEDIUM**

**User Story Requirement:** `source_platform` as required column

**Current State:** `fact_orders` has no `source_platform` column (implicitly Shopify)

**Required Change:**
```sql
-- Add to fact_orders.sql SELECT clause:
'shopify' as source_platform,
```

**Files to Modify:**
- `analytics/models/facts/fact_orders.sql`
- `analytics/models/facts/schema.yml` (add column definition with `accepted_values` test)

---

### Gap 4: Revenue Column Naming ❌ **MEDIUM**

**User Story Requirement:**
- `revenue_gross` and `revenue_net` columns
- "Revenue = net (default), gross available"

**Current State:**
- `fact_orders` has `revenue` (mapped from `total_price`)
- `subtotal_price` exists but is different from `revenue_net`
- Net revenue calculation exists in `fct_revenue.sql` but not in base fact

**Required Changes:**
```sql
-- In fact_orders.sql:
total_price as revenue_gross,          -- Gross revenue (total including tax)
subtotal_price as revenue_net,         -- Net revenue (before tax, approximation)
-- OR calculate true net after refunds (complex, may need join to refunds)
```

**Design Decision Needed:**
- Is `revenue_net = subtotal_price` (before tax)?
- Or `revenue_net = total_price - refunds`? (requires refund calculation in fact)

**Files to Modify:**
- `analytics/models/facts/fact_orders.sql`
- `analytics/models/facts/schema.yml`

---

### Gap 5: Configurable Lookback Window ❌ **MEDIUM**

**User Story Requirement:** "Default 7 days, configurable per source"

**Current State:**
- Incremental uses `airbyte_emitted_at > max(ingested_at)` — not date-based
- No configurable lookback window

**Required Changes:**

1. **Add dbt variable for lookback**:
   ```yaml
   # dbt_project.yml
   vars:
     fact_orders_lookback_days: 7
     fact_ad_spend_lookback_days: 7
     fact_campaign_performance_lookback_days: 7
   ```

2. **Modify incremental logic**:
   ```sql
   {% if is_incremental() %}
       and airbyte_emitted_at >= (
           select coalesce(
               max(ingested_at) - interval '{{ var("fact_orders_lookback_days", 7) }} days',
               '1970-01-01'::timestamp with time zone
           ) from {{ this }}
       )
   {% endif %}
   ```

**Files to Modify:**
- `analytics/dbt_project.yml`
- `analytics/models/facts/fact_orders.sql`
- `analytics/models/facts/fact_ad_spend.sql`
- `analytics/models/facts/fact_campaign_performance.sql`

---

### Gap 6: Naming Convention Mismatch ⚠️ **LOW**

**User Story Requirement:** `fact_marketing_spend`

**Current State:** `fact_ad_spend`

**Options:**
1. **Rename** `fact_ad_spend` → `fact_marketing_spend` (breaking change)
2. **Create alias/view** `fact_marketing_spend` → `fact_ad_spend`
3. **Accept current naming** (ad spend = marketing spend, semantically equivalent)

**Recommendation:** Document that `fact_ad_spend` serves as the canonical marketing spend table. Renaming introduces unnecessary migration risk.

---

### Gap 7: Missing `channel` Column ⚠️ **LOW**

**User Story Requirement:** `channel` as optional but standardized column

**Current State:** `platform` exists (`meta_ads`, `google_ads`) but no `channel` dimension

**Analysis:**
- `channel` typically means marketing channel (e.g., paid_social, paid_search, email, organic)
- `platform` is more specific (meta_ads, google_ads)

**Required Change:**
```sql
-- Add derived channel column:
case
    when platform = 'meta_ads' then 'paid_social'
    when platform = 'google_ads' then 'paid_search'
    else 'other'
end as channel,
```

**Files to Modify:**
- `analytics/models/facts/fact_ad_spend.sql`
- `analytics/models/facts/fact_campaign_performance.sql`
- `analytics/models/facts/schema.yml`

---

### Gap 8: Per-Tenant Row Count Test ⚠️ **LOW**

**User Story Requirement:** "row count > 0 per tenant after sync"

**Current State:** `test_volume_anomaly` checks overall volume, not per-tenant

**Required Change:**
```sql
-- tests/generic/test_tenant_has_rows.sql
{% test tenant_has_rows(model, tenant_id_column='tenant_id') %}
    select tenant_id, count(*) as row_count
    from {{ model }}
    group by tenant_id
    having count(*) = 0
{% endtest %}
```

**Files to Create:**
- `analytics/tests/generic/test_tenant_has_rows.sql`

**Files to Modify:**
- `analytics/models/facts/schema.yml` (add test to each model)

---

## Implementation Phases

### Phase 1: Critical Fixes (Must Have)

| Task | Priority | Effort | Risk |
|------|----------|--------|------|
| Remove PII from `fact_orders` | Critical | Low | Medium (downstream impact) |
| Add `source_platform` to `fact_orders` | Medium | Low | Low |
| Add `revenue_gross`/`revenue_net` columns | Medium | Low | Low |

### Phase 2: Lookback & Timezone (Should Have)

| Task | Priority | Effort | Risk |
|------|----------|--------|------|
| Implement configurable lookback window | Medium | Medium | Low |
| Design tenant timezone storage | High | Medium | Medium |
| Implement timezone conversion | High | High | Medium |

### Phase 3: Enhancements (Nice to Have)

| Task | Priority | Effort | Risk |
|------|----------|--------|------|
| Add `channel` dimension | Low | Low | Low |
| Add per-tenant row count test | Low | Low | Low |
| Document naming decision (ad_spend vs marketing_spend) | Low | Low | None |

---

## Detailed Implementation Tasks

### Task 1: Remove PII from fact_orders

**File:** `analytics/models/facts/fact_orders.sql`

Remove from CTE select:
```sql
-- REMOVE these lines (23-24):
customer_email,
customer_id_raw,
```

Remove from final select:
```sql
-- REMOVE these lines (75-77):
customer_email,
customer_id_raw,
```

**File:** `analytics/models/facts/schema.yml`

Remove column definitions:
```yaml
# REMOVE (lines 42-47):
- name: customer_email
  description: Customer email address
  ...
- name: customer_id_raw
  description: Raw customer ID from Shopify
```

### Task 2: Add source_platform to fact_orders

**File:** `analytics/models/facts/fact_orders.sql`

Add after line 68:
```sql
-- Source platform identifier
'shopify' as source_platform,
```

**File:** `analytics/models/facts/schema.yml`

Add column definition:
```yaml
- name: source_platform
  description: Source platform identifier (always 'shopify' for this table)
  tests:
    - not_null
    - accepted_values:
        values: ['shopify']
```

### Task 3: Rename revenue columns

**File:** `analytics/models/facts/fact_orders.sql`

Change:
```sql
-- FROM:
total_price as revenue,
subtotal_price,

-- TO:
total_price as revenue_gross,
subtotal_price as revenue_net,  -- Note: This is pre-tax, not post-refund
```

**File:** `analytics/models/facts/schema.yml`

Update column definitions accordingly.

### Task 4: Implement configurable lookback

**File:** `analytics/dbt_project.yml`

Add vars section:
```yaml
vars:
  # Incremental lookback windows (in days)
  fact_orders_lookback_days: 7
  fact_ad_spend_lookback_days: 7
  fact_campaign_performance_lookback_days: 7
```

**File:** `analytics/models/facts/fact_orders.sql`

Modify incremental clause:
```sql
{% elif is_incremental() %}
    -- Incremental mode with configurable lookback window
    and airbyte_emitted_at >= (
        select coalesce(
            max(ingested_at) - interval '{{ var("fact_orders_lookback_days", 7) }} days',
            '1970-01-01'::timestamp with time zone
        )
        from {{ this }}
    )
{% endif %}
```

Similar changes for `fact_ad_spend.sql` and `fact_campaign_performance.sql`.

### Task 5: Tenant timezone (requires design decision)

**Option A: Store timezone in tenant table**

Create `analytics/models/staging/dim_tenant.sql`:
```sql
select
    tenant_id,
    coalesce(timezone, 'UTC') as timezone
from {{ source('platform', 'tenants') }}
```

**Option B: Store timezone in Shopify shop settings**

Pull from Shopify API during ingestion and store in raw tables.

**Design Decision Required:** Where does tenant timezone come from?

### Task 6: Add channel column

**File:** `analytics/models/facts/fact_ad_spend.sql`

Add to final select:
```sql
-- Marketing channel (derived from platform)
case
    when platform = 'meta_ads' then 'paid_social'
    when platform = 'google_ads' then 'paid_search'
    else 'other'
end as channel,
```

---

## Verification Checklist

After implementation, verify:

- [ ] `fact_orders` has no PII columns (customer_email, customer_id_raw removed)
- [ ] `fact_orders` has `source_platform` column
- [ ] All fact tables have `revenue_gross` and `revenue_net` (where applicable)
- [ ] Lookback window is configurable via dbt vars
- [ ] Dates are normalized to tenant local timezone
- [ ] `channel` column exists in marketing tables
- [ ] Per-tenant row count test passes
- [ ] All existing tests still pass
- [ ] ROAS formula verified: `revenue_net / spend`

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Removing PII breaks downstream | High | Check all refs to fact_orders for customer_email usage |
| Timezone conversion performance | Medium | Use materialized timezone lookup, test on large datasets |
| Lookback window too short | Low | Make configurable, document default reasoning |
| Revenue column rename breaks dashboards | Medium | Coordinate with Superset/BI team |

---

## Dependencies

- **Tenant timezone source**: Need to confirm where timezone data will come from (Shopify shop settings, user input, or default UTC)
- **Downstream impact analysis**: Need to verify no dashboards/reports rely on removed PII columns
- **fct_revenue alignment**: Ensure revenue_net definition is consistent with fct_revenue.sql

---

## Summary

| Category | Count |
|----------|-------|
| Already Complete | 80% |
| Critical Gaps | 1 (PII removal) |
| High Priority Gaps | 2 (timezone, revenue columns) |
| Medium Priority Gaps | 2 (lookback, source_platform) |
| Low Priority Gaps | 3 (channel, naming, per-tenant test) |

**Estimated Effort:** 2-3 days for Phase 1 + Phase 2, 1 day for Phase 3

https://claude.ai/code/session_01CMEwSWqL8CUM6bc2u44Uq1
