# Metric Versioning and Governance

## Overview

This document describes the metric versioning framework for the analytics platform.
The framework ensures that metric calculations are explicit, auditable, and never
silently change.

## Why Metric Versioning?

Most analytics platforms fail because:

- Metrics silently change
- Dashboards update without warning
- Merchants lose trust when numbers "suddenly look different"
- Teams cannot explain what changed, when, and why

This framework ensures:

- Metrics can evolve safely
- Old definitions remain auditable
- Merchants are never surprised
- Rollbacks are possible without downtime

## Core Principles

1. **No Silent Metric Changes** - Every change creates a new version
2. **Explicit Version References** - Dashboards must reference specific versions
3. **Deprecated != Deleted** - Old versions remain queryable until sunset
4. **Human Approval Required** - Breaking changes require explicit approval
5. **Rollback is Always Possible** - Previous versions can be restored

## Lifecycle States

Each metric version progresses through these states:

```
draft -> active -> deprecated -> sunset -> retired
```

| State | Queryable | Dashboard Visible | Description |
|-------|-----------|-------------------|-------------|
| `draft` | No | No | Under development, not available in production |
| `active` | Yes | Yes | Current production version, default for new dashboards |
| `deprecated` | Yes | Yes (with warning) | Scheduled for removal, migration required |
| `sunset` | Yes | No | Past deprecation date, blocked in new dashboards |
| `retired` | No | No | No longer available, queries blocked |

## Metric Registry

All metrics are defined in `analytics/metrics/metric_registry.yaml`.

### Structure

```yaml
metrics:
  roas:
    display_name: "Return on Ad Spend"
    description: "Revenue generated per dollar of ad spend"
    current_version: "v1"

    versions:
      v1:
        status: active
        dbt_model: "marts/metrics/roas_v1"
        definition: "SUM(revenue) / SUM(spend)"
        approval:
          status: "approved"
          approved_by: "data-governance-board"
          approval_ticket: "ANALYTICS-001"
```

### Required Fields

- `display_name` - Human-readable metric name
- `description` - What the metric measures
- `current_version` - Default version for new dashboards
- `versions.<version>.status` - Lifecycle state
- `versions.<version>.dbt_model` - Associated dbt model
- `versions.<version>.definition` - Formula definition
- `versions.<version>.approval` - Governance approval record

## Creating a New Metric Version

### Step 1: Create Draft Version

1. Add the new version to `metric_registry.yaml` with `status: draft`
2. Create the dbt model (e.g., `roas_v2.sql`)
3. Add schema documentation and tests
4. Run `dbt test` to validate

### Step 2: Request Approval

Required for all new versions:

```yaml
approval:
  status: "pending"
  requested_by: "your-name"
  requested_at: "2026-02-04T00:00:00Z"
  approval_ticket: "ANALYTICS-XXX"
  breaking_change: true  # If formula changes significantly
```

### Step 3: Governance Review

The data governance board reviews:

- Formula correctness
- Edge case handling
- Breaking change impact
- Migration plan for affected dashboards

### Step 4: Activation

Once approved:

1. Update status to `active`
2. Update `current_version` if this is the new default
3. Emit `metric.version_status_changed` audit event

## Breaking Changes

A breaking change is any modification that:

- Changes the calculation formula
- Removes data that was previously available
- Changes the interpretation of the metric

### Breaking Change Process

1. **Identify Impact**
   - Count affected dashboards
   - Identify affected tenants
   - Estimate migration effort

2. **Create Migration Guide**
   - Document the change
   - Provide comparison queries
   - Set migration timeline

3. **Notification**
   - Notify all affected tenants
   - Post dashboard banners
   - Send email notifications

4. **Grace Period**
   - Minimum 30 days for deprecation
   - 90 days for breaking changes
   - Side-by-side comparison available

## Dashboard Compatibility

### Version Pinning

Dashboards must explicitly reference metric versions:

