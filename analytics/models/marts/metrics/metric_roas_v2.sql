{{
    config(
        materialized='view',
        schema='metrics',
        tags=['metrics', 'roas', 'versioned', 'immutable']
    )
}}

-- metric_roas_v2 - IMMUTABLE versioned ROAS view
--
-- Version: v2
-- Status: active
-- Released: 2026-02-01
-- Definition: Blended ROAS = (attributed + organic revenue) / ad_spend
--
-- Breaking change from v1:
--   v1 uses only attributed revenue (last-click)
--   v2 includes ALL revenue (attributed + organic) for a blended view
--   This produces higher ROAS values than v1
--
-- DO NOT EDIT THIS VIEW. Create a new version instead.
-- See: config/governance/metrics_versions.yaml

with all_revenue as (
    -- v2 uses total net revenue from fct_revenue (all orders, not just attributed)
    select
        tenant_id,
        date_trunc('day', revenue_date)::date as revenue_date,
        currency,
        sum(case when revenue_type = 'gross_revenue' then gross_revenue else 0 end) as total_gross_revenue,
        sum(net_revenue) as total_net_revenue,
        count(distinct order_id) as order_count
    from {{ ref('fct_revenue') }}
    where tenant_id is not null
        and revenue_date is not null
    group by 1, 2, 3
),

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
        and spend >= 0
    group by 1, 2, 3, 4, 5
),

-- Aggregate spend to tenant/date/currency level (no platform/campaign split for blended)
spend_by_day as (
    select
        tenant_id,
        spend_date,
        currency,
        sum(total_spend) as total_spend
    from ad_spend
    group by 1, 2, 3
),

-- Join blended revenue to total spend
daily_blended as (
    select
        coalesce(r.tenant_id, s.tenant_id) as tenant_id,
        'all' as platform,
        coalesce(r.revenue_date, s.spend_date) as metric_date,
        coalesce(r.currency, s.currency) as currency,
        null::text as campaign_id,

        coalesce(r.order_count, 0) as order_count,
        coalesce(r.total_gross_revenue, 0) as total_gross_revenue,
        coalesce(r.total_net_revenue, 0) as total_net_revenue,
        coalesce(s.total_spend, 0) as total_spend

    from all_revenue r
    full outer join spend_by_day s
        on r.tenant_id = s.tenant_id
        and r.revenue_date = s.spend_date
        and r.currency = s.currency
    where coalesce(r.tenant_id, s.tenant_id) is not null
),

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
        case
            when total_spend = 0 or total_spend is null then 0
            else round((total_gross_revenue / total_spend)::numeric, 2)
        end as gross_roas,
        case
            when total_spend = 0 or total_spend is null then 0
            else round((total_net_revenue / total_spend)::numeric, 2)
        end as net_roas
    from daily_blended
),

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
    md5(concat(
        tenant_id, '|',
        platform, '|',
        currency, '|',
        coalesce(campaign_id, 'all'), '|',
        period_type, '|',
        coalesce(period_start::text, 'all_time'),
        '|v2'
    )) as id,
    tenant_id,
    platform,
    period_type,
    period_start,
    currency,
    campaign_id,
    order_count,
    total_spend,
    total_gross_revenue,
    total_net_revenue,
    gross_roas,
    net_roas,
    case
        when order_count > 0 then round((total_gross_revenue / order_count)::numeric, 2)
        else 0
    end as avg_order_value_gross,
    case
        when order_count > 0 then round((total_net_revenue / order_count)::numeric, 2)
        else 0
    end as avg_order_value_net,
    current_timestamp as dbt_updated_at,
    'v2' as metric_version
from all_periods
where tenant_id is not null
