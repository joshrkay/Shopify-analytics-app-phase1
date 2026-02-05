{{
    config(
        materialized='view',
        schema='semantic',
        tags=['semantic', 'orders', 'versioned', 'immutable']
    )
}}

-- sem_orders_v1 - IMMUTABLE versioned semantic view of order data
--
-- Version: v1
-- Status: active
-- Released: 2026-02-05
-- Source: orders (canonical, schema registry v1.1.0)
--
-- DO NOT EDIT THIS VIEW. Create sem_orders_v2 instead.
--
-- This view defines the frozen column contract for v1. It exposes only
-- approved consumer-facing columns and excludes:
--   - platform (deprecated, use source_platform)
--   - refunds_json (internal, used by fct_revenue)
--   - airbyte_record_id (internal audit)
--   - ingested_at (internal audit)
--
-- See: canonical/schema_registry.yml

select
    id,
    tenant_id,
    order_id,
    order_name,
    order_number,
    customer_key,
    source_platform,
    order_created_at,
    order_updated_at,
    order_cancelled_at,
    order_closed_at,
    date,
    revenue_gross,
    revenue_net,
    total_tax,
    currency,
    financial_status,
    fulfillment_status,
    tags,
    note,
    dbt_updated_at,
    'v1' as schema_version
from {{ ref('orders') }}
where tenant_id is not null
