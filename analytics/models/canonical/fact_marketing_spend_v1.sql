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
    Canonical fact table for marketing spend (v1).

    Source of truth for ad platform spend across Meta, Google, TikTok, and Snapchat.
    Focused on delivery metrics (spend, impressions, clicks).
    Business metrics (cpm, cpc, ctr, cpa, roas) are NOT computed here -
    they belong in the semantic/metrics layer.

    Rolling Rebuild:
    - Default window: 30 days (configurable via var('ads_rebuild_days'))
    - Filters on business date (spend_date), not ingestion timestamp
    - Catches late-arriving attribution updates and platform corrections
    - Rows outside the window remain unchanged

    Grain: One row per tenant + source_system + campaign + ad_set + ad + date.

    SECURITY: All rows are tenant-isolated via tenant_id.
#}

with meta_ads as (
    select
        source_system,
        source_primary_key,
        tenant_id,
        date as spend_date,
        canonical_channel as channel,
        campaign_id,
        adset_id as ad_set_id,
        ad_id,
        spend,
        impressions,
        clicks,
        currency,
        airbyte_emitted_at
    from {{ ref('stg_facebook_ads_performance') }}
    where tenant_id is not null
        and date is not null
        and spend is not null
    {% if is_incremental() %}
        and date >= current_date - {{ var('ads_rebuild_days', 30) }}
    {% endif %}
),

google_ads as (
    select
        source_system,
        source_primary_key,
        tenant_id,
        date as spend_date,
        canonical_channel as channel,
        campaign_id,
        ad_group_id as ad_set_id,
        ad_id,
        spend,
        impressions,
        clicks,
        currency,
        airbyte_emitted_at
    from {{ ref('stg_google_ads_performance') }}
    where tenant_id is not null
        and date is not null
        and spend is not null
    {% if is_incremental() %}
        and date >= current_date - {{ var('ads_rebuild_days', 30) }}
    {% endif %}
),

tiktok_ads as (
    select
        source_system,
        source_primary_key,
        tenant_id,
        date as spend_date,
        canonical_channel as channel,
        campaign_id,
        adgroup_id as ad_set_id,
        ad_id,
        spend,
        impressions,
        clicks,
        currency,
        airbyte_emitted_at
    from {{ ref('stg_tiktok_ads_performance') }}
    where tenant_id is not null
        and date is not null
        and spend is not null
    {% if is_incremental() %}
        and date >= current_date - {{ var('ads_rebuild_days', 30) }}
    {% endif %}
),

snapchat_ads as (
    select
        'snapchat_ads' as source_system,
        concat(
            ad_account_id, '|', campaign_id, '|',
            coalesce(ad_squad_id, ''), '|', coalesce(ad_id, ''), '|',
            date::text
        ) as source_primary_key,
        tenant_id,
        date as spend_date,
        canonical_channel as channel,
        campaign_id,
        ad_squad_id as ad_set_id,
        ad_id,
        spend,
        impressions,
        clicks,
        currency,
        airbyte_emitted_at
    from {{ ref('stg_snapchat_ads') }}
    where tenant_id is not null
        and date is not null
        and spend is not null
    {% if is_incremental() %}
        and date >= current_date - {{ var('ads_rebuild_days', 30) }}
    {% endif %}
),

unified_spend as (
    select * from meta_ads
    union all
    select * from google_ads
    union all
    select * from tiktok_ads
    union all
    select * from snapchat_ads
)

select
    -- Primary key
    md5(concat(
        tenant_id, '|', source_system, '|',
        campaign_id, '|', coalesce(ad_set_id, ''), '|',
        coalesce(ad_id, ''), '|', spend_date::text
    )) as id,

    -- Tenant isolation
    tenant_id,

    -- Dimensions
    spend_date,
    channel,
    campaign_id,
    ad_set_id,

    -- Metrics (delivery only - no derived business metrics)
    spend,
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

from unified_spend
