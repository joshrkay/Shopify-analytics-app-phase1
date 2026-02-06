# Canonical Dataset Exposure & Safety Model

*Internal documentation — Story 5.2.11.*

## Overview

This document describes how canonical data models are safely exposed to end users through Apache Superset. It covers the full lifecycle from dbt semantic views through Superset dataset sync, performance guardrails, fail-safe versioning, and observability.

## Why Semantic Views Exist

Canonical datasets are not exposed directly to Superset. Instead, **semantic views** (`sem_*_v1`) provide an immutable contract between the data warehouse and the visualization layer.

**Benefits:**
- **Column governance** — Only approved columns are exposed. PII and internal columns are excluded at the view level.
- **Version stability** — Views are versioned (`_v1`, `_v2`). Breaking changes create a new version; existing dashboards continue to work.
- **RLS enforcement** — Every view includes `tenant_id` for row-level security. There is no path to query data without tenant isolation.
- **Single source of truth** — All business logic (calculations, deduplication, currency handling) lives in dbt, not Superset.

### View Naming Convention

| Pattern | Purpose | Example |
|---|---|---|
| `sem_{domain}_v{N}` | Immutable versioned semantic view | `sem_orders_v1` |
| `fact_{domain}_current` | Alias pointing to the latest stable version | `fact_orders_current` |

Superset datasets always point to `fact_*_current` aliases. When a new version is ready, the alias is updated atomically.

## How Schema Changes Propagate

```
dbt model change → dbt run → manifest.json → sync job → Superset dataset
```

### Step-by-step:

1. **Developer modifies a dbt model** (e.g., adds a column to `sem_orders_v1`).
2. **dbt run** compiles and materializes the model. The `on-run-end` hook emits sync trigger metadata.
3. **Sync job** (separate CI step) reads the dbt manifest and compares against the current Superset dataset.
4. **Compatibility check** runs:
   - **Additive change** (new columns) → Safe, proceed.
   - **Breaking change** (removed/renamed exposed columns) → Block sync, alert operators.
5. **If compatible**, the sync job creates/updates the Superset dataset and activates the new version.
6. **If incompatible**, the sync is blocked, the current dataset is preserved, and an alert is sent.

### Column Governance

Columns are governed via dbt schema YAML with `meta.superset_expose`:

```yaml
columns:
  - name: revenue_net
    description: Net revenue (default for ROAS)
    meta:
      superset_expose: true

  - name: customer_email
    description: Customer email (PII)
    meta:
      superset_expose: false  # Never exposed to Superset
```

Only columns with `superset_expose: true` are synced to Superset. Columns without this meta key default to `false` (deny-by-default).

## How Failures Are Handled

### Sync Failure (API error, timeout)

- The current Superset dataset is **unchanged** (fail-safe).
- The new version is marked as `FAILED` in the `dataset_version` table.
- Operators receive a Slack alert (`#analytics-ops`).
- If 3+ failures within 1 hour for the same dataset, PagerDuty is triggered.

### Schema Incompatibility

- Sync is **blocked** before any changes are applied.
- The new version is marked as `FAILED` with the incompatibility reason.
- Operators receive a Slack + PagerDuty alert (CRITICAL severity).
- Manual intervention required: either fix the schema or use `--force` flag.

### Rollback

Rollback is safe because:
- Semantic views are immutable (`_v1` never changes).
- The `_current` alias is only updated after successful sync + activation.
- The `dataset_version` table preserves the full version history.
- Operators can roll back to the previous `SUPERSEDED` version via the version manager.

### Version State Machine

```
PENDING → ACTIVE → SUPERSEDED
PENDING → FAILED
ACTIVE → ROLLED_BACK
SUPERSEDED → ACTIVE (on rollback)
```

## Performance Limits

Performance is enforced at three layers (defense in depth):

### Layer 1: Superset Application (`performance_config.py`)

| Limit | Value | Rationale |
|---|---|---|
| Query timeout | 20 seconds | Prevents runaway queries |
| Row limit | 50,000 | Prevents large data exports |
| Max date range | 90 days | Bounds query scope |
| Max group-by dimensions | 2 | Limits query complexity |
| Max filters | 10 | Prevents filter abuse |
| Max metrics per query | 5 | Limits aggregation cost |
| Cache TTL | 30 minutes | Balances freshness vs performance |

All limits are frozen (immutable dataclass) and cannot be overridden at runtime.

