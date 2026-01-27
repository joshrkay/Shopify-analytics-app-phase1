-- Test: Verify generate_internal_id macro produces deterministic, non-null results
--
-- This test validates:
-- 1. Same inputs produce identical outputs (determinism)
-- 2. Different inputs produce different outputs (uniqueness)
-- 3. NULL inputs return NULL (null safety)
-- 4. Output format is valid MD5 (32 hex characters)
--
-- Returns rows only when test fails (any assertion is false)

with test_cases as (
    select
        -- Test case 1: Basic functionality
        {{ generate_internal_id("'tenant_123'", "'meta_ads'", "'act_456'") }} as result_1a,
        {{ generate_internal_id("'tenant_123'", "'meta_ads'", "'act_456'") }} as result_1b,

        -- Test case 2: Different tenant produces different ID
        {{ generate_internal_id("'tenant_999'", "'meta_ads'", "'act_456'") }} as result_2,

        -- Test case 3: Different source produces different ID
        {{ generate_internal_id("'tenant_123'", "'google_ads'", "'act_456'") }} as result_3,

        -- Test case 4: Different platform_id produces different ID
        {{ generate_internal_id("'tenant_123'", "'meta_ads'", "'act_789'") }} as result_4,

        -- Test case 5: NULL tenant_id returns NULL
        {{ generate_internal_id("null", "'meta_ads'", "'act_456'") }} as result_null_tenant,

        -- Test case 6: NULL source returns NULL
        {{ generate_internal_id("'tenant_123'", "null", "'act_456'") }} as result_null_source,

        -- Test case 7: NULL platform_id returns NULL
        {{ generate_internal_id("'tenant_123'", "'meta_ads'", "null") }} as result_null_platform
),

assertions as (
    select
        -- Assertion 1: Determinism - same inputs produce same output
        case when result_1a = result_1b then 'PASS' else 'FAIL: Not deterministic' end as test_determinism,

        -- Assertion 2: Result is not null for valid inputs
        case when result_1a is not null then 'PASS' else 'FAIL: Result is null for valid inputs' end as test_not_null,

        -- Assertion 3: Different tenant produces different ID
        case when result_1a != result_2 then 'PASS' else 'FAIL: Different tenant same ID' end as test_tenant_diff,

        -- Assertion 4: Different source produces different ID
        case when result_1a != result_3 then 'PASS' else 'FAIL: Different source same ID' end as test_source_diff,

        -- Assertion 5: Different platform_id produces different ID
        case when result_1a != result_4 then 'PASS' else 'FAIL: Different platform_id same ID' end as test_platform_diff,

        -- Assertion 6: NULL tenant returns NULL
        case when result_null_tenant is null then 'PASS' else 'FAIL: NULL tenant should return NULL' end as test_null_tenant,

        -- Assertion 7: NULL source returns NULL
        case when result_null_source is null then 'PASS' else 'FAIL: NULL source should return NULL' end as test_null_source,

        -- Assertion 8: NULL platform_id returns NULL
        case when result_null_platform is null then 'PASS' else 'FAIL: NULL platform should return NULL' end as test_null_platform,

        -- Assertion 9: Valid MD5 format (32 hex characters)
        case when length(result_1a) = 32 and result_1a ~ '^[a-f0-9]+$' then 'PASS' else 'FAIL: Invalid MD5 format' end as test_md5_format
    from test_cases
)

-- Return failing assertions only
select *
from assertions
where test_determinism != 'PASS'
   or test_not_null != 'PASS'
   or test_tenant_diff != 'PASS'
   or test_source_diff != 'PASS'
   or test_platform_diff != 'PASS'
   or test_null_tenant != 'PASS'
   or test_null_source != 'PASS'
   or test_null_platform != 'PASS'
   or test_md5_format != 'PASS'
