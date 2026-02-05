{{
    config(
        materialized='incremental',
        schema='staging',
        unique_key='record_sk',
        incremental_strategy='delete+insert',
        enabled=var('enable_tiktok_ads', true)
    )
}}

{#
    Staging model for TikTok Ads with strict typing and standardization.

    This model:
    - Extracts and normalizes raw TikTok Ads data from Airbyte
    - Adds record_sk (stable surrogate key), source_system, source_primary_key
    - Deduplicates by natural key keeping the latest Airbyte emission
    - Adds internal IDs for cross-platform joins (Option B ID normalization)
    - Maps to canonical channel taxonomy
    - Supports incremental processing with configurable lookback window
    - Returns empty result if source table doesn't exist yet
    - Does NOT calculate business metrics (cpm, cpc, ctr, cpa, roas) - deferred to canonical layer

    SECURITY: Tenant isolation enforced via _tenant_airbyte_connections.
#}

-- Check if source table exists; if not, return empty result set
{% if not source_exists('raw_tiktok_ads', 'ad_reports') %}

select
    cast(null as text) as record_sk,
    cast(null as text) as source_system,
    cast(null as text) as source_primary_key,
    cast(null as text) as tenant_id,
    cast(null as date) as report_date,
    cast(null as date) as date,
    cast(null as text) as source,
    cast(null as text) as ad_account_id,
    cast(null as text) as campaign_id,
    cast(null as text) as adgroup_id,
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
    cast(null as text) as campaign_name,
    cast(null as text) as adgroup_name,
    cast(null as text) as ad_name,
    cast(null as text) as objective,
    cast(null as integer) as reach,
    cast(null as numeric) as frequency,
    cast(null as text) as platform,
    cast(null as text) as airbyte_record_id,
    cast(null as timestamp) as airbyte_emitted_at
where 1=0

{% else %}

with raw_tiktok_ads as (
    select
        _airbyte_ab_id as airbyte_record_id,
        _airbyte_emitted_at as airbyte_emitted_at,
        _airbyte_data as ad_data
    from {{ source('raw_tiktok_ads', 'ad_reports') }}
    {% if is_incremental() %}
    where _airbyte_emitted_at >= current_timestamp - interval '{{ var("tiktok_ads_lookback_days", 3) }} days'
    {% endif %}
),

tiktok_ads_extracted as (
    select
        raw.airbyte_record_id,
        raw.airbyte_emitted_at,
        raw.ad_data->>'advertiser_id' as advertiser_id_raw,
        raw.ad_data->>'campaign_id' as campaign_id_raw,
        raw.ad_data->>'adgroup_id' as adgroup_id_raw,
        raw.ad_data->>'ad_id' as ad_id_raw,
        raw.ad_data->>'stat_time_day' as date_raw,
        raw.ad_data->>'spend' as spend_raw,
        raw.ad_data->>'impressions' as impressions_raw,
        raw.ad_data->>'clicks' as clicks_raw,
        raw.ad_data->>'conversion' as conversions_raw,
        raw.ad_data->>'total_purchase_value' as conversion_value_raw,
        raw.ad_data->>'currency' as currency_code,
        raw.ad_data->>'campaign_name' as campaign_name,
        raw.ad_data->>'adgroup_name' as adgroup_name,
        raw.ad_data->>'ad_name' as ad_name,
        raw.ad_data->>'objective_type' as objective,
        raw.ad_data->>'reach' as reach_raw,
        raw.ad_data->>'frequency' as frequency_raw,
        coalesce(raw.ad_data->>'placement_type', raw.ad_data->>'objective_type', 'feed') as platform_channel_raw
    from raw_tiktok_ads raw
),

tiktok_ads_normalized as (
    select
        -- Primary identifiers: normalize IDs
        case
            when advertiser_id_raw is null or trim(advertiser_id_raw) = '' then null
            else trim(advertiser_id_raw)
        end as ad_account_id,

        case
            when campaign_id_raw is null or trim(campaign_id_raw) = '' then null
            else trim(campaign_id_raw)
        end as campaign_id,

        case
            when adgroup_id_raw is null or trim(adgroup_id_raw) = '' then null
            else trim(adgroup_id_raw)
        end as adgroup_id,

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

        -- Spend: convert to numeric
        case
            when spend_raw is null or trim(spend_raw) = '' then 0.0
            when trim(spend_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$'
                then least(greatest(trim(spend_raw)::numeric, -999999999.99), 999999999.99)
            else 0.0
        end as spend,

        -- Impressions: convert to integer
        case
            when impressions_raw is null or trim(impressions_raw) = '' then 0
            when trim(impressions_raw) ~ '^-?[0-9]+$'
                then least(greatest(trim(impressions_raw)::integer, 0), 2147483647)
            else 0
        end as impressions,

        -- Clicks: convert to integer
        case
            when clicks_raw is null or trim(clicks_raw) = '' then 0
            when trim(clicks_raw) ~ '^-?[0-9]+$'
                then least(greatest(trim(clicks_raw)::integer, 0), 2147483647)
            else 0
        end as clicks,

        -- Conversions: convert to numeric
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
        adgroup_name,
        ad_name,
        objective,

        -- Platform channel (raw value from platform)
        coalesce(platform_channel_raw, 'feed') as platform_channel,

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

        -- Platform/source identifiers
        'tiktok_ads' as platform,
        'tiktok_ads' as source,

        -- Metadata
        airbyte_record_id,
        airbyte_emitted_at

    from tiktok_ads_extracted
),

-- Join to tenant mapping to get tenant_id
tiktok_ads_with_tenant as (
    select
        ads.*,
        coalesce(
            (select tenant_id
             from {{ ref('_tenant_airbyte_connections') }}
             where source_type = 'source-tiktok-marketing'
               and status = 'active'
               and is_enabled = true
             limit 1),
            null
        ) as tenant_id
    from tiktok_ads_normalized ads
),

-- Add internal IDs, canonical channel, and dedup
tiktok_ads_enriched as (
    select
        tenant_id,
        date,
        date as report_date,
        source,
        ad_account_id,
        campaign_id,
        adgroup_id,
        ad_id,

        -- Internal IDs (Option B ID normalization)
        {{ generate_internal_id('tenant_id', 'source', 'ad_account_id') }} as internal_account_id,
        {{ generate_internal_id('tenant_id', 'source', 'campaign_id') }} as internal_campaign_id,

        -- Channel taxonomy
        platform_channel,
        {{ map_canonical_channel('source', 'platform_channel') }} as canonical_channel,

        -- Core metrics only (no derived business metrics)
        spend,
        impressions,
        clicks,
        conversions,
        conversion_value,
        currency,

        -- Additional fields
        campaign_name,
        adgroup_name,
        ad_name,
        objective,
        reach,
        frequency,

        platform,
        airbyte_record_id,
        airbyte_emitted_at,

        -- Dedup: keep latest record per natural key
        row_number() over (
            partition by tenant_id, ad_account_id, campaign_id, adgroup_id, ad_id, date
            order by airbyte_emitted_at desc
        ) as _row_num

    from tiktok_ads_with_tenant
    where tenant_id is not null
        and ad_account_id is not null
        and trim(ad_account_id) != ''
        and campaign_id is not null
        and trim(campaign_id) != ''
        and date is not null
)

select
    -- Surrogate key: md5(tenant_id || source_system || source_primary_key)
    md5(concat(
        tenant_id, '|', 'tiktok_ads', '|',
        ad_account_id, '|', campaign_id, '|',
        coalesce(adgroup_id, ''), '|', coalesce(ad_id, ''), '|',
        date::text
    )) as record_sk,

    -- Source tracking
    'tiktok_ads' as source_system,
    concat(
        ad_account_id, '|', campaign_id, '|',
        coalesce(adgroup_id, ''), '|', coalesce(ad_id, ''), '|',
        date::text
    ) as source_primary_key,

    -- All staging columns
    tenant_id,
    report_date,
    date,
    source,
    ad_account_id,
    campaign_id,
    adgroup_id,
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
    campaign_name,
    adgroup_name,
    ad_name,
    objective,
    reach,
    frequency,
    platform,
    airbyte_record_id,
    airbyte_emitted_at

from tiktok_ads_enriched
where _row_num = 1
    {% if is_incremental() %}
    and date >= current_date - {{ var("tiktok_ads_lookback_days", 3) }}
    {% endif %}

{% endif %}