```sql
SELECT *
FROM roas_v1  -- Explicitly pinned to v1
WHERE tenant_id = ?
  AND metric_version = 'v1';
```

### Rules

- New dashboards use `current_version` by default
- Existing dashboards do NOT auto-upgrade
- Deprecated versions emit warnings but continue to work
- Sunset versions are blocked for new dashboards

### Migration Process

1. Dashboard owner is notified of deprecation
2. Side-by-side comparison is available
3. Dashboard owner updates version reference
4. Old version is sunset after grace period

## Audit Events

All metric lifecycle changes are logged:

| Event | Severity | Description |
|-------|----------|-------------|
| `metric.version_created` | Medium | New version created |
| `metric.version_status_changed` | High | Lifecycle state change |
| `metric.version_approval_requested` | Medium | Approval requested |
| `metric.version_approval_granted` | High | Approval granted |
| `metric.version_approval_rejected` | High | Approval rejected |
| `metric.version_sunset_scheduled` | High | Sunset date set |
| `metric.dashboard_version_pinned` | Medium | Dashboard pinned to version |
| `metric.deprecated_query_logged` | Low | Deprecated metric queried |
| `metric.rollback_executed` | Critical | Version rollback |

## Rollback Procedure

If a new version causes issues:

1. **Identify the Problem**
   - Check error logs
   - Compare v1 vs v2 outputs
   - Identify affected dashboards

2. **Execute Rollback**
   - Update `current_version` to previous version
   - Emit `metric.rollback_executed` audit event
   - Notify affected users

3. **Post-Rollback**
   - Deprecate the problematic version
   - Document the issue
   - Plan fix for next version

## Current Metrics

### ROAS v1 (active)

- **Definition:** `SUM(revenue) / SUM(spend)`
- **Model:** `analytics/models/metrics/fct_roas.sql`
- **Approval:** ANALYTICS-001
- **Columns:**
  - `metric_name = 'roas'`
  - `metric_version = 'v1'`
- **Edge Cases:**
  - Zero spend: Returns 0
  - Multi-currency: Separate calculations

### CAC v1 (active)

- **Definition:** `SUM(spend) / COUNT(new_customers)`
- **Model:** `analytics/models/metrics/fct_cac.sql`
- **Approval:** ANALYTICS-002
- **Columns:**
  - `metric_name = 'cac'`
  - `metric_version = 'v1'`
- **Edge Cases:**
  - Zero customers: Returns 0
  - Multi-currency: Separate calculations

## FAQ

### Q: Why can't metrics auto-upgrade?

Auto-upgrade would silently change dashboard values, violating the trust
principle. Merchants need to understand and approve any changes to their
reported metrics.

### Q: How long should deprecation last?

- Standard changes: 30 days minimum
- Breaking changes: 90 days minimum
- Critical security fixes: Can be expedited with approval

### Q: What if I need to fix a bug in an active metric?

Bug fixes that don't change the intended formula can be applied to the
existing version with audit logging. Formula changes require a new version.

### Q: How do I compare v1 vs v2 output?

Both versions can run simultaneously. Use:

```sql
SELECT
  v1.period_start,
  v1.roas as roas_v1,
  v2.roas as roas_v2,
  v2.roas - v1.roas as difference
FROM roas_v1 v1
JOIN roas_v2 v2 ON v1.tenant_id = v2.tenant_id
  AND v1.period_start = v2.period_start
  AND v1.currency = v2.currency;
```

## Human-Required Decisions

The following cannot be automated:

- Determine whether a change is breaking
- Approve default version changes
- Approve merchant communication language
- Decide sunset timelines
- Approve forced migrations (if ever)

## Related Documentation

- [Metric Registry](../analytics/metrics/metric_registry.yaml)
- [dbt Models](../analytics/models/marts/metrics/)
- [Audit Events](../backend/src/platform/audit_events.py)
- [MetricVersionResolver](../backend/src/governance/metric_versioning.py)
