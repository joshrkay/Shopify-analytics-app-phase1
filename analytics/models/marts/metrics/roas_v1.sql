{{
    config(
        materialized='table',
        schema='marts',
        tags=['marts', 'metrics', 'roas', 'v1', 'versioned']
    )
}}

-- =============================================================================
-- ROAS v1 - Return on Ad Spend (Versioned Metric)
-- =============================================================================
--
-- METRIC REGISTRY: metrics/metric_registry.yaml
-- DEFINITION: SUM(revenue) / SUM(spend)
-- STATUS: active
-- APPROVAL: ANALYTICS-001 (2026-02-04)
--
-- This is a VERSIONED metric model. Changes to the calculation formula
-- require a new version (v2, v3, etc.) - never modify this file.
--
-- EDGE CASES:
--   - Zero spend: Returns 0 (not NULL or infinity)
--   - Null spend: Treated as 0
--   - Negative revenue: Included (reflects refunds)
--   - Multi-currency: Calculated separately per currency
--
-- DRILL-DOWN: channel -> campaign -> adset
-- TENANT ISOLATION: Enforced via tenant_id filter
--
-- =============================================================================

{% set metric_name = 'roas' %}
{% set metric_version = 'v1' %}

-- -----------------------------------------------------------------------------
-- SOURCE: Ad Spend from fact_ad_spend
-- -----------------------------------------------------------------------------
with ad_spend as (
    select
        tenant_id,
        date,
        source_platform,
        channel,
        campaign_id,
        adset_id,
        currency,
        sum(spend) as spend,
        sum(impressions) as impressions,
        sum(clicks) as clicks,
        sum(conversions) as conversions,
        sum(conversion_value) as conversion_value
    from {{ ref('fact_ad_spend') }}
    where tenant_id is not null
        and date is not null
        and spend is not null
        and spend >= 0  -- Exclude negative spend (data quality)
    group by 1, 2, 3, 4, 5, 6, 7
),

-- -----------------------------------------------------------------------------
-- SOURCE: Revenue from fact_orders
-- -----------------------------------------------------------------------------
orders_revenue as (
    select
        tenant_id,
        date,
        currency,
        sum(revenue_net) as revenue,
        count(distinct order_id) as order_count
    from {{ ref('fact_orders') }}
    where tenant_id is not null
        and date is not null
        and revenue_net is not null
    group by 1, 2, 3
),

-- -----------------------------------------------------------------------------
-- AGGREGATION: Channel Level (highest)
-- -----------------------------------------------------------------------------
channel_metrics as (
    select
        s.tenant_id,
        s.date,
        s.currency,
        s.channel,
        null::text as campaign_id,
        null::text as adset_id,
        'channel' as hierarchy_level,

        sum(s.spend) as total_spend,
        sum(s.impressions) as total_impressions,
        sum(s.clicks) as total_clicks,
        sum(s.conversions) as total_conversions,
        coalesce(r.revenue, 0) as total_revenue,
        coalesce(r.order_count, 0) as order_count

    from ad_spend s
    left join orders_revenue r
        on s.tenant_id = r.tenant_id
        and s.date = r.date
        and s.currency = r.currency
    group by s.tenant_id, s.date, s.currency, s.channel, r.revenue, r.order_count
),

-- -----------------------------------------------------------------------------
-- AGGREGATION: Campaign Level (middle)
-- -----------------------------------------------------------------------------
campaign_metrics as (
    select
        tenant_id,
        date,
        currency,
        channel,
        campaign_id,
        null::text as adset_id,
        'campaign' as hierarchy_level,

        sum(spend) as total_spend,
        sum(impressions) as total_impressions,
        sum(clicks) as total_clicks,
        sum(conversions) as total_conversions,
        sum(conversion_value) as total_revenue,  -- Use conversion_value at campaign level
        sum(conversions)::int as order_count     -- Use conversions as proxy

    from ad_spend
    where campaign_id is not null
    group by 1, 2, 3, 4, 5
),

-- -----------------------------------------------------------------------------
-- AGGREGATION: Adset Level (lowest)
-- -----------------------------------------------------------------------------
adset_metrics as (
    select
        tenant_id,
        date,
        currency,
        channel,
        campaign_id,
        adset_id,
        'adset' as hierarchy_level,

        sum(spend) as total_spend,
        sum(impressions) as total_impressions,
        sum(clicks) as total_clicks,
        sum(conversions) as total_conversions,
        sum(conversion_value) as total_revenue,  -- Use conversion_value at adset level
        sum(conversions)::int as order_count     -- Use conversions as proxy

    from ad_spend
    where campaign_id is not null
        and adset_id is not null
    group by 1, 2, 3, 4, 5, 6
),

-- -----------------------------------------------------------------------------
-- UNION: All hierarchy levels
-- -----------------------------------------------------------------------------
all_levels as (
    select * from channel_metrics
    union all
    select * from campaign_metrics
    union all
    select * from adset_metrics
),

