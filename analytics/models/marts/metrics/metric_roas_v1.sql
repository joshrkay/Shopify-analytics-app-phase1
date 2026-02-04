{{
    config(
        materialized='view',
        schema='metrics',
        tags=['metrics', 'roas', 'versioned', 'immutable']
    )
}}

-- metric_roas_v1 - IMMUTABLE versioned ROAS view
--
-- Version: v1
-- Status: active
-- Released: 2025-06-01
-- Definition: Gross ROAS = revenue / ad_spend (platform-attributed, last-click)
--
-- DO NOT EDIT THIS VIEW. Create a new version instead.
-- See: config/governance/metrics_versions.yaml

select
    id,
    tenant_id,
    platform,
    period_type,
    period_start,
    currency,
    campaign_id,
    order_count,
    total_spend,
    total_gross_revenue,
    total_net_revenue,
    gross_roas,
    net_roas,
    avg_order_value_gross,
    avg_order_value_net,
    dbt_updated_at,
    'v1' as metric_version
from {{ ref('fct_roas') }}
