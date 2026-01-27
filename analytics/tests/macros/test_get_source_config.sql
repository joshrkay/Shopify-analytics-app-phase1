-- Test: Verify get_source_config macros return expected values
--
-- This test validates:
-- 1. get_lookback_days returns default value for unknown sources
-- 2. get_lookback_days returns configured value for known sources
-- 3. get_freshness_warn_hours returns expected defaults
-- 4. get_freshness_error_hours returns expected defaults
--
-- Returns rows only when test fails

with test_cases as (
    select
        -- Test lookback days
        {{ get_lookback_days('meta_ads') }} as lookback_meta_ads,
        {{ get_lookback_days('google_ads') }} as lookback_google_ads,
        {{ get_lookback_days('unknown_source') }} as lookback_unknown,

        -- Test freshness thresholds
        {{ get_freshness_warn_hours('shopify') }} as freshness_warn_shopify,
        {{ get_freshness_error_hours('shopify') }} as freshness_error_shopify
),

assertions as (
    select
        -- Lookback days should be 3 for configured sources
        case when lookback_meta_ads = 3 then 'PASS' else 'FAIL: meta_ads lookback=' || lookback_meta_ads::text end as test_lookback_meta,

        case when lookback_google_ads = 3 then 'PASS' else 'FAIL: google_ads lookback=' || lookback_google_ads::text end as test_lookback_google,

        -- Unknown source should get default (3)
        case when lookback_unknown = 3 then 'PASS' else 'FAIL: unknown lookback=' || lookback_unknown::text end as test_lookback_unknown,

        -- Freshness warn should be 24 hours by default
        case when freshness_warn_shopify = 24 then 'PASS' else 'FAIL: warn_hours=' || freshness_warn_shopify::text end as test_freshness_warn,

        -- Freshness error should be 48 hours by default
        case when freshness_error_shopify = 48 then 'PASS' else 'FAIL: error_hours=' || freshness_error_shopify::text end as test_freshness_error
    from test_cases
)

-- Return failing assertions only
select *
from assertions
where test_lookback_meta != 'PASS'
   or test_lookback_google != 'PASS'
   or test_lookback_unknown != 'PASS'
   or test_freshness_warn != 'PASS'
   or test_freshness_error != 'PASS'
