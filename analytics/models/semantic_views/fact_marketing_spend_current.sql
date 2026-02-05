{{
    config(
        materialized='view',
        schema='semantic',
        tags=['semantic', 'marketing', 'spend', 'alias', 'governed']
    )
}}

-- fact_marketing_spend_current - Governed alias for the approved spend version
--
-- This view ALWAYS points to the latest approved version.
-- It is the ONLY entry point downstream consumers (Superset, AI marts)
-- should use for marketing spend data.
--
-- Current target: sem_marketing_spend_v1 (approved 2026-02-05)
--
-- To upgrade:
--   1. Create sem_marketing_spend_v2 with the new column contract
--   2. Get approval via config/governance/change_requests.yaml
--   3. Update this alias to ref('sem_marketing_spend_v2')
--   4. Run pre-deploy validation
--   5. Communicate to affected dashboards
--
-- See: canonical/schema_registry.yml

select * from {{ ref('sem_marketing_spend_v1') }}
