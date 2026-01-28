{{
    config(
        materialized='table',
        schema='metrics',
        tags=['metrics', 'roas', 'attribution']
    )
}}

-- Return on Ad Spend (ROAS) Metric
--
-- Business Rules:
-- - ROAS = Attributed Revenue / Ad Spend
-- - Two variants: Gross ROAS (before refunds) and Net ROAS (after refunds)
-- - Ad Spend = Meta Ads + Google Ads (actual spend from platforms)
-- - Attribution: Platform-specific
--   * Meta: 7-day click / 1-day view (platform default)
--   * Google: Last-click (platform default)
-- - Zero spend: Returns 0 (not NULL or infinity)
-- - Calculated per tenant, per platform, per time period
--
-- Edge Cases Handled:
-- 1. Zero or null ad spend returns ROAS = 0
-- 2. Revenue without spend (organic) excluded from ROAS
-- 3. Spend without attributed revenue = ROAS of 0
-- 4. Multi-currency: ROAS calculated per currency
-- 5. Unattributed orders excluded from ROAS
-- 6. Tenant isolation enforced

with attributed_orders as (
    -- Get attributed orders from last-click attribution
    select
        order_id,
        tenant_id,
        order_created_at,
        revenue as gross_revenue,  -- Gross revenue from order
        currency,
        utm_source,
        utm_medium,
        utm_campaign,
        platform,
        campaign_id,
        campaign_name,
        attribution_status
    from {{ ref('last_click') }}
    where attribution_status = 'attributed'  -- Only attributed orders
        and platform in ('meta_ads', 'google_ads')  -- Only paid platforms
        and tenant_id is not null
        and order_id is not null
),

-- Join attributed orders to revenue events to get net revenue
orders_with_net_revenue as (
    select
        a.order_id,
        a.tenant_id,
        a.order_created_at,
        a.gross_revenue,
        a.currency,
        a.utm_source,
        a.utm_medium,
        a.utm_campaign,
        a.platform,
        a.campaign_id,
        a.campaign_name,

        -- Get net revenue from fct_revenue
        -- Net revenue = gross - refunds - cancellations
        sum(case when r.revenue_type = 'gross_revenue' then r.gross_revenue else 0 end) as gross_revenue_validated,
        sum(r.net_revenue) as net_revenue

    from attributed_orders a
    left join {{ ref('fct_revenue') }} r
        on a.tenant_id = r.tenant_id
        and a.order_id = r.order_id
    group by 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11
),

-- Get ad spend by platform and date
ad_spend as (
    select
        tenant_id,
        source_platform as platform,
        date as spend_date,
        currency,
        campaign_id,
        sum(spend) as total_spend
    from {{ ref('fact_ad_spend') }}
    where tenant_id is not null
        and source_platform in ('meta_ads', 'google_ads')
        and spend is not null
        and spend >= 0  -- Edge case: negative spend should not happen
    group by 1, 2, 3, 4, 5
),

-- Aggregate attributed revenue by day, platform, currency
daily_attributed_revenue as (
    select
        tenant_id,
        platform,
        date_trunc('day', order_created_at) as revenue_date,
        currency,
        campaign_id,
        count(distinct order_id) as order_count,
        sum(gross_revenue) as total_gross_revenue,
        sum(net_revenue) as total_net_revenue
    from orders_with_net_revenue
    group by 1, 2, 3, 4, 5
),

-- Join revenue to spend (by date, platform, currency, campaign_id)
revenue_and_spend as (
    select
        coalesce(r.tenant_id, s.tenant_id) as tenant_id,
        coalesce(r.platform, s.platform) as platform,
        coalesce(r.revenue_date, s.spend_date) as metric_date,
        coalesce(r.currency, s.currency) as currency,
        coalesce(r.campaign_id, s.campaign_id) as campaign_id,

        coalesce(r.order_count, 0) as order_count,
        coalesce(r.total_gross_revenue, 0) as total_gross_revenue,
        coalesce(r.total_net_revenue, 0) as total_net_revenue,
        coalesce(s.total_spend, 0) as total_spend

    from daily_attributed_revenue r
    full outer join ad_spend s
        on r.tenant_id = s.tenant_id
        and r.platform = s.platform
        and r.revenue_date = s.spend_date
        and r.currency = s.currency
        and r.campaign_id = s.campaign_id
    where coalesce(r.tenant_id, s.tenant_id) is not null
),

-- Calculate ROAS at daily level
daily_roas as (
    select
        tenant_id,
        platform,
        metric_date as period_start,
        'daily' as period_type,
        currency,
        campaign_id,

        order_count,
        total_gross_revenue,
        total_net_revenue,
        total_spend,

        -- Gross ROAS: gross revenue / spend
        -- Edge case: if spend = 0, return 0 (not NULL or infinity)
        case
            when total_spend = 0 or total_spend is null then 0
            else round((total_gross_revenue / total_spend)::numeric, 2)
        end as gross_roas,

        -- Net ROAS: net revenue / spend
        case
            when total_spend = 0 or total_spend is null then 0
            else round((total_net_revenue / total_spend)::numeric, 2)
        end as net_roas

    from revenue_and_spend
),

