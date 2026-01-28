{{
    config(
        materialized='incremental',
        unique_key='id',
        schema='analytics',
        on_schema_change='append_new_columns'
    )
}}

-- Canonical fact table for Shopify orders
-- 
-- This table represents the source of truth for all order events.
-- It is incremental and only processes new/updated orders based on airbyte_emitted_at.
--
-- SECURITY: Tenant isolation is enforced - all rows must have tenant_id
-- and tenant_id is validated against _tenant_airbyte_connections

with tenant_timezones as (
    select tenant_id, timezone
    from {{ ref('dim_tenant') }}
),

staging_orders as (
    select
        o.order_id,
        o.order_name,
        o.order_number,
        -- PII fields used only for hashing (not exposed in final output)
        o.customer_email,
        o.customer_id_raw,
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
        o.note,
        o.refunds_json,
        o.airbyte_record_id,
        o.airbyte_emitted_at,
        o.tenant_id,
        coalesce(t.timezone, 'UTC') as tenant_timezone
    from {{ ref('stg_shopify_orders') }} o
    left join tenant_timezones t on o.tenant_id = t.tenant_id
    where o.tenant_id is not null
        and o.order_id is not null
        and trim(o.order_id) != ''
    
    {% if var('backfill_start_date', none) and var('backfill_end_date', none) %}
        -- Backfill mode: filter by date range
        -- SECURITY: Tenant isolation still enforced via tenant_id filter above
        and {{ backfill_date_filter('airbyte_emitted_at', var('backfill_start_date'), var('backfill_end_date')) }}
        {% if var('backfill_tenant_id', none) %}
            -- Additional tenant filter for backfill (defense in depth)
            and tenant_id = '{{ var("backfill_tenant_id") }}'
        {% endif %}
    {% elif is_incremental() %}
        -- Incremental mode with configurable lookback window (default 7 days)
        -- This reprocesses recent data to catch late-arriving records and updates
        and airbyte_emitted_at >= (
            current_timestamp - interval '{{ var("fact_orders_lookback_days", 7) }} days'
        )
    {% endif %}
)

select
    -- Primary key: composite of tenant_id and order_id for uniqueness across tenants
    -- Using MD5 hash for deterministic surrogate key generation
    md5(concat(tenant_id, '|', order_id)) as id,
    
    -- Order identifiers
    order_id,
    order_name,
    order_number,

    -- Customer identifier (pseudonymized per Shopify pattern)
    -- Uses hashed email/ID instead of raw PII for customer-level analytics
    -- Enables: CAC, LTV, cohort analysis without exposing PII
    md5(lower(trim(coalesce(
        nullif(customer_email, ''),
        customer_id_raw::text,
        ''
    )))) as customer_key,

    -- Source platform (canonical column per user story 7.7.1)
    'shopify' as source_platform,

    -- Timestamps (all UTC)
    created_at as order_created_at,
    updated_at as order_updated_at,
    cancelled_at as order_cancelled_at,
    closed_at as order_closed_at,

    -- Tenant local date (per user story 7.7.1)
    -- Normalized to tenant's timezone for consistent daily reporting
    {{ convert_to_tenant_local_date('created_at', 'tenant_timezone') }} as date,
    
    -- Financial fields (all numeric, normalized)
    -- revenue_gross: total price including tax (use for gross revenue metrics)
    -- revenue_net: subtotal before tax (use as default revenue per user story 7.7.1)
    total_price as revenue_gross,
    subtotal_price as revenue_net,
    total_tax,
    currency,
    
    -- Status fields
    financial_status,
    fulfillment_status,
    
    -- Metadata
    tags,
    note,
    refunds_json,
    
    -- Tenant isolation (CRITICAL)
    tenant_id,
    
    -- Airbyte metadata for tracking
    airbyte_record_id,
    airbyte_emitted_at as ingested_at,
    
    -- Audit fields
    current_timestamp as dbt_updated_at

from staging_orders
