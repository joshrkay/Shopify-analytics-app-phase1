{{
    config(
        materialized='view',
        schema='staging'
    )
}}

with raw_orders as (
    select
        _airbyte_ab_id as airbyte_record_id,
        _airbyte_emitted_at as airbyte_emitted_at,
        _airbyte_data as order_data
    from {{ source('airbyte_raw', '_airbyte_raw_shopify_orders') }}
),

tenant_mapping as (
    select
        airbyte_connection_id,
        tenant_id,
        source_type
    from {{ ref('_tenant_airbyte_connections') }}
    where source_type = 'shopify'
        and status = 'active'
        and is_enabled = true
),

orders_extracted as (
    select
        raw.airbyte_record_id,
        raw.airbyte_emitted_at,
        raw.order_data->>'id' as order_id_raw,
        raw.order_data->>'name' as order_name,
        raw.order_data->>'email' as customer_email,
        raw.order_data->>'created_at' as created_at_raw,
        raw.order_data->>'updated_at' as updated_at_raw,
        raw.order_data->>'cancelled_at' as cancelled_at_raw,
        raw.order_data->>'closed_at' as closed_at_raw,
        raw.order_data->>'financial_status' as financial_status,
        raw.order_data->>'fulfillment_status' as fulfillment_status,
        raw.order_data->>'total_price' as total_price_raw,
        raw.order_data->>'subtotal_price' as subtotal_price_raw,
        raw.order_data->>'total_tax' as total_tax_raw,
        raw.order_data->>'currency' as currency_code,
        raw.order_data->>'customer' as customer_json,
        raw.order_data->>'line_items' as line_items_json,
        raw.order_data->>'billing_address' as billing_address_json,
        raw.order_data->>'shipping_address' as shipping_address_json,
        raw.order_data->>'tags' as tags_raw,
        raw.order_data->>'note' as note,
        raw.order_data->>'order_number' as order_number_raw,
        raw.order_data->'refunds' as refunds_json
    from raw_orders raw
),

