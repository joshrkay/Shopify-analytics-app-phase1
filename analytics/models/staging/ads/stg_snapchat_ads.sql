{{
    config(
        materialized='incremental',
        schema='staging',
        unique_key=['tenant_id', 'ad_account_id', 'campaign_id', 'ad_squad_id', 'ad_id', 'date'],
        incremental_strategy='delete+insert',
        enabled=var('enable_snapchat_ads', true)
    )
}}

{#
    Staging model for Snapchat Ads with normalized fields and tenant isolation.

    This model:
    - Extracts and normalizes raw Snapchat Ads data from Airbyte
    - Adds internal IDs for cross-platform joins (Option B ID normalization)
    - Maps to canonical channel taxonomy
    - Supports incremental processing with configurable lookback window
    - Excludes PII fields
    - Returns empty result if source table doesn't exist yet

    Required output columns (staging contract):
    - tenant_id, report_date, source, platform_channel, canonical_channel
    - platform_account_id, internal_account_id, platform_campaign_id, internal_campaign_id
    - spend, impressions, clicks, conversions, conversion_value
    - cpm, cpc, ctr, cpa, roas_platform (derived where possible)
#}

-- Check if source table exists; if not, return empty result set
{% if not source_exists('airbyte_raw', '_airbyte_raw_snapchat_ads') %}

select
    cast(null as text) as tenant_id,
    cast(null as date) as report_date,
    cast(null as date) as date,
    cast(null as text) as source,
    cast(null as text) as ad_account_id,
    cast(null as text) as campaign_id,
    cast(null as text) as ad_squad_id,
    cast(null as text) as ad_id,
    cast(null as text) as internal_account_id,
    cast(null as text) as internal_campaign_id,
    cast(null as text) as platform_channel,
    cast(null as text) as canonical_channel,
    cast(null as numeric) as spend,
    cast(null as integer) as impressions,
    cast(null as integer) as clicks,
    cast(null as numeric) as conversions,
    cast(null as numeric) as conversion_value,
    cast(null as text) as currency,
    cast(null as numeric) as cpm,
    cast(null as numeric) as cpc,
    cast(null as numeric) as ctr,
    cast(null as numeric) as cpa,
    cast(null as numeric) as roas_platform,
    cast(null as text) as campaign_name,
    cast(null as text) as ad_squad_name,
    cast(null as text) as ad_name,
    cast(null as text) as objective,
    cast(null as integer) as reach,
    cast(null as numeric) as frequency,
    cast(null as text) as platform,
    cast(null as text) as airbyte_record_id,
    cast(null as timestamp) as airbyte_emitted_at
where 1=0

{% else %}

with raw_snapchat_ads as (
    select
        _airbyte_ab_id as airbyte_record_id,
        _airbyte_emitted_at as airbyte_emitted_at,
        _airbyte_data as ad_data
    from {{ source('airbyte_raw', '_airbyte_raw_snapchat_ads') }}
    {% if is_incremental() %}
    where _airbyte_emitted_at >= current_timestamp - interval '{{ var("snapchat_ads_lookback_days", 3) }} days'
    {% endif %}
),

snapchat_ads_extracted as (
    select
        raw.airbyte_record_id,
        raw.airbyte_emitted_at,
        raw.ad_data->>'ad_account_id' as ad_account_id_raw,
        raw.ad_data->>'campaign_id' as campaign_id_raw,
        raw.ad_data->>'ad_squad_id' as ad_squad_id_raw,
        raw.ad_data->>'ad_id' as ad_id_raw,
        raw.ad_data->>'start_time' as date_raw,
        raw.ad_data->>'spend' as spend_raw,
        raw.ad_data->>'impressions' as impressions_raw,
        raw.ad_data->>'swipes' as clicks_raw,  -- Snapchat calls clicks "swipes"
        raw.ad_data->>'conversion_purchases' as conversions_raw,
        raw.ad_data->>'conversion_purchases_value' as conversion_value_raw,
        raw.ad_data->>'currency' as currency_code,
        raw.ad_data->>'campaign_name' as campaign_name,
        raw.ad_data->>'ad_squad_name' as ad_squad_name,
        raw.ad_data->>'ad_name' as ad_name,
        raw.ad_data->>'objective' as objective,
        raw.ad_data->>'uniques' as reach_raw,
        raw.ad_data->>'frequency' as frequency_raw,
        raw.ad_data->>'ecpm' as cpm_raw,
        raw.ad_data->>'ecpc' as cpc_raw,
        raw.ad_data->>'swipe_rate' as ctr_raw,
        -- Platform channel: derive from objective or placement
        coalesce(raw.ad_data->>'placement', raw.ad_data->>'objective', 'snap_ads') as platform_channel_raw
    from raw_snapchat_ads raw
),

snapchat_ads_normalized as (
    select
        -- Primary identifiers: normalize IDs
        case
            when ad_account_id_raw is null or trim(ad_account_id_raw) = '' then null
            else trim(ad_account_id_raw)
        end as ad_account_id,

        case
            when campaign_id_raw is null or trim(campaign_id_raw) = '' then null
            else trim(campaign_id_raw)
        end as campaign_id,

        case
            when ad_squad_id_raw is null or trim(ad_squad_id_raw) = '' then null
            else trim(ad_squad_id_raw)
        end as ad_squad_id,

        case
            when ad_id_raw is null or trim(ad_id_raw) = '' then null
            else trim(ad_id_raw)
        end as ad_id,

        -- Date field: normalize to date type (Snapchat uses ISO timestamps)
        case
            when date_raw is null or trim(date_raw) = '' then null
            when date_raw ~ '^\d{4}-\d{2}-\d{2}'
                then date_raw::date
            else null
        end as date,

        -- Spend: Snapchat provides spend in micro-currency (divide by 1,000,000)
        case
            when spend_raw is null or trim(spend_raw) = '' then 0.0
            when trim(spend_raw) ~ '^-?[0-9]+$' then
                least(greatest((trim(spend_raw)::bigint / 1000000.0)::numeric, -999999999.99), 999999999.99)
            when trim(spend_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' then
                least(greatest(trim(spend_raw)::numeric, -999999999.99), 999999999.99)
            else 0.0
        end as spend,

        -- Impressions: convert to integer, handle nulls
        case
            when impressions_raw is null or trim(impressions_raw) = '' then 0
            when trim(impressions_raw) ~ '^-?[0-9]+$'
                then least(greatest(trim(impressions_raw)::integer, 0), 2147483647)
            else 0
        end as impressions,

        -- Clicks (swipes): convert to integer, handle nulls
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

        -- Conversion value: convert to numeric (also in micro-currency)
        case
            when conversion_value_raw is null or trim(conversion_value_raw) = '' then 0.0
            when trim(conversion_value_raw) ~ '^-?[0-9]+$' then
                least(greatest((trim(conversion_value_raw)::bigint / 1000000.0)::numeric, 0.0), 999999999.99)
            when trim(conversion_value_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' then
                least(greatest(trim(conversion_value_raw)::numeric, 0.0), 999999999.99)
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
        ad_squad_name,
        ad_name,
        objective,

        -- Platform channel (raw value from platform)
        coalesce(platform_channel_raw, 'snap_ads') as platform_channel,

        -- Reach (uniques): convert to integer
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

        -- eCPM: convert to numeric (in micro-currency)
        case
            when cpm_raw is null or trim(cpm_raw) = '' then null
            when trim(cpm_raw) ~ '^-?[0-9]+$' then
                least(greatest((trim(cpm_raw)::bigint / 1000000.0)::numeric, 0.0), 999999.99)
            when trim(cpm_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' then
                least(greatest(trim(cpm_raw)::numeric, 0.0), 999999.99)
            else null
        end as cpm_platform,

        -- eCPC: convert to numeric (in micro-currency)
        case
            when cpc_raw is null or trim(cpc_raw) = '' then null
            when trim(cpc_raw) ~ '^-?[0-9]+$' then
                least(greatest((trim(cpc_raw)::bigint / 1000000.0)::numeric, 0.0), 999999.99)
            when trim(cpc_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' then
                least(greatest(trim(cpc_raw)::numeric, 0.0), 999999.99)
            else null
        end as cpc_platform,

        -- Swipe rate (CTR): convert to numeric (percentage)
        case
            when ctr_raw is null or trim(ctr_raw) = '' then null
            when trim(ctr_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$'
                then least(greatest(trim(ctr_raw)::numeric * 100, 0.0), 100.0)  -- Convert to percentage
            else null
        end as ctr_platform,

        -- Platform identifier
        'snapchat_ads' as platform,

        -- Source identifier (same as platform for consistency)
        'snap_ads' as source,

        -- Metadata
        airbyte_record_id,
        airbyte_emitted_at

    from snapchat_ads_extracted
),

-- Join to tenant mapping to get tenant_id
snapchat_ads_with_tenant as (
    select
        ads.*,
        coalesce(
            (select tenant_id
             from {{ ref('_tenant_airbyte_connections') }}
             where source_type = 'source-snapchat-marketing'
               and status = 'active'
               and is_enabled = true
             limit 1),
            null
        ) as tenant_id
    from snapchat_ads_normalized ads
),

-- Add internal IDs and canonical channel
snapchat_ads_final as (
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
        ad_squad_id,
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
            else cpm_platform
        end as cpm,

        -- CPC: Cost Per Click = spend / clicks
        case
            when clicks > 0 then round(spend / clicks, 4)
            else cpc_platform
        end as cpc,

        -- CTR: Click Through Rate = (clicks / impressions) * 100
        case
            when impressions > 0 then round((clicks::numeric / impressions) * 100, 4)
            else ctr_platform
        end as ctr,

        -- CPA: Cost Per Acquisition = spend / conversions
        case
            when conversions > 0 then round(spend / conversions, 4)
            else null
        end as cpa,

        -- ROAS Platform: Return on Ad Spend = conversion_value / spend
        case
            when spend > 0 then round(conversion_value / spend, 4)
            else null
        end as roas_platform,

        -- Additional fields
        campaign_name,
        ad_squad_name,
        ad_name,
        objective,
        reach,
        frequency,

        -- Platform identifier (kept for backward compatibility)
        platform,

        -- Metadata
        airbyte_record_id,
        airbyte_emitted_at

    from snapchat_ads_with_tenant
)

select
    tenant_id,
    report_date,
    date,
    source,
    ad_account_id,
    campaign_id,
    ad_squad_id,
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
    ad_squad_name,
    ad_name,
    objective,
    reach,
    frequency,
    platform,
    airbyte_record_id,
    airbyte_emitted_at
from snapchat_ads_final
where tenant_id is not null
    and ad_account_id is not null
    and trim(ad_account_id) != ''
    and campaign_id is not null
    and trim(campaign_id) != ''
    and date is not null
    {% if is_incremental() %}
    and date >= current_date - {{ var("snapchat_ads_lookback_days", 3) }}
    {% endif %}

{% endif %}
