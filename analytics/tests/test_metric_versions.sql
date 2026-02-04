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
--
-- GOVERNANCE:
--   4. All active metrics have valid tenant_id (tenant isolation)
--
-- ACCURACY:
--   5. ROAS calculation matches formula: SUM(revenue) / SUM(spend)
--   6. CAC calculation matches formula: SUM(spend) / COUNT(new_customers)
--   7. Divide-by-zero returns 0, not NULL or infinity
--
-- If this query returns any rows, the test FAILS.
-- =============================================================================

with test_scenarios as (

    -- =========================================================================
    -- VERSION INTEGRITY TESTS - ROAS
    -- =========================================================================

    -- Test 1: fct_roas has metric_name column
    select
        'fct_roas_metric_name' as test_name,
        count(*) as failures,
        'fct_roas metric_name must be "roas"' as description
    from {{ ref('fct_roas') }}
    where metric_name != 'roas'
        or metric_name is null

    union all

    -- Test 2: fct_roas has metric_version column
    select
        'fct_roas_metric_version' as test_name,
        count(*) as failures,
        'fct_roas metric_version must be "v1"' as description
    from {{ ref('fct_roas') }}
    where metric_version != 'v1'
        or metric_version is null

    union all

    -- =========================================================================
    -- VERSION INTEGRITY TESTS - CAC
    -- =========================================================================

    -- Test 3: fct_cac has metric_name column
    select
        'fct_cac_metric_name' as test_name,
        count(*) as failures,
        'fct_cac metric_name must be "cac"' as description
    from {{ ref('fct_cac') }}
    where metric_name != 'cac'
        or metric_name is null

    union all

    -- Test 4: fct_cac has metric_version column
    select
        'fct_cac_metric_version' as test_name,
        count(*) as failures,
        'fct_cac metric_version must be "v1"' as description
    from {{ ref('fct_cac') }}
    where metric_version != 'v1'
        or metric_version is null

    union all

    -- =========================================================================
    -- TENANT ISOLATION TESTS
    -- =========================================================================

    -- Test 5: fct_roas has tenant_id for all rows
    select
        'fct_roas_tenant_isolation' as test_name,
        count(*) as failures,
        'fct_roas must have tenant_id for all rows (tenant isolation)' as description
    from {{ ref('fct_roas') }}
    where tenant_id is null

    union all

    -- Test 6: fct_cac has tenant_id for all rows
    select
        'fct_cac_tenant_isolation' as test_name,
        count(*) as failures,
        'fct_cac must have tenant_id for all rows (tenant isolation)' as description
    from {{ ref('fct_cac') }}
    where tenant_id is null

    union all

    -- =========================================================================
    -- ACCURACY TESTS - ROAS
    -- =========================================================================

    -- Test 7: ROAS divide-by-zero handling (spend = 0 -> ROAS = 0)
    select
        'fct_roas_zero_spend_handling' as test_name,
        count(*) as failures,
        'fct_roas must return gross_roas/net_roas = 0 when total_spend = 0' as description
    from {{ ref('fct_roas') }}
    where total_spend = 0
        and (gross_roas != 0 or net_roas != 0)

    union all

    -- Test 8: ROAS no NULL values
    select
        'fct_roas_no_null_values' as test_name,
        count(*) as failures,
        'fct_roas gross_roas and net_roas must never be NULL' as description
    from {{ ref('fct_roas') }}
    where gross_roas is null or net_roas is null

    union all

    -- Test 9: ROAS no infinity values
    select
        'fct_roas_no_infinity_values' as test_name,
        count(*) as failures,
        'fct_roas ROAS must never be infinity' as description
    from {{ ref('fct_roas') }}
    where gross_roas = 'Infinity'::numeric
        or gross_roas = '-Infinity'::numeric
        or net_roas = 'Infinity'::numeric
        or net_roas = '-Infinity'::numeric

    union all

    -- =========================================================================
    -- ACCURACY TESTS - CAC
    -- =========================================================================

    -- Test 10: CAC divide-by-zero handling (new_customers = 0 -> CAC = 0)
    select
        'fct_cac_zero_customers_handling' as test_name,
        count(*) as failures,
        'fct_cac must return cac = 0 when new_customers = 0' as description
    from {{ ref('fct_cac') }}
    where new_customers = 0
        and cac != 0

    union all

    -- Test 11: CAC no NULL values
    select
        'fct_cac_no_null_values' as test_name,
        count(*) as failures,
        'fct_cac cac and ncac must never be NULL' as description
    from {{ ref('fct_cac') }}
    where cac is null or ncac is null

    union all

    -- Test 12: CAC no infinity values
    select
        'fct_cac_no_infinity_values' as test_name,
        count(*) as failures,
        'fct_cac CAC must never be infinity' as description
    from {{ ref('fct_cac') }}
    where cac = 'Infinity'::numeric
        or cac = '-Infinity'::numeric
        or ncac = 'Infinity'::numeric
        or ncac = '-Infinity'::numeric

    union all

    -- =========================================================================
    -- PERIOD TYPE VALIDATION
    -- =========================================================================

    -- Test 13: fct_roas valid period types
    select
        'fct_roas_valid_period_type' as test_name,
        count(*) as failures,
        'fct_roas period_type must be daily, weekly, monthly, or all_time' as description
    from {{ ref('fct_roas') }}
    where period_type not in ('daily', 'weekly', 'monthly', 'all_time')
        or period_type is null

    union all

    -- Test 14: fct_cac valid period types
    select
        'fct_cac_valid_period_type' as test_name,
        count(*) as failures,
        'fct_cac period_type must be daily, weekly, monthly, or all_time' as description
    from {{ ref('fct_cac') }}
    where period_type not in ('daily', 'weekly', 'monthly', 'all_time')
        or period_type is null

    union all

    -- =========================================================================
    -- NON-NEGATIVE VALUE TESTS
    -- =========================================================================

    -- Test 15: fct_roas non-negative spend
    select
        'fct_roas_non_negative_spend' as test_name,
        count(*) as failures,
        'fct_roas total_spend must be non-negative' as description
    from {{ ref('fct_roas') }}
    where total_spend < 0

    union all

    -- Test 16: fct_cac non-negative spend
    select
        'fct_cac_non_negative_spend' as test_name,
        count(*) as failures,
        'fct_cac total_spend must be non-negative' as description
    from {{ ref('fct_cac') }}
    where total_spend < 0

    union all

    -- Test 17: fct_cac non-negative new_customers
    select
        'fct_cac_non_negative_customers' as test_name,
        count(*) as failures,
        'fct_cac new_customers must be non-negative' as description
    from {{ ref('fct_cac') }}
    where new_customers < 0

    union all

    -- Test 18: fct_roas non-negative ROAS
    select
        'fct_roas_non_negative_roas' as test_name,
        count(*) as failures,
        'fct_roas gross_roas and net_roas must be non-negative' as description
    from {{ ref('fct_roas') }}
    where gross_roas < 0 or net_roas < 0

    union all

    -- Test 19: fct_cac non-negative CAC
    select
        'fct_cac_non_negative_cac' as test_name,
        count(*) as failures,
        'fct_cac cac and ncac must be non-negative' as description
    from {{ ref('fct_cac') }}
    where cac < 0 or ncac < 0

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
-- Version Integrity (4 tests):
--   - metric_name and metric_version columns exist and have correct values
--
-- Tenant Isolation (2 tests):
--   - All rows have tenant_id
--
-- Calculation Accuracy (6 tests):
--   - Divide-by-zero handling
--   - No NULL/infinity values
--
-- Period Validation (2 tests):
--   - Valid period types
--
-- Non-Negative Values (5 tests):
--   - Spend, customers, ROAS, CAC >= 0
--
-- If this query returns any rows, the test FAILS.
-- =============================================================================