orders_normalized as (
    select
        -- Primary key: normalize order ID (remove gid:// prefix if present)
        -- Edge case: Handle null, empty, and various GID formats
        case
            when order_id_raw is null or trim(order_id_raw) = '' then null
            when order_id_raw like 'gid://shopify/Order/%' 
                then replace(order_id_raw, 'gid://shopify/Order/', '')
            when order_id_raw like 'gid://shopify/Order%' 
                then regexp_replace(order_id_raw, '^gid://shopify/Order/?', '', 'g')
            else trim(order_id_raw)
        end as order_id,
        
        -- Order identifiers
        order_name,
        -- Edge case: Handle invalid integers, nulls, empty strings
        case
            when order_number_raw is null or trim(order_number_raw) = '' then null
            when order_number_raw ~ '^[0-9]+$' 
                then order_number_raw::integer
            else null
        end as order_number,
        
        -- Customer information
        customer_email,
        -- Edge case: Validate JSON before extraction to prevent casting errors
        case
            when customer_json is null or trim(customer_json) = '' then null
            when customer_json::text ~ '^\s*\{' 
                then (customer_json::json->>'id')
            else null
        end as customer_id_raw,
        
        -- Timestamps: normalize to UTC
        -- Edge case: Handle invalid timestamp formats gracefully
        case
            when created_at_raw is null or trim(created_at_raw) = '' then null
            when created_at_raw ~ '^\d{4}-\d{2}-\d{2}' 
                then (created_at_raw::timestamp with time zone) at time zone 'UTC'
            else null
        end as created_at,
        
        case
            when updated_at_raw is null or trim(updated_at_raw) = '' then null
            when updated_at_raw ~ '^\d{4}-\d{2}-\d{2}' 
                then (updated_at_raw::timestamp with time zone) at time zone 'UTC'
            else null
        end as updated_at,
        
        case
            when cancelled_at_raw is null or trim(cancelled_at_raw) = '' then null
            when cancelled_at_raw ~ '^\d{4}-\d{2}-\d{2}' 
                then (cancelled_at_raw::timestamp with time zone) at time zone 'UTC'
            else null
        end as cancelled_at,
        
        case
            when closed_at_raw is null or trim(closed_at_raw) = '' then null
            when closed_at_raw ~ '^\d{4}-\d{2}-\d{2}' 
                then (closed_at_raw::timestamp with time zone) at time zone 'UTC'
            else null
        end as closed_at,
        
        -- Financial fields: convert to numeric, handle nulls and invalid values
        -- Edge case: Validate numeric format, handle negative, scientific notation
        case
            when total_price_raw is null or trim(total_price_raw) = '' then 0.0
            when trim(total_price_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' 
                then least(greatest(trim(total_price_raw)::numeric, -999999999.99), 999999999.99)
            else 0.0
        end as total_price,
        
        case
            when subtotal_price_raw is null or trim(subtotal_price_raw) = '' then 0.0
            when trim(subtotal_price_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' 
                then least(greatest(trim(subtotal_price_raw)::numeric, -999999999.99), 999999999.99)
            else 0.0
        end as subtotal_price,
        
        case
            when total_tax_raw is null or trim(total_tax_raw) = '' then 0.0
            when trim(total_tax_raw) ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' 
                then least(greatest(trim(total_tax_raw)::numeric, -999999999.99), 999999999.99)
            else 0.0
        end as total_tax,
        
        -- Currency: standardize to uppercase, validate format
        -- Edge case: Handle null, empty, invalid currency codes
        case
            when currency_code is null or trim(currency_code) = '' then 'USD'
            when upper(trim(currency_code)) ~ '^[A-Z]{3}$' 
                then upper(trim(currency_code))
            else 'USD'
        end as currency,
        
        -- Status fields
        coalesce(financial_status, 'unknown') as financial_status,
        coalesce(fulfillment_status, 'unfulfilled') as fulfillment_status,
        
        -- Additional fields
        tags_raw as tags,
        note,
        refunds_json,
        
        -- Metadata
        airbyte_record_id,
        airbyte_emitted_at
        
    from orders_extracted
),

-- Join to tenant mapping to get tenant_id
-- 
-- CRITICAL: Tenant isolation must be properly configured based on your Airbyte setup.
-- The current implementation assumes single connection per tenant.
-- 
-- Tenant mapping strategies:
-- 1. Connection-specific schemas: Extract connection_id from schema name
-- 2. Connection ID in metadata: Join on connection_id from _airbyte_data or metadata
-- 3. Single connection per tenant: Use the approach below (current)
--
-- SECURITY WARNING: If multiple tenants have active Shopify connections,
-- the current `limit 1` approach will assign ALL orders to the first tenant.
-- This causes cross-tenant data leakage. You MUST configure proper tenant mapping.
--
-- To fix: Uncomment and configure one of the options below based on your setup.
orders_with_tenant as (
    select
        ord.*,
        coalesce(
            -- Option 1: Extract connection_id from schema name (if Airbyte uses connection-specific schemas)
            -- Example: schema name is "_airbyte_raw_<connection_id>_shopify"
            -- (select tenant_id 
            --  from {{ ref('_tenant_airbyte_connections') }} t
            --  where t.airbyte_connection_id = split_part(current_schema(), '_', 3)
            --    and t.source_type = 'shopify'
            --    and t.status = 'active'
            --    and t.is_enabled = true
            --  limit 1),
            
            -- Option 2: Extract connection_id from table metadata or _airbyte_data
            -- (select tenant_id 
            --  from {{ ref('_tenant_airbyte_connections') }} t
            --  where t.airbyte_connection_id = ord.airbyte_connection_id_from_metadata
            --    and t.source_type = 'shopify'
            --    and t.status = 'active'
            --    and t.is_enabled = true
            --  limit 1),
            
            -- Option 3: Single connection per tenant (CURRENT - USE WITH CAUTION)
            -- This only works if exactly one active Shopify connection exists
            -- If multiple connections exist, this causes data leakage
            (select tenant_id 
             from {{ ref('_tenant_airbyte_connections') }}
             where source_type = 'shopify'
               and status = 'active'
               and is_enabled = true
             limit 1),
            
            -- Fallback: null if no connection found
            null
        ) as tenant_id
    from orders_normalized ord
)

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
    refunds_json,
    airbyte_record_id,
    airbyte_emitted_at,
    tenant_id
from orders_with_tenant
where tenant_id is not null
    and order_id is not null  -- Edge case: Filter out null primary keys
    and trim(order_id) != ''  -- Edge case: Filter out empty primary keys
