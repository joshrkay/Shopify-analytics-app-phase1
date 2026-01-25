-- Regression test: Tenant Isolation
-- 
-- This test verifies that staging models properly filter by tenant_id
-- and that no cross-tenant data leakage occurs.
--
-- CRITICAL: This test must pass to prove security compliance.
-- Returns rows only when violations are found (test fails if any rows returned)

with violations as (
    -- Test 1: Verify all orders have tenant_id
    select 
        'orders_without_tenant' as violation_type,
        count(*)::text as violation_count
    from {{ ref('stg_shopify_orders') }}
    where tenant_id is null
    having count(*) > 0
    
    union all
    
    -- Test 2: Verify all customers have tenant_id
    select 
        'customers_without_tenant' as violation_type,
        count(*)::text as violation_count
    from {{ ref('stg_shopify_customers') }}
    where tenant_id is null
    having count(*) > 0
    
    union all
    
    -- Test 3: Verify tenant_id exists in tenant_airbyte_connections
    -- This ensures tenant_id values are valid and not arbitrary
    select 
        'invalid_tenant_id_in_orders' as violation_type,
        string_agg(distinct o.tenant_id::text, ', ' order by o.tenant_id) as violation_count
    from {{ ref('stg_shopify_orders') }} o
    left join {{ ref('_tenant_airbyte_connections') }} t
        on o.tenant_id = t.tenant_id
    where o.tenant_id is not null
        and t.tenant_id is null
    group by 1
    having count(*) > 0
    
    union all
    
    -- Test 4: Verify no duplicate order_ids across different tenants
    -- This would indicate data leakage if the same order appears for multiple tenants
    select 
        'duplicate_order_ids_across_tenants' as violation_type,
        string_agg(distinct order_id::text, ', ' order by order_id) as violation_count
    from (
        select 
            order_id,
            count(distinct tenant_id) as tenant_count
        from {{ ref('stg_shopify_orders') }}
        group by order_id
        having count(distinct tenant_id) > 1
    ) duplicates
    group by 1
    
    union all
    
    -- Test 5: Verify no duplicate ad records across different tenants (Meta Ads)
    -- Composite key: ad_account_id, campaign_id, date
    select 
        'duplicate_meta_ads_across_tenants' as violation_type,
        string_agg((ad_account_id || '|' || campaign_id || '|' || date::text), ', ' 
                   order by ad_account_id, campaign_id, date) as violation_count
    from (
        select distinct
            ad_account_id,
            campaign_id,
            date
        from {{ ref('stg_meta_ads') }}
        where (ad_account_id, campaign_id, date) in (
            select ad_account_id, campaign_id, date
            from {{ ref('stg_meta_ads') }}
            group by ad_account_id, campaign_id, date
            having count(distinct tenant_id) > 1
        )
    ) duplicates
    group by 1
    
    union all
    
    -- Test 6: Verify no duplicate ad records across different tenants (Google Ads)
    -- Composite key: ad_account_id, campaign_id, date
    select 
        'duplicate_google_ads_across_tenants' as violation_type,
        string_agg((ad_account_id || '|' || campaign_id || '|' || date::text), ', ' 
                   order by ad_account_id, campaign_id, date) as violation_count
    from (
        select distinct
            ad_account_id,
            campaign_id,
            date
        from {{ ref('stg_google_ads') }}
        where (ad_account_id, campaign_id, date) in (
            select ad_account_id, campaign_id, date
            from {{ ref('stg_google_ads') }}
            group by ad_account_id, campaign_id, date
            having count(distinct tenant_id) > 1
        )
    ) duplicates
    group by 1
)

select 
    violation_type,
    violation_count
from violations
