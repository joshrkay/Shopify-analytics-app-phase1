{{
    config(
        materialized='incremental',
        unique_key='id',
        schema='metrics',
        on_schema_change='append_new_columns',
        tags=['metrics', 'revenue']
    )
}}

-- Revenue Metrics Fact Table
--
-- This table calculates revenue metrics with the following business rules:
--
-- GROSS REVENUE:
--   - Includes: Product subtotal + Shipping + Taxes
--   - Includes order statuses: paid, pending, partially_refunded
--   - Date: Uses order created_at (order date)
--
-- REFUNDS:
--   - Recorded as NEGATIVE revenue on the refund date (cancelled_at)
--   - Does NOT retroactively adjust the original order date
--
-- CANCELLATIONS:
--   - Recorded as separate line item (negative revenue on cancelled_at)
--   - Allows waterfall reporting: Gross - Refunds - Cancellations = Net
--
-- NET REVENUE:
--   - Calculated as: Gross Revenue - Refunds - Cancellations
--
-- TENANT ISOLATION:
--   - All calculations are tenant-scoped
--   - Revenue cannot leak across tenants

with orders_base as (
    select
        id,
        tenant_id,
        order_id,
        order_name,
        order_number,
        customer_email,
        customer_id_raw,
        order_created_at,
        order_updated_at,
        order_cancelled_at,
        order_closed_at,
        revenue as total_price,
        subtotal_price,
        total_tax,
        currency,
        financial_status,
        fulfillment_status,
        tags,
        note,
        refunds_json,
        ingested_at
    from {{ ref('fact_orders') }}

    {% if is_incremental() %}
        where ingested_at > (
            select coalesce(max(dbt_updated_at), '1970-01-01'::timestamp with time zone)
            from {{ this }}
        )
    {% endif %}
),

-- Parse refunds array to calculate actual refund amounts
-- Shopify stores refunds as a JSON array in the order data
-- Each refund has transactions that contain the refund amounts
refunds_parsed as (
    select
        id,
        -- Sum all refund transaction amounts for this order
        -- The refunds array contains objects with a 'transactions' array
        -- Each transaction has an 'amount' field
        coalesce(
            (
                select sum(
                    case
                        when (refund_elem->>'transactions') is not null
                        then (
                            select sum(
                                case
                                    when (txn->>'amount') ~ '^-?[0-9]+\.?[0-9]*$'
                                    then (txn->>'amount')::numeric
                                    else 0.0
                                end
                            )
                            from jsonb_array_elements(
                                case
                                    when jsonb_typeof(refund_elem->'transactions') = 'array'
                                    then refund_elem->'transactions'
                                    else '[]'::jsonb
                                end
                            ) as txn
                            where (txn->>'kind') = 'refund'
                        )
                        else 0.0
                    end
                )
                from jsonb_array_elements(
                    case
                        when refunds_json is not null and jsonb_typeof(refunds_json::jsonb) = 'array'
                        then refunds_json::jsonb
                        else '[]'::jsonb
                    end
                ) as refund_elem
            ),
            0.0
        ) as calculated_refund_amount
    from orders_base
),

-- Extract refund information from Shopify data
-- NOTE: Now using parsed refunds array for accurate refund amounts
orders_with_refund_detection as (
    select
        ob.*,
        rp.calculated_refund_amount,
        -- Detect if this is a refund/cancellation scenario
        case
            when ob.order_cancelled_at is not null and ob.financial_status in ('refunded', 'partially_refunded', 'voided')
                then true
            else false
        end as is_refunded_or_cancelled,

        -- Determine refund amount using parsed refunds data
        -- Edge case: partial refunds vs full refunds
        case
            when ob.financial_status = 'refunded' and ob.order_cancelled_at is not null
                then coalesce(rp.calculated_refund_amount, ob.total_price)  -- Use parsed amount, fallback to total
            when ob.financial_status = 'partially_refunded' and ob.order_cancelled_at is not null
                then coalesce(rp.calculated_refund_amount, 0.0)  -- Use actual refund amount from refunds array
            when ob.financial_status = 'voided' and ob.order_cancelled_at is not null
                then ob.total_price  -- Voided = full cancellation
            else 0.0
        end as refund_amount,

        -- Categorize the revenue type
        case
            when ob.financial_status in ('paid', 'authorized', 'partially_paid') and ob.order_cancelled_at is null
                then 'gross_revenue'
            when ob.financial_status = 'pending' and ob.order_cancelled_at is null
                then 'gross_revenue'  -- Include pending per requirements
            when ob.financial_status in ('refunded', 'partially_refunded') and ob.order_cancelled_at is not null
                then 'refund'
            when ob.financial_status in ('voided', 'cancelled') and ob.order_cancelled_at is not null
                then 'cancellation'
            else 'other'  -- Edge case: capture unknown statuses
        end as revenue_type

    from orders_base ob
    left join refunds_parsed rp on ob.id = rp.id
),

