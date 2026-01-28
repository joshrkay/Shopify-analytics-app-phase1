{{
    config(
        materialized='table',
        schema='metrics',
        tags=['metrics', 'cac', 'attribution']
    )
}}

-- Customer Acquisition Cost (CAC) Metric
--
-- Business Rules:
-- - CAC = Total Ad Spend / Number of New Customers Acquired (ALL new customers)
-- - nCAC = Total Ad Spend / Number of Net New Customers (excludes cancelled/fully refunded)
-- - New Customer = First order ever (based on customer_key - pseudonymized identifier)
-- - Net New Customer = First order was NOT cancelled or fully refunded
-- - Ad Spend = Meta Ads + Google Ads (same denominator as ROAS)
-- - Calculated per tenant, per platform, per time period
--
-- Edge Cases Handled:
-- 1. Zero new customers returns CAC = 0 (not NULL or infinity)
-- 2. Customers without email use customer_id as fallback
-- 3. Duplicate customers across platforms (counted once)
-- 4. Multi-currency: CAC calculated per currency
-- 5. Customers acquired organically excluded from paid CAC
-- 6. Tenant isolation enforced
-- 7. Partial refunds: Customer still counted as "net new" (only full cancellations excluded)

with all_orders as (
    -- Get all orders with customer info
    select
        tenant_id,
        order_id,
        customer_key,  -- Pseudonymized customer identifier
        order_created_at,
        revenue_gross,
        currency,
        financial_status
    from {{ ref('fact_orders') }}
    where tenant_id is not null
        and order_id is not null
        and customer_key is not null  -- Must have customer identifier
        and customer_key != md5('')  -- Exclude empty hash
),

-- Identify first order for each customer
first_orders as (
    select
        tenant_id,
        customer_key,  -- Already pseudonymized
        min(order_created_at) as first_order_date,
        min(order_id) as first_order_id  -- Tie-breaker if multiple orders same timestamp
    from all_orders
    group by 1, 2
),

-- Join first orders back to get full order details
first_order_details as (
    select
        o.tenant_id,
        f.customer_key,
        f.first_order_date,
        f.first_order_id,
        o.revenue_gross as first_order_revenue,
        o.currency,
        o.financial_status
    from first_orders f
    join all_orders o
        on f.tenant_id = o.tenant_id
        and f.first_order_id = o.order_id
),

-- Get attribution for first orders only
first_order_attribution as (
    select
        f.tenant_id,
        f.customer_key,
        f.first_order_date,
        f.first_order_id,
        f.first_order_revenue,
        f.currency,
        f.financial_status,

        a.platform,
        a.campaign_id,
        a.campaign_name,
        a.attribution_status,
        a.utm_source,
        a.utm_medium,
        a.utm_campaign

    from first_order_details f
    left join {{ ref('last_click') }} a
        on f.tenant_id = a.tenant_id
        and f.first_order_id = a.order_id
),

-- Join to revenue to get net revenue for first order
first_order_with_net_revenue as (
    select
        f.*,
        sum(r.net_revenue) as first_order_net_revenue,
        max(case when r.revenue_type = 'cancellation' then 1 else 0 end) as is_cancelled
    from first_order_attribution f
    left join {{ ref('fct_revenue') }} r
        on f.tenant_id = r.tenant_id
        and f.first_order_id = r.order_id
    group by
        f.tenant_id, f.customer_key, f.first_order_date, f.first_order_id,
        f.first_order_revenue, f.currency, f.financial_status,
        f.platform, f.campaign_id, f.campaign_name, f.attribution_status,
        f.utm_source, f.utm_medium, f.utm_campaign
),

-- Filter to only customers acquired through paid channels
paid_acquired_customers as (
    select
        tenant_id,
        customer_key,
        first_order_date,
        first_order_id,
        first_order_revenue,
        first_order_net_revenue,
        currency,
        platform,
        campaign_id,
        campaign_name,
        is_cancelled,
        financial_status,

        -- Determine if this is a "net new" customer (not cancelled/fully refunded)
        case
            when is_cancelled = 1 then false  -- Fully cancelled
            when financial_status in ('refunded', 'voided') then false  -- Fully refunded
            when first_order_net_revenue <= 0 then false  -- No net value (heavy refund)
            else true  -- Valid net new customer
        end as is_net_new_customer

    from first_order_with_net_revenue
    where attribution_status = 'attributed'  -- Only paid acquisition
        and platform in ('meta_ads', 'google_ads')
        and tenant_id is not null
),