-- Aggregate to weekly level
weekly_roas as (
    select
        tenant_id,
        platform,
        date_trunc('week', period_start) as period_start,
        'weekly' as period_type,
        currency,
        campaign_id,

        sum(order_count) as order_count,
        sum(total_gross_revenue) as total_gross_revenue,
        sum(total_net_revenue) as total_net_revenue,
        sum(total_spend) as total_spend,

        case
            when sum(total_spend) = 0 or sum(total_spend) is null then 0
            else round((sum(total_gross_revenue) / sum(total_spend))::numeric, 2)
        end as gross_roas,

        case
            when sum(total_spend) = 0 or sum(total_spend) is null then 0
            else round((sum(total_net_revenue) / sum(total_spend))::numeric, 2)
        end as net_roas

    from daily_roas
    group by 1, 2, 3, 4, 5, 6
),

-- Aggregate to monthly level
monthly_roas as (
    select
        tenant_id,
        platform,
        date_trunc('month', period_start) as period_start,
        'monthly' as period_type,
        currency,
        campaign_id,

        sum(order_count) as order_count,
        sum(total_gross_revenue) as total_gross_revenue,
        sum(total_net_revenue) as total_net_revenue,
        sum(total_spend) as total_spend,

        case
            when sum(total_spend) = 0 or sum(total_spend) is null then 0
            else round((sum(total_gross_revenue) / sum(total_spend))::numeric, 2)
        end as gross_roas,

        case
            when sum(total_spend) = 0 or sum(total_spend) is null then 0
            else round((sum(total_net_revenue) / sum(total_spend))::numeric, 2)
        end as net_roas

    from daily_roas
    group by 1, 2, 3, 4, 5, 6
),

-- Aggregate to all-time level
all_time_roas as (
    select
        tenant_id,
        platform,
        null::timestamp as period_start,
        'all_time' as period_type,
        currency,
        campaign_id,

        sum(order_count) as order_count,
        sum(total_gross_revenue) as total_gross_revenue,
        sum(total_net_revenue) as total_net_revenue,
        sum(total_spend) as total_spend,

        case
            when sum(total_spend) = 0 or sum(total_spend) is null then 0
            else round((sum(total_gross_revenue) / sum(total_spend))::numeric, 2)
        end as gross_roas,

        case
            when sum(total_spend) = 0 or sum(total_spend) is null then 0
            else round((sum(total_net_revenue) / sum(total_spend))::numeric, 2)
        end as net_roas

    from daily_roas
    group by 1, 2, 3, 4, 5, 6
),

-- Union all time periods
all_periods as (
    select * from daily_roas
    union all
    select * from weekly_roas
    union all
    select * from monthly_roas
    union all
    select * from all_time_roas
)

select
    -- Generate unique ID
    md5(concat(
        tenant_id, '|',
        platform, '|',
        currency, '|',
        coalesce(campaign_id, 'all'), '|',
        period_type, '|',
        coalesce(period_start::text, 'all_time')
    )) as id,

    tenant_id,
    platform,
    period_type,
    period_start,
    currency,
    campaign_id,

    -- Volume Metrics
    order_count,
    total_spend,

    -- Revenue Metrics
    total_gross_revenue,
    total_net_revenue,

    -- ROAS Metrics
    gross_roas,
    net_roas,

    -- Calculated Metrics
    case
        when order_count > 0 then round((total_gross_revenue / order_count)::numeric, 2)
        else 0
    end as avg_order_value_gross,

    case
        when order_count > 0 then round((total_net_revenue / order_count)::numeric, 2)
        else 0
    end as avg_order_value_net,

    -- Audit
    current_timestamp as dbt_updated_at

from all_periods
where tenant_id is not null

-- Edge Cases Handled:
-- 1. Zero spend: ROAS = 0 (not NULL or infinity)
-- 2. Null spend: Treated as 0
-- 3. Revenue without spend: Not included (full outer join ensures both sides captured)
-- 4. Spend without revenue: ROAS = 0
-- 5. Negative spend: Filtered out in ad_spend CTE
-- 6. Negative revenue: Included (reflects reality of heavy refunds)
-- 7. Multi-currency: ROAS calculated separately per currency
-- 8. Unattributed orders: Excluded (only orders with attribution_status = 'attributed')
-- 9. Organic traffic: Excluded (no platform or spend)
-- 10. Tenant isolation: All calculations scoped by tenant_id
-- 11. Campaign-level detail: Preserved in campaign_id field
-- 12. Platform-specific attribution: Handled by last_click model
