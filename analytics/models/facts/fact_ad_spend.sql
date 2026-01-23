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
-- This table unifies ad spend data from Meta Ads and Google Ads.
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
        currency,
        platform,
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
        ad_group_id as adset_id,  -- Map ad_group_id to adset_id for consistency
        ad_id,
        date as spend_date,
        spend,
        currency,
        platform,
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
        and airbyte_emitted_at > (
            select coalesce(max(ingested_at), '1970-01-01'::timestamp with time zone)
            from {{ this }}
            where platform = 'google_ads'
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
        currency,
        platform,
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
        currency,
        platform,
        airbyte_record_id,
        airbyte_emitted_at,
        tenant_id
    from google_ads
)

select
    -- Primary key: composite of tenant_id, platform, ad_account_id, campaign_id, ad_id, spend_date
    -- Using MD5 hash for deterministic surrogate key generation
    md5(concat(tenant_id, '|', platform, '|', ad_account_id, '|', campaign_id, '|', coalesce(ad_id, ''), '|', spend_date::text)) as id,
    
    -- Ad identifiers
    ad_account_id,
    campaign_id,
    adset_id,
    ad_id,
    
    -- Spend information
    spend_date,
    spend,
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

from unified_ad_spend
