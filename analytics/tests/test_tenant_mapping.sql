-- Test: Verify tenant mapping doesn't have multiple active Shopify connections
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

-- Returns rows only when there's a problem (count > 1)
-- count = 0: OK - No active Shopify connections (e.g., CI environment)
-- count = 1: OK - Single tenant setup working correctly
-- count > 1: FAIL - Multiple tenants would cause data leakage
select active_shopify_tenant_count
from tenant_count
where active_shopify_tenant_count > 1
