-- =============================================================================
-- Test: CAC Metric Accuracy and Divide-by-Zero Handling
-- Model: fct_marketing_metrics (v1)
-- =============================================================================
--
-- This test validates:
-- 1. CAC calculation accuracy: CAC = SUM(spend) / COUNT(new_customers)
-- 2. Divide-by-zero handling: CAC = 0 when new_customers = 0
-- 3. No NULL CAC values
-- 4. No infinite CAC values
-- 5. CAC non-negative
-- 6. New customers count validity
-- 7. Tenant isolation
--
-- If this query returns any rows, the test FAILS.
-- =============================================================================

with test_scenarios as (

    -- =========================================================================
    -- TEST 1: CAC Calculation Accuracy
    -- Verify CAC matches the formula: total_spend / new_customers
    -- Allow tolerance of 0.01 for rounding
    -- CAC only meaningful at channel hierarchy_level
    -- =========================================================================
    select
        'cac_calculation_accuracy' as test_name,
        count(*) as failures,
        'CAC should equal total_spend / new_customers (tolerance: 0.01)' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and hierarchy_level = 'channel'  -- CAC only valid at channel level
        and new_customers > 0
        and abs(cac - (total_spend / new_customers)) > 0.01

    union all

    -- =========================================================================
    -- TEST 2: Divide-by-Zero Handling - CAC = 0 when new_customers = 0
    -- =========================================================================
    select
        'cac_zero_customers_returns_zero' as test_name,
        count(*) as failures,
        'CAC must be 0 when new_customers = 0 (divide-by-zero handling)' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and new_customers = 0
        and cac != 0

    union all

    -- =========================================================================
    -- TEST 3: No NULL CAC values
    -- =========================================================================
    select
        'cac_no_null_values' as test_name,
        count(*) as failures,
        'CAC should never be NULL' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and cac is null

    union all

    -- =========================================================================
    -- TEST 4: No Infinite CAC values
    -- =========================================================================
    select
        'cac_no_infinite_values' as test_name,
        count(*) as failures,
        'CAC should never be infinity' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and (cac = 'Infinity'::numeric or cac = '-Infinity'::numeric)

    union all

    -- =========================================================================
    -- TEST 5: CAC Non-Negative
    -- CAC should never be negative (spend and customers are both positive)
    -- =========================================================================
    select
        'cac_non_negative' as test_name,
        count(*) as failures,
        'CAC must be non-negative' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and cac < 0

    union all

    -- =========================================================================
    -- TEST 6: New Customers Count Non-Negative
    -- =========================================================================
    select
        'cac_new_customers_non_negative' as test_name,
        count(*) as failures,
        'New customers count must be non-negative' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and new_customers < 0

    union all

    -- =========================================================================
    -- TEST 7: Tenant Isolation - All rows have tenant_id
    -- =========================================================================
    select
        'cac_tenant_isolation' as test_name,
        count(*) as failures,
        'All CAC records must have tenant_id (tenant isolation)' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and tenant_id is null

    union all

    -- =========================================================================
    -- TEST 8: Valid Period Type
    -- =========================================================================
    select
        'cac_valid_period_type' as test_name,
        count(*) as failures,
        'Period type must be daily, weekly, monthly, or all_time' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and period_type not in ('daily', 'weekly', 'monthly', 'all_time')

    union all

    -- =========================================================================
    -- TEST 9: CAC only populated at channel level
    -- Below channel level, new_customers should be 0 (not attributable)
    -- =========================================================================
    select
        'cac_only_at_channel_level' as test_name,
        count(*) as failures,
        'New customers should be 0 at campaign/adset levels (not attributable)' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and hierarchy_level in ('campaign', 'adset')
        and new_customers > 0

    union all

    -- =========================================================================
    -- TEST 10: Metric Version Present
    -- =========================================================================
    select
        'cac_metric_version_present' as test_name,
        count(*) as failures,
        'All records must have metric_version = v1' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version is null or metric_version != 'v1'

    union all

    -- =========================================================================
    -- TEST 11: New customers count is integer (no fractional customers)
    -- =========================================================================
    select
        'cac_new_customers_integer' as test_name,
        count(*) as failures,
        'New customers count must be a whole number' as description
    from {{ ref('fct_marketing_metrics') }}
    where metric_version = 'v1'
        and new_customers != floor(new_customers)

    union all

    -- =========================================================================
    -- TEST 12: Spend non-negative (for CAC calculation validity)
    -- =========================================================================
    select
        'cac_spend_non_negative' as test_name,
        count(*) as failures,
        'Total spend must be non-negative for CAC calculation' as description
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
