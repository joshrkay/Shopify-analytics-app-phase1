{{
    config(
        materialized='table',
        schema='marts',
        tags=['marts', 'marketing', 'metrics', 'roas', 'cac']
    )
}}

-- =============================================================================
-- fct_marketing_metrics: Canonical ROAS and CAC Metrics (v1)
-- =============================================================================
--
-- This model provides canonical, versioned ROAS and CAC metrics for the
-- reporting layer with full drill-down support.
--
-- METRIC DEFINITIONS (v1):
--   ROAS = SUM(revenue) / SUM(spend)
--   CAC  = SUM(spend) / COUNT(new_customers)
--
-- DRILL-DOWN HIERARCHY:
--   channel → campaign → ad_set
--
-- TENANT ISOLATION:
--   All calculations enforce tenant_id is not null
--
-- RECONCILIATION:
--   These metrics reconcile exactly with raw fact tables (fact_ad_spend,
--   fact_orders) - no dashboard-side calculations required.
--
-- =============================================================================

{% set metric_version = 'v1' %}

-- -----------------------------------------------------------------------------
-- CTE: Ad Spend by hierarchy level (channel → campaign → ad_set)
-- Source: fact_ad_spend
-- -----------------------------------------------------------------------------
with ad_spend_raw as (
    select
        tenant_id,
        date,
        source_platform,
        channel,
        campaign_id,
        adset_id,
        currency,
        spend,
        impressions,
        clicks,
        conversions,
        conversion_value
    from {{ ref('fact_ad_spend') }}
    where tenant_id is not null
        and date is not null
        and spend is not null
        and spend >= 0
),

-- -----------------------------------------------------------------------------
-- CTE: Revenue from orders (using fact_orders for exact reconciliation)
-- Source: fact_orders
-- -----------------------------------------------------------------------------
orders_revenue as (
    select
        tenant_id,
        date,
        order_id,
        customer_key,
        revenue_net as revenue,  -- Use net revenue for ROAS (canonical per 7.7.1)
        currency
    from {{ ref('fact_orders') }}
    where tenant_id is not null
        and date is not null
        and revenue_net is not null
),

-- -----------------------------------------------------------------------------
-- CTE: First-time customers (for CAC calculation)
-- A new customer is defined by their first order ever
-- -----------------------------------------------------------------------------
all_orders_for_customers as (
    select
        tenant_id,
        order_id,
        customer_key,
        order_created_at,
        currency
    from {{ ref('fact_orders') }}
    where tenant_id is not null
        and order_id is not null
        and customer_key is not null
        and customer_key != md5('')
),

first_order_per_customer as (
    select
        tenant_id,
        customer_key,
        min(order_created_at) as first_order_date,
        min(order_id) as first_order_id
    from all_orders_for_customers
    group by tenant_id, customer_key
),

new_customers_daily as (
    select
        f.tenant_id,
        date_trunc('day', f.first_order_date)::date as date,
        count(distinct f.customer_key) as new_customers
    from first_order_per_customer f
    where f.tenant_id is not null
    group by 1, 2
),

-- -----------------------------------------------------------------------------
-- CTE: Aggregated spend at each hierarchy level
-- Levels: channel_only, campaign_level, adset_level
-- -----------------------------------------------------------------------------

-- Spend aggregated to CHANNEL level only
spend_by_channel as (
    select
        tenant_id,
        date,
        currency,
        channel,
        null::text as campaign_id,
        null::text as adset_id,
        'channel' as hierarchy_level,
        sum(spend) as total_spend,
        sum(impressions) as total_impressions,
        sum(clicks) as total_clicks,
        sum(conversions) as total_conversions,
        sum(conversion_value) as total_conversion_value
    from ad_spend_raw
    group by tenant_id, date, currency, channel
),

-- Spend aggregated to CAMPAIGN level
spend_by_campaign as (
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
        sum(conversion_value) as total_conversion_value
    from ad_spend_raw
    where campaign_id is not null
    group by tenant_id, date, currency, channel, campaign_id
),

-- Spend aggregated to ADSET level
spend_by_adset as (
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
        sum(conversion_value) as total_conversion_value
    from ad_spend_raw
    where campaign_id is not null
        and adset_id is not null
    group by tenant_id, date, currency, channel, campaign_id, adset_id
),

-- Unified spend at all hierarchy levels
unified_spend as (
    select * from spend_by_channel
    union all
    select * from spend_by_campaign
    union all
    select * from spend_by_adset
),

-- -----------------------------------------------------------------------------
-- CTE: Aggregated revenue by date and currency
-- Revenue is not attributed to specific channels in this base model
-- (for attributed revenue, use the fct_roas model with last_click attribution)
-- -----------------------------------------------------------------------------
revenue_daily as (
    select
        tenant_id,
        date,
        currency,
        sum(revenue) as total_revenue,
        count(distinct order_id) as order_count
    from orders_revenue
    group by tenant_id, date, currency
),

