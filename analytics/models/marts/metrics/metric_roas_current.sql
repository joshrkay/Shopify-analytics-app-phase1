{{
    config(
        materialized='view',
        schema='metrics',
        tags=['metrics', 'roas', 'alias', 'governed']
    )
}}

-- metric_roas_current - Governed alias for the approved ROAS version
--
-- This view ALWAYS points to the latest approved version.
-- It is the ONLY entry point dashboards should use for "current" ROAS.
--
-- Current target: metric_roas_v1 (approved 2025-06-01)
--
-- To upgrade:
--   1. Get approval via change_requests.yaml
--   2. Update this alias to point to the new version
--   3. Run pre-deploy validation
--   4. Communicate to affected dashboards
--
-- See: config/governance/metrics_versions.yaml
-- See: config/governance/change_approvals.yaml

select * from {{ ref('metric_roas_v1') }}
