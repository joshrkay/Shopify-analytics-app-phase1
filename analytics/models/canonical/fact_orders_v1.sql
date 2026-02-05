{{
    config(
        materialized='incremental',
        unique_key='id',
        schema='analytics',
        incremental_strategy='delete+insert',
        on_schema_change='append_new_columns'
    )
}}

{#
    Canonical fact table for Shopify orders (v1).

    Source of truth for actual revenue (Shopify orders).
    Part of hybrid revenue truth policy: Shopify revenue here,
    attributed revenue in fact_campaign_performance_v1.

    Rolling Rebuild:
    - Default window: 90 days (configurable via var('shopify_rebuild_days'))
    - Filters on business date (order_date), not ingestion timestamp
    - Catches late-arriving refunds, status updates, and late syncs
    - Rows outside the window remain unchanged

    Grain: One row per order.

    SECURITY: All rows are tenant-isolated via tenant_id.
#}

with staging_orders as (
    select
        o.record_sk,
        o.source_system,
        o.source_primary_key,
        o.tenant_id,
        o.order_id,
        o.order_name,
        o.order_number,
        o.customer_email,
        o.customer_id_raw,
        o.report_date,
        o.created_at,
        o.updated_at,
        o.cancelled_at,
        o.closed_at,
        o.total_price,
        o.subtotal_price,
        o.total_tax,
        o.currency,
        o.financial_status,
        o.fulfillment_status,
        o.tags,
        o.refunds_json,
        o.airbyte_emitted_at
    from {{ ref('stg_shopify_orders') }} o
    where o.tenant_id is not null
        and o.order_id is not null
        and trim(o.order_id) != ''

    {% if is_incremental() %}
        -- Rolling rebuild: reprocess orders within the window to catch
        -- late-arriving refunds, status changes, and attribution updates
        and o.report_date >= current_date - {{ var('shopify_rebuild_days', 90) }}
    {% endif %}
)

select
    -- Primary key
    md5(concat(tenant_id, '|', order_id)) as id,

    -- Tenant isolation
    tenant_id,

    -- Order identifiers
    order_id,
    report_date as order_date,

    -- Customer identifier (pseudonymized)
    md5(lower(trim(coalesce(
        nullif(customer_email, ''),
        customer_id_raw::text,
        ''
    )))) as customer_id,

    -- Revenue (Shopify is source of truth for actual revenue)
    total_price as revenue_gross,
    subtotal_price as revenue_net,
    currency,

    -- Refund flag
    case
        when financial_status in ('refunded', 'partially_refunded') then true
        else false
    end as is_refund,

    -- Timestamps
    coalesce(updated_at, created_at) as updated_at,

    -- Record lineage
    source_system,
    source_primary_key,

    -- Audit
    airbyte_emitted_at as ingested_at,
    current_timestamp as dbt_updated_at

from staging_orders
