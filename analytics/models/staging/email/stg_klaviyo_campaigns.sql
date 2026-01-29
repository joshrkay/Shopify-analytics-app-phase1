{{
    config(
        materialized='incremental',
        schema='staging',
        unique_key=['tenant_id', 'campaign_id', 'report_date'],
        incremental_strategy='delete+insert'
    )
}}

{#
    Staging model for Klaviyo campaign metrics aggregated from events.

    This model:
    - Aggregates Klaviyo events to campaign-level daily metrics
    - Provides standard email marketing KPIs (open rate, click rate, etc.)
    - Includes revenue attribution for ROI calculation
    - Maps to canonical channel taxonomy

    Output metrics:
    - sends, deliveries, opens, unique_opens, clicks, unique_clicks
    - bounces, spam_complaints, unsubscribes
    - conversions, revenue
    - Calculated rates: delivery_rate, open_rate, click_rate, conversion_rate
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

        -- Event counts
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
),

campaign_metrics_with_rates as (
    select
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

        -- Raw counts
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

        -- Calculated rates (as percentages)
        -- Delivery rate: deliveries / sends
        case
            when sends > 0 then round((deliveries::numeric / sends) * 100, 2)
            else null
        end as delivery_rate,

        -- Open rate: unique_opens / deliveries
        case
            when deliveries > 0 then round((unique_opens::numeric / deliveries) * 100, 2)
            else null
        end as open_rate,

        -- Click rate: unique_clicks / deliveries
        case
            when deliveries > 0 then round((unique_clicks::numeric / deliveries) * 100, 2)
            else null
        end as click_rate,

        -- Click-to-open rate: unique_clicks / unique_opens
        case
            when unique_opens > 0 then round((unique_clicks::numeric / unique_opens) * 100, 2)
            else null
        end as click_to_open_rate,

        -- Bounce rate: bounces / sends
        case
            when sends > 0 then round((bounces::numeric / sends) * 100, 2)
            else null
        end as bounce_rate,

        -- Unsubscribe rate: unsubscribes / deliveries
        case
            when deliveries > 0 then round((unsubscribes::numeric / deliveries) * 100, 2)
            else null
        end as unsubscribe_rate,

        -- Spam complaint rate: spam_complaints / deliveries
        case
            when deliveries > 0 then round((spam_complaints::numeric / deliveries) * 100, 2)
            else null
        end as spam_rate,

        -- Conversion rate: conversions / unique_clicks
        case
            when unique_clicks > 0 then round((conversions::numeric / unique_clicks) * 100, 2)
            else null
        end as conversion_rate,

        -- Revenue per email (RPE): revenue / deliveries
        case
            when deliveries > 0 then round(revenue / deliveries, 4)
            else null
        end as revenue_per_email,

        -- Platform identifier
        'klaviyo' as platform,

        -- Metadata
        airbyte_emitted_at

    from campaign_daily_metrics
)

select
    tenant_id,
    campaign_id,
    campaign_name,
    report_date,
    source,
    internal_campaign_id,
    platform_channel,
    canonical_channel,
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
    revenue,
    currency,
    delivery_rate,
    open_rate,
    click_rate,
    click_to_open_rate,
    bounce_rate,
    unsubscribe_rate,
    spam_rate,
    conversion_rate,
    revenue_per_email,
    platform,
    airbyte_emitted_at
from campaign_metrics_with_rates
where tenant_id is not null
    and campaign_id is not null
    and report_date is not null
