{{
    config(
        materialized='view',
        schema='staging'
    )
}}

{#
    Staging model for Shopify orders with strict typing, standardization, and dedup.

    This model:
    - Extracts and normalizes raw Shopify order data from Airbyte
    - Adds record_sk (stable surrogate key), source_system, source_primary_key
    - Deduplicates by (tenant_id, order_id) keeping the latest Airbyte emission
    - Applies defensive type casting with regex validation
    - Excludes PII from downstream consumers via canonical layer
    - Tenant isolation via shop_domain join to _tenant_airbyte_connections

    SECURITY: Tenant isolation enforced via inner join on shop_domain.
#}

with raw_orders as (
    select
        _airbyte_ab_id as airbyte_record_id,
        _airbyte_emitted_at as airbyte_emitted_at,
        _airbyte_data as order_data
    from {{ source('raw_shopify', 'orders') }}
),

tenant_mapping as (
    select
        tenant_id,
        shop_domain
    from {{ ref('_tenant_airbyte_connections') }}
    where source_type in ('shopify', 'source-shopify')
        and status = 'active'
        and is_enabled = true
        and shop_domain is not null
        and shop_domain != ''
),

orders_extracted as (
    select
        raw.airbyte_record_id,
        raw.airbyte_emitted_at,
        raw.order_data->>'shop_url' as shop_url,
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
        raw.order_data->>'tags' as tags_raw,
        raw.order_data->>'note' as note,
        raw.order_data->>'order_number' as order_number_raw,
        raw.order_data->'refunds' as refunds_json
    from raw_orders raw
),

orders_normalized as (
    select
        -- Primary key: normalize order ID (remove gid:// prefix if present)
        case
            when order_id_raw is null or trim(order_id_raw) = '' then null
            when order_id_raw like 'gid://shopify/Order/%'
                then replace(order_id_raw, 'gid://shopify/Order/', '')
            when order_id_raw like 'gid://shopify/Order%'
                then regexp_replace(order_id_raw, '^gid://shopify/Order/?', '', 'g')
            else trim(order_id_raw)
        end as order_id,

        order_name,

        case
            when order_number_raw is null or trim(order_number_raw) = '' then null
            when order_number_raw ~ '^[0-9]+$'
                then order_number_raw::integer
            else null
        end as order_number,

        customer_email,

        case
            when customer_json is null or trim(customer_json) = '' then null
            when customer_json::text ~ '^\s*\{'
                then (customer_json::json->>'id')
            else null
        end as customer_id_raw,

        -- Timestamps: normalize to UTC
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

        -- Financial fields: defensive numeric casting
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
        case
            when currency_code is null or trim(currency_code) = '' then 'USD'
            when upper(trim(currency_code)) ~ '^[A-Z]{3}$'
                then upper(trim(currency_code))
            else 'USD'
        end as currency,

        coalesce(financial_status, 'unknown') as financial_status,
        coalesce(fulfillment_status, 'unfulfilled') as fulfillment_status,

        tags_raw as tags,
        note,
        refunds_json,

        airbyte_record_id,
        airbyte_emitted_at,

        -- Normalized shop_domain for tenant mapping
        lower(
            trim(
                trailing '/' from
                regexp_replace(
                    coalesce(shop_url, ''),
                    '^https?://',
                    '',
                    'i'
                )
            )
        ) as shop_domain

    from orders_extracted
),

orders_with_tenant as (
    select
        ord.*,
        tm.tenant_id
    from orders_normalized ord
    inner join tenant_mapping tm
        on ord.shop_domain = tm.shop_domain
),

-- Dedup: keep latest record per (tenant_id, order_id)
orders_deduped as (
    select
        *,
        row_number() over (
            partition by tenant_id, order_id
            order by airbyte_emitted_at desc
        ) as _row_num
    from orders_with_tenant
    where order_id is not null
        and trim(order_id) != ''
)

select
    -- Surrogate key: md5(tenant_id || source_system || source_primary_key)
    md5(tenant_id || '|' || 'shopify' || '|' || order_id) as record_sk,

    -- Source tracking
    'shopify' as source_system,
    order_id as source_primary_key,

    -- Tenant isolation
    tenant_id,

    -- Order identifiers
    order_id,
    order_name,
    order_number,
    created_at::date as report_date,

    -- Customer fields
    customer_email,
    customer_id_raw,

    -- Timestamps (all UTC)
    created_at,
    updated_at,
    cancelled_at,
    closed_at,

    -- Financial fields (strict numeric types, no business metric calculations)
    total_price,
    subtotal_price,
    total_tax,
    currency,

    -- Status fields
    financial_status,
    fulfillment_status,

    -- Additional fields
    tags,
    note,
    refunds_json,

    -- Metadata
    airbyte_record_id,
    airbyte_emitted_at

from orders_deduped
where _row_num = 1