### Layer 2: Explore Guardrails (`explore_guardrails.py`)

- **Persona-based access** — Merchants and agencies see different datasets/metrics.
- **Dataset-level restrictions** — Each dataset has an allow-list of dimensions, metrics, and visualizations.
- **Per-dataset guardrail overrides** — Individual datasets can have stricter limits than the global defaults (loaded from YAML configs).
- **SQL injection prevention** — Custom SQL, subqueries, and Jinja templates are disabled.
- **Export controls** — All file exports (CSV, pivot) are disabled.

### Layer 3: PostgreSQL Database (`database_timeouts.sql`)

| Role | `statement_timeout` | `work_mem` | Connection Limit |
|---|---|---|---|
| `analytics_reader` | 20s | 64MB | 50 |
| `superset_service` | 30s | 128MB | 20 |
| `markinsight_user` (admin) | none | default | default |

The `analytics_reader` role is used for all tenant-facing queries. Even if Superset guardrails are bypassed, the database kills queries exceeding 20 seconds.

### Performance Indexes

Composite indexes are created on the most common query patterns:

```sql
-- tenant_id + date (range scans)
CREATE INDEX ix_fact_orders_tenant_date
    ON analytics.fact_orders_current (tenant_id, order_date DESC);

-- tenant_id + channel (group-by)
CREATE INDEX ix_fact_orders_tenant_channel
    ON analytics.fact_orders_current (tenant_id, channel);

-- tenant_id + date + channel (covers most Explore queries)
CREATE INDEX ix_fact_orders_tenant_date_channel
    ON analytics.fact_orders_current (tenant_id, order_date DESC, channel);
```

## Observability

### Dataset Metrics (`dataset_metrics` table)

Each dataset tracks:

| Metric | Source | Update Frequency |
|---|---|---|
| `last_sync_at` | Sync job | Every sync |
| `sync_status` | Sync job | Every sync |
| `schema_version` | Sync job | Every sync |
| `row_count` | `pg_class` (approximate) | Periodic |
| `query_count_24h` | `pg_stat_statements` | Periodic |
| `avg_query_latency_ms` | `pg_stat_statements` | Periodic |
| `cache_hit_rate` | Application metrics | Periodic |

### API Endpoint

`GET /api/data-health/dataset-health` returns the current health of all tracked datasets.

### Alerting

| Alert | Severity | Channels | Cooldown |
|---|---|---|---|
| Sync failure | HIGH | Slack → PagerDuty (3+ in 1h) | 5 min |
| Schema incompatibility | CRITICAL | Slack + PagerDuty | 5 min |
| Stale dataset (beyond SLA) | MEDIUM | Slack | 5 min |
| Version rollback | HIGH | Slack + PagerDuty | 5 min |

### Audit Events

All dataset lifecycle events are logged to the immutable audit log:

| Event | When |
|---|---|
| `dataset.sync.started` | Sync job begins |
| `dataset.sync.completed` | Sync succeeds |
| `dataset.sync.failed` | Sync fails |
| `dataset.version.activated` | New version promoted to ACTIVE |
| `dataset.version.rolled_back` | Operator rolls back to previous version |

## File Reference

| File | Purpose |
|---|---|
| `analytics/models/semantic_views/sem_*_v1.sql` | Immutable versioned semantic views |
| `analytics/models/semantic_views/fact_*_current.sql` | Aliases to latest stable version |
| `analytics/models/semantic_views/schema.yml` | Column governance (superset_expose) |
| `docker/superset/performance_config.py` | Frozen performance limits |
| `docker/superset/explore_guardrails.py` | Persona + dataset restrictions |
| `docker/superset/guards.py` | Startup + runtime safety checks |
| `docker/superset/sync/dbt_superset_sync.py` | Sync job (manifest → Superset) |
| `docker/superset/datasets/*.yaml` | Per-dataset configuration |
| `db/migrations/performance_indexes.sql` | DB indexes + role setup |
| `db/config/database_timeouts.sql` | Per-role timeout configuration |
| `backend/src/models/dataset_version.py` | Version tracking model |
| `backend/src/models/dataset_metrics.py` | Observability metrics model |
| `backend/src/services/dataset_version_manager.py` | Version lifecycle management |
| `backend/src/services/dataset_observability.py` | Metrics collection service |
| `backend/src/monitoring/dataset_alerts.py` | Operator alerting |
| `backend/src/services/audit_logger.py` | Audit event emitters |
