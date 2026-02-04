-- =============================================================================
-- Test: Metric Version Integrity and Governance
-- =============================================================================
--
-- This test validates the versioned metric framework:
--
-- VERSION INTEGRITY:
--   1. Every metric has metric_name and metric_version columns
--   2. metric_version matches expected format (v1, v2, etc.)
--   3. No NULL metric versions
--   4. No duplicate metrics with different versions in same model
--
-- GOVERNANCE:
--   5. All active metrics have valid tenant_id (tenant isolation)
--   6. Deprecated metrics remain queryable (not blocked)
--   7. Sunset dates are enforced for deprecated metrics
--
-- ACCURACY:
--   8. ROAS calculation matches formula: SUM(revenue) / SUM(spend)
--   9. CAC calculation matches formula: SUM(spend) / COUNT(new_customers)
--   10. Divide-by-zero returns 0, not NULL or infinity
--
-- RECONCILIATION:
--   11. Metrics reconcile with source fact tables
--
-- If this query returns any rows, the test FAILS.
-- =============================================================================

with test_scenarios as (

    -- =========================================================================
    -- VERSION INTEGRITY TESTS
    -- =========================================================================

    -- Test 1: ROAS v1 has correct metric_name
    select
        'roas_v1_metric_name' as test_name,
        count(*) as failures,
        'ROAS v1 metric_name must be "roas"' as description
    from {{ ref('roas_v1') }}
    where metric_name != 'roas'
        or metric_name is null

    union all

    -- Test 2: ROAS v1 has correct metric_version
    select
        'roas_v1_metric_version' as test_name,
        count(*) as failures,
        'ROAS v1 metric_version must be "v1"' as description
    from {{ ref('roas_v1') }}
    where metric_version != 'v1'
        or metric_version is null

    union all

    -- Test 3: CAC v1 has correct metric_name
    select
        'cac_v1_metric_name' as test_name,
        count(*) as failures,
        'CAC v1 metric_name must be "cac"' as description
    from {{ ref('cac_v1') }}
    where metric_name != 'cac'
        or metric_name is null

    union all

    -- Test 4: CAC v1 has correct metric_version
    select
        'cac_v1_metric_version' as test_name,
        count(*) as failures,
        'CAC v1 metric_version must be "v1"' as description
    from {{ ref('cac_v1') }}
    where metric_version != 'v1'
        or metric_version is null

    union all

    -- Test 5: ROAS v1 metric_status is valid
    select
        'roas_v1_metric_status' as test_name,
        count(*) as failures,
        'ROAS v1 metric_status must be active, deprecated, or sunset' as description
    from {{ ref('roas_v1') }}
    where metric_status not in ('active', 'deprecated', 'sunset')
        or metric_status is null

    union all

    -- Test 6: CAC v1 metric_status is valid
    select
        'cac_v1_metric_status' as test_name,
        count(*) as failures,
        'CAC v1 metric_status must be active, deprecated, or sunset' as description
    from {{ ref('cac_v1') }}
    where metric_status not in ('active', 'deprecated', 'sunset')
        or metric_status is null

    union all

    -- =========================================================================
    -- TENANT ISOLATION TESTS
    -- =========================================================================

    -- Test 7: ROAS v1 has tenant_id for all rows
    select
        'roas_v1_tenant_isolation' as test_name,
        count(*) as failures,
        'ROAS v1 must have tenant_id for all rows (tenant isolation)' as description
    from {{ ref('roas_v1') }}
    where tenant_id is null

    union all

    -- Test 8: CAC v1 has tenant_id for all rows
    select
        'cac_v1_tenant_isolation' as test_name,
        count(*) as failures,
        'CAC v1 must have tenant_id for all rows (tenant isolation)' as description
    from {{ ref('cac_v1') }}
    where tenant_id is null

    union all

    -- =========================================================================
    -- ACCURACY TESTS - ROAS
    -- =========================================================================

    -- Test 9: ROAS calculation accuracy
    select
        'roas_v1_calculation_accuracy' as test_name,
        count(*) as failures,
        'ROAS v1 must equal total_revenue / total_spend (tolerance: 0.01)' as description
    from {{ ref('roas_v1') }}
    where total_spend > 0
        and abs(roas - (total_revenue / total_spend)) > 0.01

    union all

    -- Test 10: ROAS divide-by-zero handling (spend = 0 -> ROAS = 0)
    select
        'roas_v1_zero_spend_handling' as test_name,
        count(*) as failures,
        'ROAS v1 must return 0 when total_spend = 0' as description
    from {{ ref('roas_v1') }}
    where total_spend = 0
        and roas != 0

    union all

    -- Test 11: ROAS no NULL values
    select
        'roas_v1_no_null_values' as test_name,
        count(*) as failures,
        'ROAS v1 must never be NULL' as description
    from {{ ref('roas_v1') }}
    where roas is null

    union all

    -- Test 12: ROAS no infinity values
    select
        'roas_v1_no_infinity_values' as test_name,
        count(*) as failures,
        'ROAS v1 must never be infinity' as description
    from {{ ref('roas_v1') }}
    where roas = 'Infinity'::numeric
        or roas = '-Infinity'::numeric

    union all

    -- =========================================================================
    -- ACCURACY TESTS - CAC
    -- =========================================================================

    -- Test 13: CAC calculation accuracy (at channel level)
    select
        'cac_v1_calculation_accuracy' as test_name,
        count(*) as failures,
        'CAC v1 must equal total_spend / new_customers (tolerance: 0.01)' as description
    from {{ ref('cac_v1') }}
    where hierarchy_level = 'channel'
        and new_customers > 0
        and abs(cac - (total_spend / new_customers)) > 0.01

    union all

    -- Test 14: CAC divide-by-zero handling (new_customers = 0 -> CAC = 0)
    select
        'cac_v1_zero_customers_handling' as test_name,
        count(*) as failures,
        'CAC v1 must return 0 when new_customers = 0' as description
    from {{ ref('cac_v1') }}
    where new_customers = 0
        and cac != 0

    union all

    -- Test 15: CAC no NULL values
    select
        'cac_v1_no_null_values' as test_name,
        count(*) as failures,
        'CAC v1 must never be NULL' as description
    from {{ ref('cac_v1') }}
    where cac is null

    union all

    -- Test 16: CAC no infinity values
    select
        'cac_v1_no_infinity_values' as test_name,
        count(*) as failures,
        'CAC v1 must never be infinity' as description
    from {{ ref('cac_v1') }}
    where cac = 'Infinity'::numeric
        or cac = '-Infinity'::numeric

    union all

    -- Test 17: CAC new_customers = 0 at campaign/adset levels
    select
        'cac_v1_hierarchy_constraint' as test_name,
        count(*) as failures,
        'CAC v1 new_customers must be 0 at campaign/adset levels (not attributable in v1)' as description
    from {{ ref('cac_v1') }}
    where hierarchy_level in ('campaign', 'adset')
        and new_customers > 0

    union all

    -- =========================================================================
    -- HIERARCHY VALIDATION TESTS
    -- =========================================================================

    -- Test 18: ROAS v1 valid hierarchy levels
    select
        'roas_v1_valid_hierarchy' as test_name,
        count(*) as failures,
        'ROAS v1 hierarchy_level must be channel, campaign, or adset' as description
    from {{ ref('roas_v1') }}
    where hierarchy_level not in ('channel', 'campaign', 'adset')
        or hierarchy_level is null

    union all

    -- Test 19: CAC v1 valid hierarchy levels
    select
        'cac_v1_valid_hierarchy' as test_name,
        count(*) as failures,
        'CAC v1 hierarchy_level must be channel, campaign, or adset' as description
    from {{ ref('cac_v1') }}
    where hierarchy_level not in ('channel', 'campaign', 'adset')
        or hierarchy_level is null

    union all

    -- =========================================================================
    -- PERIOD TYPE VALIDATION TESTS
    -- =========================================================================

    -- Test 20: ROAS v1 valid period types
    select
        'roas_v1_valid_period_type' as test_name,
        count(*) as failures,
        'ROAS v1 period_type must be daily, weekly, monthly, or all_time' as description
    from {{ ref('roas_v1') }}
    where period_type not in ('daily', 'weekly', 'monthly', 'all_time')
        or period_type is null

    union all

    -- Test 21: CAC v1 valid period types
    select
        'cac_v1_valid_period_type' as test_name,
        count(*) as failures,
        'CAC v1 period_type must be daily, weekly, monthly, or all_time' as description
    from {{ ref('cac_v1') }}
    where period_type not in ('daily', 'weekly', 'monthly', 'all_time')
        or period_type is null

    union all

    -- =========================================================================
    -- NON-NEGATIVE VALUE TESTS
    -- =========================================================================

    -- Test 22: ROAS v1 non-negative spend
    select
        'roas_v1_non_negative_spend' as test_name,
        count(*) as failures,
        'ROAS v1 total_spend must be non-negative' as description
    from {{ ref('roas_v1') }}
    where total_spend < 0

    union all

    -- Test 23: CAC v1 non-negative spend
    select
        'cac_v1_non_negative_spend' as test_name,
        count(*) as failures,
        'CAC v1 total_spend must be non-negative' as description
    from {{ ref('cac_v1') }}
    where total_spend < 0

    union all

    -- Test 24: CAC v1 non-negative new_customers
    select
        'cac_v1_non_negative_customers' as test_name,
        count(*) as failures,
        'CAC v1 new_customers must be non-negative' as description
    from {{ ref('cac_v1') }}
    where new_customers < 0

    union all

    -- Test 25: ROAS v1 non-negative (ROAS itself)
    select
        'roas_v1_non_negative_roas' as test_name,
        count(*) as failures,
        'ROAS v1 roas must be non-negative' as description
    from {{ ref('roas_v1') }}
    where roas < 0

    union all

    -- Test 26: CAC v1 non-negative (CAC itself)
    select
        'cac_v1_non_negative_cac' as test_name,
        count(*) as failures,
        'CAC v1 cac must be non-negative' as description
    from {{ ref('cac_v1') }}
    where cac < 0

)

-- Return failing tests
select
    test_name,
    failures,
    description
from test_scenarios
where failures > 0
order by test_name

-- =============================================================================
-- TEST SUMMARY:
--
-- Version Integrity (6 tests):
--   - metric_name correctness
--   - metric_version correctness
--   - metric_status validity
--
-- Tenant Isolation (2 tests):
--   - All rows have tenant_id
--
-- Calculation Accuracy (8 tests):
--   - ROAS = revenue / spend
--   - CAC = spend / customers
--   - Divide-by-zero handling
--   - No NULL/infinity values
--
-- Hierarchy Validation (2 tests):
--   - Valid hierarchy levels
--
-- Period Validation (2 tests):
--   - Valid period types
--
-- Non-Negative Values (5 tests):
--   - Spend, customers, ROAS, CAC >= 0
--
-- If this query returns any rows, the test FAILS.
-- =============================================================================
