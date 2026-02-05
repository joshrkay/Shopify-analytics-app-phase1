{{
    config(
        materialized='incremental',
        unique_key='id',
        schema='analytics',
        on_schema_change='append_new_columns'
    )
}}

-- Canonical fact table for campaign performance across all platforms
-- 
-- This table unifies campaign-level performance metrics from Meta Ads and Google Ads.
-- It provides a single source of truth for campaign analytics.
--
-- SECURITY: Tenant isolation is enforced - all rows must have tenant_id

with meta_ads as (
    select
        ad_account_id,
        campaign_id,
        date as performance_date,
        spend,
        impressions,
        clicks,
        conversions,
        currency,
        campaign_name,
        platform,
        airbyte_record_id,
        airbyte_emitted_at,
        tenant_id
    from {{ ref('stg_facebook_ads_performance') }}
    where tenant_id is not null
        and ad_account_id is not null
        and campaign_id is not null
        and date is not null
    
    {% if is_incremental() %}
        -- Incremental mode with configurable lookback window (default 7 days)
        and airbyte_emitted_at >= (
            current_timestamp - interval '{{ var("fact_campaign_performance_lookback_days", 7) }} days'
        )
    {% endif %}
),

google_ads as (
    select
        ad_account_id,
        campaign_id,
        date as performance_date,
        spend,
        impressions,
        clicks,
        conversions,
        currency,
        campaign_name,
        platform,
        airbyte_record_id,
        airbyte_emitted_at,
        tenant_id
    from {{ ref('stg_google_ads_performance') }}
    where tenant_id is not null
        and ad_account_id is not null
        and campaign_id is not null
        and date is not null
    
    {% if is_incremental() %}
        -- Incremental mode with configurable lookback window (default 7 days)
        and airbyte_emitted_at >= (
            current_timestamp - interval '{{ var("fact_campaign_performance_lookback_days", 7) }} days'
        )
    {% endif %}
),

unified_campaigns as (
    select
        ad_account_id,
        campaign_id,
        performance_date,
        spend,
        impressions,
        clicks,
        conversions,
        currency,
        campaign_name,
        platform,
        airbyte_record_id,
        airbyte_emitted_at,
        tenant_id
    from meta_ads
    
    union all
    
    select
        ad_account_id,
        campaign_id,
        performance_date,
        spend,
        impressions,
        clicks,
        conversions,
        currency,
        campaign_name,
        platform,
        airbyte_record_id,
        airbyte_emitted_at,
        tenant_id
    from google_ads
)

select
    -- Primary key: composite of tenant_id, platform, ad_account_id, campaign_id, date
    -- Using MD5 hash for deterministic surrogate key generation
    md5(concat(tenant_id, '|', platform, '|', ad_account_id, '|', campaign_id, '|', performance_date::text)) as id,

    -- Canonical columns (per user story 7.7.1)
    tenant_id,
    performance_date as date,  -- Renamed from performance_date for canonical schema
    platform as source_platform,

    -- Marketing channel (derived from platform per user story 7.7.1)
    case
        when platform = 'meta_ads' then 'paid_social'
        when platform = 'google_ads' then 'paid_search'
        else 'other'
    end as channel,

    -- Campaign identifiers
    ad_account_id,
    campaign_id,
    campaign_name,

    -- Performance metrics (all numeric, normalized)
    spend,
    impressions,
    clicks,
    conversions,

    -- Calculated metrics
    case
        when impressions > 0 then (clicks::numeric / impressions::numeric) * 100
        else null
    end as ctr,  -- Click-through rate (percentage)

    case
        when clicks > 0 then spend / clicks::numeric
        else null
    end as cpc,  -- Cost per click

    case
        when conversions > 0 then spend / conversions::numeric
        else null
    end as cpa,  -- Cost per acquisition/conversion

    -- Currency
    currency,

    -- Legacy: keep platform for backward compatibility
    platform,

    -- Airbyte metadata
    airbyte_record_id,
    airbyte_emitted_at as ingested_at,

    -- Audit fields
    current_timestamp as dbt_updated_at

from unified_campaigns
