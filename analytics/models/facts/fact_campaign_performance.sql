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
    from {{ ref('stg_meta_ads') }}
    where tenant_id is not null
        and ad_account_id is not null
        and campaign_id is not null
        and date is not null
    
    {% if is_incremental() %}
        and airbyte_emitted_at > (
            select coalesce(max(ingested_at), '1970-01-01'::timestamp with time zone)
            from {{ this }}
            where platform = 'meta_ads'
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
    from {{ ref('stg_google_ads') }}
    where tenant_id is not null
        and ad_account_id is not null
        and campaign_id is not null
        and date is not null
    
    {% if is_incremental() %}
        and airbyte_emitted_at > (
            select coalesce(max(ingested_at), '1970-01-01'::timestamp with time zone)
            from {{ this }}
            where platform = 'google_ads'
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
    -- Primary key: composite of tenant_id, platform, ad_account_id, campaign_id, performance_date
    -- Using MD5 hash for deterministic surrogate key generation
    md5(concat(tenant_id, '|', platform, '|', ad_account_id, '|', campaign_id, '|', performance_date::text)) as id,
    
    -- Campaign identifiers
    ad_account_id,
    campaign_id,
    campaign_name,
    
    -- Performance date
    performance_date,
    
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
    
    -- Platform identifier
    platform,
    
    -- Tenant isolation (CRITICAL)
    tenant_id,
    
    -- Airbyte metadata
    airbyte_record_id,
    airbyte_emitted_at as ingested_at,
    
    -- Audit fields
    current_timestamp as dbt_updated_at

from unified_campaigns
