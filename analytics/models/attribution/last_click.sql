{{
    config(
        materialized='view',
        schema='analytics'
    )
}}

-- Last-Click Attribution Model
-- 
-- This model implements baseline last-click attribution by joining orders to campaigns
-- via UTM parameters. It uses the UTM parameters captured at order time to attribute
-- revenue to the marketing campaign that drove the conversion.
--
-- ASSUMPTIONS & LIMITATIONS:
-- 1. UTM parameters are captured at order creation time (stored in order note_attributes)
-- 2. Last-click means the UTM parameters on the order represent the last marketing touchpoint
-- 3. Campaign matching is done via utm_campaign matching campaign_name or campaign_id
-- 4. Orders without UTM parameters are not attributed (attribution fields will be null)
-- 5. This is a simplified model that does not track multi-touch customer journeys
-- 6. Attribution is deterministic: same order + same UTM = same attribution result
--
-- SECURITY: Tenant isolation is enforced - all rows must have tenant_id

with raw_orders as (
    select
        _airbyte_ab_id as airbyte_record_id,
        _airbyte_emitted_at as airbyte_emitted_at,
        _airbyte_data as order_data
    from {{ source('airbyte_raw', '_airbyte_raw_shopify_orders') }}
),

tenant_mapping as (
    select
        tenant_id
    from {{ ref('_tenant_airbyte_connections') }}
    where source_type = 'shopify'
        and status = 'active'
        and is_enabled = true
    limit 1
),

-- Extract UTM parameters from order note_attributes
-- Shopify stores UTM parameters in note_attributes array: [{"name": "utm_source", "value": "google"}, ...]
orders_with_utm as (
    select
        raw.order_data->>'id' as order_id_raw,
        raw.order_data->>'note_attributes' as note_attributes_json,
        (select tenant_id from tenant_mapping limit 1) as tenant_id
    from raw_orders raw
),

