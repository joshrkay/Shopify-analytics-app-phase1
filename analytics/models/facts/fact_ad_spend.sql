{{
    config(
        materialized='incremental',
        unique_key='id',
        schema='analytics',
        on_schema_change='append_new_columns'
    )
}}

-- Canonical fact table for ad spend across all platforms
--
-- This table unifies ad spend data from Meta Ads, Google Ads, TikTok Ads, and Snapchat Ads.
-- It provides a single source of truth for all advertising spend.
--
-- SECURITY: Tenant isolation is enforced - all rows must have tenant_id

with meta_ads as (
    select
        ad_account_id,
        campaign_id,
        adset_id,
        ad_id,
        date as spend_date,
        spend,
        impressions,
        clicks,
        conversions,
        conversion_value,
        currency,
        platform,
        canonical_channel,
        airbyte_record_id,
        airbyte_emitted_at,
        tenant_id
    from {{ ref('stg_meta_ads') }}
    where tenant_id is not null
        and ad_account_id is not null
        and campaign_id is not null
        and date is not null
        and spend is not null

    {% if is_incremental() %}
        -- Incremental mode with configurable lookback window (default 7 days)
        and airbyte_emitted_at >= (
            current_timestamp - interval '{{ var("fact_ad_spend_lookback_days", 7) }} days'
        )
    {% endif %}
),

google_ads as (
    select
        ad_account_id,
        campaign_id,
        ad_group_id as adset_id,  -- Map ad_group_id to adset_id for consistency
        ad_id,
        date as spend_date,
        spend,
        impressions,
        clicks,
        conversions,
        conversion_value,
        currency,
        platform,
        canonical_channel,
        airbyte_record_id,
        airbyte_emitted_at,
        tenant_id
    from {{ ref('stg_google_ads') }}
    where tenant_id is not null
        and ad_account_id is not null
        and campaign_id is not null
        and date is not null
        and spend is not null

    {% if is_incremental() %}
        -- Incremental mode with configurable lookback window (default 7 days)
        and airbyte_emitted_at >= (
            current_timestamp - interval '{{ var("fact_ad_spend_lookback_days", 7) }} days'
        )
    {% endif %}
),

tiktok_ads as (
    select
        ad_account_id,
        campaign_id,
        adgroup_id as adset_id,  -- Map adgroup_id to adset_id for consistency
        ad_id,
        date as spend_date,
        spend,
        impressions,
        clicks,
        conversions,
        conversion_value,
        currency,
        platform,
        canonical_channel,
        airbyte_record_id,
        airbyte_emitted_at,
        tenant_id
    from {{ ref('stg_tiktok_ads') }}
    where tenant_id is not null
        and ad_account_id is not null
        and campaign_id is not null
        and date is not null
        and spend is not null

    {% if is_incremental() %}
        -- Incremental mode with configurable lookback window (default 7 days)
        and airbyte_emitted_at >= (
            current_timestamp - interval '{{ var("fact_ad_spend_lookback_days", 7) }} days'
        )
    {% endif %}
),

snapchat_ads as (
    select
        ad_account_id,
        campaign_id,
        ad_squad_id as adset_id,  -- Map ad_squad_id to adset_id for consistency
        ad_id,
        date as spend_date,
        spend,
        impressions,
        clicks,
        conversions,
        conversion_value,
        currency,
        platform,
        canonical_channel,
        airbyte_record_id,
        airbyte_emitted_at,
        tenant_id
    from {{ ref('stg_snapchat_ads') }}
    where tenant_id is not null
        and ad_account_id is not null
        and campaign_id is not null
        and date is not null
        and spend is not null

    {% if is_incremental() %}
        -- Incremental mode with configurable lookback window (default 7 days)
        and airbyte_emitted_at >= (
            current_timestamp - interval '{{ var("fact_ad_spend_lookback_days", 7) }} days'
        )
    {% endif %}
),

unified_ad_spend as (
    select
        ad_account_id,
        campaign_id,
        adset_id,
        ad_id,
        spend_date,
        spend,
        impressions,
        clicks,
        conversions,
        conversion_value,
        currency,
        platform,
        canonical_channel,
        airbyte_record_id,
        airbyte_emitted_at,
        tenant_id
    from meta_ads

    union all

    select
        ad_account_id,
        campaign_id,
        adset_id,
        ad_id,
        spend_date,
        spend,
        impressions,
        clicks,
        conversions,
        conversion_value,
        currency,
        platform,
        canonical_channel,
        airbyte_record_id,
        airbyte_emitted_at,
        tenant_id
    from google_ads

    union all

    select
        ad_account_id,
        campaign_id,
        adset_id,
        ad_id,
        spend_date,
        spend,
        impressions,
        clicks,
        conversions,
        conversion_value,
        currency,
        platform,
        canonical_channel,
        airbyte_record_id,
        airbyte_emitted_at,
        tenant_id
    from tiktok_ads

    union all

    select
        ad_account_id,
        campaign_id,
        adset_id,
        ad_id,
        spend_date,
        spend,
        impressions,
        clicks,
        conversions,
        conversion_value,
        currency,
        platform,
        canonical_channel,
        airbyte_record_id,
        airbyte_emitted_at,
        tenant_id
    from snapchat_ads
)

select
    -- Primary key: composite of tenant_id, platform, ad_account_id, campaign_id, ad_id, date
    -- Using MD5 hash for deterministic surrogate key generation
    md5(concat(tenant_id, '|', platform, '|', ad_account_id, '|', campaign_id, '|', coalesce(ad_id, ''), '|', spend_date::text)) as id,

    -- Canonical columns (per user story 7.7.1)
    tenant_id,
    spend_date as date,  -- Renamed from spend_date for canonical schema
    platform as source_platform,

    -- Marketing channel (derived from canonical_channel or platform)
    coalesce(canonical_channel,
        case
            when platform = 'meta_ads' then 'paid_social'
            when platform = 'google_ads' then 'paid_search'
            when platform = 'tiktok_ads' then 'paid_social'
            when platform = 'snapchat_ads' then 'paid_social'
            else 'other'
        end
    ) as channel,

    -- Ad identifiers
    ad_account_id,
    campaign_id,
    adset_id,
    ad_id,

    -- Spend information
    spend,
    currency,

    -- Performance metrics
    impressions,
    clicks,
    conversions,
    conversion_value,

    -- Derived metrics
    case
        when impressions > 0 then round((spend / impressions) * 1000, 4)
        else null
    end as cpm,
    case
        when clicks > 0 then round(spend / clicks, 4)
        else null
    end as cpc,
    case
        when impressions > 0 then round((clicks::numeric / impressions) * 100, 4)
        else null
    end as ctr,
    case
        when conversions > 0 then round(spend / conversions, 4)
        else null
    end as cpa,
    case
        when spend > 0 then round(conversion_value / spend, 4)
        else null
    end as roas,

    -- Legacy: keep platform for backward compatibility
    platform,

    -- Airbyte metadata
    airbyte_record_id,
    airbyte_emitted_at as ingested_at,

    -- Audit fields
    current_timestamp as dbt_updated_at

from unified_ad_spend
