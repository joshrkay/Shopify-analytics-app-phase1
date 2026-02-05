{{
    config(
        materialized='incremental',
        schema='staging',
        unique_key='record_sk',
        incremental_strategy='delete+insert'
    )
}}

{#
    Staging model for email campaign metrics aggregated from Klaviyo events.

    This model:
    - Aggregates Klaviyo events to campaign-level daily metrics
    - Adds record_sk (stable surrogate key), source_system, source_primary_key
    - Provides raw count metrics only (sends, deliveries, opens, clicks, etc.)
    - Includes revenue attribution for conversion events
    - Maps to canonical channel taxonomy
    - Does NOT calculate derived rates (open_rate, click_rate, etc.) - deferred to canonical layer

    SECURITY: Tenant isolation enforced via upstream stg_klaviyo_events.
#}

with klaviyo_events as (
    select *
    from {{ ref('stg_klaviyo_events') }}
    where attribution_source = 'campaign'
      and campaign_id is not null
    {% if is_incremental() %}
      and report_date >= current_date - {{ var("klaviyo_lookback_days", 3) }}
    {% endif %}
),

campaign_daily_metrics as (
    select
        tenant_id,
        campaign_id,
        campaign_name,
        report_date,
        source,
        currency,
        internal_campaign_id,

        -- Event counts (raw metrics only)
        count(case when event_type = 'sent' then 1 end) as sends,
        count(case when event_type = 'delivered' then 1 end) as deliveries,
        count(case when event_type = 'opened' then 1 end) as opens,
        count(distinct case when event_type = 'opened' then profile_id_hash end) as unique_opens,
        count(case when event_type = 'clicked' then 1 end) as clicks,
        count(distinct case when event_type = 'clicked' then profile_id_hash end) as unique_clicks,
        count(case when event_type = 'bounced' then 1 end) as bounces,
        count(case when event_type = 'spam_complaint' then 1 end) as spam_complaints,
        count(case when event_type = 'unsubscribed' then 1 end) as unsubscribes,
        count(case when event_type = 'converted' then 1 end) as conversions,

        -- Revenue
        sum(case when event_type = 'converted' then revenue else 0 end) as revenue,

        -- Unique recipients (approximation from events)
        count(distinct profile_id_hash) as unique_recipients,

        -- Metadata
        max(airbyte_emitted_at) as airbyte_emitted_at

    from klaviyo_events
    group by
        tenant_id,
        campaign_id,
        campaign_name,
        report_date,
        source,
        currency,
        internal_campaign_id
)

select
    -- Surrogate key: md5(tenant_id || source_system || source_primary_key)
    md5(concat(
        tenant_id, '|', 'klaviyo', '|',
        campaign_id, '|', report_date::text
    )) as record_sk,

    -- Source tracking
    'klaviyo' as source_system,
    concat(campaign_id, '|', report_date::text) as source_primary_key,

    -- Identifiers
    tenant_id,
    campaign_id,
    campaign_name,
    report_date,
    source,
    internal_campaign_id,

    -- Channel taxonomy
    'email' as platform_channel,
    'email' as canonical_channel,

    -- Raw count metrics (no derived rates - deferred to canonical/semantic layer)
    sends,
    deliveries,
    opens,
    unique_opens,
    clicks,
    unique_clicks,
    bounces,
    spam_complaints,
    unsubscribes,
    conversions,
    unique_recipients,

    -- Revenue
    revenue,
    currency,

    -- Platform identifier
    'klaviyo' as platform,

    -- Metadata
    airbyte_emitted_at

from campaign_daily_metrics
where tenant_id is not null
    and campaign_id is not null
    and report_date is not null
