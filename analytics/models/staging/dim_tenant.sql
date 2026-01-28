{{
    config(
        materialized='view',
        schema='staging'
    )
}}

-- Tenant dimension with timezone support for date normalization
--
-- This model provides tenant-level attributes including timezone for
-- normalizing timestamps to tenant local dates (per user story 7.7.1).
--
-- FUTURE: When tenant timezone data is available (e.g., from Shopify shop
-- settings or user configuration), update this model to pull from that source.
-- For now, defaults to UTC to maintain backward compatibility.
--
-- USAGE: Join to this model to get tenant timezone, then use the
-- convert_to_tenant_local_date macro for date conversion.

with tenant_base as (
    select distinct
        tenant_id
    from {{ ref('_tenant_airbyte_connections') }}
    where tenant_id is not null
)

select
    tenant_id,

    -- Timezone for date normalization
    -- TODO: Replace with actual tenant timezone when available
    -- Common sources: Shopify shop.iana_timezone, user settings table
    'UTC' as timezone,

    -- Metadata
    current_timestamp as dbt_updated_at

from tenant_base
