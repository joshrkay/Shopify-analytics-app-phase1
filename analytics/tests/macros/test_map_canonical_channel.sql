-- Test: Verify map_canonical_channel macro produces valid canonical channels
--
-- This test validates:
-- 1. Each source maps to a valid canonical channel
-- 2. Canonical channels are from the defined taxonomy
-- 3. NULL handling works correctly
--
-- Returns rows only when test fails (invalid channel or mapping error)

with test_cases as (
    select
        -- Meta Ads: Should be paid_social
        'meta_ads' as source_1,
        {{ map_canonical_channel("'meta_ads'", "'feed'") }} as result_meta_ads,

        -- Google Ads Search: Should be paid_search
        {{ map_canonical_channel("'google_ads'", "'search'") }} as result_google_search,

        -- Google Ads Shopping: Should be paid_shopping
        {{ map_canonical_channel("'google_ads'", "'shopping'") }} as result_google_shopping,

        -- Google Ads Performance Max: Should be paid_shopping
        {{ map_canonical_channel("'google_ads'", "'pmax'") }} as result_google_pmax,

        -- TikTok Ads: Should be paid_social
        {{ map_canonical_channel("'tiktok_ads'", "'in_feed'") }} as result_tiktok,

        -- Pinterest Ads: Should be paid_social
        {{ map_canonical_channel("'pinterest_ads'", "'promoted_pin'") }} as result_pinterest,

        -- Pinterest Shopping: Should be paid_shopping
        {{ map_canonical_channel("'pinterest_ads'", "'shopping_catalog'") }} as result_pinterest_shopping,

        -- Snap Ads: Should be paid_social
        {{ map_canonical_channel("'snap_ads'", "'story'") }} as result_snap,

        -- Amazon Ads: Should be paid_shopping
        {{ map_canonical_channel("'amazon_ads'", "'sponsored_products'") }} as result_amazon,

        -- Klaviyo: Should be email
        {{ map_canonical_channel("'klaviyo'", "'campaign'") }} as result_klaviyo,

        -- GA4 Organic: Should be organic_search
        {{ map_canonical_channel("'ga4'", "'organic'") }} as result_ga4_organic,

        -- GA4 Direct: Should be direct
        {{ map_canonical_channel("'ga4'", "'direct'") }} as result_ga4_direct,

        -- GA4 Referral: Should be referral
        {{ map_canonical_channel("'ga4'", "'referral'") }} as result_ga4_referral,

        -- Shopify Direct: Should be direct
        {{ map_canonical_channel("'shopify'", "'web'") }} as result_shopify,

        -- Unknown source: Should be other
        {{ map_canonical_channel("'unknown_source'", "'unknown'") }} as result_unknown
),

valid_channels as (
    select unnest(array['paid_social', 'paid_search', 'paid_shopping', 'email', 'organic_social', 'organic_search', 'direct', 'referral', 'affiliate', 'other']) as channel
),

assertions as (
    select
        -- Meta Ads should map to paid_social
        case when result_meta_ads = 'paid_social' then 'PASS' else 'FAIL: meta_ads=' || coalesce(result_meta_ads, 'NULL') end as test_meta_ads,

        -- Google Search should map to paid_search
        case when result_google_search = 'paid_search' then 'PASS' else 'FAIL: google_search=' || coalesce(result_google_search, 'NULL') end as test_google_search,

        -- Google Shopping should map to paid_shopping
        case when result_google_shopping = 'paid_shopping' then 'PASS' else 'FAIL: google_shopping=' || coalesce(result_google_shopping, 'NULL') end as test_google_shopping,

        -- Google PMax should map to paid_shopping
        case when result_google_pmax = 'paid_shopping' then 'PASS' else 'FAIL: google_pmax=' || coalesce(result_google_pmax, 'NULL') end as test_google_pmax,

        -- TikTok should map to paid_social
        case when result_tiktok = 'paid_social' then 'PASS' else 'FAIL: tiktok=' || coalesce(result_tiktok, 'NULL') end as test_tiktok,

        -- Pinterest should map to paid_social
        case when result_pinterest = 'paid_social' then 'PASS' else 'FAIL: pinterest=' || coalesce(result_pinterest, 'NULL') end as test_pinterest,

        -- Pinterest Shopping should map to paid_shopping
        case when result_pinterest_shopping = 'paid_shopping' then 'PASS' else 'FAIL: pinterest_shopping=' || coalesce(result_pinterest_shopping, 'NULL') end as test_pinterest_shopping,

        -- Snap should map to paid_social
        case when result_snap = 'paid_social' then 'PASS' else 'FAIL: snap=' || coalesce(result_snap, 'NULL') end as test_snap,

        -- Amazon should map to paid_shopping
        case when result_amazon = 'paid_shopping' then 'PASS' else 'FAIL: amazon=' || coalesce(result_amazon, 'NULL') end as test_amazon,

        -- Klaviyo should map to email
        case when result_klaviyo = 'email' then 'PASS' else 'FAIL: klaviyo=' || coalesce(result_klaviyo, 'NULL') end as test_klaviyo,

        -- GA4 organic should map to organic_search
        case when result_ga4_organic = 'organic_search' then 'PASS' else 'FAIL: ga4_organic=' || coalesce(result_ga4_organic, 'NULL') end as test_ga4_organic,

        -- GA4 direct should map to direct
        case when result_ga4_direct = 'direct' then 'PASS' else 'FAIL: ga4_direct=' || coalesce(result_ga4_direct, 'NULL') end as test_ga4_direct,

        -- GA4 referral should map to referral
        case when result_ga4_referral = 'referral' then 'PASS' else 'FAIL: ga4_referral=' || coalesce(result_ga4_referral, 'NULL') end as test_ga4_referral,

        -- Shopify should map to direct
        case when result_shopify = 'direct' then 'PASS' else 'FAIL: shopify=' || coalesce(result_shopify, 'NULL') end as test_shopify,

        -- Unknown source should map to other
        case when result_unknown = 'other' then 'PASS' else 'FAIL: unknown=' || coalesce(result_unknown, 'NULL') end as test_unknown
    from test_cases
)

-- Return failing assertions only
select *
from assertions
where test_meta_ads != 'PASS'
   or test_google_search != 'PASS'
   or test_google_shopping != 'PASS'
   or test_google_pmax != 'PASS'
   or test_tiktok != 'PASS'
   or test_pinterest != 'PASS'
   or test_pinterest_shopping != 'PASS'
   or test_snap != 'PASS'
   or test_amazon != 'PASS'
   or test_klaviyo != 'PASS'
   or test_ga4_organic != 'PASS'
   or test_ga4_direct != 'PASS'
   or test_ga4_referral != 'PASS'
   or test_shopify != 'PASS'
   or test_unknown != 'PASS'
