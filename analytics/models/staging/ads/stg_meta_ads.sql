{{
    config(
        materialized='view',
        schema='staging'
    )
}}

with raw_meta_ads as (
    select
        _airbyte_ab_id as airbyte_record_id,
        _airbyte_emitted_at as airbyte_emitted_at,
        _airbyte_data as ad_data
    from {{ source('airbyte_raw', '_airbyte_raw_meta_ads') }}
),

meta_ads_extracted as (
    select
        raw.airbyte_record_id,
        raw.airbyte_emitted_at,
        raw.ad_data->>'account_id' as account_id_raw,
        raw.ad_data->>'campaign_id' as campaign_id_raw,
        raw.ad_data->>'adset_id' as adset_id_raw,
        raw.ad_data->>'ad_id' as ad_id_raw,
        raw.ad_data->>'date_start' as date_start_raw,
        raw.ad_data->>'date_stop' as date_stop_raw,
        raw.ad_data->>'spend' as spend_raw,
        raw.ad_data->>'impressions' as impressions_raw,
        raw.ad_data->>'clicks' as clicks_raw,
        raw.ad_data->>'conversions' as conversions_raw,
        raw.ad_data->>'currency' as currency_code,
        raw.ad_data->>'campaign_name' as campaign_name,
        raw.ad_data->>'adset_name' as adset_name,
        raw.ad_data->>'ad_name' as ad_name,
        raw.ad_data->>'objective' as objective,
        raw.ad_data->>'reach' as reach_raw,
        raw.ad_data->>'frequency' as frequency_raw,
        raw.ad_data->>'cpm' as cpm_raw,
        raw.ad_data->>'cpp' as cpp_raw,
        raw.ad_data->>'ctr' as ctr_raw
    from raw_meta_ads raw
),

