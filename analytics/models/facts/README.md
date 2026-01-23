# Fact Tables

Canonical fact tables representing the source of truth for business events.

## Overview

Fact tables are materialized as **incremental** models in the `analytics` schema. They process only new or updated records based on `airbyte_emitted_at` timestamps.

## Models

### `fact_orders`

Canonical fact table for Shopify orders.

**Source**: `stg_shopify_orders`

**Key Fields**:
- `id`: Surrogate key (MD5 hash of `tenant_id` + `order_id`)
- `order_id`: Shopify order ID (normalized)
- `revenue`: Total order price (renamed from `total_price`)
- `tenant_id`: Tenant identifier (required for isolation)

**Incremental Strategy**:
- Processes records where `airbyte_emitted_at > max(ingested_at)` from existing table
- First run processes all records

### `fact_ad_spend`

Unified fact table for ad spend across all platforms (Meta Ads, Google Ads).

**Sources**: `stg_meta_ads`, `stg_google_ads`

**Key Fields**:
- `id`: Surrogate key (MD5 hash of composite key)
- `platform`: Platform identifier (`meta_ads` or `google_ads`)
- `spend`: Amount spent (normalized currency)
- `spend_date`: Date of the spend
- `tenant_id`: Tenant identifier (required for isolation)

**Incremental Strategy**:
- Processes records per platform where `airbyte_emitted_at > max(ingested_at)` for that platform
- Handles platform-specific incremental logic

### `fact_campaign_performance`

Unified fact table for campaign-level performance metrics across all platforms.

**Sources**: `stg_meta_ads`, `stg_google_ads`

**Key Fields**:
- `id`: Surrogate key (MD5 hash of composite key)
- `platform`: Platform identifier (`meta_ads` or `google_ads`)
- `spend`, `impressions`, `clicks`, `conversions`: Performance metrics
- `ctr`, `cpc`, `cpa`: Calculated metrics
- `performance_date`: Date of the metrics
- `tenant_id`: Tenant identifier (required for isolation)

**Calculated Metrics**:
- `ctr`: Click-through rate = (clicks / impressions) * 100
- `cpc`: Cost per click = spend / clicks
- `cpa`: Cost per acquisition = spend / conversions

**Incremental Strategy**:
- Processes records per platform where `airbyte_emitted_at > max(ingested_at)` for that platform

## Tenant Isolation

All fact tables enforce tenant isolation:

1. **Filtering**: Only includes records where `tenant_id is not null`
2. **Validation**: `tenant_id` is tested against `_tenant_airbyte_connections`
3. **Primary Keys**: Include `tenant_id` in surrogate key generation to ensure uniqueness across tenants

## Incremental Processing

All fact tables use incremental materialization:

- **First Run**: Processes all records from staging
- **Subsequent Runs**: Only processes new/updated records based on `airbyte_emitted_at`
- **Strategy**: Time-based incremental using `airbyte_emitted_at` timestamp

## Data Quality Tests

All fact tables have comprehensive tests defined in `schema.yml`:

- `not_null` on primary keys and required fields
- `unique` on primary keys
- `relationships` for tenant_id validation
- `accepted_values` for currency and platform codes

## Usage

```sql
-- Run all fact tables
dbt run --select facts

-- Run specific fact table
dbt run --select fact_orders

-- Run tests
dbt test --select facts
```

## Schema

All fact tables are created in the `analytics` schema as defined in `dbt_project.yml`.
