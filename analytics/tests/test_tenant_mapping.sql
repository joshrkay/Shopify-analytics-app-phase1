-- Test: Verify tenant mapping is configured correctly
-- 
-- This test detects if multiple tenants have active Shopify connections,
-- which would cause data leakage with the current `limit 1` approach.
--
-- If this test fails, you MUST configure proper tenant mapping in staging models.
-- Returns rows only when tenant count is NOT exactly 1 (test fails if any rows returned)

with tenant_count as (
    select 
        count(distinct tenant_id) as active_shopify_tenant_count
    from {{ ref('_tenant_airbyte_connections') }}
    where source_type = 'shopify'
        and status = 'active'
        and is_enabled = true
)
select 
    active_shopify_tenant_count,
    case 
        when active_shopify_tenant_count = 0 then 'No active Shopify connections configured'
        when active_shopify_tenant_count > 1 then 'Multiple tenants detected - must configure connection-specific tenant mapping'
        else 'Unexpected tenant count'
    end as issue_description
from tenant_count
where active_shopify_tenant_count != 1  -- Fail if count is not exactly 1
