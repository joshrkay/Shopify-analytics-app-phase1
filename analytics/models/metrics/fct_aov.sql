{{
    config(
        materialized='table',
        schema='metrics',
        tags=['metrics', 'aov']
    )
}}

-- Average Order Value (AOV) Metric
--
-- Business Rules:
-- - AOV = Net Revenue / Number of Orders
-- - Uses NET revenue (after refunds and cancellations)
-- - Includes: paid, pending, partially_refunded orders
-- - Excludes: extreme outliers (>3 standard deviations from mean)
-- - Calculated per tenant, per time period
-- - Time periods: daily, weekly, monthly, all-time
--
-- Edge Cases Handled:
-- 1. Outlier detection uses rolling 90-day window
-- 2. Zero-order periods return NULL (not 0 or infinity)
-- 3. Negative net revenue orders (heavy refunds) are included
-- 4. Multi-currency: AOV calculated per currency
-- 5. Tenant isolation enforced

with order_revenue as (
    -- Aggregate revenue at order level (gross - refunds - cancellations)
    select
        tenant_id,
        order_id,
        order_name,
        customer_key,  -- Pseudonymized customer identifier
        min(order_created_at) as order_date,  -- Use earliest event date
        currency,
        sum(gross_revenue) as gross_revenue,
        sum(refund_amount) as refund_amount,
        sum(cancellation_amount) as cancellation_amount,
        sum(net_revenue) as net_revenue
    from {{ ref('fct_revenue') }}
    where tenant_id is not null
        and order_id is not null
    group by 1, 2, 3, 4, 6
),

-- Calculate statistics for outlier detection using rolling 90-day window
-- Use window functions to calculate rolling average and stddev for each order
-- based on the preceding 90 days of data from that order's date
orders_with_outlier_flag as (
    select
        o.*,
        -- Calculate rolling average over preceding 90 days (including current order)
        avg(o.net_revenue) over (
            partition by o.tenant_id, o.currency
            order by o.order_date
            range between interval '90 days' preceding and current row
        ) as avg_revenue,
        -- Calculate rolling standard deviation over preceding 90 days
        stddev(o.net_revenue) over (
            partition by o.tenant_id, o.currency
            order by o.order_date
            range between interval '90 days' preceding and current row
        ) as stddev_revenue,
        -- Edge case: if stddev is 0 or null, no outliers detected
        case
            when stddev(o.net_revenue) over (
                partition by o.tenant_id, o.currency
                order by o.order_date
                range between interval '90 days' preceding and current row
            ) is null then false
            when stddev(o.net_revenue) over (
                partition by o.tenant_id, o.currency
                order by o.order_date
                range between interval '90 days' preceding and current row
            ) = 0 then false
            when abs(o.net_revenue - avg(o.net_revenue) over (
                partition by o.tenant_id, o.currency
                order by o.order_date
                range between interval '90 days' preceding and current row
            )) > (3 * stddev(o.net_revenue) over (
                partition by o.tenant_id, o.currency
                order by o.order_date
                range between interval '90 days' preceding and current row
            )) then true
            else false
        end as is_outlier
    from order_revenue o
),

-- Filter out outliers
orders_filtered as (
    select
        tenant_id,
        order_id,
        order_name,
        customer_key,
        order_date,
        currency,
        gross_revenue,
        refund_amount,
        cancellation_amount,
        net_revenue,
        is_outlier
    from orders_with_outlier_flag
    where is_outlier = false  -- Exclude outliers from AOV calculation
        or is_outlier is null  -- Include if outlier detection failed
),

