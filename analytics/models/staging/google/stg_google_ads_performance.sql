{{
    config(
        materialized='incremental',
        schema='staging',
        unique_key='record_sk',
        incremental_strategy='delete+insert'
    )
}}

{#
    Staging model for Google Ads with strict typing and standardization.

    This model:
    - Extracts and normalizes raw Google Ads data from Airbyte
    - Adds record_sk (stable surrogate key), source_system, source_primary_key
    - Deduplicates by natural key keeping the latest Airbyte emission
    - Handles cost_micros conversion (divide by 1,000,000) for spend normalization
    - Adds internal IDs for cross-platform joins (Option B ID normalization)
    - Maps to canonical channel taxonomy
    - Supports incremental processing with configurable lookback window
    - Does NOT calculate business metrics (cpm, cpc, ctr, cpa, roas) - deferred to canonical layer

    SECURITY: Tenant isolation enforced via _tenant_airbyte_connections.
#}

with raw_google_ads as (
    select
        _airbyte_ab_id as airbyte_record_id,
        _airbyte_emitted_at as airbyte_emitted_at,
        _airbyte_data as ad_data
    from {{ source('raw_google_ads', 'ad_stats') }}
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
        coalesce(raw.ad_data->>'network', raw.ad_data->>'campaign_type', 'search') as platform_channel_raw
    from raw_google_ads raw
),

google_ads_normalized as (
    select
        -- Primary identifiers: Google Ads uses customer_id as account_id
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

        -- Spend: Google Ads provides cost_micros (divide by 1,000,000) or cost (decimal)
        case
            when cost_micros_raw is not null and trim(cost_micros_raw) != ''
                and trim(cost_micros_raw) ~ '^-?[0-9]+$' then
                least(greatest((trim(cost_micros_raw)::bigint / 1000000.0)::numeric, -999999999.99), 999999999.99)
            when cost_raw is not null and trim(cost_raw) != ''
                and trim(cost_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' then
                least(greatest(trim(cost_raw)::numeric, -999999999.99), 999999999.99)
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
        ad_group_name,
        ad_type,
        device,
        network,

        -- Platform channel (raw value from platform)
        coalesce(platform_channel_raw, 'search') as platform_channel,

        -- Platform/source identifiers
        'google_ads' as platform,
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

-- Add internal IDs, canonical channel, and dedup
google_ads_enriched as (
    select
        tenant_id,
        date,
        date as report_date,
        source,
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

        -- Core metrics only (no derived business metrics)
        spend,
        impressions,
        clicks,
        conversions,
        conversion_value,
        currency,

        -- Additional fields
        campaign_name,
        ad_group_name,
        ad_type,
        device,
        network,

        platform,
        airbyte_record_id,
        airbyte_emitted_at,

        -- Dedup: keep latest record per natural key
        row_number() over (
            partition by tenant_id, ad_account_id, campaign_id, ad_group_id, ad_id, date
            order by airbyte_emitted_at desc
        ) as _row_num

    from google_ads_with_tenant
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
        tenant_id, '|', 'google_ads', '|',
        ad_account_id, '|', campaign_id, '|',
        coalesce(ad_group_id, ''), '|', coalesce(ad_id, ''), '|',
        date::text
    )) as record_sk,

    -- Source tracking
    'google_ads' as source_system,
    concat(
        ad_account_id, '|', campaign_id, '|',
        coalesce(ad_group_id, ''), '|', coalesce(ad_id, ''), '|',
        date::text
    ) as source_primary_key,

    -- All staging columns
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
    campaign_name,
    ad_group_name,
    ad_type,
    device,
    network,
    platform,
    airbyte_record_id,
    airbyte_emitted_at

from google_ads_enriched
where _row_num = 1
    {% if is_incremental() %}
    and date >= current_date - {{ get_lookback_days('google_ads') }}
    {% endif %}
