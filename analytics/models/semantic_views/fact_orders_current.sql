{{
    config(
        materialized='view',
        schema='semantic',
        tags=['semantic', 'orders', 'alias', 'governed']
    )
}}

-- fact_orders_current - Governed alias for the approved order data version
--
-- This view ALWAYS points to the latest approved version.
-- It is the ONLY entry point downstream consumers (Superset, AI marts)
-- should use for order data.
--
-- Current target: sem_orders_v1 (approved 2026-02-05)
--
-- To upgrade:
--   1. Create sem_orders_v2 with the new column contract
--   2. Get approval via config/governance/change_requests.yaml
--   3. Update this alias to ref('sem_orders_v2')
--   4. Run pre-deploy validation
--   5. Communicate to affected dashboards
--
-- See: canonical/schema_registry.yml

select * from {{ ref('sem_orders_v1') }}
