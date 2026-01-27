{{
    config(
        materialized='table',
        schema='staging'
    )
}}

{#
    Dimension table for normalized campaign IDs across all platforms.

    This implements Option B ID normalization: generate internal normalized IDs
    while keeping platform IDs as attributes. Internal IDs are stable hashes
    that can be used for consistent joins across different ad platforms.

    Columns:
        - tenant_id: Tenant identifier for data isolation
        - source: Platform source identifier (meta_ads, google_ads, etc.)
        - platform_campaign_id: Original platform-specific campaign ID
        - internal_campaign_id: Deterministic hash ID for cross-platform joins
        - platform_account_id: Platform-specific account ID
        - internal_account_id: Links to dim_ad_accounts
        - campaign_name: Human-readable campaign name
        - first_seen_at: Earliest record timestamp
        - last_seen_at: Most recent record timestamp
#}

with meta_ads_campaigns as (
    select distinct
        tenant_id,
        'meta_ads' as source,
        campaign_id as platform_campaign_id,
        ad_account_id as platform_account_id,
        campaign_name,
        min(airbyte_emitted_at) as first_seen_at,
        max(airbyte_emitted_at) as last_seen_at
    from {{ ref('stg_meta_ads') }}
    where campaign_id is not null
    group by 1, 2, 3, 4, 5
),

google_ads_campaigns as (
    select distinct
        tenant_id,
        'google_ads' as source,
        campaign_id as platform_campaign_id,
        ad_account_id as platform_account_id,
        campaign_name,
        min(airbyte_emitted_at) as first_seen_at,
        max(airbyte_emitted_at) as last_seen_at
    from {{ ref('stg_google_ads') }}
    where campaign_id is not null
    group by 1, 2, 3, 4, 5
),

-- Union all ad platform campaigns
-- Additional platforms will be added here as their staging models are created:
-- tiktok_ads_campaigns, pinterest_ads_campaigns, snap_ads_campaigns, amazon_ads_campaigns

all_campaigns as (
    select * from meta_ads_campaigns
    union all
    select * from google_ads_campaigns
),

campaigns_with_internal_id as (
    select
        c.tenant_id,
        c.source,
        c.platform_campaign_id,
        {{ generate_internal_id('c.tenant_id', 'c.source', 'c.platform_campaign_id') }} as internal_campaign_id,
        c.platform_account_id,
        {{ generate_internal_id('c.tenant_id', 'c.source', 'c.platform_account_id') }} as internal_account_id,
        c.campaign_name,
        c.first_seen_at,
        c.last_seen_at,
        current_timestamp as created_at,
        current_timestamp as updated_at
    from all_campaigns c
)

select
    tenant_id,
    source,
    platform_campaign_id,
    internal_campaign_id,
    platform_account_id,
    internal_account_id,
    campaign_name,
    first_seen_at,
    last_seen_at,
    created_at,
    updated_at
from campaigns_with_internal_id
where internal_campaign_id is not null
