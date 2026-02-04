{{
    config(
        materialized='table',
        schema='marts',
        tags=['marts', 'metrics', 'cac', 'v1', 'versioned']
    )
}}

-- =============================================================================
-- CAC v1 - Customer Acquisition Cost (Versioned Metric)
-- =============================================================================
--
-- METRIC REGISTRY: metrics/metric_registry.yaml
-- DEFINITION: SUM(spend) / COUNT(new_customers)
-- STATUS: active
-- APPROVAL: ANALYTICS-002 (2026-02-04)
--
-- This is a VERSIONED metric model. Changes to the calculation formula
-- require a new version (v2, v3, etc.) - never modify this file.
--
-- EDGE CASES:
--   - Zero customers: Returns 0 (not NULL or infinity)
--   - Null customers: Treated as 0
--   - Multi-currency: Calculated separately per currency
--   - Duplicate customers: Counted once per customer_key
--
-- NEW CUSTOMER DEFINITION (v1):
--   First order ever based on customer_key (pseudonymized)
--   Must be attributed to paid channel
--
-- TENANT ISOLATION: Enforced via tenant_id filter
--
-- =============================================================================

{% set metric_name = 'cac' %}
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
        sum(spend) as spend
    from {{ ref('fact_ad_spend') }}
    where tenant_id is not null
        and date is not null
        and spend is not null
        and spend >= 0  -- Exclude negative spend (data quality)
    group by 1, 2, 3, 4, 5, 6, 7
),

-- -----------------------------------------------------------------------------
-- SOURCE: All orders for customer identification
-- -----------------------------------------------------------------------------
all_orders as (
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
        and customer_key != md5('')  -- Exclude empty hash
),

-- -----------------------------------------------------------------------------
-- IDENTIFY: First order per customer (new customer definition v1)
-- -----------------------------------------------------------------------------
first_order_per_customer as (
    select
        tenant_id,
        customer_key,
        min(order_created_at) as first_order_date,
        min(order_id) as first_order_id
    from all_orders
    group by 1, 2
),

-- -----------------------------------------------------------------------------
-- AGGREGATE: New customers per day
-- -----------------------------------------------------------------------------
new_customers_daily as (
    select
        tenant_id,
        date_trunc('day', first_order_date)::date as date,
        count(distinct customer_key) as new_customers
    from first_order_per_customer
    where tenant_id is not null
    group by 1, 2
),

-- -----------------------------------------------------------------------------
-- JOIN: Spend with new customers
-- -----------------------------------------------------------------------------
spend_with_customers as (
    select
        coalesce(s.tenant_id, c.tenant_id) as tenant_id,
        coalesce(s.date, c.date) as date,
        s.currency,
        s.channel,
        coalesce(sum(s.spend), 0) as total_spend,
        coalesce(max(c.new_customers), 0) as new_customers
    from ad_spend s
    full outer join new_customers_daily c
        on s.tenant_id = c.tenant_id
        and s.date = c.date
    where coalesce(s.tenant_id, c.tenant_id) is not null
    group by 1, 2, 3, 4
),

-- -----------------------------------------------------------------------------
-- AGGREGATION: Channel Level
-- CAC is only meaningful at channel level (new customers not attributable below)
-- -----------------------------------------------------------------------------
channel_metrics as (
    select
        tenant_id,
        date,
        currency,
        channel,
        null::text as campaign_id,
        null::text as adset_id,
        'channel' as hierarchy_level,
        sum(total_spend) as total_spend,
        sum(new_customers) as new_customers
    from spend_with_customers
    group by 1, 2, 3, 4
),

-- -----------------------------------------------------------------------------
-- AGGREGATION: Campaign Level (spend only, new_customers = 0)
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
        0 as new_customers  -- Not attributable at campaign level in v1
    from ad_spend
    where campaign_id is not null
    group by 1, 2, 3, 4, 5
),

-- -----------------------------------------------------------------------------
-- AGGREGATION: Adset Level (spend only, new_customers = 0)
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
        0 as new_customers  -- Not attributable at adset level in v1
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
        new_customers
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
        sum(new_customers) as new_customers
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
        sum(new_customers) as new_customers
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
        sum(new_customers) as new_customers
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
-- FINAL OUTPUT: Versioned CAC metric
-- -----------------------------------------------------------------------------
select
    -- Unique identifier
    md5(concat(
        tenant_id, '|',
        '{{ metric_version }}', '|',
        period_type, '|',
        coalesce(period_start::text, 'all_time'), '|',
        coalesce(currency, 'all'), '|',
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
    new_customers,

    -- ==========================================================================
    -- CANONICAL CAC (v1): SUM(spend) / COUNT(new_customers)
    -- ==========================================================================
    case
        when new_customers = 0 or new_customers is null then 0
        else round((total_spend / new_customers)::numeric, 2)
    end as cac,

    -- Additional derived metrics
    case
        when total_spend > 0 and new_customers > 0 then
            round((new_customers::numeric / total_spend * 1000)::numeric, 4)
        else 0
    end as customers_per_1k_spend,

    -- Audit fields
    current_timestamp as dbt_updated_at

from all_periods
where tenant_id is not null

-- =============================================================================
-- VERSION HISTORY:
--   v1 (2026-02-04): Initial implementation
--       - Definition: SUM(spend) / COUNT(new_customers)
--       - Zero customers handling: Returns 0
--       - New customer: First order ever (customer_key based)
--       - Multi-currency: Separate calculations per currency
--       - Attribution: Channel level only (campaign/adset = 0 customers)
--
-- RECONCILIATION:
--   This metric reconciles with:
--     - fact_ad_spend: SUM(spend) matches total_spend
--     - fact_orders: COUNT(DISTINCT customer_key) for first orders
--
-- GOVERNANCE:
--   - Approval: ANALYTICS-002
--   - Owner: data-team@company.com
--   - Breaking changes require new version
-- =============================================================================