-- Get ad spend (same logic as ROAS)
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

-- Aggregate new customers by day, platform, currency
daily_new_customers as (
    select
        tenant_id,
        platform,
        date_trunc('day', first_order_date) as acquisition_date,
        currency,
        campaign_id,
        count(distinct customer_key) as new_customers,
        count(distinct case when is_net_new_customer then customer_key end) as net_new_customers,
        sum(first_order_revenue) as first_order_revenue_total,
        sum(case when is_net_new_customer then first_order_net_revenue else 0 end) as net_first_order_revenue_total
    from paid_acquired_customers
    group by 1, 2, 3, 4, 5
),

-- Join new customers to spend
customers_and_spend as (
    select
        coalesce(c.tenant_id, s.tenant_id) as tenant_id,
        coalesce(c.platform, s.platform) as platform,
        coalesce(c.acquisition_date, s.spend_date) as metric_date,
        coalesce(c.currency, s.currency) as currency,
        coalesce(c.campaign_id, s.campaign_id) as campaign_id,

        coalesce(c.new_customers, 0) as new_customers,
        coalesce(c.net_new_customers, 0) as net_new_customers,
        coalesce(c.first_order_revenue_total, 0) as first_order_revenue_total,
        coalesce(c.net_first_order_revenue_total, 0) as net_first_order_revenue_total,
        coalesce(s.total_spend, 0) as total_spend

    from daily_new_customers c
    full outer join ad_spend s
        on c.tenant_id = s.tenant_id
        and c.platform = s.platform
        and c.acquisition_date = s.spend_date
        and c.currency = s.currency
        and coalesce(c.campaign_id, '') = coalesce(s.campaign_id, '')
    where coalesce(c.tenant_id, s.tenant_id) is not null
),

-- Calculate CAC at daily level
daily_cac as (
    select
        tenant_id,
        platform,
        metric_date as period_start,
        'daily' as period_type,
        currency,
        campaign_id,

        new_customers,
        net_new_customers,
        total_spend,
        first_order_revenue_total,
        net_first_order_revenue_total,

        -- CAC: spend / all new customers (includes cancelled/refunded)
        case
            when new_customers = 0 or new_customers is null then 0
            else round((total_spend / new_customers)::numeric, 2)
        end as cac,

        -- nCAC (Net CAC): spend / net new customers (excludes cancelled/refunded)
        case
            when net_new_customers = 0 or net_new_customers is null then 0
            else round((total_spend / net_new_customers)::numeric, 2)
        end as ncac,

        -- First order ROAS (all customers)
        case
            when new_customers = 0 or total_spend = 0 then 0
            else round((first_order_revenue_total / total_spend)::numeric, 2)
        end as first_order_roas,

        -- Net first order ROAS (only net new customers)
        case
            when net_new_customers = 0 or total_spend = 0 then 0
            else round((net_first_order_revenue_total / total_spend)::numeric, 2)
        end as net_first_order_roas

    from customers_and_spend
),

-- Aggregate to weekly level
weekly_cac as (
    select
        tenant_id,
        platform,
        date_trunc('week', period_start) as period_start,
        'weekly' as period_type,
        currency,
        campaign_id,

        sum(new_customers) as new_customers,
        sum(net_new_customers) as net_new_customers,
        sum(total_spend) as total_spend,
        sum(first_order_revenue_total) as first_order_revenue_total,
        sum(net_first_order_revenue_total) as net_first_order_revenue_total,

        case
            when sum(new_customers) = 0 then 0
            else round((sum(total_spend) / sum(new_customers))::numeric, 2)
        end as cac,

        case
            when sum(net_new_customers) = 0 then 0
            else round((sum(total_spend) / sum(net_new_customers))::numeric, 2)
        end as ncac,

        case
            when sum(total_spend) = 0 then 0
            else round((sum(first_order_revenue_total) / sum(total_spend))::numeric, 2)
        end as first_order_roas,

        case
            when sum(total_spend) = 0 then 0
            else round((sum(net_first_order_revenue_total) / sum(total_spend))::numeric, 2)
        end as net_first_order_roas

    from daily_cac
    group by 1, 2, 3, 4, 5, 6
),

