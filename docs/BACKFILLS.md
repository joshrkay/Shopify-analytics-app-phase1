# Backfills - Operator Guide

Story 3.4 - Historical Data Backfill Operations

## When to Run a Backfill

Run a backfill when historical data needs reprocessing. Common scenarios:

- **Schema migration** - A dbt model changed and historical rows need the new logic applied.
- **Data gap** - An Airbyte sync failed for several days and raw data was re-ingested.
- **Bug fix** - An attribution or metric calculation was incorrect for a past period.
- **New source connected** - A merchant connected a new ad platform and imported historical data.
- **Metric version rollout** - A new metric version (e.g. ROAS v2) needs to be computed over historical dates.

## When NOT to Run a Backfill

- **During peak merchant hours.** Backfills override data availability to STALE, which disables AI insights and shows warnings on dashboards. Schedule during off-peak windows.
- **When the same tenant+source already has an active backfill.** The system rejects overlapping date ranges. Wait for the existing backfill to finish or cancel it first.
- **For trivial date ranges.** A 1-2 day gap is often faster to fix via a manual dbt run than a full backfill request.
- **When the underlying data source is still broken.** If Airbyte syncs are failing, a backfill will also fail. Fix the source connection first.
- **On free/growth tenants for ranges > 90 days.** The system enforces tier limits (see Scoping below). Enterprise tenants can go up to 365 days.

## How to Scope Safely

### Billing Tier Limits

| Tier | Max date range |
|---|---|
| Free | 90 days |
| Growth | 90 days |
| Enterprise | 365 days |

### Chunking

All backfills are split into **7-day chunks** automatically. A 28-day backfill creates 4 chunks that execute sequentially with one active job per tenant at a time. This prevents resource exhaustion.

### Overlap Protection

The system rejects requests that overlap with any `pending`, `approved`, or `running` backfill for the same `tenant_id` + `source_system`. If you need to adjust scope, cancel the existing request first.

### Scoping Recommendations

- **Start narrow.** If unsure of impact, backfill a 7-day window first (1 chunk) and check results before expanding.
- **Scope to one source system.** A Shopify backfill does not touch Facebook models. Keep them separate.
- **Check the cost estimate.** The planner estimates row counts and processing time. A Shopify backfill over 90 days (~45,000 rows) is very different from a GA4 backfill over 90 days (~90,000 rows). See [BACKFILL_PLANNING.md](./BACKFILL_PLANNING.md) for per-source estimates.

## Creating a Backfill

### Endpoint

```
POST /api/v1/admin/backfills
Authorization: Bearer <clerk_jwt>
```

Requires **super admin** status (verified from database, not JWT claims).

### Request

```json
{
  "tenant_id": "tenant_abc123",
  "source_system": "shopify",
  "start_date": "2024-01-01",
  "end_date": "2024-03-31",
  "reason": "Schema migration: orders model v2 backfill"
}
```

Supported source systems: `shopify`, `facebook`, `google`, `tiktok`, `snapchat`, `klaviyo`, `recharge`, `pinterest`, `amazon`, `ga4`.

### Response

**201 Created** - New backfill request created with status `pending`.

**200 OK** - Idempotent match. Same tenant/source/dates already requested. Returns the existing request.

**400** - Tenant not active or date range exceeds tier limit.

**409 Conflict** - Overlapping active backfill exists for this tenant+source.

### What Happens Next

1. Request is created with status **pending**.
2. Once approved (status set to **approved**), the background worker picks it up.
3. Worker creates 7-day chunk jobs and transitions to **running**.
4. Chunks execute sequentially, one per tenant at a time.
5. On completion, status moves to **completed** (all chunks succeeded) or **failed** (one or more chunks failed permanently after retries).

## Expected Impact on Merchants

When a backfill is running for a tenant, the system protects downstream analytics:

### Data Availability

Data availability for the affected source is overridden to **STALE**. This triggers the existing middleware stack automatically:

| System | Behavior During Backfill |
|---|---|
| **API responses** | Requests succeed but include a staleness warning: *"Some of your data sources are being updated. Results may not reflect the latest changes."* |
| **AI insights** | **Disabled.** AI features are blocked for the tenant while the backfill is active. Message: *"AI insights are temporarily paused while your data catches up."* |
| **Dashboards** | **Allowed with warning** (default). Queries execute but display: *"Some data may not reflect the very latest changes. An update is in progress."* |
| **Dashboard lock mode** | Set `BACKFILL_DASHBOARD_MODE=lock` to block dashboard queries entirely during backfills. Default is `warn`. |

### When It Clears

Once the backfill reaches a terminal state (completed, failed, or cancelled):

1. **Freshness recalculated** for affected data sources.
2. **Entitlement cache cleared** so access decisions refresh immediately.
3. Data availability returns to normal (FRESH if syncs are current).
4. AI insights re-enable automatically.

## How to Monitor Progress

### List All Backfills

