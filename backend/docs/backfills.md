# Backfills & Reprocessing

**Story 4.8** - Support for parameterized dbt backfills with tenant isolation and audit logging.

## Overview

The backfill system allows platform operators to reprocess historical data safely by:
- Parameterizing dbt models with date range filters
- Enforcing tenant isolation at the model level
- Auditing all backfill executions

## Architecture

### Components

1. **dbt Macro** (`analytics/macros/backfill.sql`)
   - Provides `backfill_date_filter()` macro for date range filtering
   - Used in incremental models to override default incremental logic

2. **Backend Service** (`backend/src/services/backfill_service.py`)
   - Executes dbt commands with date range variables
   - Enforces tenant isolation
   - Logs audit events

3. **API Route** (`backend/src/api/routes/backfills.py`)
   - REST endpoint for triggering backfills
   - Validates date ranges
   - Returns execution results

## Usage

### API Endpoint

**POST** `/api/backfills/trigger`

**Request Body:**
```json
{
  "model_selector": "fact_orders",
  "start_date": "2024-01-01",
  "end_date": "2024-01-31"
}
```

**Response:**
```json
{
  "backfill_id": "uuid",
  "tenant_id": "tenant-123",
  "model_selector": "fact_orders",
  "start_date": "2024-01-01",
  "end_date": "2024-01-31",
  "status": "success",
  "is_successful": true,
  "rows_affected": 1500,
  "duration_seconds": 45.2,
  "completed_at": "2024-02-01T10:30:00Z"
}
```

### Model Selectors

The `model_selector` parameter uses dbt's selection syntax:

- `fact_orders` - Single model
- `facts` - All models in facts directory
- `fact_orders+` - fact_orders and all downstream dependencies
- `fact_orders+2` - fact_orders and 2 levels of downstream dependencies

### Date Formats

Supported date formats:
- `YYYY-MM-DD` (e.g., `2024-01-01`)
- `YYYY-MM-DD HH:MI:SS` (e.g., `2024-01-01 00:00:00`)

Dates are interpreted as UTC timestamps.

### Constraints

- **Maximum date range**: 365 days
- **Tenant isolation**: All backfills are automatically scoped to the authenticated tenant
- **Idempotency**: Running the same backfill multiple times is safe (models use upsert logic)

## Model Implementation

To enable backfill support in a dbt model, use the `backfill_date_filter()` macro:

```sql
{{
    config(
        materialized='incremental',
        unique_key='id',
    )
}}

with staging_data as (
    select *
    from {{ ref('stg_source') }}
    where tenant_id is not null
    
    {% if var('backfill_start_date', none) and var('backfill_end_date', none) %}
        -- Backfill mode: filter by date range
        and {{ backfill_date_filter('airbyte_emitted_at', var('backfill_start_date'), var('backfill_end_date')) }}
        {% if var('backfill_tenant_id', none) %}
            -- Additional tenant filter (defense in depth)
            and tenant_id = '{{ var("backfill_tenant_id") }}'
        {% endif %}
    {% elif is_incremental() %}
        -- Incremental mode: only new/updated records
        and airbyte_emitted_at > (
            select coalesce(max(ingested_at), '1970-01-01'::timestamp with time zone)
            from {{ this }}
        )
    {% endif %}
)

select * from staging_data
```

### Key Points

1. **Tenant Isolation**: Always filter by `tenant_id is not null` (and optionally by `backfill_tenant_id` variable)
2. **Date Column**: Use the appropriate timestamp column (typically `airbyte_emitted_at` or `created_at`)
3. **Incremental Logic**: The backfill mode overrides the default incremental filter

## Security

### Tenant Isolation

- All backfills are scoped to the authenticated tenant (from JWT)
- Models must filter by `tenant_id` to prevent cross-tenant data access
- The service passes `backfill_tenant_id` as a dbt variable for additional validation

### Audit Logging

All backfill executions are logged to the audit system:

- `backfill.started` - When backfill execution begins
- `backfill.completed` - When backfill succeeds
- `backfill.failed` - When backfill fails

Audit events include:
- `backfill_id` - Unique identifier for the backfill
- `model_selector` - Which models were processed
- `start_date` / `end_date` - Date range
- `duration_seconds` - Execution time
- `rows_affected` - Number of rows processed (if available)
- `error` - Error message (if failed)

## Examples

### Backfill Single Model

```bash
curl -X POST https://api.example.com/api/backfills/trigger \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model_selector": "fact_orders",
    "start_date": "2024-01-01",
    "end_date": "2024-01-31"
  }'
```

### Backfill All Fact Tables

```bash
curl -X POST https://api.example.com/api/backfills/trigger \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model_selector": "facts",
    "start_date": "2024-01-01",
    "end_date": "2024-01-31"
  }'
```

### Backfill with Dependencies

```bash
curl -X POST https://api.example.com/api/backfills/trigger \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model_selector": "fact_orders+",
    "start_date": "2024-01-01",
    "end_date": "2024-01-31"
  }'
```

## Error Handling

### Invalid Date Range

**Status:** `400 Bad Request`

```json
{
  "detail": "Start date (2024-01-31) must be before end date (2024-01-01)"
}
```

### Date Range Too Large

**Status:** `400 Bad Request`

```json
{
  "detail": "Date range too large: 400 days. Maximum allowed: 365 days"
}
```

### dbt Execution Failure

**Status:** `500 Internal Server Error`

```json
{
  "detail": "Backfill execution failed: dbt execution failed: ..."
}
```

## Monitoring

### Audit Logs

Query audit logs to monitor backfill activity:

```sql
SELECT 
    action,
    resource_id as backfill_id,
    event_metadata->>'model_selector' as model_selector,
    event_metadata->>'start_date' as start_date,
    event_metadata->>'end_date' as end_date,
    event_metadata->>'duration_seconds' as duration_seconds,
    event_metadata->>'rows_affected' as rows_affected,
    timestamp
FROM audit_logs
WHERE action IN ('backfill.started', 'backfill.completed', 'backfill.failed')
    AND tenant_id = 'your-tenant-id'
ORDER BY timestamp DESC;
```

### Application Logs

Backfill service logs include:
- Execution start/end
- dbt command details
- Row counts
- Errors

Search for logs with:
- `backfill_id` - Specific backfill tracking
- `tenant_id` - Tenant-scoped queries
- `model_selector` - Model-specific queries

## Best Practices

1. **Test on Small Ranges First**: Start with a small date range (e.g., 1 day) before backfilling large periods
2. **Monitor Resource Usage**: Large backfills can be resource-intensive; monitor database and dbt execution
3. **Use Model Selectors Wisely**: Be specific with model selectors to avoid unnecessary reprocessing
4. **Check Audit Logs**: Review audit logs after backfills to verify successful execution
5. **Idempotency**: Backfills are safe to re-run; models use upsert logic

## Troubleshooting

### Backfill Hangs

- Check dbt process status
- Review database connection pool
- Verify date range is reasonable

### No Rows Processed

- Verify date range matches data availability
- Check tenant_id filtering in model
- Review staging data for the date range

### Cross-Tenant Data Concerns

- Verify models filter by `tenant_id`
- Check audit logs for tenant_id in metadata
- Review model SQL for tenant isolation

## Related Documentation

- [dbt Selection Syntax](https://docs.getdbt.com/reference/node-selection/syntax)
- [Incremental Models](https://docs.getdbt.com/docs/build/incremental-models)
- [Audit Logging](../src/platform/audit.py)