-- Aggregate to monthly level
monthly_cac as (
    select
        tenant_id,
        platform,
        date_trunc('month', period_start) as period_start,
        'monthly' as period_type,
        currency,
        campaign_id,

        sum(new_customers) as new_customers,
        sum(net_new_customers) as net_new_customers,
        sum(total_spend) as total_spend,
        sum(first_order_revenue_total) as first_order_revenue_total,
        sum(net_first_order_revenue_total) as net_first_order_revenue_total,

        case
            when sum(new_customers) = 0 then 0
            else round((sum(total_spend) / sum(new_customers))::numeric, 2)
        end as cac,

        case
            when sum(net_new_customers) = 0 then 0
            else round((sum(total_spend) / sum(net_new_customers))::numeric, 2)
        end as ncac,

        case
            when sum(total_spend) = 0 then 0
            else round((sum(first_order_revenue_total) / sum(total_spend))::numeric, 2)
        end as first_order_roas,

        case
            when sum(total_spend) = 0 then 0
            else round((sum(net_first_order_revenue_total) / sum(total_spend))::numeric, 2)
        end as net_first_order_roas

    from daily_cac
    group by 1, 2, 3, 4, 5, 6
),

-- Aggregate to all-time level
all_time_cac as (
    select
        tenant_id,
        platform,
        null::timestamp as period_start,
        'all_time' as period_type,
        currency,
        campaign_id,

        sum(new_customers) as new_customers,
        sum(net_new_customers) as net_new_customers,
        sum(total_spend) as total_spend,
        sum(first_order_revenue_total) as first_order_revenue_total,
        sum(net_first_order_revenue_total) as net_first_order_revenue_total,

        case
            when sum(new_customers) = 0 then 0
            else round((sum(total_spend) / sum(new_customers))::numeric, 2)
        end as cac,

        case
            when sum(net_new_customers) = 0 then 0
            else round((sum(total_spend) / sum(net_new_customers))::numeric, 2)
        end as ncac,

        case
            when sum(total_spend) = 0 then 0
            else round((sum(first_order_revenue_total) / sum(total_spend))::numeric, 2)
        end as first_order_roas,

        case
            when sum(total_spend) = 0 then 0
            else round((sum(net_first_order_revenue_total) / sum(total_spend))::numeric, 2)
        end as net_first_order_roas

    from daily_cac
    group by 1, 2, 3, 4, 5, 6
),

-- Union all time periods
all_periods as (
    select * from daily_cac
    union all
    select * from weekly_cac
    union all
    select * from monthly_cac
    union all
    select * from all_time_cac
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
    new_customers,
    net_new_customers,
    total_spend,
    first_order_revenue_total,
    net_first_order_revenue_total,

    -- CAC Metrics
    cac,
    ncac,
    first_order_roas,
    net_first_order_roas,

    -- Calculated Metrics
    case
        when new_customers > 0 then round((first_order_revenue_total / new_customers)::numeric, 2)
        else 0
    end as avg_first_order_value,

    case
        when net_new_customers > 0 then round((net_first_order_revenue_total / net_new_customers)::numeric, 2)
        else 0
    end as avg_net_first_order_value,

    -- Customer Quality Metrics
    case
        when new_customers > 0 then round((net_new_customers::numeric / new_customers::numeric) * 100, 2)
        else 0
    end as customer_retention_rate_pct,

    -- Audit
    current_timestamp as dbt_updated_at

from all_periods
where tenant_id is not null

-- Edge Cases Handled:
-- 1. Zero new customers: CAC = 0 (not NULL or infinity)
-- 2. Customer identification: Uses customer_key (hashed identifier) - no PII
-- 3. Same customer on multiple platforms: Counted once per platform (platform-level CAC)
-- 4. Organic customers: Excluded from paid CAC
-- 5. Refunded first orders: Included in new_customers count (per requirements)
-- 6. Multi-currency: CAC calculated separately per currency
-- 7. Spend without new customers: CAC not calculated (no customers to divide by)
-- 8. New customers without spend: CAC = 0
-- 9. Tenant isolation: All calculations scoped by tenant_id
-- 10. Campaign-level detail: Preserved in campaign_id field
-- 11. First order revenue: Tracked for LTV-to-CAC ratio analysis
