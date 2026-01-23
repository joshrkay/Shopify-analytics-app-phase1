# PR: Story 4.3 - Ad Platform Staging Models

## Commit Message

```
feat(epic-4): Add Meta Ads and Google Ads staging models (Story 4.3)

- Created stg_meta_ads.sql with normalized fields and tenant isolation
- Created stg_google_ads.sql with unified naming conventions
- Unified field naming: spend, impressions, clicks, conversions, currency
- Normalized currency fields (uppercase, validated 3-letter codes)
- Normalized dates to date type (timezone-safe)
- Handled Google Ads cost_micros conversion (micros to dollars)
- Added comprehensive edge case handling (type validation, bounds checking)
- Updated schema.yml with ad platform sources and tests
- Added tenant isolation regression tests for ad platforms
- Updated _tenant_airbyte_connections to include ad platform source types

This implements staging models for Meta Ads and Google Ads that normalize
raw Airbyte data into consistent, comparable formats. All models enforce
tenant isolation and handle edge cases to prevent data corruption or query
failures. Spend metrics are now comparable across platforms.
```

## PR Description

### Why

**Story 4.3** - As a reporting layer, I want ad platform data standardized so that spend and performance metrics are comparable across channels.

This PR creates staging models for Meta Ads and Google Ads that transform raw Airbyte data into normalized, comparable formats. Without standardized ad platform models, we cannot:
- Compare spend and performance across Meta and Google
- Build unified fact tables for ad spend
- Calculate cross-platform metrics like total ROAS
- Ensure data consistency across different ad platforms

### What Changed

- **Created `analytics/models/staging/ads/stg_meta_ads.sql`**: Meta Ads staging model
  - Normalizes Meta Ads data from Airbyte JSONB
  - Unified field naming: `spend`, `impressions`, `clicks`, `conversions`, `currency`
  - Handles Meta-specific fields: `adset_id`, `reach`, `frequency`, `cpm`, `cpp`, `ctr`
  - Currency normalization (uppercase, validated)
  - Date normalization (date type)
  - Tenant isolation enforced

- **Created `analytics/models/staging/ads/stg_google_ads.sql`**: Google Ads staging model
  - Normalizes Google Ads data from Airbyte JSONB
  - Unified field naming matching Meta Ads
  - Handles Google-specific: `cost_micros` conversion (micros to dollars)
  - Google-specific fields: `ad_group_id`, `conversion_value`, `device`, `network`
  - Currency normalization (uppercase, validated)
  - Date normalization (date type)
  - Tenant isolation enforced

- **Updated `analytics/models/staging/schema.yml`**:
  - Added source definitions for `_airbyte_raw_meta_ads` and `_airbyte_raw_google_ads`
  - Added model definitions with comprehensive tests
  - Tests: `not_null`, `relationships`, `accepted_values` for platform field

- **Updated `analytics/models/staging/_tenant_airbyte_connections.sql`**:
  - Now includes ad platform source types: `source-facebook-marketing`, `source-google-ads`

- **Updated `analytics/tests/tenant_isolation.sql`**:
  - Added tests for Meta Ads and Google Ads tenant isolation
  - Verifies no duplicate ad records across tenants

### Unified Field Naming

Both models use consistent field names for cross-platform comparison:
- `spend` - Amount spent (normalized currency)
- `impressions` - Number of impressions (integer)
- `clicks` - Number of clicks (integer)
- `conversions` - Number of conversions (numeric)
- `currency` - Currency code (uppercase, 3-letter, validated)
- `date` - Date of performance (date type)
- `platform` - Platform identifier (`meta_ads` or `google_ads`)
- `ad_account_id` - Account/customer ID
- `campaign_id` - Campaign ID
- `tenant_id` - Tenant identifier

### Edge Cases Handled

All edge cases from Story 4.2 analysis were applied:
- ✅ Type conversion failures: Regex validation before casting
- ✅ Null primary keys: Filtered out in WHERE clause
- ✅ Invalid JSON extraction: JSON validation before casting
- ✅ Timestamp parsing errors: Date format validation
- ✅ Empty string vs null: `trim()` before all validations
- ✅ Currency code validation: Regex validation for 3-letter codes
- ✅ Numeric conversion edge cases: Bounds checking (-999M to +999M)
- ✅ Google Ads cost_micros: Proper conversion from micros to dollars
- ✅ Tenant isolation: Same strategy as Shopify models

### Security

- ✅ **Tenant isolation**: All models filter by `tenant_id` with regression tests
- ✅ **No data leakage**: Tests verify no duplicate records across tenants
- ✅ **Configuration warnings**: Clear documentation about multi-tenant setup requirements

### Testing

- ✅ **Comprehensive tests**: `not_null`, `relationships`, `accepted_values` for platform field
- ✅ **Tenant isolation tests**: Regression tests verify no cross-tenant data leakage
- ✅ **Validation script**: All files pass validation checks
- ✅ **No breaking changes**: New models, no existing code affected

### Compliance with .cursorrules

- ✅ **YAGNI**: Only implements Story 4.3 requirements (no extras)
- ✅ **No TODOs**: All code is complete, no placeholder comments
- ✅ **Documentation**: Schema.yml includes comprehensive descriptions
- ✅ **Security**: Tenant isolation enforced and tested
- ✅ **No dead code**: Only necessary files created
- ✅ **Edge cases**: All edge cases from Story 4.2 applied

### Acceptance Criteria

- [x] Created `stg_meta_ads`
- [x] Created `stg_google_ads`
- [x] Unified naming conventions (spend, impressions, clicks, conversions)
- [x] Timezone normalization (dates as date type)
- [x] Currency normalization (uppercase, validated)
- [x] Filtered by tenant_id
- [x] Added tests: not_null, relationships, accepted_values
- [x] Added tenant isolation regression tests

### How to Test Locally

```bash
cd analytics
pip install -r requirements.txt

# Set database environment variables
export DB_HOST="localhost"
export DB_USER="postgres"
export DB_PASSWORD="your-password"
export DB_PORT="5432"
export DB_NAME="shopify_analytics"

# Compile staging models
dbt compile --select staging

# Run ad platform staging models
dbt run --select stg_meta_ads stg_google_ads

# Run tests
dbt test --select stg_meta_ads stg_google_ads
```

### Files Changed

```
analytics/
├── models/staging/
│   ├── ads/
│   │   ├── stg_meta_ads.sql (new)
│   │   └── stg_google_ads.sql (new)
│   ├── _tenant_airbyte_connections.sql (updated)
│   └── schema.yml (updated - added ad platform sources and models)
└── tests/
    └── tenant_isolation.sql (updated - added ad platform tests)
```

### Next Steps

After this PR is merged:
- Story 4.4: Create canonical fact tables (fact_orders, fact_ad_spend, fact_campaign_performance)
- Story 4.5: Define canonical metrics (revenue, AOV, ROAS, CAC, spend)
- Story 4.6: Implement baseline attribution model

---

**Story**: 4.3 - Ad Platform Staging Models  
**Epic**: 4 - Analytics Platform  
**Points**: 5
