{{
    config(
        materialized='incremental',
        unique_key='id',
        schema='analytics',
        incremental_strategy='delete+insert',
        on_schema_change='append_new_columns'
    )
}}

{#
    Canonical fact table for campaign performance (v1).

    Includes both attributed revenue and spend for ROAS calculation.
    Part of hybrid revenue truth policy: attributed revenue (from ad platforms)
    lives here, actual revenue (Shopify) lives in fact_orders_v1.

    Rolling Rebuild:
    - Default window: 30 days (configurable via var('ads_rebuild_days'))
    - Filters on business date (campaign_date), not ingestion timestamp
    - Catches late conversions, attribution window updates, and platform corrections
    - Rows outside the window remain unchanged

    Grain: One row per tenant + source_system + campaign + ad_set + date.

    SECURITY: All rows are tenant-isolated via tenant_id.
#}

with meta_ads as (
    select
        source_system,
        source_primary_key,
        tenant_id,
        date as campaign_date,
        canonical_channel as channel,
        campaign_id,
        campaign_name,
        adset_id as ad_set_id,
        conversion_value as attributed_revenue,
        spend,
        conversions,
        impressions,
        clicks,
        currency,
        airbyte_emitted_at
    from {{ ref('stg_facebook_ads_performance') }}
    where tenant_id is not null
        and campaign_id is not null
        and date is not null
    {% if is_incremental() %}
        and date >= current_date - {{ var('ads_rebuild_days', 30) }}
    {% endif %}
),

google_ads as (
    select
        source_system,
        source_primary_key,
        tenant_id,
        date as campaign_date,
        canonical_channel as channel,
        campaign_id,
        campaign_name,
        ad_group_id as ad_set_id,
        conversion_value as attributed_revenue,
        spend,
        conversions,
        impressions,
        clicks,
        currency,
        airbyte_emitted_at
    from {{ ref('stg_google_ads_performance') }}
    where tenant_id is not null
        and campaign_id is not null
        and date is not null
    {% if is_incremental() %}
        and date >= current_date - {{ var('ads_rebuild_days', 30) }}
    {% endif %}
),

tiktok_ads as (
    select
        source_system,
        source_primary_key,
        tenant_id,
        date as campaign_date,
        canonical_channel as channel,
        campaign_id,
        campaign_name,
        adgroup_id as ad_set_id,
        conversion_value as attributed_revenue,
        spend,
        conversions,
        impressions,
        clicks,
        currency,
        airbyte_emitted_at
    from {{ ref('stg_tiktok_ads_performance') }}
    where tenant_id is not null
        and campaign_id is not null
        and date is not null
    {% if is_incremental() %}
        and date >= current_date - {{ var('ads_rebuild_days', 30) }}
    {% endif %}
),

snapchat_ads as (
    select
        'snapchat_ads' as source_system,
        concat(
            ad_account_id, '|', campaign_id, '|',
            coalesce(ad_squad_id, ''), '|', date::text
        ) as source_primary_key,
        tenant_id,
        date as campaign_date,
        canonical_channel as channel,
        campaign_id,
        campaign_name,
        ad_squad_id as ad_set_id,
        conversion_value as attributed_revenue,
        spend,
        conversions,
        impressions,
        clicks,
        currency,
        airbyte_emitted_at
    from {{ ref('stg_snapchat_ads') }}
    where tenant_id is not null
        and campaign_id is not null
        and date is not null
    {% if is_incremental() %}
        and date >= current_date - {{ var('ads_rebuild_days', 30) }}
    {% endif %}
),

unified_performance as (
    select * from meta_ads
    union all
    select * from google_ads
    union all
    select * from tiktok_ads
    union all
    select * from snapchat_ads
)

select
    -- Primary key (campaign + ad_set level, not ad level)
    md5(concat(
        tenant_id, '|', source_system, '|',
        campaign_id, '|', coalesce(ad_set_id, ''), '|',
        campaign_date::text
    )) as id,

    -- Tenant isolation
    tenant_id,

    -- Dimensions
    campaign_date,
    channel,
    campaign_id,
    campaign_name,
    ad_set_id,

    -- Attributed revenue (from ad platforms, for ROAS calculation)
    attributed_revenue,

    -- Spend and performance
    spend,
    conversions,
    impressions,
    clicks,
    currency,

    -- Timestamps
    airbyte_emitted_at as updated_at,

    -- Record lineage
    source_system,
    source_primary_key,

    -- Audit
    current_timestamp as dbt_updated_at

from unified_performance