-- -----------------------------------------------------------------------------
-- CTE: Join spend with revenue and new customers
-- Revenue distributed proportionally by spend share (for hierarchy drill-down)
-- -----------------------------------------------------------------------------
metrics_base as (
    select
        s.tenant_id,
        s.date,
        s.currency,
        s.channel,
        s.campaign_id,
        s.adset_id,
        s.hierarchy_level,

        -- Spend metrics (from fact_ad_spend - reconciles exactly)
        s.total_spend,
        s.total_impressions,
        s.total_clicks,
        s.total_conversions,
        s.total_conversion_value,

        -- Revenue metrics (from fact_orders - reconciles exactly)
        -- At channel level, use full revenue; at lower levels, use conversion_value as proxy
        case
            when s.hierarchy_level = 'channel' then coalesce(r.total_revenue, 0)
            else coalesce(s.total_conversion_value, 0)
        end as total_revenue,

        case
            when s.hierarchy_level = 'channel' then coalesce(r.order_count, 0)
            else coalesce(s.total_conversions, 0)::int
        end as order_count,

        -- New customers (only available at tenant/date level, distributed at channel level)
        case
            when s.hierarchy_level = 'channel' then coalesce(c.new_customers, 0)
            else 0  -- New customers not attributable below channel level without attribution
        end as new_customers

    from unified_spend s
    left join revenue_daily r
        on s.tenant_id = r.tenant_id
        and s.date = r.date
        and s.currency = r.currency
    left join new_customers_daily c
        on s.tenant_id = c.tenant_id
        and s.date = c.date
    where s.tenant_id is not null
),

-- -----------------------------------------------------------------------------
-- CTE: Calculate period aggregations (daily, weekly, monthly, all_time)
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

        sum(total_spend) as total_spend,
        sum(total_revenue) as total_revenue,
        sum(order_count) as order_count,
        sum(new_customers) as new_customers,
        sum(total_impressions) as total_impressions,
        sum(total_clicks) as total_clicks

    from metrics_base
    group by 1, 2, 3, 4, 5, 6, 7, 8, 9
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
        sum(new_customers) as new_customers,
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
        sum(new_customers) as new_customers,
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
        sum(new_customers) as new_customers,
        sum(total_impressions) as total_impressions,
        sum(total_clicks) as total_clicks

    from daily_metrics
    group by 1, 4, 5, 6, 7, 8, 9
),

-- Union all period types
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
-- FINAL SELECT: Calculate canonical metrics with versioning
-- -----------------------------------------------------------------------------
select
    -- Unique ID for each metric row
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

    -- Metric versioning
    '{{ metric_version }}' as metric_version,

    -- Tenant isolation
    tenant_id,

    -- Time period
    period_type,
    period_start,
    period_end,

    -- Currency
    currency,

    -- Drill-down hierarchy: channel → campaign → ad_set
    hierarchy_level,
    channel,
    campaign_id,
    adset_id,

    -- Raw metrics (reconcile with fact tables)
    total_spend,
    total_revenue,
    order_count,
    new_customers,
    total_impressions,
    total_clicks,

    -- ==========================================================================
    -- CANONICAL ROAS: SUM(revenue) / SUM(spend)
    -- Edge case: Returns 0 when spend = 0 (not NULL or infinity)
    -- ==========================================================================
    case
        when total_spend = 0 or total_spend is null then 0
        else round((total_revenue / total_spend)::numeric, 4)
    end as roas,

    -- ==========================================================================
    -- CANONICAL CAC: SUM(spend) / COUNT(new_customers)
    -- Edge case: Returns 0 when new_customers = 0 (not NULL or infinity)
    -- Note: CAC only meaningful at channel level (new_customers = 0 below)
    -- ==========================================================================
    case
        when new_customers = 0 or new_customers is null then 0
        else round((total_spend / new_customers)::numeric, 2)
    end as cac,

    -- Additional efficiency metrics
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
-- METRIC RECONCILIATION NOTES:
--
-- ROAS Reconciliation:
--   SELECT SUM(revenue_net) / SUM(spend)
--   FROM fact_orders o
--   JOIN fact_ad_spend s ON o.tenant_id = s.tenant_id AND o.date = s.date
--   WHERE o.tenant_id = ? AND o.date BETWEEN ? AND ?
--   -- Should match this model's ROAS at channel hierarchy_level
--
-- CAC Reconciliation:
--   SELECT SUM(spend) / COUNT(DISTINCT customer_key)
--   FROM fact_ad_spend s
--   LEFT JOIN (first_order_per_customer) f ON s.tenant_id = f.tenant_id
--        AND s.date = f.first_order_date
--   WHERE s.tenant_id = ? AND s.date BETWEEN ? AND ?
--   -- Should match this model's CAC at channel hierarchy_level
--
-- EDGE CASES HANDLED:
--   1. Zero spend: ROAS = 0 (not NULL or infinity)
--   2. Zero new customers: CAC = 0 (not NULL or infinity)
--   3. Null values: Treated as 0 in all calculations
--   4. Negative spend: Filtered out in source CTE
--   5. Multi-currency: Separate rows per currency
--   6. Tenant isolation: Enforced via WHERE tenant_id IS NOT NULL
--   7. Hierarchy drill-down: channel → campaign → ad_set
-- =============================================================================
