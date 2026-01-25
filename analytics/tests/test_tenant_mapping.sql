-- Test: Verify tenant mapping is configured correctly
--
-- This test detects if multiple tenants have active Shopify connections,
-- which would cause data leakage with the current `limit 1` approach.
--
-- If this test fails, you MUST configure proper tenant mapping in staging models.

with tenant_count as (
    select
        count(distinct tenant_id) as active_shopify_tenant_count
    from {{ ref('_tenant_airbyte_connections') }}
    where source_type = 'shopify'
        and status = 'active'
        and is_enabled = true
)

-- Returns rows only when there's a problem (count != 1)
-- Expected: Exactly 1 tenant (for single-connection setup)
-- If count > 1: You must configure connection-specific tenant mapping
-- If count = 0: No active Shopify connections configured
select active_shopify_tenant_count
from tenant_count
where active_shopify_tenant_count != 1
