# Incident Runbook: Root Cause Diagnostics

On-call guide for responding to data quality anomalies using automated root cause signals.

See [ROOT_CAUSE_DIAGNOSTICS.md](./ROOT_CAUSE_DIAGNOSTICS.md) for full system architecture.

---

## Quick Reference

| Signal Type | Confidence | First Action | Escalation |
|-------------|-----------|--------------|------------|
| Ingestion failure (> 0.8) | High | Check Airbyte connection | Infra team |
| Schema drift (> 0.8) | High | Compare column snapshots | Data eng |
| dbt model failure (> 0.8) | High | Check dbt run logs | Analytics eng |
| Upstream data shift (> 0.7) | Medium | Review source distribution changes | Data eng + source owner |
| No signal detected (0.0) | -- | Manual investigation | Data eng lead |

---

## Step 0: Access the Diagnostics Panel

1. Navigate to `/admin/diagnostics` in the operator UI
2. Select the affected dataset from the dropdown
3. Review the event timeline for the most recent signal
4. Check the ranked hypotheses list

Or query the API directly:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://api.example.com/api/admin/diagnostics/shopify_orders?active_only=true"
```

---

## Step 1: Ingestion Failure (Top Cause)

**Symptoms:** Sync failure, partial sync, or missing sync detected.

**What operators should do first:**

1. Check the evidence `signal` field:
   - `sync_failure` -- Airbyte sync explicitly failed
   - `partial_sync` -- Sync ran but row count dropped significantly
   - `long_running_sync` -- Sync still running, exceeding 2x median duration
   - `missing_sync` -- No sync in expected window
2. Check `error_code` in evidence:
   - `auth_error` -- API credentials expired or revoked
   - `rate_limit` -- Source API rate limit hit
3. Open the Airbyte UI and check the connection status
4. Query recent ingestion jobs:

```sql
SELECT id, status, error_message, error_code, started_at
FROM ingestion_jobs
WHERE tenant_id = '<tenant_id>'
  AND connector_id = '<connector_id>'
ORDER BY started_at DESC
LIMIT 5;
```

**When to escalate:**
- Auth errors persisting > 1 hour -- escalate to infra team to check credential rotation
- Rate limit errors across multiple tenants -- escalate to platform team
- Partial syncs with no error message -- escalate to data engineering

---

## Step 2: Schema Drift (Top Cause)

**Symptoms:** Column removed, type changed, or unexpected columns added.

**What operators should do first:**

1. Check the evidence `column_changes` array for specific changes
2. Compare `current_columns` vs `baseline_columns` in the evidence
3. Check if dbt models are failing (look for correlated `dbt_model_failure` signal)
4. Query recent DQ results for distribution drift:

```sql
SELECT check_id, status, severity, context_metadata
FROM dq_results
WHERE tenant_id = '<tenant_id>'
  AND status = 'failed'
ORDER BY executed_at DESC
LIMIT 10;
```

**When to escalate:**
- Column removed that is used in critical dbt models -- escalate to analytics eng immediately
- Type changes causing dbt compilation errors -- escalate to analytics eng
- Multiple columns changed simultaneously -- likely a source API version change, escalate to data eng lead

---

## Step 3: Transformation Regression (Top Cause)

**Symptoms:** dbt model failures, pass-to-fail transitions, execution time spikes.

**What operators should do first:**

1. Check the evidence for `failing_models` or `transitions` arrays
2. Review the dbt run logs for the specific model:

```bash
# Check recent dbt run results
dbt run --select model_name --target prod
```

3. Look for `execution_time_regression` signal -- may indicate data volume increase, not a code bug
4. Check `dbt_generated_at` in evidence to correlate with recent deployments

**When to escalate:**
- Model failures after a recent dbt deployment -- escalate to the engineer who deployed
- Execution time > 10x baseline -- escalate to data eng for query optimization
- Pass-to-fail transitions with no recent code changes -- investigate upstream schema changes first

---

## Step 4: Upstream Data Shift (Top Cause)

**Symptoms:** Distribution drift, cardinality explosion, new dimension values.

**What operators should do first:**

1. Check the evidence `signal` field:
   - `distribution_drift` -- Check `top_movers` for which categories changed
   - `cardinality_explosion` -- Check `dimension` and `cardinality_change_pct`
   - `new_values_appearing` -- New IDs or categories from zero baseline
2. Verify ingestion is healthy (`ingestion_healthy: true` in evidence)
3. If `ingestion_healthy: false`, investigate ingestion first (the shift may be a symptom)
4. Review the JSD score -- closer to 1.0 means more dramatic shift

**When to escalate:**
- JSD > 0.5 with healthy ingestion -- major upstream change, notify source team
- Cardinality > 200% increase -- possible data explosion (duplicate IDs?), escalate to data eng
- New values from zero baseline across multiple dimensions -- likely a new upstream feature or integration

---

## Step 5: No Signals Detected

**Symptoms:** The analysis returned zero hypotheses.

**What operators should do first:**

1. Check if the anomaly is still active (it may have self-resolved)
2. Run on-demand analysis:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  "https://api.example.com/api/admin/diagnostics/shopify_orders/analyze?anomaly_type=volume_anomaly"
```

3. Review recent sync runs, dbt runs, and DQ results manually
4. Check if the anomaly is in a dataset/connector not yet covered by diagnostics

**When to escalate:**
- Persistent anomaly with no signals after manual review -- escalate to data eng lead
- Anomaly affecting merchant-facing dashboards -- escalate immediately regardless of diagnostics

---

## General Escalation Matrix

| Confidence Level | Response | Escalation |
|-----------------|----------|------------|
| > 0.85 | Act on the top hypothesis immediately | Only if action fails |
| 0.60 - 0.85 | Investigate top 2 hypotheses | If not resolved in 30 min |
| 0.40 - 0.60 | Investigate all hypotheses + manual review | If not resolved in 1 hour |
| < 0.40 or none | Full manual investigation required | Escalate to data eng lead |

---

## Useful Queries

### Recent root cause signals for a tenant

```sql
SELECT id, dataset, anomaly_type, top_cause_type, top_confidence,
       hypothesis_count, is_active, detected_at
FROM root_cause_signals
WHERE tenant_id = '<tenant_id>'
ORDER BY detected_at DESC
LIMIT 20;
```

### Hypothesis details for a signal

```sql
SELECT id, hypotheses
FROM root_cause_signals
WHERE id = '<signal_id>';
```

### Correlation chain (link DQ results to root cause)

```sql
SELECT rcs.id AS signal_id, rcs.top_cause_type, rcs.top_confidence,
       dqr.check_id, dqr.status, dqr.severity
FROM root_cause_signals rcs
JOIN dq_results dqr ON dqr.correlation_id = rcs.correlation_id
WHERE rcs.tenant_id = '<tenant_id>'
ORDER BY rcs.detected_at DESC;
```
