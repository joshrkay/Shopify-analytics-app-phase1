{{
    config(
        materialized='incremental',
        schema='staging',
        unique_key=['tenant_id', 'event_id'],
        incremental_strategy='delete+insert',
        enabled=var('enable_klaviyo', true)
    )
}}

{#
    Staging model for Klaviyo email events with normalized fields and tenant isolation.

    This model:
    - Extracts and normalizes raw Klaviyo event data from Airbyte
    - Tracks message-level email events (sent, delivered, opened, clicked, bounced, etc.)
    - Supports campaign and flow attribution
    - Includes revenue attribution for conversion events
    - Supports incremental processing with configurable lookback window
    - Excludes PII fields (email addresses are hashed)
    - Returns empty result if source table doesn't exist yet

    Event Types:
    - Received Email: Email was delivered to inbox
    - Opened Email: Recipient opened the email
    - Clicked Email: Recipient clicked a link in the email
    - Bounced Email: Email bounced (hard or soft)
    - Marked Email as Spam: Recipient marked as spam
    - Unsubscribed: Recipient unsubscribed
    - Placed Order: Conversion event with revenue attribution

    Required output columns (email staging contract):
    - tenant_id, event_id, event_type, event_timestamp, report_date
    - campaign_id, campaign_name, flow_id, flow_name
    - profile_id_hash (hashed for privacy)
    - revenue, currency (for conversion events)
#}

-- Check if source table exists; if not, return empty result set
{% if not source_exists('airbyte_raw', '_airbyte_raw_klaviyo_events') %}

select
    cast(null as text) as tenant_id,
    cast(null as text) as event_id,
    cast(null as text) as event_type,
    cast(null as text) as event_type_raw,
    cast(null as timestamp) as event_timestamp,
    cast(null as date) as report_date,
    cast(null as text) as source,
    cast(null as text) as profile_id_hash,
    cast(null as text) as campaign_id,
    cast(null as text) as campaign_name,
    cast(null as text) as message_id,
    cast(null as text) as flow_id,
    cast(null as text) as flow_name,
    cast(null as text) as flow_message_id,
    cast(null as text) as attribution_source,
    cast(null as text) as internal_campaign_id,
    cast(null as text) as platform_channel,
    cast(null as text) as canonical_channel,
    cast(null as text) as email_subject,
    cast(null as text) as list_name,
    cast(null as text) as clicked_url,
    cast(null as text) as bounce_type,
    cast(null as numeric) as revenue,
    cast(null as text) as currency,
    cast(null as text) as order_id,
    cast(null as text) as platform,
    cast(null as text) as metric_id,
    cast(null as text) as airbyte_record_id,
    cast(null as timestamp) as airbyte_emitted_at
where 1=0

{% else %}

with raw_klaviyo_events as (
    select
        _airbyte_ab_id as airbyte_record_id,
        _airbyte_emitted_at as airbyte_emitted_at,
        _airbyte_data as event_data
    from {{ source('airbyte_raw', '_airbyte_raw_klaviyo_events') }}
    {% if is_incremental() %}
    where _airbyte_emitted_at >= current_timestamp - interval '{{ var("klaviyo_lookback_days", 3) }} days'
    {% endif %}
),

klaviyo_events_extracted as (
    select
        raw.airbyte_record_id,
        raw.airbyte_emitted_at,
        raw.event_data->>'id' as event_id_raw,
        raw.event_data->>'type' as event_type_raw,
        raw.event_data->>'datetime' as event_timestamp_raw,
        raw.event_data->'attributes'->>'metric_id' as metric_id,
        raw.event_data->'attributes'->>'profile_id' as profile_id_raw,
        -- Campaign attribution
        raw.event_data->'attributes'->'attribution'->>'campaign_id' as campaign_id_raw,
        raw.event_data->'attributes'->'attribution'->>'campaign_name' as campaign_name,
        raw.event_data->'attributes'->'attribution'->>'message_id' as message_id,
        -- Flow attribution
        raw.event_data->'attributes'->'attribution'->>'flow_id' as flow_id_raw,
        raw.event_data->'attributes'->'attribution'->>'flow_name' as flow_name,
        raw.event_data->'attributes'->'attribution'->>'flow_message_id' as flow_message_id,
        -- Event properties
        raw.event_data->'attributes'->'properties'->>'Subject' as email_subject,
        raw.event_data->'attributes'->'properties'->>'List' as list_name,
        raw.event_data->'attributes'->'properties'->>'URL' as clicked_url,
        raw.event_data->'attributes'->'properties'->>'Bounce Type' as bounce_type,
        -- Revenue attribution (for Placed Order events)
        raw.event_data->'attributes'->'properties'->>'$value' as revenue_raw,
        raw.event_data->'attributes'->'properties'->>'Currency' as currency_code,
        raw.event_data->'attributes'->'properties'->>'OrderId' as order_id
    from raw_klaviyo_events raw
),

klaviyo_events_normalized as (
    select
        -- Event identifiers
        case
            when event_id_raw is null or trim(event_id_raw) = '' then null
            else trim(event_id_raw)
        end as event_id,

        -- Normalize event type to standard taxonomy
        case
            when lower(event_type_raw) like '%received%' or lower(event_type_raw) like '%delivered%' then 'delivered'
            when lower(event_type_raw) like '%opened%' then 'opened'
            when lower(event_type_raw) like '%clicked%' then 'clicked'
            when lower(event_type_raw) like '%bounced%' then 'bounced'
            when lower(event_type_raw) like '%spam%' then 'spam_complaint'
            when lower(event_type_raw) like '%unsubscribed%' then 'unsubscribed'
            when lower(event_type_raw) like '%placed order%' or lower(event_type_raw) like '%conversion%' then 'converted'
            when lower(event_type_raw) like '%sent%' then 'sent'
            else coalesce(lower(event_type_raw), 'unknown')
        end as event_type,

        -- Original event type for reference
        event_type_raw as event_type_raw,

        -- Event timestamp
        case
            when event_timestamp_raw is null or trim(event_timestamp_raw) = '' then null
            when event_timestamp_raw ~ '^\d{4}-\d{2}-\d{2}'
                then event_timestamp_raw::timestamp
            else null
        end as event_timestamp,

        -- Report date (date portion of timestamp)
        case
            when event_timestamp_raw is null or trim(event_timestamp_raw) = '' then null
            when event_timestamp_raw ~ '^\d{4}-\d{2}-\d{2}'
                then event_timestamp_raw::date
            else null
        end as report_date,

        -- Profile ID (hashed for privacy)
        case
            when profile_id_raw is null or trim(profile_id_raw) = '' then null
            else md5(trim(profile_id_raw))
        end as profile_id_hash,

        -- Campaign attribution
        case
            when campaign_id_raw is null or trim(campaign_id_raw) = '' then null
            else trim(campaign_id_raw)
        end as campaign_id,
        campaign_name,
        message_id,

        -- Flow attribution
        case
            when flow_id_raw is null or trim(flow_id_raw) = '' then null
            else trim(flow_id_raw)
        end as flow_id,
        flow_name,
        flow_message_id,

        -- Determine attribution source
        case
            when campaign_id_raw is not null and trim(campaign_id_raw) != '' then 'campaign'
            when flow_id_raw is not null and trim(flow_id_raw) != '' then 'flow'
            else 'other'
        end as attribution_source,

        -- Email details
        email_subject,
        list_name,
        clicked_url,
        bounce_type,

        -- Revenue attribution (for conversion events)
        case
            when revenue_raw is null or trim(revenue_raw) = '' then 0.0
            when trim(revenue_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$'
                then least(greatest(trim(revenue_raw)::numeric, 0.0), 999999999.99)
            else 0.0
        end as revenue,

        -- Currency: standardize to uppercase
        case
            when currency_code is null or trim(currency_code) = '' then 'USD'
            when upper(trim(currency_code)) ~ '^[A-Z]{3}$'
                then upper(trim(currency_code))
            else 'USD'
        end as currency,

        -- Order reference
        order_id,

        -- Platform identifiers
        'klaviyo' as platform,
        'klaviyo' as source,

        -- Metadata
        metric_id,
        airbyte_record_id,
        airbyte_emitted_at

    from klaviyo_events_extracted
),

-- Join to tenant mapping to get tenant_id
klaviyo_events_with_tenant as (
    select
        events.*,
        coalesce(
            (select tenant_id
             from {{ ref('_tenant_airbyte_connections') }}
             where source_type = 'source-klaviyo'
               and status = 'active'
               and is_enabled = true
             limit 1),
            null
        ) as tenant_id
    from klaviyo_events_normalized events
),

-- Add internal IDs and canonical channel
klaviyo_events_final as (
    select
        -- Tenant ID (required for multi-tenant isolation)
        tenant_id,

        -- Event identifiers
        event_id,
        event_type,
        event_type_raw,
        event_timestamp,
        report_date,

        -- Source identifier
        source,

        -- Profile (hashed)
        profile_id_hash,

        -- Campaign/Flow attribution
        campaign_id,
        campaign_name,
        message_id,
        flow_id,
        flow_name,
        flow_message_id,
        attribution_source,

        -- Internal IDs (Option B ID normalization)
        case
            when campaign_id is not null then
                {{ generate_internal_id('tenant_id', 'source', 'campaign_id') }}
            when flow_id is not null then
                {{ generate_internal_id('tenant_id', 'source', 'flow_id') }}
            else null
        end as internal_campaign_id,

        -- Channel taxonomy
        'email' as platform_channel,
        'email' as canonical_channel,

        -- Email details
        email_subject,
        list_name,
        clicked_url,
        bounce_type,

        -- Revenue (for conversion events)
        revenue,
        currency,
        order_id,

        -- Platform identifier
        platform,
        metric_id,

        -- Metadata
        airbyte_record_id,
        airbyte_emitted_at

    from klaviyo_events_with_tenant
)

select
    tenant_id,
    event_id,
    event_type,
    event_type_raw,
    event_timestamp,
    report_date,
    source,
    profile_id_hash,
    campaign_id,
    campaign_name,
    message_id,
    flow_id,
    flow_name,
    flow_message_id,
    attribution_source,
    internal_campaign_id,
    platform_channel,
    canonical_channel,
    email_subject,
    list_name,
    clicked_url,
    bounce_type,
    revenue,
    currency,
    order_id,
    platform,
    metric_id,
    airbyte_record_id,
    airbyte_emitted_at
from klaviyo_events_final
where tenant_id is not null
    and event_id is not null
    and event_timestamp is not null
    {% if is_incremental() %}
    and report_date >= current_date - {{ var("klaviyo_lookback_days", 3) }}
    {% endif %}

{% endif %}
