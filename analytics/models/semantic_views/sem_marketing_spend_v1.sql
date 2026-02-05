{{
    config(
        materialized='view',
        schema='semantic',
        tags=['semantic', 'marketing', 'spend', 'versioned', 'immutable']
    )
}}

-- sem_marketing_spend_v1 - IMMUTABLE versioned semantic view of marketing spend
--
-- Version: v1
-- Status: active
-- Released: 2026-02-05
-- Source: marketing_spend (canonical, schema registry v1.1.0)
--
-- DO NOT EDIT THIS VIEW. Create sem_marketing_spend_v2 instead.
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
    adset_id,
    ad_id,
    spend,
    currency,
    impressions,
    clicks,
    conversions,
    conversion_value,
    cpm,
    cpc,
    ctr,
    cpa,
    roas,
    dbt_updated_at,
    'v1' as schema_version
from {{ ref('marketing_spend') }}
where tenant_id is not null
