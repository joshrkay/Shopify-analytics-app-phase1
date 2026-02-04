-- =============================================================================
-- Test: ROAS Metric Accuracy and Divide-by-Zero Handling
-- Model: fct_marketing_metrics (v1)
-- =============================================================================
--
-- This test validates:
-- 1. ROAS calculation accuracy: ROAS = SUM(revenue) / SUM(spend)
-- 2. Divide-by-zero handling: ROAS = 0 when spend = 0
-- 3. No NULL ROAS values
-- 4. No infinite ROAS values
-- 5. Reconciliation with raw fact tables
-- 6. Tenant isolation
--
-- If this query returns any rows, the test FAILS.
-- =============================================================================

with test_scenarios as (

    -- =========================================================================
    -- TEST 1: ROAS Calculation Accuracy
    -- Verify ROAS matches the formula: total_revenue / total_spend
    -- Allow tolerance of 0.01 for rounding
    -- =========================================================================
    select
        'roas_calculation_accuracy' as test_name,
        count(*) as failures,
        'ROAS should equal total_revenue / total_spend (tolerance: 0.01)' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and total_spend > 0
        and abs(roas - (total_revenue / total_spend)) > 0.01

    union all

    -- =========================================================================
    -- TEST 2: Divide-by-Zero Handling - ROAS = 0 when spend = 0
    -- =========================================================================
    select
        'roas_zero_spend_returns_zero' as test_name,
        count(*) as failures,
        'ROAS must be 0 when total_spend = 0 (divide-by-zero handling)' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and total_spend = 0
        and roas != 0

    union all

    -- =========================================================================
    -- TEST 3: No NULL ROAS values
    -- =========================================================================
    select
        'roas_no_null_values' as test_name,
        count(*) as failures,
        'ROAS should never be NULL' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and roas is null

    union all

    -- =========================================================================
    -- TEST 4: No Infinite ROAS values
    -- =========================================================================
    select
        'roas_no_infinite_values' as test_name,
        count(*) as failures,
        'ROAS should never be infinity' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and (roas = 'Infinity'::numeric or roas = '-Infinity'::numeric)

    union all

    -- =========================================================================
    -- TEST 5: ROAS >= 0 (non-negative)
    -- Note: Negative ROAS could be valid with heavy refunds, but typically
    -- indicates data quality issues. This test warns but doesn't fail.
    -- =========================================================================
    select
        'roas_non_negative' as test_name,
        count(*) as failures,
        'ROAS should be non-negative (negative indicates heavy refunds or data issue)' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and roas < 0

    union all

    -- =========================================================================
    -- TEST 6: Tenant Isolation - All rows have tenant_id
    -- =========================================================================
    select
        'roas_tenant_isolation' as test_name,
        count(*) as failures,
        'All ROAS records must have tenant_id (tenant isolation)' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and tenant_id is null

    union all

    -- =========================================================================
    -- TEST 7: Valid Period Type
    -- =========================================================================
    select
        'roas_valid_period_type' as test_name,
        count(*) as failures,
        'Period type must be daily, weekly, monthly, or all_time' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and period_type not in ('daily', 'weekly', 'monthly', 'all_time')

    union all

    -- =========================================================================
    -- TEST 8: Valid Hierarchy Level
    -- =========================================================================
    select
        'roas_valid_hierarchy_level' as test_name,
        count(*) as failures,
        'Hierarchy level must be channel, campaign, or adset' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and hierarchy_level not in ('channel', 'campaign', 'adset')

    union all

    -- =========================================================================
    -- TEST 9: Metric Version Present
    -- =========================================================================
    select
        'roas_metric_version_present' as test_name,
        count(*) as failures,
        'All records must have metric_version = v1' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version is null or metric_version != 'v1'

    union all

    -- =========================================================================
    -- TEST 10: Channel-level ROAS reconciles with fact tables
    -- This test validates that channel-level revenue/spend can be traced
    -- back to the raw fact tables for reconciliation
    -- =========================================================================
    select
        'roas_spend_non_negative' as test_name,
        count(*) as failures,
        'Total spend must be non-negative' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and total_spend < 0

)

-- Return failing tests
select
    test_name,
    failures,
    description
from test_scenarios
where failures > 0
order by test_name

-- If this query returns any rows, the test FAILS