-- -----------------------------------------------------------------------------
-- PERIOD AGGREGATIONS: daily, weekly, monthly, all_time
-- -----------------------------------------------------------------------------
daily_metrics as (
    select
        tenant_id,
        date as period_start,
        date as period_end,
        'daily' as period_type,
        currency,
        channel,
        campaign_id,
        adset_id,
        hierarchy_level,
        total_spend,
        total_revenue,
        order_count,
        total_impressions,
        total_clicks
    from all_levels
),

weekly_metrics as (
    select
        tenant_id,
        date_trunc('week', period_start)::date as period_start,
        (date_trunc('week', period_start) + interval '6 days')::date as period_end,
        'weekly' as period_type,
        currency,
        channel,
        campaign_id,
        adset_id,
        hierarchy_level,
        sum(total_spend) as total_spend,
        sum(total_revenue) as total_revenue,
        sum(order_count) as order_count,
        sum(total_impressions) as total_impressions,
        sum(total_clicks) as total_clicks
    from daily_metrics
    group by 1, 2, 3, 4, 5, 6, 7, 8, 9
),

monthly_metrics as (
    select
        tenant_id,
        date_trunc('month', period_start)::date as period_start,
        (date_trunc('month', period_start) + interval '1 month' - interval '1 day')::date as period_end,
        'monthly' as period_type,
        currency,
        channel,
        campaign_id,
        adset_id,
        hierarchy_level,
        sum(total_spend) as total_spend,
        sum(total_revenue) as total_revenue,
        sum(order_count) as order_count,
        sum(total_impressions) as total_impressions,
        sum(total_clicks) as total_clicks
    from daily_metrics
    group by 1, 2, 3, 4, 5, 6, 7, 8, 9
),

all_time_metrics as (
    select
        tenant_id,
        min(period_start) as period_start,
        max(period_end) as period_end,
        'all_time' as period_type,
        currency,
        channel,
        campaign_id,
        adset_id,
        hierarchy_level,
        sum(total_spend) as total_spend,
        sum(total_revenue) as total_revenue,
        sum(order_count) as order_count,
        sum(total_impressions) as total_impressions,
        sum(total_clicks) as total_clicks
    from daily_metrics
    group by 1, 4, 5, 6, 7, 8, 9
),

-- Union all periods
all_periods as (
    select * from daily_metrics
    union all
    select * from weekly_metrics
    union all
    select * from monthly_metrics
    union all
    select * from all_time_metrics
)

-- -----------------------------------------------------------------------------
-- FINAL OUTPUT: Versioned ROAS metric
-- -----------------------------------------------------------------------------
select
    -- Unique identifier
    md5(concat(
        tenant_id, '|',
        '{{ metric_version }}', '|',
        period_type, '|',
        coalesce(period_start::text, 'all_time'), '|',
        currency, '|',
        coalesce(channel, 'all'), '|',
        coalesce(campaign_id, 'all'), '|',
        coalesce(adset_id, 'all'), '|',
        hierarchy_level
    )) as id,

    -- Metric identification (CRITICAL for versioning)
    '{{ metric_name }}' as metric_name,
    '{{ metric_version }}' as metric_version,
    'active' as metric_status,

    -- Tenant isolation
    tenant_id,

    -- Time dimensions
    period_type,
    period_start,
    period_end,

    -- Currency
    currency,

    -- Drill-down hierarchy
    hierarchy_level,
    channel,
    campaign_id,
    adset_id,

    -- Raw metrics (for reconciliation with fact tables)
    total_spend,
    total_revenue,
    order_count,
    total_impressions,
    total_clicks,

    -- ==========================================================================
    -- CANONICAL ROAS (v1): SUM(revenue) / SUM(spend)
    -- ==========================================================================
    case
        when total_spend = 0 or total_spend is null then 0
        else round((total_revenue / total_spend)::numeric, 4)
    end as roas,

    -- Additional derived metrics
    case
        when total_clicks > 0 then round((total_spend / total_clicks)::numeric, 4)
        else 0
    end as cpc,

    case
        when total_impressions > 0 then round((total_spend / total_impressions * 1000)::numeric, 4)
        else 0
    end as cpm,

    case
        when total_impressions > 0 then round((total_clicks::numeric / total_impressions * 100)::numeric, 4)
        else 0
    end as ctr,

    case
        when order_count > 0 then round((total_revenue / order_count)::numeric, 2)
        else 0
    end as aov,

    -- Audit fields
    current_timestamp as dbt_updated_at

from all_periods
where tenant_id is not null

-- =============================================================================
-- VERSION HISTORY:
--   v1 (2026-02-04): Initial implementation
--       - Definition: SUM(revenue) / SUM(spend)
--       - Zero spend handling: Returns 0
--       - Multi-currency: Separate calculations per currency
--       - Drill-down: channel -> campaign -> adset
--
-- RECONCILIATION:
--   This metric reconciles with:
--     - fact_ad_spend: SUM(spend) matches total_spend
--     - fact_orders: SUM(revenue_net) matches total_revenue (at channel level)
--
-- GOVERNANCE:
--   - Approval: ANALYTICS-001
--   - Owner: data-team@company.com
--   - Breaking changes require new version
-- =============================================================================
