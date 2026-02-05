{{
    config(
        materialized='view',
        schema='semantic',
        tags=['semantic', 'campaigns', 'versioned', 'immutable']
    )
}}

-- sem_campaign_performance_v1 - IMMUTABLE versioned semantic view of campaigns
--
-- Version: v1
-- Status: active
-- Released: 2026-02-05
-- Source: campaign_performance (canonical, schema registry v1.0.0)
--
-- DO NOT EDIT THIS VIEW. Create sem_campaign_performance_v2 instead.
--
-- This view defines the frozen column contract for v1. It exposes only
-- approved consumer-facing columns and excludes:
--   - platform (deprecated, use source_platform)
--   - airbyte_record_id (internal audit)
--   - ingested_at (internal audit)
--
-- See: canonical/schema_registry.yml

select
    id,
    tenant_id,
    date,
    source_platform,
    channel,
    ad_account_id,
    campaign_id,
    campaign_name,
    spend,
    impressions,
    clicks,
    conversions,
    ctr,
    cpc,
    cpa,
    currency,
    dbt_updated_at,
    'v1' as schema_version
from {{ ref('campaign_performance') }}
where tenant_id is not null