-- Parse UTM parameters from note_attributes JSON array
utm_extracted as (
    select
        -- Normalize order ID (remove gid:// prefix if present)
        case
            when order_id_raw is null or trim(order_id_raw) = '' then null
            when order_id_raw like 'gid://shopify/Order/%' 
                then replace(order_id_raw, 'gid://shopify/Order/', '')
            when order_id_raw like 'gid://shopify/Order%' 
                then regexp_replace(order_id_raw, '^gid://shopify/Order/?', '', 'g')
            else trim(order_id_raw)
        end as order_id,
        
        -- Extract UTM parameters from note_attributes JSON array using macro
        {{ extract_utm_param('note_attributes_json', "'utm_source'") }} as utm_source,
        {{ extract_utm_param('note_attributes_json', "'utm_medium'") }} as utm_medium,
        {{ extract_utm_param('note_attributes_json', "'utm_campaign'") }} as utm_campaign,
        {{ extract_utm_param('note_attributes_json', "'utm_term'") }} as utm_term,
        {{ extract_utm_param('note_attributes_json', "'utm_content'") }} as utm_content,
        
        tenant_id
        
    from orders_with_utm
    where tenant_id is not null
        and order_id_raw is not null
        and trim(order_id_raw) != ''
),

-- Get order details from fact table
orders_fact as (
    select
        id as order_fact_id,
        order_id,
        order_name,
        order_number,
        customer_key,  -- Pseudonymized customer identifier (replaces PII)
        order_created_at,
        revenue_gross as revenue,
        currency,
        tenant_id
    from {{ ref('fact_orders') }}
),

-- Get campaign performance data
campaigns as (
    select
        id as campaign_fact_id,
        ad_account_id,
        campaign_id,
        campaign_name,
        source_platform as platform,
        date as performance_date,
        spend,
        clicks,
        impressions,
        conversions,
        currency as campaign_currency,
        tenant_id
    from {{ ref('fact_campaign_performance') }}
),

-- Join orders with UTM to campaigns
-- Match on: utm_campaign = campaign_name OR utm_campaign = campaign_id
-- Also match on tenant_id and ensure dates align (order date should be >= campaign performance date)
-- Note: We use LEFT JOIN to include all orders, even those without UTM parameters
attribution_joined as (
    select
        ord.order_fact_id,
        ord.order_id,
        ord.order_name,
        ord.order_number,
        ord.customer_key,
        ord.order_created_at,
        ord.revenue,
        ord.currency,
        ord.tenant_id,
        
        -- UTM parameters (null if order has no UTM parameters)
        utm.utm_source,
        utm.utm_medium,
        utm.utm_campaign,
        utm.utm_term,
        utm.utm_content,
        
        -- Campaign attribution (last-click: most recent campaign match)
        camp.campaign_fact_id,
        camp.ad_account_id,
        camp.campaign_id,
        camp.campaign_name,
        camp.platform,
        camp.performance_date as campaign_performance_date,
        camp.spend as campaign_spend,
        camp.clicks as campaign_clicks,
        camp.impressions as campaign_impressions,
        camp.conversions as campaign_conversions
        
    from orders_fact ord
    left join utm_extracted utm
        on ord.order_id = utm.order_id
        and ord.tenant_id = utm.tenant_id
    left join campaigns camp
        on ord.tenant_id = camp.tenant_id
        and utm.utm_campaign is not null
        and trim(utm.utm_campaign) != ''
        and (
            -- Match utm_campaign to campaign_name (case-insensitive)
            lower(trim(utm.utm_campaign)) = lower(trim(camp.campaign_name))
            or
            -- Match utm_campaign to campaign_id (case-insensitive)
            lower(trim(utm.utm_campaign)) = lower(trim(camp.campaign_id))
        )
        -- Ensure campaign performance date is on or before order date (campaign must exist before order)
        and camp.performance_date <= date(ord.order_created_at)
),

-- Rank campaign matches to select the most recent (last-click)
-- For orders with multiple campaign matches, select the one with the latest performance_date
attribution_raw as (
    select
        *,
        -- Attribution logic: match utm_campaign to campaign_name or campaign_id
        -- Use row_number to get the most recent campaign match (last-click)
        -- Deterministic: same order + same UTM + same campaigns = same rank
        row_number() over (
            partition by order_id, tenant_id
            order by 
                case when campaign_fact_id is not null then 0 else 1 end,  -- Prioritize matches
                campaign_performance_date desc nulls last,  -- Most recent campaign
                campaign_fact_id desc nulls last  -- Tie-breaker for same date
        ) as attribution_rank
    from attribution_joined
)

-- Final output: only the top-ranked attribution (last-click)
select
    -- Primary key: deterministic hash of order_id + tenant_id
    md5(concat(order_id, '|', tenant_id, '|', 'last_click')) as id,

    -- Order identifiers
    order_id,
    order_name,
    order_number,
    customer_key,
    order_created_at,
    
    -- Financial metrics
    revenue,
    currency,
    
    -- UTM parameters (the last-click touchpoint)
    utm_source,
    utm_medium,
    utm_campaign,
    utm_term,
    utm_content,
    
    -- Attributed campaign (null if no match found)
    campaign_fact_id,
    ad_account_id,
    campaign_id,
    campaign_name,
    platform,
    campaign_performance_date,
    campaign_spend,
    campaign_clicks,
    campaign_impressions,
    campaign_conversions,
    
    -- Attribution metadata
    case 
        when campaign_fact_id is not null then 'attributed'
        when utm_campaign is not null then 'unattributed_utm_present'
        else 'unattributed_no_utm'
    end as attribution_status,
    
    -- Tenant isolation (CRITICAL)
    tenant_id,
    
    -- Audit fields
    current_timestamp as dbt_updated_at
    
from attribution_raw
where attribution_rank = 1  -- Only the last-click attribution
