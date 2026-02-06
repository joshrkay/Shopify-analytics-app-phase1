{#
    Test: Dataset Sync Compatibility (Story 5.2)

    Singular dbt test that validates no exposed column has been removed from
    semantic views. Each CTE selects only columns with meta.superset_expose: true.
    If a column was removed from a model, this query fails at compile/run.

    Run: dbt test --select test_dataset_sync_compatibility
#}

-- sem_orders_v1: exposed columns per schema.yml
select
    tenant_id,
    order_id,
    order_name,
    customer_key,
    source_platform,
    order_created_at,
    date,
    revenue_gross,
    revenue_net,
    currency
from {{ ref('sem_orders_v1') }}
where false

union all

-- sem_marketing_spend_v1: exposed columns per schema.yml
select
    tenant_id,
    date,
    source_platform,
    channel,
    ad_account_id,
    campaign_id,
    adset_id,
    ad_id,
    spend,
    currency,
    impressions,
    clicks,
    conversions,
    conversion_value,
    cpm,
    cpc,
    ctr,
    cpa,
    roas
from {{ ref('sem_marketing_spend_v1') }}
where false

union all

-- sem_campaign_performance_v1: exposed columns per schema.yml
select
    tenant_id,
    date,
    source_platform,
    channel,
    ad_account_id,
    campaign_id,
    campaign_name,
    spend,
    impressions,
    clicks,
    conversions,
    ctr,
    cpc,
    cpa,
    currency
from {{ ref('sem_campaign_performance_v1') }}
where false