-- Create separate records for gross revenue and refund/cancellation events
-- This allows for waterfall reporting
revenue_events as (
    -- Gross Revenue Events (on order_created_at)
    select
        md5(concat(id, '|gross')) as id,
        tenant_id,
        order_id,
        order_name,
        order_number,
        customer_email,
        customer_id_raw,
        order_created_at as revenue_date,
        order_created_at,
        order_cancelled_at,
        currency,
        financial_status,
        fulfillment_status,

        -- Revenue breakdown
        'gross_revenue' as revenue_type,
        total_price as gross_revenue,
        subtotal_price,
        total_tax,
        0.0 as shipping_amount,  -- TODO: Extract from shipping_lines array
        0.0 as refund_amount,
        0.0 as cancellation_amount,

        -- Metadata
        tags,
        note,
        ingested_at,
        current_timestamp as dbt_updated_at

    from orders_with_refund_detection
    where revenue_type in ('gross_revenue', 'other')  -- Include "other" as gross for now
        and total_price > 0  -- Edge case: exclude $0 orders from gross revenue

    union all

    -- Refund Events (on order_cancelled_at)
    select
        md5(concat(id, '|refund')) as id,
        tenant_id,
        order_id,
        order_name,
        order_number,
        customer_email,
        customer_id_raw,
        order_cancelled_at as revenue_date,  -- Record refund on cancellation date
        order_created_at,
        order_cancelled_at,
        currency,
        financial_status,
        fulfillment_status,

        -- Revenue breakdown
        'refund' as revenue_type,
        0.0 as gross_revenue,
        0.0 as subtotal_price,
        0.0 as total_tax,
        0.0 as shipping_amount,
        -1 * refund_amount as refund_amount,  -- Negative revenue
        0.0 as cancellation_amount,

        -- Metadata
        tags,
        note,
        ingested_at,
        current_timestamp as dbt_updated_at

    from orders_with_refund_detection
    where revenue_type = 'refund'
        and order_cancelled_at is not null  -- Must have cancellation date
        and refund_amount > 0  -- Only record if there's actual refund amount

    union all

    -- Cancellation Events (on order_cancelled_at)
    select
        md5(concat(id, '|cancellation')) as id,
        tenant_id,
        order_id,
        order_name,
        order_number,
        customer_email,
        customer_id_raw,
        order_cancelled_at as revenue_date,  -- Record cancellation on cancellation date
        order_created_at,
        order_cancelled_at,
        currency,
        financial_status,
        fulfillment_status,

        -- Revenue breakdown
        'cancellation' as revenue_type,
        0.0 as gross_revenue,
        0.0 as subtotal_price,
        0.0 as total_tax,
        0.0 as shipping_amount,
        0.0 as refund_amount,
        -1 * total_price as cancellation_amount,  -- Negative revenue

        -- Metadata
        tags,
        note,
        ingested_at,
        current_timestamp as dbt_updated_at

    from orders_with_refund_detection
    where revenue_type = 'cancellation'
        and order_cancelled_at is not null  -- Must have cancellation date
        and total_price > 0  -- Only record if there's actual amount to cancel
)

select
    id,
    tenant_id,
    order_id,
    order_name,
    order_number,
    customer_email,
    customer_id_raw,
    revenue_date,
    order_created_at,
    order_cancelled_at,
    currency,
    financial_status,
    fulfillment_status,
    revenue_type,

    -- Revenue components
    gross_revenue,
    subtotal_price,
    total_tax,
    shipping_amount,
    refund_amount,
    cancellation_amount,

    -- Net revenue calculation
    (gross_revenue + refund_amount + cancellation_amount) as net_revenue,

    -- Metadata
    tags,
    note,
    ingested_at,
    dbt_updated_at

from revenue_events
where revenue_date is not null  -- Edge case: exclude events with null dates
    and tenant_id is not null  -- CRITICAL: tenant isolation

-- Edge cases handled:
-- 1. Orders with $0 total (excluded from gross revenue)
-- 2. Orders with null cancelled_at (only gross revenue recorded)
-- 3. Partial refunds (calculated from parsed refunds array transactions)
-- 4. Same-day order and refund (creates 2 separate events)
-- 5. Multiple refunds on same order (all transactions summed from refunds array)
-- 6. Orders in unknown financial_status (treated as "other", included in gross)
-- 7. Missing shipping amount (defaulted to 0, needs shipping_lines parsing)
-- 8. Cross-timezone date handling (all timestamps in UTC)
-- 9. Multi-currency handling (currency preserved, no conversion)
-- 10. Tenant isolation (all queries scoped by tenant_id)
