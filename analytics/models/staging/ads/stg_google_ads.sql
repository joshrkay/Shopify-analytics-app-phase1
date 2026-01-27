{{
    config(
        materialized='incremental',
        schema='staging',
        unique_key=['tenant_id', 'ad_account_id', 'campaign_id', 'ad_group_id', 'ad_id', 'date'],
        incremental_strategy='delete+insert'
    )
}}

{#
    Staging model for Google Ads with normalized fields and tenant isolation.

    This model:
    - Extracts and normalizes raw Google Ads data from Airbyte
    - Adds internal IDs for cross-platform joins (Option B ID normalization)
    - Maps to canonical channel taxonomy
    - Supports incremental processing with configurable lookback window
    - Excludes PII fields

    Required output columns (staging contract):
    - tenant_id, report_date, source, platform_channel, canonical_channel
    - platform_account_id, internal_account_id, platform_campaign_id, internal_campaign_id
    - spend, impressions, clicks, conversions, conversion_value
    - cpm, cpc, ctr, cpa, roas_platform (derived where possible)
#}

with raw_google_ads as (
    select
        _airbyte_ab_id as airbyte_record_id,
        _airbyte_emitted_at as airbyte_emitted_at,
        _airbyte_data as ad_data
    from {{ source('airbyte_raw', '_airbyte_raw_google_ads') }}
    {% if is_incremental() %}
    where _airbyte_emitted_at >= current_timestamp - interval '{{ get_lookback_days("google_ads") }} days'
    {% endif %}
),

google_ads_extracted as (
    select
        raw.airbyte_record_id,
        raw.airbyte_emitted_at,
        raw.ad_data->>'customer_id' as customer_id_raw,
        raw.ad_data->>'campaign_id' as campaign_id_raw,
        raw.ad_data->>'ad_group_id' as ad_group_id_raw,
        raw.ad_data->>'ad_id' as ad_id_raw,
        raw.ad_data->>'date' as date_raw,
        raw.ad_data->>'cost_micros' as cost_micros_raw,
        raw.ad_data->>'cost' as cost_raw,
        raw.ad_data->>'impressions' as impressions_raw,
        raw.ad_data->>'clicks' as clicks_raw,
        raw.ad_data->>'conversions' as conversions_raw,
        raw.ad_data->>'conversion_value' as conversion_value_raw,
        raw.ad_data->>'currency_code' as currency_code,
        raw.ad_data->>'campaign_name' as campaign_name,
        raw.ad_data->>'ad_group_name' as ad_group_name,
        raw.ad_data->>'ad_type' as ad_type,
        raw.ad_data->>'device' as device,
        raw.ad_data->>'network' as network,
        raw.ad_data->>'ctr' as ctr_raw,
        raw.ad_data->>'average_cpc' as average_cpc_raw,
        raw.ad_data->>'cost_per_conversion' as cost_per_conversion_raw,
        -- Platform channel: derive from network or campaign type
        coalesce(raw.ad_data->>'network', raw.ad_data->>'campaign_type', 'search') as platform_channel_raw
    from raw_google_ads raw
),

google_ads_normalized as (
    select
        -- Primary identifiers: normalize IDs
        -- Google Ads uses customer_id instead of account_id
        case
            when customer_id_raw is null or trim(customer_id_raw) = '' then null
            else trim(customer_id_raw)
        end as ad_account_id,

        case
            when campaign_id_raw is null or trim(campaign_id_raw) = '' then null
            else trim(campaign_id_raw)
        end as campaign_id,

        case
            when ad_group_id_raw is null or trim(ad_group_id_raw) = '' then null
            else trim(ad_group_id_raw)
        end as ad_group_id,

        case
            when ad_id_raw is null or trim(ad_id_raw) = '' then null
            else trim(ad_id_raw)
        end as ad_id,

        -- Date field: normalize to date type
        case
            when date_raw is null or trim(date_raw) = '' then null
            when date_raw ~ '^\d{4}-\d{2}-\d{2}'
                then date_raw::date
            else null
        end as date,

        -- Spend: Google Ads provides cost_micros (micros) or cost (decimal)
        -- Convert micros to dollars: divide by 1,000,000
        case
            when cost_micros_raw is not null and trim(cost_micros_raw) != ''
                and trim(cost_micros_raw) ~ '^-?[0-9]+$' then
                least(greatest((trim(cost_micros_raw)::bigint / 1000000.0)::numeric, -999999999.99), 999999999.99)
            when cost_raw is not null and trim(cost_raw) != ''
                and trim(cost_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' then
                least(greatest(trim(cost_raw)::numeric, -999999999.99), 999999999.99)
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

        -- Conversion value: convert to numeric
        case
            when conversion_value_raw is null or trim(conversion_value_raw) = '' then 0.0
            when trim(conversion_value_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$'
                then least(greatest(trim(conversion_value_raw)::numeric, 0.0), 999999999.99)
            else 0.0
        end as conversion_value,

        -- Currency: standardize to uppercase, validate format
        case
            when currency_code is null or trim(currency_code) = '' then 'USD'
            when upper(trim(currency_code)) ~ '^[A-Z]{3}$'
                then upper(trim(currency_code))
            else 'USD'
        end as currency,

        -- Additional fields
        campaign_name,
        ad_group_name,
        ad_type,
        device,
        network,

        -- Platform channel (raw value from platform)
        coalesce(platform_channel_raw, 'search') as platform_channel,

        -- CTR (Click-Through Rate): convert to numeric (percentage)
        case
            when ctr_raw is null or trim(ctr_raw) = '' then null
            when trim(ctr_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$'
                then least(greatest(trim(ctr_raw)::numeric, 0.0), 100.0)
            else null
        end as ctr,

        -- Average CPC: convert to numeric
        case
            when average_cpc_raw is null or trim(average_cpc_raw) = '' then null
            when trim(average_cpc_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$'
                then least(greatest(trim(average_cpc_raw)::numeric, 0.0), 999999.99)
            else null
        end as average_cpc,

        -- Cost per conversion: convert to numeric
        case
            when cost_per_conversion_raw is null or trim(cost_per_conversion_raw) = '' then null
            when trim(cost_per_conversion_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$'
                then least(greatest(trim(cost_per_conversion_raw)::numeric, 0.0), 999999.99)
            else null
        end as cost_per_conversion,

        -- Platform identifier (kept for backward compatibility)
        'google_ads' as platform,

        -- Source identifier (new, same as platform for consistency)
        'google_ads' as source,

        -- Metadata
        airbyte_record_id,
        airbyte_emitted_at

    from google_ads_extracted
),

-- Join to tenant mapping to get tenant_id
google_ads_with_tenant as (
    select
        ads.*,
        coalesce(
            (select tenant_id
             from {{ ref('_tenant_airbyte_connections') }}
             where source_type = 'source-google-ads'
               and status = 'active'
               and is_enabled = true
             limit 1),
            null
        ) as tenant_id
    from google_ads_normalized ads
),

-- Add internal IDs and canonical channel
google_ads_final as (
    select
        -- Tenant ID (required for multi-tenant isolation)
        tenant_id,

        -- Date fields
        date,
        date as report_date,  -- Alias for staging contract consistency

        -- Source identifier
        source,

        -- Platform IDs (kept for backward compatibility)
        ad_account_id,
        campaign_id,
        ad_group_id,
        ad_id,

        -- Internal IDs (Option B ID normalization)
        {{ generate_internal_id('tenant_id', 'source', 'ad_account_id') }} as internal_account_id,
        {{ generate_internal_id('tenant_id', 'source', 'campaign_id') }} as internal_campaign_id,

        -- Channel taxonomy
        platform_channel,
        {{ map_canonical_channel('source', 'platform_channel') }} as canonical_channel,

        -- Core metrics
        spend,
        impressions,
        clicks,
        conversions,
        conversion_value,
        currency,

        -- Derived metrics (calculated where possible)
        -- CPM: Cost Per Mille = (spend / impressions) * 1000
        case
            when impressions > 0 then round((spend / impressions) * 1000, 4)
            else null
        end as cpm,

        -- CPC: Cost Per Click = spend / clicks
        case
            when clicks > 0 then round(spend / clicks, 4)
            else average_cpc
        end as cpc,

        -- CTR: Click Through Rate = (clicks / impressions) * 100
        case
            when impressions > 0 then round((clicks::numeric / impressions) * 100, 4)
            else ctr
        end as ctr,

        -- CPA: Cost Per Acquisition = spend / conversions
        case
            when conversions > 0 then round(spend / conversions, 4)
            else cost_per_conversion
        end as cpa,

        -- ROAS Platform: Return on Ad Spend = conversion_value / spend
        case
            when spend > 0 then round(conversion_value / spend, 4)
            else null
        end as roas_platform,

        -- Additional fields (kept for backward compatibility)
        campaign_name,
        ad_group_name,
        ad_type,
        device,
        network,
        average_cpc,
        cost_per_conversion,

        -- Platform identifier (kept for backward compatibility)
        platform,

        -- Metadata
        airbyte_record_id,
        airbyte_emitted_at

    from google_ads_with_tenant
)

select
    tenant_id,
    report_date,
    date,
    source,
    ad_account_id,
    campaign_id,
    ad_group_id,
    ad_id,
    internal_account_id,
    internal_campaign_id,
    platform_channel,
    canonical_channel,
    spend,
    impressions,
    clicks,
    conversions,
    conversion_value,
    currency,
    cpm,
    cpc,
    ctr,
    cpa,
    roas_platform,
    campaign_name,
    ad_group_name,
    ad_type,
    device,
    network,
    average_cpc,
    cost_per_conversion,
    platform,
    airbyte_record_id,
    airbyte_emitted_at
from google_ads_final
where tenant_id is not null
    and ad_account_id is not null
    and trim(ad_account_id) != ''
    and campaign_id is not null
    and trim(campaign_id) != ''
    and date is not null
    {% if is_incremental() %}
    and date >= current_date - {{ get_lookback_days('google_ads') }}
    {% endif %}
