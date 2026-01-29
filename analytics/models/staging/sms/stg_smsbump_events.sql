{{
    config(
        materialized='incremental',
        schema='staging',
        unique_key=['tenant_id', 'event_id'],
        incremental_strategy='delete+insert',
        enabled=var('enable_smsbump', true)
    )
}}

{#
    Staging model for SMSBump (Yotpo SMSBump) events with normalized fields and tenant isolation.

    This model:
    - Extracts and normalizes raw SMSBump event data from Airbyte
    - Tracks message-level SMS events (sent, delivered, clicked, etc.)
    - Supports campaign and flow attribution
    - Includes revenue attribution for conversion events
    - Supports incremental processing with configurable lookback window
    - Excludes PII fields (phone numbers are hashed)
    - Returns empty result if source table doesn't exist yet

    Event Types:
    - message_sent: SMS was sent
    - message_delivered: SMS was delivered
    - message_clicked: Recipient clicked a link
    - message_failed: SMS failed to send
    - opt_out: Recipient opted out
    - conversion: Attributed purchase

    Required output columns (SMS staging contract):
    - tenant_id, event_id, event_type, event_timestamp, report_date
    - campaign_id, campaign_name, flow_id, flow_name
    - subscriber_id_hash (hashed for privacy)
    - revenue, currency (for conversion events)
#}

-- Check if source table exists; if not, return empty result set
{% if not source_exists('airbyte_raw', '_airbyte_raw_smsbump_events') %}

select
    cast(null as text) as tenant_id,
    cast(null as text) as event_id,
    cast(null as text) as event_type,
    cast(null as text) as event_type_raw,
    cast(null as timestamp) as event_timestamp,
    cast(null as date) as report_date,
    cast(null as text) as source,
    cast(null as text) as subscriber_id_hash,
    cast(null as text) as campaign_id,
    cast(null as text) as campaign_name,
    cast(null as text) as message_id,
    cast(null as text) as flow_id,
    cast(null as text) as flow_name,
    cast(null as text) as step_id,
    cast(null as text) as attribution_source,
    cast(null as text) as internal_campaign_id,
    cast(null as text) as platform_channel,
    cast(null as text) as canonical_channel,
    cast(null as text) as list_id,
    cast(null as text) as list_name,
    cast(null as text) as clicked_url,
    cast(null as text) as delivery_status,
    cast(null as text) as error_message,
    cast(null as text) as carrier,
    cast(null as numeric) as revenue,
    cast(null as text) as currency,
    cast(null as text) as order_id,
    cast(null as text) as order_name,
    cast(null as text) as platform,
    cast(null as text) as airbyte_record_id,
    cast(null as timestamp) as airbyte_emitted_at
where 1=0

{% else %}

with raw_smsbump_events as (
    select
        _airbyte_ab_id as airbyte_record_id,
        _airbyte_emitted_at as airbyte_emitted_at,
        _airbyte_data as event_data
    from {{ source('airbyte_raw', '_airbyte_raw_smsbump_events') }}
    {% if is_incremental() %}
    where _airbyte_emitted_at >= current_timestamp - interval '{{ var("smsbump_lookback_days", 3) }} days'
    {% endif %}
),

smsbump_events_extracted as (
    select
        raw.airbyte_record_id,
        raw.airbyte_emitted_at,
        raw.event_data->>'id' as event_id_raw,
        raw.event_data->>'type' as event_type_raw,
        raw.event_data->>'created_at' as event_timestamp_raw,
        -- Subscriber info
        raw.event_data->'subscriber'->>'id' as subscriber_id_raw,
        raw.event_data->'subscriber'->>'phone' as phone_raw,
        -- Campaign attribution
        raw.event_data->'message'->>'campaign_id' as campaign_id_raw,
        raw.event_data->'message'->>'campaign_name' as campaign_name,
        raw.event_data->'message'->>'message_id' as message_id,
        -- Flow attribution (SMSBump uses flows for automations)
        raw.event_data->'message'->>'flow_id' as flow_id_raw,
        raw.event_data->'message'->>'flow_name' as flow_name,
        raw.event_data->'message'->>'step_id' as step_id,
        -- Message details
        raw.event_data->'message'->>'content' as message_content,
        raw.event_data->'message'->>'short_url' as clicked_url,
        raw.event_data->'message'->>'list_id' as list_id,
        raw.event_data->'message'->>'list_name' as list_name,
        -- Delivery info
        raw.event_data->'delivery'->>'status' as delivery_status,
        raw.event_data->'delivery'->>'error' as error_message,
        raw.event_data->'delivery'->>'carrier' as carrier,
        -- Revenue attribution
        raw.event_data->'attribution'->>'revenue' as revenue_raw,
        raw.event_data->'attribution'->>'currency' as currency_code,
        raw.event_data->'attribution'->>'order_id' as order_id,
        raw.event_data->'attribution'->>'order_name' as order_name
    from raw_smsbump_events raw
),

smsbump_events_normalized as (
    select
        -- Event identifiers
        case
            when event_id_raw is null or trim(event_id_raw) = '' then null
            else trim(event_id_raw)
        end as event_id,

        -- Normalize event type to standard taxonomy
        case
            when lower(event_type_raw) like '%sent%' then 'sent'
            when lower(event_type_raw) like '%delivered%' then 'delivered'
            when lower(event_type_raw) like '%clicked%' or lower(event_type_raw) like '%click%' then 'clicked'
            when lower(event_type_raw) like '%failed%' or lower(event_type_raw) like '%error%' or lower(event_type_raw) like '%undelivered%' then 'failed'
            when lower(event_type_raw) like '%opt%out%' or lower(event_type_raw) like '%unsubscribe%' or lower(event_type_raw) like '%stop%' then 'opted_out'
            when lower(event_type_raw) like '%replied%' or lower(event_type_raw) like '%reply%' or lower(event_type_raw) like '%inbound%' then 'replied'
            when lower(event_type_raw) like '%conversion%' or lower(event_type_raw) like '%purchase%' or lower(event_type_raw) like '%order%' or lower(event_type_raw) like '%revenue%' then 'converted'
            else coalesce(lower(event_type_raw), 'unknown')
        end as event_type,

        -- Original event type for reference
        event_type_raw as event_type_raw,

        -- Event timestamp
        case
            when event_timestamp_raw is null or trim(event_timestamp_raw) = '' then null
            when event_timestamp_raw ~ '^\d{4}-\d{2}-\d{2}'
                then event_timestamp_raw::timestamp
            when event_timestamp_raw ~ '^\d+$'
                then to_timestamp(event_timestamp_raw::bigint)
            else null
        end as event_timestamp,

        -- Report date (date portion of timestamp)
        case
            when event_timestamp_raw is null or trim(event_timestamp_raw) = '' then null
            when event_timestamp_raw ~ '^\d{4}-\d{2}-\d{2}'
                then event_timestamp_raw::date
            when event_timestamp_raw ~ '^\d+$'
                then to_timestamp(event_timestamp_raw::bigint)::date
            else null
        end as report_date,

        -- Subscriber ID (hashed for privacy)
        case
            when subscriber_id_raw is not null and trim(subscriber_id_raw) != '' then
                md5(trim(subscriber_id_raw))
            when phone_raw is not null and trim(phone_raw) != '' then
                md5(trim(phone_raw))
            else null
        end as subscriber_id_hash,

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
        step_id,

        -- Determine attribution source
        case
            when campaign_id_raw is not null and trim(campaign_id_raw) != '' then 'campaign'
            when flow_id_raw is not null and trim(flow_id_raw) != '' then 'flow'
            else 'other'
        end as attribution_source,

        -- List info
        list_id,
        list_name,

        -- Message details
        clicked_url,

        -- Delivery info
        delivery_status,
        error_message,
        carrier,

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
        order_name,

        -- Platform identifiers
        'smsbump' as platform,
        'smsbump' as source,

        -- Metadata
        airbyte_record_id,
        airbyte_emitted_at

    from smsbump_events_extracted
),

-- Join to tenant mapping to get tenant_id
smsbump_events_with_tenant as (
    select
        events.*,
        coalesce(
            (select tenant_id
             from {{ ref('_tenant_airbyte_connections') }}
             where source_type = 'source-smsbump'
               and status = 'active'
               and is_enabled = true
             limit 1),
            null
        ) as tenant_id
    from smsbump_events_normalized events
),

-- Add internal IDs and canonical channel
smsbump_events_final as (
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

        -- Subscriber (hashed)
        subscriber_id_hash,

        -- Campaign/Flow attribution
        campaign_id,
        campaign_name,
        message_id,
        flow_id,
        flow_name,
        step_id,
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
        'sms' as platform_channel,
        'sms' as canonical_channel,

        -- List info
        list_id,
        list_name,

        -- Message details
        clicked_url,

        -- Delivery info
        delivery_status,
        error_message,
        carrier,

        -- Revenue (for conversion events)
        revenue,
        currency,
        order_id,
        order_name,

        -- Platform identifier
        platform,

        -- Metadata
        airbyte_record_id,
        airbyte_emitted_at

    from smsbump_events_with_tenant
)

select
    tenant_id,
    event_id,
    event_type,
    event_type_raw,
    event_timestamp,
    report_date,
    source,
    subscriber_id_hash,
    campaign_id,
    campaign_name,
    message_id,
    flow_id,
    flow_name,
    step_id,
    attribution_source,
    internal_campaign_id,
    platform_channel,
    canonical_channel,
    list_id,
    list_name,
    clicked_url,
    delivery_status,
    error_message,
    carrier,
    revenue,
    currency,
    order_id,
    order_name,
    platform,
    airbyte_record_id,
    airbyte_emitted_at
from smsbump_events_final
where tenant_id is not null
    and event_id is not null
    and event_timestamp is not null
    {% if is_incremental() %}
    and report_date >= current_date - {{ var("smsbump_lookback_days", 3) }}
    {% endif %}

{% endif %}
