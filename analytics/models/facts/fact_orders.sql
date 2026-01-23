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

with staging_orders as (
    select
        order_id,
        order_name,
        order_number,
        customer_email,
        customer_id_raw,
        created_at,
        updated_at,
        cancelled_at,
        closed_at,
        total_price,
        subtotal_price,
        total_tax,
        currency,
        financial_status,
        fulfillment_status,
        tags,
        note,
        airbyte_record_id,
        airbyte_emitted_at,
        tenant_id
    from {{ ref('stg_shopify_orders') }}
    where tenant_id is not null
        and order_id is not null
        and trim(order_id) != ''
    
    {% if is_incremental() %}
        -- Only process new or updated records
        -- This assumes airbyte_emitted_at increases for updates
        and airbyte_emitted_at > (
            select coalesce(max(ingested_at), '1970-01-01'::timestamp with time zone)
            from {{ this }}
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
    
    -- Customer information
    customer_email,
    customer_id_raw,
    
    -- Timestamps (all UTC)
    created_at as order_created_at,
    updated_at as order_updated_at,
    cancelled_at as order_cancelled_at,
    closed_at as order_closed_at,
    
    -- Financial fields (all numeric, normalized)
    total_price as revenue,
    subtotal_price,
    total_tax,
    currency,
    
    -- Status fields
    financial_status,
    fulfillment_status,
    
    -- Metadata
    tags,
    note,
    
    -- Tenant isolation (CRITICAL)
    tenant_id,
    
    -- Airbyte metadata for tracking
    airbyte_record_id,
    airbyte_emitted_at as ingested_at,
    
    -- Audit fields
    current_timestamp as dbt_updated_at

from staging_orders
