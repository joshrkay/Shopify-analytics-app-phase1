# Root Cause Diagnostics

How automated root cause analysis works for data quality anomalies.

Story 4.2 - Data Quality Root Cause Signals

---

## Overview

When the data quality system (Story 4.1) detects an anomaly, the root cause engine automatically generates **ranked hypotheses** explaining what broke, where, and why. This is operator-grade diagnostics -- not merchant-facing, not auto-fixing, not LLM-generated.

Five root cause categories are evaluated:

| Category | Module | What It Detects |
|----------|--------|-----------------|
| Ingestion Failure | `ingestion_diagnostics.py` | Sync failures, partial syncs, long-running jobs, missing syncs |
| Schema Drift | `schema_drift.py` | Column added/removed/type-changed, correlated dbt failures |
| Transformation Regression | `transformation_regression.py` | dbt model failures, pass-to-fail transitions, execution time spikes |
| Upstream Data Shift | `upstream_shift.py` | Distribution drift (JSD), cardinality explosion, new dimension values |
| Downstream Logic Change | (future) | Reserved for reporting/dashboard logic changes |

---

## How Hypotheses Are Generated

### Phase 1: Signal Collection

The `RootCauseRanker.analyze()` method calls each diagnostic module independently. Each module:

1. Queries relevant data sources (IngestionJob, SyncRun, DQResult, dbt artifacts)
2. Compares current state against baselines
3. Returns a result dataclass with `detected: bool`, `confidence_score: float`, and `evidence: dict`

All diagnostic modules are wrapped in `_safe_diagnose()` so a failure in one module does not block others.

### Phase 2: Causal Ordering

Hypotheses are sorted by confidence (descending), with ties broken by causal priority:

```
ingestion_failure (1) > schema_drift (2) > transformation_regression (3) > upstream_data_shift (4)
```

**Dampening rule:** If ingestion failure has confidence > 0.7, transformation regression confidence is multiplied by 0.5x. This prevents downstream effects from masking the root cause.

### Phase 3: Confidence Normalization

If the sum of all confidence scores exceeds 1.0, they are proportionally scaled so the total equals 1.0. This ensures confidence values are interpretable as relative likelihoods.

### Phase 4: Truncation & Persistence

- Top N hypotheses are returned (default 3)
- A `RootCauseSignal` row is persisted with the full hypotheses array as JSONB
- An audit event (`data.quality.root_cause_generated`) is emitted

---

## How Confidence Is Calculated

Each diagnostic module assigns confidence based on signal strength:

### Ingestion Failure

| Signal | Confidence Range |
|--------|-----------------|
| Sync failure (FAILED/DEAD_LETTER) | 0.85 - 0.95 |
| Partial sync (rows < 50% baseline) | 0.60 - 0.80 |
| Long-running sync (> 2x median) | 0.50 - 0.70 |
| Missing sync (no sync in expected window) | 0.70 - 0.85 |
| Auth error or rate limit code | +0.05 boost (cap 0.95) |

### Schema Drift

| Signal | Confidence |
|--------|-----------|
| Column removed | 0.90 |
| Column type changed | 0.75 |
| Column added | 0.40 |
| Multiple columns changed | +0.01 per extra (max +0.05) |
| Correlated dbt failure | +0.05 boost |

### Transformation Regression

| Signal | Confidence |
|--------|-----------|
| dbt model error/fail | 0.85 - 0.90 |
| Pass-to-fail transition | 0.85 |
| Execution time > 3x baseline | 0.50 |
| Source freshness degradation | 0.40 |

### Upstream Data Shift

| Signal | Confidence |
|--------|-----------|
| Distribution drift (JSD > 0.1) | 0.75 - 0.90 |
| Cardinality explosion (> 50%) | 0.70 - 0.85 |
| New dimension values (from zero) | 0.65 |
| Historical DQ drift (weak) | 0.55 - 0.65 |
| Ingestion unhealthy | x0.7 dampening |

---

## API Access

### List signals for a dataset

```
GET /api/admin/diagnostics/{dataset}?active_only=true&limit=10
```

### Get a specific signal

```
GET /api/admin/diagnostics/{dataset}/{signal_id}
```

### Run on-demand analysis

```
POST /api/admin/diagnostics/{dataset}/analyze?anomaly_type=volume_anomaly
```

All endpoints require admin role. Tenant scoping is from JWT.

---

## Operator UI

The Root Cause Panel (`/admin/diagnostics`) provides:

1. **Dataset selector** -- choose which dataset to inspect
2. **Event timeline** -- chronological list of signals with status badges
3. **Ranked hypotheses** -- confidence bars, cause type labels, evidence details
4. **Investigation steps** -- ordered actions derived from the top causes
5. **Evidence links** -- links to sync runs, dbt runs, DQ results, and logs
6. **Run Analysis button** -- trigger on-demand root cause analysis

---

## Audit Events

| Event | When |
|-------|------|
| `data.quality.root_cause_generated` | A new root cause signal is created |
| `data.quality.root_cause_updated` | An existing signal is resolved or re-analyzed |

Both events include: `tenant_id`, `dataset`, `signal_id`, `hypothesis_count`, `highest_confidence`.

---

## Data Model

### `root_cause_signals` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(255) PK | UUID |
| `tenant_id` | VARCHAR(255) | From JWT org_id |
| `dataset` | VARCHAR(255) | e.g. "shopify_orders" |
| `anomaly_type` | VARCHAR(100) | DQ check type that triggered analysis |
| `detected_at` | TIMESTAMPTZ | When the anomaly was detected |
| `hypotheses` | JSONB | Array of `{cause_type, confidence_score, evidence, first_seen_at, suggested_next_step}` |
| `top_cause_type` | VARCHAR(50) | Denormalized highest-confidence cause |
| `top_confidence` | DECIMAL(4,3) | Denormalized highest confidence score |
| `hypothesis_count` | INTEGER | Number of hypotheses |
| `is_active` | BOOLEAN | Whether signal is still active |
| `connector_id` | VARCHAR(255) | Optional connector scope |
| `correlation_id` | VARCHAR(255) | Links to related DQ events |

Indexes: `(tenant_id, dataset)`, `(detected_at)`, `(correlation_id)`, `(tenant_id, is_active)`.

---

## Architecture Diagram

```
DQ Anomaly Detected (Story 4.1)
        |
        v
  RootCauseRanker.analyze()
        |
   +----|----+----+----+
   |    |    |    |    |
   v    v    v    v    v
 Ingest Schema  dbt  Upstream  (future)
 Diag   Drift  Regr  Shift
   |    |    |    |
   +----+----+----+
        |
   Causal Ordering + Dampening
        |
   Confidence Normalization
        |
   Top N Truncation
        |
   Persist RootCauseSignal
        |
   Emit Audit Event
```
