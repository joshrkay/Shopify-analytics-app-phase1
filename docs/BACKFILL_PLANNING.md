# Backfill Planning — How Historical Reprocessing Works

Story 3.4 — Backfill Request API & Planner

## Overview

When data needs reprocessing (schema changes, bug fixes, attribution window
updates), the backfill planner determines **exactly what to rebuild** for a
given tenant, source system, and date range.

## Pipeline Layers

Data flows through these layers in order:

```
raw → staging → canonical → attribution → semantic → metrics → marts
```

| Layer | Materialization | Rebuild strategy |
|---|---|---|
| **raw** | External (Airbyte) | Re-ingest from source API |
| **staging** | VIEW | Automatic (reads raw) |
| **canonical** | INCREMENTAL (delete+insert) | Date-range scoped rebuild |
| **attribution** | VIEW | Automatic (reads canonical) |
| **semantic** | VIEW (immutable) | Automatic (reads canonical) |
| **metrics** | VIEW / TABLE | Views auto-update; tables full refresh |
| **marts** | TABLE | Full refresh |

## Source System → Model Mapping

### Shopify
```
raw_shopify_orders, raw_shopify_customers
  → stg_shopify_orders, stg_shopify_customers
    → orders, fact_orders_v1
      → sem_orders_v1 → fact_orders_current
      → last_click (attribution)
      → fct_revenue → fct_aov
      → fct_roas, fct_cac
      → fct_marketing_metrics
      → mart_revenue_metrics, mart_marketing_metrics
```

### Facebook (Meta Ads)
```
raw_meta_ads
  → stg_facebook_ads_performance
    → marketing_spend, fact_marketing_spend_v1
    → campaign_performance, fact_campaign_performance_v1
      → sem_marketing_spend_v1, sem_campaign_performance_v1
      → fct_roas, fct_cac, fct_marketing_metrics
      → metric_roas_v1, metric_roas_v2
      → mart_marketing_metrics
```

### Google Ads
Same downstream as Facebook — feeds `marketing_spend` and
`campaign_performance` canonical models.

### TikTok Ads
```
raw_tiktok_ads
  → stg_tiktok_ads_performance
    → marketing_spend, fact_marketing_spend_v1
      → sem_marketing_spend_v1 → ...
```

### Snapchat Ads
```
raw_snapchat_ads
  → stg_snapchat_ads
    → marketing_spend, fact_marketing_spend_v1
      → sem_marketing_spend_v1 → ...
```

### Klaviyo (Email)
```
raw_klaviyo_events
  → stg_klaviyo_events → stg_email_campaigns
```

## How the Planner Works

1. **Input**: `(tenant_id, source_system, start_date, end_date)`
2. **Resolve seed models**: Look up staging models for the source system
3. **Walk the dependency graph**: BFS forward through `MODEL_REGISTRY` to find
   all affected downstream models
4. **Sort by layer**: Execution order follows the pipeline: staging first,
   marts last
5. **Estimate cost**: Based on rows-per-day heuristics and materialisation type
6. **Produce dbt command**: `dbt run --select <models> --vars '{...}'`

## Partial Rebuilds

The planner only rebuilds models that are **downstream** of the requested
source system. For example, a Shopify-only backfill will **not** touch
`stg_facebook_ads_performance` or other ad-platform staging models.

Canonical models like `marketing_spend` that union multiple sources will only
reprocess the relevant date range for the affected source's partition.

## Tenant Isolation

All backfills are scoped to a single `tenant_id`:
- The `backfill_tenant_id` dbt variable is passed to every model
- Staging models join on `_tenant_airbyte_connections` to filter by tenant
- Canonical incremental models use `delete+insert` scoped by tenant + date

## Cost Estimation

Estimates are rough heuristics, not guarantees:

| Source | Rows/day (approx) |
|---|---|
| Shopify | ~500 |
| Facebook Ads | ~200 |
| Google Ads | ~200 |
| TikTok Ads | ~100 |
| Snapchat Ads | ~50 |
| Klaviyo Email | ~300 |

Processing time per 1,000 rows:
- VIEW: 0s (instant — reads from upstream)
- INCREMENTAL: ~2s (delete+insert)
- TABLE: ~3s (full refresh)

## API Endpoint

```
POST /api/v1/admin/backfills
```

Super admin only. See `admin_backfills.py` for the endpoint implementation
and `backfill_validator.py` for validation rules (billing tier limits,
overlap detection, idempotency).

## Billing Tier Limits

| Tier | Max backfill window |
|---|---|
| Free | 90 days |
| Growth | 90 days |
| Enterprise | 365 days |
