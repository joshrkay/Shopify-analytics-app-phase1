{{
    config(
        materialized='table',
        schema='staging'
    )
}}

{#
    Dimension table for normalized ad account IDs across all platforms.

    This implements Option B ID normalization: generate internal normalized IDs
    while keeping platform IDs as attributes. Internal IDs are stable hashes
    that can be used for consistent joins across different ad platforms.

    Columns:
        - tenant_id: Tenant identifier for data isolation
        - source: Platform source identifier (meta_ads, google_ads, etc.)
        - platform_account_id: Original platform-specific account ID
        - internal_account_id: Deterministic hash ID for cross-platform joins
        - account_name: Human-readable account name (if available)
        - currency: Account currency (if available)
        - first_seen_at: Earliest record timestamp
        - last_seen_at: Most recent record timestamp
#}

with meta_ads_accounts as (
    select distinct
        tenant_id,
        'meta_ads' as source,
        ad_account_id as platform_account_id,
        currency,
        min(airbyte_emitted_at) as first_seen_at,
        max(airbyte_emitted_at) as last_seen_at
    from {{ ref('stg_meta_ads') }}
    where ad_account_id is not null
    group by 1, 2, 3, 4
),

google_ads_accounts as (
    select distinct
        tenant_id,
        'google_ads' as source,
        ad_account_id as platform_account_id,
        currency,
        min(airbyte_emitted_at) as first_seen_at,
        max(airbyte_emitted_at) as last_seen_at
    from {{ ref('stg_google_ads') }}
    where ad_account_id is not null
    group by 1, 2, 3, 4
),

-- Union all ad platform accounts
-- Additional platforms will be added here as their staging models are created:
-- tiktok_ads_accounts, pinterest_ads_accounts, snap_ads_accounts, amazon_ads_accounts

all_accounts as (
    select * from meta_ads_accounts
    union all
    select * from google_ads_accounts
),

accounts_with_internal_id as (
    select
        tenant_id,
        source,
        platform_account_id,
        {{ generate_internal_id('tenant_id', 'source', 'platform_account_id') }} as internal_account_id,
        currency,
        first_seen_at,
        last_seen_at,
        current_timestamp as created_at,
        current_timestamp as updated_at
    from all_accounts
)

select
    tenant_id,
    source,
    platform_account_id,
    internal_account_id,
    currency,
    first_seen_at,
    last_seen_at,
    created_at,
    updated_at
from accounts_with_internal_id
where internal_account_id is not null
