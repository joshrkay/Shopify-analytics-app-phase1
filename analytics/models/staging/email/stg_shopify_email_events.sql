{{
    config(
        materialized='incremental',
        schema='staging',
        unique_key=['tenant_id', 'activity_id'],
        incremental_strategy='delete+insert',
        enabled=var('enable_shopify_email', true)
    )
}}

{#
    Staging model for Shopify Email marketing events with normalized fields and tenant isolation.

    This model:
    - Extracts and normalizes Shopify Email marketing activity data
    - Tracks message-level email events (sent, delivered, opened, clicked, etc.)
    - Supports campaign attribution
    - Includes revenue attribution for conversion events
    - Supports incremental processing with configurable lookback window
    - Excludes PII fields (email addresses are hashed)
    - Returns empty result if source table doesn't exist yet

    Shopify Email Activity Types:
    - email_sent: Email was sent
    - email_delivered: Email was delivered
    - email_opened: Recipient opened the email
    - email_clicked: Recipient clicked a link
    - email_bounced: Email bounced
    - email_marked_as_spam: Recipient marked as spam
    - email_unsubscribed: Recipient unsubscribed

    Required output columns (email staging contract):
    - tenant_id, activity_id, event_type, event_timestamp, report_date
    - campaign_id, campaign_name
    - customer_id_hash (hashed for privacy)
    - revenue, currency (for conversion events)
#}

-- Check if source table exists; if not, return empty result set
{% if not source_exists('airbyte_raw', '_airbyte_raw_shopify_email_activities') %}

select
    cast(null as text) as tenant_id,
    cast(null as text) as activity_id,
    cast(null as text) as event_type,
    cast(null as text) as event_type_raw,
    cast(null as timestamp) as event_timestamp,
    cast(null as date) as report_date,
    cast(null as text) as source,
    cast(null as text) as customer_id_hash,
    cast(null as text) as campaign_id,
    cast(null as text) as campaign_name,
    cast(null as text) as marketing_channel,
    cast(null as text) as internal_campaign_id,
    cast(null as text) as platform_channel,
    cast(null as text) as canonical_channel,
    cast(null as text) as email_subject,
    cast(null as text) as clicked_url,
    cast(null as text) as bounce_type,
    cast(null as numeric) as revenue,
    cast(null as text) as currency,
    cast(null as text) as order_id,
    cast(null as text) as platform,
    cast(null as text) as airbyte_record_id,
    cast(null as timestamp) as airbyte_emitted_at
where 1=0

{% else %}

with raw_shopify_email as (
    select
        _airbyte_ab_id as airbyte_record_id,
        _airbyte_emitted_at as airbyte_emitted_at,
        _airbyte_data as activity_data
    from {{ source('airbyte_raw', '_airbyte_raw_shopify_email_activities') }}
    {% if is_incremental() %}
    where _airbyte_emitted_at >= current_timestamp - interval '{{ var("shopify_email_lookback_days", 3) }} days'
    {% endif %}
),

shopify_email_extracted as (
    select
        raw.airbyte_record_id,
        raw.airbyte_emitted_at,
        raw.activity_data->>'id' as activity_id_raw,
        raw.activity_data->>'activity_type' as activity_type_raw,
        raw.activity_data->>'occurred_at' as event_timestamp_raw,
        -- Campaign attribution
        raw.activity_data->'marketing_activity'->>'id' as campaign_id_raw,
        raw.activity_data->'marketing_activity'->>'title' as campaign_name,
        raw.activity_data->'marketing_activity'->>'marketing_channel' as marketing_channel,
        -- Customer (recipient) info
        raw.activity_data->'recipient'->>'email' as recipient_email_raw,
        raw.activity_data->'recipient'->>'customer_id' as customer_id_raw,
        -- Email details
        raw.activity_data->>'subject' as email_subject,
        raw.activity_data->>'url' as clicked_url,
        raw.activity_data->>'bounce_type' as bounce_type,
        -- Revenue attribution
        raw.activity_data->'attributed_order'->>'total_price' as revenue_raw,
        raw.activity_data->'attributed_order'->>'currency' as currency_code,
        raw.activity_data->'attributed_order'->>'id' as order_id
    from raw_shopify_email raw
),

shopify_email_normalized as (
    select
        -- Activity identifiers
        case
            when activity_id_raw is null or trim(activity_id_raw) = '' then null
            else trim(activity_id_raw)
        end as activity_id,

        -- Normalize event type to standard taxonomy
        case
            when lower(activity_type_raw) like '%sent%' then 'sent'
            when lower(activity_type_raw) like '%delivered%' then 'delivered'
            when lower(activity_type_raw) like '%opened%' or lower(activity_type_raw) like '%open%' then 'opened'
            when lower(activity_type_raw) like '%clicked%' or lower(activity_type_raw) like '%click%' then 'clicked'
            when lower(activity_type_raw) like '%bounced%' or lower(activity_type_raw) like '%bounce%' then 'bounced'
            when lower(activity_type_raw) like '%spam%' then 'spam_complaint'
            when lower(activity_type_raw) like '%unsubscribed%' or lower(activity_type_raw) like '%unsubscribe%' then 'unsubscribed'
            when lower(activity_type_raw) like '%conversion%' or lower(activity_type_raw) like '%purchase%' then 'converted'
            else coalesce(lower(activity_type_raw), 'unknown')
        end as event_type,

        -- Original event type for reference
        activity_type_raw as event_type_raw,

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

        -- Customer ID (hashed for privacy)
        case
            when customer_id_raw is null or trim(customer_id_raw) = '' then
                case
                    when recipient_email_raw is not null and trim(recipient_email_raw) != '' then
                        md5(lower(trim(recipient_email_raw)))
                    else null
                end
            else md5(trim(customer_id_raw))
        end as customer_id_hash,

        -- Campaign attribution
        case
            when campaign_id_raw is null or trim(campaign_id_raw) = '' then null
            else trim(campaign_id_raw)
        end as campaign_id,
        campaign_name,
        marketing_channel,

        -- Email details
        email_subject,
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
        'shopify_email' as platform,
        'shopify_email' as source,

        -- Metadata
        airbyte_record_id,
        airbyte_emitted_at

    from shopify_email_extracted
),

-- Join to tenant mapping to get tenant_id
shopify_email_with_tenant as (
    select
        events.*,
        coalesce(
            (select tenant_id
             from {{ ref('_tenant_airbyte_connections') }}
             where source_type = 'source-shopify'
               and status = 'active'
               and is_enabled = true
             limit 1),
            null
        ) as tenant_id
    from shopify_email_normalized events
),

-- Add internal IDs and canonical channel
shopify_email_final as (
    select
        -- Tenant ID (required for multi-tenant isolation)
        tenant_id,

        -- Activity identifiers
        activity_id,
        event_type,
        event_type_raw,
        event_timestamp,
        report_date,

        -- Source identifier
        source,

        -- Customer (hashed)
        customer_id_hash,

        -- Campaign attribution
        campaign_id,
        campaign_name,
        marketing_channel,

        -- Internal IDs (Option B ID normalization)
        case
            when campaign_id is not null then
                {{ generate_internal_id('tenant_id', 'source', 'campaign_id') }}
            else null
        end as internal_campaign_id,

        -- Channel taxonomy
        'email' as platform_channel,
        'email' as canonical_channel,

        -- Email details
        email_subject,
        clicked_url,
        bounce_type,

        -- Revenue (for conversion events)
        revenue,
        currency,
        order_id,

        -- Platform identifier
        platform,

        -- Metadata
        airbyte_record_id,
        airbyte_emitted_at

    from shopify_email_with_tenant
)

select
    tenant_id,
    activity_id,
    event_type,
    event_type_raw,
    event_timestamp,
    report_date,
    source,
    customer_id_hash,
    campaign_id,
    campaign_name,
    marketing_channel,
    internal_campaign_id,
    platform_channel,
    canonical_channel,
    email_subject,
    clicked_url,
    bounce_type,
    revenue,
    currency,
    order_id,
    platform,
    airbyte_record_id,
    airbyte_emitted_at
from shopify_email_final
where tenant_id is not null
    and activity_id is not null
    and event_timestamp is not null
    {% if is_incremental() %}
    and report_date >= current_date - {{ var("shopify_email_lookback_days", 3) }}
    {% endif %}

{% endif %}
