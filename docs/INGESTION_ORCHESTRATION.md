# Ingestion Orchestration

This document describes the ingestion orchestration layer for Airbyte Cloud data pipelines.

## Architecture Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Cron Trigger  │────▶│  Job Dispatcher │────▶│  Ingestion Job  │
│  (Render Cron)  │     │                 │     │   (Database)    │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                        ┌─────────────────┐              │
                        │   Job Runner    │◀─────────────┘
                        │   (Worker)      │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │ Airbyte Cloud   │
                        │     API         │
                        └─────────────────┘
```

## Components

### 1. Job Model (`ingestion/jobs/models.py`)

The `IngestionJob` model tracks sync job execution with:

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | UUID | Primary key |
| `tenant_id` | String | Tenant isolation (from JWT) |
| `connector_id` | String | Internal connection ID |
| `external_account_id` | String | External platform account ID |
| `status` | Enum | queued, running, failed, dead_letter, success |
| `retry_count` | Integer | Current retry attempt (max 5) |
| `run_id` | String | Airbyte job run ID |
| `correlation_id` | String | Distributed tracing ID |
| `error_message` | Text | Last error description |
| `error_code` | String | Error classification |
| `next_retry_at` | Timestamp | Scheduled retry time |

### 2. Job Dispatcher (`ingestion/jobs/dispatcher.py`)

Handles job creation and queue management:

```python
from src.ingestion.jobs.dispatcher import JobDispatcher

dispatcher = JobDispatcher(db_session, tenant_id)

# Create new job
job = dispatcher.dispatch(
    connector_id="conn-123",
    external_account_id="shop-456",
    correlation_id="req-789",
)

# Get queued jobs
queued = dispatcher.get_queued_jobs()

# Requeue from DLQ (support-only)
requeued = dispatcher.requeue_from_dlq(job_id="...")
```

### 3. Job Runner (`ingestion/jobs/runner.py`)

Executes jobs by calling Airbyte Cloud API:

```python
from src.ingestion.jobs.runner import run_worker_cycle

# Run one cycle of job processing
result = await run_worker_cycle(db_session)
# Returns: {"queued_processed": N, "retry_processed": M}
```

### 4. Retry Policy (`ingestion/jobs/retry.py`)

Error-aware retry logic:

| Error Type | HTTP Codes | Behavior |
|------------|------------|----------|
| Auth Error | 401, 403 | Fail immediately, move to DLQ |
| Rate Limit | 429 | Retry with Retry-After header |
| Server Error | 5xx | Retry with exponential backoff |
| Timeout | N/A | Retry with backoff |
| Connection | N/A | Retry with backoff |

**Backoff Formula:** `base_delay * (2^attempt) + random_jitter`

- Base delay: 60 seconds
- Max delay: 3600 seconds (1 hour)
- Jitter: ±25%
- Max retries: 5

### 5. Airbyte Client (`ingestion/airbyte/client.py`)

Extended Airbyte client with:

- Per-connector rate limiting
- Per-external-account rate limiting
- Error classification for retry decisions
- Sync result extraction

## Job Lifecycle

```
┌─────────┐     ┌─────────┐     ┌─────────┐
│ QUEUED  │────▶│ RUNNING │────▶│ SUCCESS │
└────┬────┘     └────┬────┘     └─────────┘
     │               │
     │               ▼
     │         ┌─────────┐     ┌─────────────┐
     │         │ FAILED  │────▶│ DEAD_LETTER │
     │         └────┬────┘     └─────────────┘
     │              │
     └──────────────┘
         (retry)
```

## Job Isolation

**Critical:** Only ONE active job per tenant + connector combination.

This is enforced at two levels:

1. **Database:** Partial unique index on `(tenant_id, connector_id)` where `status IN ('queued', 'running')`
2. **Application:** Pre-dispatch check in `JobDispatcher.dispatch()`

```sql
-- Partial unique index
CREATE UNIQUE INDEX ix_ingestion_jobs_active_unique
    ON ingestion_jobs(tenant_id, connector_id)
    WHERE status IN ('queued', 'running');
```

## Sync Cadence by Plan

| Plan | Configurable | Minimum Interval |
|------|--------------|------------------|
| Free | No (fixed) | 24 hours |
| Growth | Yes | 6 hours |
| Enterprise | Yes | 1 hour |

## Audit Events

The following events are logged for observability:

| Event | When | Key Fields |
|-------|------|------------|
| `job.queued` | Job created | job_id, tenant_id, connector_id |
| `job.started` | Job execution begins | job_id, run_id |
| `job.retry` | Job scheduled for retry | job_id, retry_count, delay_seconds |
| `job.failed` | Job failed (retryable) | job_id, error_message, error_code |
| `job.dead_lettered` | Job moved to DLQ | job_id, retry_count, error_message |
| `job.completed` | Job succeeded | job_id, records_synced, duration_seconds |

## Dead Letter Queue

Jobs move to DLQ when:
- Authentication error (401, 403) - immediate
- Max retries (5) exceeded

**Requeue Process (Support-only):**

```python
dispatcher = JobDispatcher(db_session, tenant_id)
new_job = dispatcher.requeue_from_dlq(
    job_id="dlq-job-id",
    correlation_id="support-ticket-123",
)
```

## Rate Limiting

Rate limits are applied at two levels:

1. **Per-connector:** Minimum 60 seconds between sync triggers
2. **Per-external-account:** Prevents abuse of individual data sources

Rate limit state is tracked in-memory. For distributed deployments, consider Redis.

## Database Migration

Run the migration to create the jobs table:

```bash
psql $DATABASE_URL -f backend/migrations/ingestion_jobs.sql
```

## Worker Deployment (Render)

The worker runs as a Render managed worker with cron triggers:

```yaml
# render.yaml
services:
  - type: worker
    name: ingestion-worker
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: python -m src.ingestion.worker
    cron:
      schedule: "*/5 * * * *"  # Every 5 minutes
```

## Configuration

Environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `AIRBYTE_BASE_URL` | Airbyte Cloud API URL | `https://api.airbyte.com/v1` |
| `AIRBYTE_API_TOKEN` | API authentication token | Required |
| `AIRBYTE_WORKSPACE_ID` | Workspace identifier | Required |

## Testing

Run the test suite:

```bash
# Job isolation tests
pytest backend/src/tests/test_job_isolation.py -v

# Retry and DLQ tests
pytest backend/src/tests/test_retry_and_dlq.py -v
```

## Security Considerations

1. **Tenant Isolation:** `tenant_id` is ONLY extracted from JWT, never from client input
2. **API Token Security:** Never log or expose Airbyte API tokens
3. **DLQ Requeue:** Restricted to support staff via RBAC
4. **Rate Limiting:** Prevents abuse of external APIs

## Monitoring

Key metrics to track:

- Jobs queued per minute
- Job success rate by connector
- Average job duration
- DLQ size by tenant
- Retry rate by error type

## Troubleshooting

### Job stuck in RUNNING state

```sql
-- Find stuck jobs (running > 2 hours)
SELECT job_id, tenant_id, connector_id, started_at
FROM ingestion_jobs
WHERE status = 'running'
  AND started_at < NOW() - INTERVAL '2 hours';
```

### High DLQ count

```sql
-- DLQ jobs by error code
SELECT error_code, COUNT(*) as count
FROM ingestion_jobs
WHERE status = 'dead_letter'
GROUP BY error_code
ORDER BY count DESC;
```

### Rate limit issues

Check the Airbyte Cloud rate limit headers and adjust `min_interval_seconds` if needed.