meta_ads_normalized as (
    select
        -- Primary identifiers: normalize IDs
        case
            when account_id_raw is null or trim(account_id_raw) = '' then null
            else trim(account_id_raw)
        end as ad_account_id,
        
        case
            when campaign_id_raw is null or trim(campaign_id_raw) = '' then null
            else trim(campaign_id_raw)
        end as campaign_id,
        
        case
            when adset_id_raw is null or trim(adset_id_raw) = '' then null
            else trim(adset_id_raw)
        end as adset_id,
        
        case
            when ad_id_raw is null or trim(ad_id_raw) = '' then null
            else trim(ad_id_raw)
        end as ad_id,
        
        -- Date fields: normalize to date type
        case
            when date_start_raw is null or trim(date_start_raw) = '' then null
            when date_start_raw ~ '^\d{4}-\d{2}-\d{2}' 
                then date_start_raw::date
            else null
        end as date,
        
        case
            when date_stop_raw is null or trim(date_stop_raw) = '' then null
            when date_stop_raw ~ '^\d{4}-\d{2}-\d{2}' 
                then date_stop_raw::date
            else null
        end as date_stop,
        
        -- Spend: convert to numeric, handle nulls and invalid values
        -- Edge case: Validate numeric format, handle negative, scientific notation
        case
            when spend_raw is null or trim(spend_raw) = '' then 0.0
            when trim(spend_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' 
                then least(greatest(trim(spend_raw)::numeric, -999999999.99), 999999999.99)
            else 0.0
        end as spend,
        
        -- Impressions: convert to integer, handle nulls
        case
            when impressions_raw is null or trim(impressions_raw) = '' then 0
            when trim(impressions_raw) ~ '^-?[0-9]+$' 
                then least(greatest(trim(impressions_raw)::integer, 0), 2147483647)
            else 0
        end as impressions,
        
        -- Clicks: convert to integer, handle nulls
        case
            when clicks_raw is null or trim(clicks_raw) = '' then 0
            when trim(clicks_raw) ~ '^-?[0-9]+$' 
                then least(greatest(trim(clicks_raw)::integer, 0), 2147483647)
            else 0
        end as clicks,
        
        -- Conversions: convert to numeric, handle nulls
        case
            when conversions_raw is null or trim(conversions_raw) = '' then 0.0
            when trim(conversions_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' 
                then least(greatest(trim(conversions_raw)::numeric, 0.0), 999999999.99)
            else 0.0
        end as conversions,
        
        -- Currency: standardize to uppercase, validate format
        case
            when currency_code is null or trim(currency_code) = '' then 'USD'
            when upper(trim(currency_code)) ~ '^[A-Z]{3}$' 
                then upper(trim(currency_code))
            else 'USD'
        end as currency,
        
        -- Additional fields
        campaign_name,
        adset_name,
        ad_name,
        objective,
        
        -- Reach: convert to integer
        case
            when reach_raw is null or trim(reach_raw) = '' then null
            when trim(reach_raw) ~ '^-?[0-9]+$' 
                then least(greatest(trim(reach_raw)::integer, 0), 2147483647)
            else null
        end as reach,
        
        -- Frequency: convert to numeric
        case
            when frequency_raw is null or trim(frequency_raw) = '' then null
            when trim(frequency_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' 
                then least(greatest(trim(frequency_raw)::numeric, 0.0), 100.0)
            else null
        end as frequency,
        
        -- CPM (Cost Per Mille): convert to numeric
        case
            when cpm_raw is null or trim(cpm_raw) = '' then null
            when trim(cpm_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' 
                then least(greatest(trim(cpm_raw)::numeric, 0.0), 999999.99)
            else null
        end as cpm,
        
        -- CPP (Cost Per Purchase): convert to numeric
        case
            when cpp_raw is null or trim(cpp_raw) = '' then null
            when trim(cpp_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' 
                then least(greatest(trim(cpp_raw)::numeric, 0.0), 999999.99)
            else null
        end as cpp,
        
        -- CTR (Click-Through Rate): convert to numeric (percentage)
        case
            when ctr_raw is null or trim(ctr_raw) = '' then null
            when trim(ctr_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' 
                then least(greatest(trim(ctr_raw)::numeric, 0.0), 100.0)
            else null
        end as ctr,
        
        -- Platform identifier
        'meta_ads' as platform,
        
        -- Metadata
        airbyte_record_id,
        airbyte_emitted_at
        
    from meta_ads_extracted
),

-- Join to tenant mapping to get tenant_id
-- Uses same strategy as stg_shopify_orders
meta_ads_with_tenant as (
    select
        ads.*,
        coalesce(
            -- Option 1: Extract connection_id from schema name (if Airbyte uses connection-specific schemas)
            -- (select tenant_id 
            --  from {{ ref('_tenant_airbyte_connections') }} t
            --  where t.airbyte_connection_id = split_part(current_schema(), '_', 3)
            --    and t.source_type = 'source-facebook-marketing'
            --    and t.status = 'active'
            --    and t.is_enabled = true
            --  limit 1),
            
            -- Option 2: Extract connection_id from table metadata
            -- (select tenant_id 
            --  from {{ ref('_tenant_airbyte_connections') }} t
            --  where t.airbyte_connection_id = ads.airbyte_connection_id_from_metadata
            --    and t.source_type = 'source-facebook-marketing'
            --    and t.status = 'active'
            --    and t.is_enabled = true
            --  limit 1),
            
            -- Option 3: Single connection per tenant (CURRENT - USE WITH CAUTION)
            (select tenant_id 
             from {{ ref('_tenant_airbyte_connections') }}
             where source_type = 'source-facebook-marketing'
               and status = 'active'
               and is_enabled = true
             limit 1),
            
            -- Fallback: null if no connection found
            null
        ) as tenant_id
    from meta_ads_normalized ads
)

select
    ad_account_id,
    campaign_id,
    adset_id,
    ad_id,
    date,
    date_stop,
    spend,
    impressions,
    clicks,
    conversions,
    currency,
    campaign_name,
    adset_name,
    ad_name,
    objective,
    reach,
    frequency,
    cpm,
    cpp,
    ctr,
    platform,
    airbyte_record_id,
    airbyte_emitted_at,
    tenant_id
from meta_ads_with_tenant
where tenant_id is not null
    and ad_account_id is not null  -- Edge case: Filter out null account IDs
    and trim(ad_account_id) != ''
    and campaign_id is not null    -- Edge case: Filter out null campaign IDs
    and trim(campaign_id) != ''
    and date is not null           -- Edge case: Filter out null dates (required for time-series)