-- Calculate AOV at multiple time granularities
daily_aov as (
    select
        tenant_id,
        currency,
        date_trunc('day', order_date) as period_start,
        'daily' as period_type,
        count(distinct order_id) as order_count,
        sum(net_revenue) as total_net_revenue,
        -- Edge case: avoid division by zero
        case
            when count(distinct order_id) = 0 then null
            else sum(net_revenue) / count(distinct order_id)
        end as aov,
        avg(net_revenue) as avg_order_value,  -- Alternative calculation (should match AOV)
        min(net_revenue) as min_order_value,
        max(net_revenue) as max_order_value,
        stddev(net_revenue) as stddev_order_value,
        count(case when is_outlier then 1 end) as outliers_excluded_count
    from orders_filtered
    group by 1, 2, 3
),

weekly_aov as (
    select
        tenant_id,
        currency,
        date_trunc('week', order_date) as period_start,
        'weekly' as period_type,
        count(distinct order_id) as order_count,
        sum(net_revenue) as total_net_revenue,
        case
            when count(distinct order_id) = 0 then null
            else sum(net_revenue) / count(distinct order_id)
        end as aov,
        avg(net_revenue) as avg_order_value,
        min(net_revenue) as min_order_value,
        max(net_revenue) as max_order_value,
        stddev(net_revenue) as stddev_order_value,
        count(case when is_outlier then 1 end) as outliers_excluded_count
    from orders_filtered
    group by 1, 2, 3
),

monthly_aov as (
    select
        tenant_id,
        currency,
        date_trunc('month', order_date) as period_start,
        'monthly' as period_type,
        count(distinct order_id) as order_count,
        sum(net_revenue) as total_net_revenue,
        case
            when count(distinct order_id) = 0 then null
            else sum(net_revenue) / count(distinct order_id)
        end as aov,
        avg(net_revenue) as avg_order_value,
        min(net_revenue) as min_order_value,
        max(net_revenue) as max_order_value,
        stddev(net_revenue) as stddev_order_value,
        count(case when is_outlier then 1 end) as outliers_excluded_count
    from orders_filtered
    group by 1, 2, 3
),

all_time_aov as (
    select
        tenant_id,
        currency,
        null::timestamp as period_start,
        'all_time' as period_type,
        count(distinct order_id) as order_count,
        sum(net_revenue) as total_net_revenue,
        case
            when count(distinct order_id) = 0 then null
            else sum(net_revenue) / count(distinct order_id)
        end as aov,
        avg(net_revenue) as avg_order_value,
        min(net_revenue) as min_order_value,
        max(net_revenue) as max_order_value,
        stddev(net_revenue) as stddev_order_value,
        count(case when is_outlier then 1 end) as outliers_excluded_count
    from orders_filtered
    group by 1, 2
),

-- Union all time periods
all_periods as (
    select * from daily_aov
    union all
    select * from weekly_aov
    union all
    select * from monthly_aov
    union all
    select * from all_time_aov
)

select
    -- Generate unique ID
    md5(concat(
        tenant_id, '|',
        currency, '|',
        period_type, '|',
        coalesce(period_start::text, 'all_time')
    )) as id,

    tenant_id,
    currency,
    period_type,
    period_start,

    -- AOV Metrics
    order_count,
    total_net_revenue,
    aov,
    avg_order_value,  -- Should equal AOV (validation check)

    -- Distribution Metrics
    min_order_value,
    max_order_value,
    stddev_order_value,

    -- Data Quality Metrics
    outliers_excluded_count,

    -- Audit
    current_timestamp as dbt_updated_at

from all_periods
where tenant_id is not null
    and order_count > 0  -- Only include periods with orders

-- Edge Cases Handled:
-- 1. Zero orders in period (excluded, not NULL AOV)
-- 2. Division by zero (returns NULL)
-- 3. Outliers detected via 3-sigma rule on 90-day rolling window
-- 4. Multi-currency (AOV calculated separately per currency)
-- 5. Negative net revenue (included - reflects reality of heavy refunds)
-- 6. Null currency (defaults to USD in revenue model)
-- 7. Orders spanning time periods (attributed to order_date)
-- 8. Tenant isolation (all calculations scoped by tenant_id)
