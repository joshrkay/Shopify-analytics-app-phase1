-- Regression test: Tenant Isolation
-- 
-- This test verifies that staging models properly filter by tenant_id
-- and that no cross-tenant data leakage occurs.
--
-- CRITICAL: This test must pass to prove security compliance.

-- Test 1: Verify all orders have tenant_id
select count(*) as orders_without_tenant
from {{ ref('stg_shopify_orders') }}
where tenant_id is null

-- Test 2: Verify all customers have tenant_id
select count(*) as customers_without_tenant
from {{ ref('stg_shopify_customers') }}
where tenant_id is null

-- Test 3: Verify tenant_id exists in tenant_airbyte_connections
-- This ensures tenant_id values are valid and not arbitrary
select distinct o.tenant_id as invalid_tenant_id
from {{ ref('stg_shopify_orders') }} o
left join {{ ref('_tenant_airbyte_connections') }} t
    on o.tenant_id = t.tenant_id
where o.tenant_id is not null
    and t.tenant_id is null

-- Test 4: Verify no duplicate order_ids across different tenants
-- This would indicate data leakage if the same order appears for multiple tenants
select 
    order_id,
    count(distinct tenant_id) as tenant_count
from {{ ref('stg_shopify_orders') }}
group by order_id
having count(distinct tenant_id) > 1

-- Test 5: Verify no duplicate ad records across different tenants (Meta Ads)
-- Composite key: ad_account_id, campaign_id, date
select 
    ad_account_id,
    campaign_id,
    date,
    count(distinct tenant_id) as tenant_count
from {{ ref('stg_meta_ads') }}
group by ad_account_id, campaign_id, date
having count(distinct tenant_id) > 1

-- Test 6: Verify no duplicate ad records across different tenants (Google Ads)
-- Composite key: ad_account_id, campaign_id, date
select 
    ad_account_id,
    campaign_id,
    date,
    count(distinct tenant_id) as tenant_count
from {{ ref('stg_google_ads') }}
group by ad_account_id, campaign_id, date
having count(distinct tenant_id) > 1