```
GET /api/v1/admin/backfills
GET /api/v1/admin/backfills?tenant_id=tenant_abc123
GET /api/v1/admin/backfills?status=running
```

### Get Detailed Status

```
GET /api/v1/admin/backfills/{request_id}/status
```

### Response Fields

| Field | Description |
|---|---|
| `status` | One of: `pending`, `running`, `paused`, `failed`, `completed` |
| `percent_complete` | 0-100, based on completed chunks / total chunks |
| `total_chunks` | Number of 7-day slices |
| `completed_chunks` | Chunks that finished successfully |
| `failed_chunks` | Chunks that failed permanently (exhausted retries) |
| `current_chunk` | The currently executing chunk (index, date range, attempt number) |
| `failure_reasons` | List of error messages from failed chunks |
| `estimated_seconds_remaining` | Based on average chunk duration so far. `null` if no chunks completed yet. |

### Status Mapping

The API exposes 5 statuses mapped from internal states:

| Exposed Status | Internal States |
|---|---|
| `pending` | PENDING, APPROVED |
| `running` | RUNNING (with active jobs) |
| `paused` | RUNNING but all non-terminal jobs are PAUSED |
| `failed` | FAILED, REJECTED |
| `completed` | COMPLETED, CANCELLED |

### Audit Trail

Every lifecycle transition emits an audit event. Query the audit log for:

| Event | When |
|---|---|
| `backfill.requested` | Admin creates the request |
| `backfill.started` | Worker begins execution, chunk jobs created |
| `backfill.paused` | Operator pauses the backfill |
| `backfill.failed` | Backfill reaches terminal failure |
| `backfill.completed` | All chunks succeeded |

All events include: `backfill_id`, `tenant_id`, `source_system`, `date_range`, `requested_by`, and event-specific timestamps.

## How to Stop and Resume

### Pause

Pausing marks all `queued` chunk jobs as `paused`. Any currently running chunk will finish, but no new chunks will start.

The backfill status changes to `paused` once no chunks are actively running.

There is no dedicated pause endpoint yet. Pause is invoked through the executor's `pause_request(request_id)` method. If you need to pause urgently, use the application's admin tooling or invoke the method directly.

### Resume

Resuming marks all `paused` chunk jobs back to `queued` and restores the parent request to `running`. The worker will pick them up in the next cycle.

Invoked through `BackfillExecutor.resume_request(request_id)`.

### Cancel

Cancelling marks all non-terminal jobs (`queued` + `paused`) as `cancelled`. Any currently running chunk will finish. Once all jobs are terminal, the parent request transitions to `cancelled`.

Invoked through `BackfillExecutor.cancel_request(request_id)`.

## Retry Behavior

Failed chunks are retried automatically:

| Parameter | Value |
|---|---|
| Max retries per chunk | 3 |
| Base delay | 60 seconds |
| Backoff | Exponential (60s, 120s, 240s, ...) |
| Max delay | 1 hour |
| Jitter | +/- 25% of computed delay |

A chunk that fails 3 times is marked as permanently failed. If any chunk fails permanently, the entire request transitions to `failed`.

### Stale Job Recovery

If a chunk has been `running` for more than **30 minutes** without completing (e.g., worker crash), the next worker cycle resets it to `queued` for re-execution.

## Worker Configuration

The backfill worker is a Render managed background process.

| Environment Variable | Default | Description |
|---|---|---|
| `BACKFILL_POLL_INTERVAL_SECONDS` | 30 | Seconds between worker cycles |
| `BACKFILL_MAX_JOBS_PER_CYCLE` | 2 | Max chunk jobs executed per cycle |
| `BACKFILL_DASHBOARD_MODE` | warn | `warn` or `lock` for dashboard behavior |
| `DATABASE_URL` | (required) | Database connection string |

### Rate Limiting

The worker enforces **one active chunk job per tenant** at a time. If tenant A has a running chunk, no additional chunks for tenant A will start until it finishes. This prevents a single large backfill from monopolizing database resources.

### Graceful Shutdown

On SIGTERM/SIGINT, the worker finishes the current chunk before exiting. No work is lost.

## Troubleshooting

### Backfill stuck at "pending"

The request needs to be approved (status set to `approved`) before the worker will process it. Check whether an approval step was missed.

### Backfill stuck at "running" with 0% progress

The worker may not be running. Check the Render dashboard for the backfill worker process. Also verify `DATABASE_URL` is set correctly in the worker's environment.

### Chunks failing with connection errors

Check the Airbyte connection health for the tenant's source. If the underlying data source is down, chunks will retry up to 3 times and then fail permanently.

### Percent complete not advancing

Only `success` chunks count toward percent complete. If chunks are retrying (status cycling between `failed` and `queued`), progress will stall until they succeed or exhaust retries.

### AI insights not re-enabling after completion

Verify the backfill reached a terminal state (`completed`, `failed`, or `cancelled`). The freshness recalculation and cache clear only trigger on terminal transitions. If the request is still `running`, something may be stuck - check for stale jobs.
