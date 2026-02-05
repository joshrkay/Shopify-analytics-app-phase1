# Rolling Rebuild Strategy

## Overview

The v1 canonical fact tables use a **rolling rebuild window** to handle late-arriving data. Instead of only processing newly-ingested records (like the legacy models), the rolling rebuild reprocesses all records within a configurable time window on every incremental run.

This catches:
- Late-arriving refunds and order status updates (Shopify)
- Attribution window updates from ad platforms
- Late conversions reported after initial sync
- Platform corrections and restatements

## How It Works

### Business-Date Filtering

The rolling rebuild filters on **business date** (the date the event occurred), not ingestion timestamp (`airbyte_emitted_at`). This is a deliberate design choice:

- A refund processed today for an order placed 15 days ago updates the *order record*, not the refund date
- Attribution windows on ad platforms revise conversion data for past campaign dates
- Business-date filtering ensures these updates are captured when the original date falls within the window

### Incremental Strategy: `delete+insert`

All v1 models use `delete+insert` instead of `merge`:

1. On each incremental run, dbt deletes all rows in the target table whose `id` matches the incoming data
2. Then inserts the fresh rows from the source query
3. Rows **outside** the rolling window are untouched

This guarantees that updates to existing records (refund status changes, attribution corrections) are always reflected.

## Configuration

Rolling rebuild windows are configured as dbt vars in `dbt_project.yml`:

| Variable | Default | Used By |
|---|---|---|
| `shopify_rebuild_days` | 90 | `fact_orders_v1` |
| `ads_rebuild_days` | 30 | `fact_marketing_spend_v1`, `fact_campaign_performance_v1` |
| `email_rebuild_days` | 30 | (Future email canonical models) |

### Override at Runtime

```bash
# Use a wider window for Shopify (e.g., catching late refunds)
dbt run --select fact_orders_v1 --vars '{shopify_rebuild_days: 120}'

# Narrow window for a quick ad refresh
dbt run --select fact_marketing_spend_v1 --vars '{ads_rebuild_days: 7}'

# Full refresh (reprocess all data, ignoring the window)
dbt run --select fact_orders_v1 --full-refresh
```

## Model Details

### fact_orders_v1

- **Window:** 90 days on `order_date` (mapped from `report_date`)
- **Grain:** One row per order
- **Why 90 days:** Shopify refunds and chargebacks can arrive weeks after the original order. A 90-day window covers the typical dispute resolution timeline.

```sql
{% if is_incremental() %}
    and o.report_date >= current_date - {{ var('shopify_rebuild_days', 90) }}
{% endif %}
```

### fact_marketing_spend_v1

- **Window:** 30 days on `spend_date` (mapped from `date`)
- **Grain:** One row per tenant + source_system + campaign + ad_set + ad + date
- **Why 30 days:** Ad platform reporting is typically finalized within 7-14 days. A 30-day window provides margin for platform corrections and restatements.

```sql
{% if is_incremental() %}
    and date >= current_date - {{ var('ads_rebuild_days', 30) }}
{% endif %}
```

### fact_campaign_performance_v1

- **Window:** 30 days on `campaign_date` (mapped from `date`)
- **Grain:** One row per tenant + source_system + campaign + ad_set + date
- **Why 30 days:** Attribution windows (typically 7-28 days) mean conversion data is revised after initial reporting. A 30-day window ensures attributed revenue reflects final attribution.

```sql
{% if is_incremental() %}
    and date >= current_date - {{ var('ads_rebuild_days', 30) }}
{% endif %}
```

## Behavior Summary

| Run Type | Rows Inside Window | Rows Outside Window |
|---|---|---|
| Full refresh (`--full-refresh`) | Reprocessed | Reprocessed |
| Incremental run | Deleted and re-inserted | Unchanged |
| First run (empty table) | All rows inserted | N/A |

## Trade-offs

1. **Cost vs. correctness:** Wider windows reprocess more data per run, increasing compute cost. Narrower windows risk missing late-arriving updates.
2. **Business date vs. ingestion date:** Business-date filtering may reprocess records that haven't changed if they fall within the window. This is an acceptable trade-off for correctness.
3. **delete+insert vs. merge:** `delete+insert` is simpler and avoids merge conflicts but requires the unique key (`id`) to be deterministic and stable.

## Monitoring

To verify the rolling rebuild is working correctly:

- Check that `dbt_updated_at` timestamps within the window are recent (updated on last run)
- Check that `dbt_updated_at` timestamps outside the window are from a previous run
- Monitor row counts: a sudden drop may indicate the window is too narrow
