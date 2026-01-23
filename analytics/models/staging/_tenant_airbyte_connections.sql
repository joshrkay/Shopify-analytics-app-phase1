{{
    config(
        materialized='view',
        schema='staging'
    )
}}

-- This model exposes the tenant_airbyte_connections table for use in staging models
-- It filters to only active Shopify connections for tenant isolation
--
-- SECURITY: This model is used to map Airbyte connections to tenants.
-- All staging models must join through this to ensure tenant isolation.

select
    airbyte_connection_id,
    tenant_id,
    source_type,
    connection_name,
    status,
    is_enabled
from {{ source('platform', 'tenant_airbyte_connections') }}
where source_type in ('shopify', 'source-facebook-marketing', 'source-google-ads')
    and status = 'active'
    and is_enabled = true
