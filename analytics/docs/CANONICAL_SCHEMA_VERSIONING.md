# Canonical Schema Versioning

## Overview

Every canonical model (facts, metrics, marts) has a semantic version tracked in
`canonical/schema_registry.yml`. This ensures downstream consumers -- dashboards,
APIs, and reports -- are never broken by silent schema changes.

**Registry location:** `analytics/canonical/schema_registry.yml`

## Semantic Versioning Rules

We follow [Semantic Versioning 2.0.0](https://semver.org) adapted for data
schemas:

| Bump    | When                                                      | Example                                  |
|---------|-----------------------------------------------------------|------------------------------------------|
| **MAJOR** | Column removed, renamed, or type changed (breaking)       | `revenue` renamed to `revenue_net`       |
| **MINOR** | New column added (backward-compatible)                    | Added `shipping_amount` to `fct_revenue` |
| **PATCH** | Documentation, description, or test-only change           | Updated column description text          |

### What counts as a breaking change

- Removing a column that dashboards or APIs reference
- Renaming a column (consumers will get "column not found" errors)
- Changing a column's data type (e.g., `text` to `integer`)
- Changing a metric formula that alters historical values
- Changing the grain of a table (e.g., from daily to hourly)

### What is NOT breaking

- Adding a new column (existing queries ignore unknown columns)
- Adding a new accepted value to an enum column
- Changing a column's description or adding tests
- Performance optimizations that don't change output

## Registry Structure

Each table entry in `schema_registry.yml` contains:

```yaml
fact_orders:
  layer: facts                  # facts | metrics | marts
  schema: analytics             # Target database schema
  materialization: incremental  # table | view | incremental
  grain: "one row per order per tenant"
  owner: "Analytics Tech Lead"
  current_version: "1.1.0"

  versions:
    - version: "1.0.0"
      released: "2025-06-01"
      status: active            # active | deprecated | sunset
      deprecated_date: null     # Set when status becomes deprecated
      sunset_date: null         # Set when status becomes sunset
      description: "Initial release..."
      columns_added: [...]
      columns_removed: [...]
      breaking: false
      migration_guide: null     # Required when breaking: true

  deprecated_columns:
    - column: platform
      reason: "Renamed to source_platform"
      sunset_date: "2026-06-01"
```

## Registered Tables

### Facts Layer

| Table                       | Current Version | Status  | Grain                           |
|-----------------------------|----------------:|---------|----------------------------------|
| `fact_orders`               |           1.1.0 | active  | One row per order per tenant     |
| `fact_ad_spend`             |           1.1.0 | active  | Per day + platform + campaign    |
| `fact_campaign_performance` |           1.0.0 | active  | Per day + campaign per tenant    |

### Metrics Layer

| Table          | Current Version | Status  | Grain                                      |
|----------------|----------------:|---------|--------------------------------------------|
| `fct_revenue`  |           2.0.0 | active  | Per order + revenue_type per tenant        |
| `fct_aov`      |           1.0.0 | active  | Per tenant + currency + period             |
| `fct_roas`     |           1.0.0 | active  | Varies by period_type and platform         |
| `fct_cac`      |           1.0.0 | active  | Varies by period_type and platform         |

### Marts Layer

| Table                    | Current Version | Status  | Notes                            |
|--------------------------|----------------:|---------|----------------------------------|
| `fct_marketing_metrics`  |           1.0.0 | active  | Canonical ROAS + CAC with drill  |
| `metric_roas_v1`         |           1.0.0 | active  | IMMUTABLE attributed ROAS        |
| `metric_roas_v2`         |           1.0.0 | active  | IMMUTABLE blended ROAS           |
| `metric_roas_current`    |           1.0.0 | active  | Governed alias -> metric_roas_v1 |

## How to Make a Schema Change

### Step 1: Determine the version bump

Ask yourself:
- Am I removing or renaming a column? -> **MAJOR** bump
- Am I adding a new column? -> **MINOR** bump
- Am I only changing docs or tests? -> **PATCH** bump

### Step 2: Update the model SQL

Make your changes in the model's `.sql` file (e.g.,
`models/facts/fact_orders.sql`).

### Step 3: Update the schema.yml contract

Add or update the column definition in the model's `schema.yml`.

### Step 4: Update the schema registry

Edit `analytics/canonical/schema_registry.yml`:

```bash
cd analytics
nano canonical/schema_registry.yml
```

1. Bump `current_version` on the table entry.
2. Add a new entry to the `versions` list:

```yaml
  - version: "1.2.0"
    released: "2026-02-15"
    status: active
    description: "Added discount_amount column for order discounts"
    columns_added:
      - discount_amount
    columns_removed: []
    breaking: false
    migration_guide: null
```

3. If this is a MAJOR bump, write a migration guide and link it:

```yaml
    breaking: true
    migration_guide: "docs/migrate_fact_orders_v1_to_v2.md"
```

### Step 5: Update the column allowlist (if staging)

If this change affects a staging model, also update the corresponding
`governance/approved_columns_*.yml` file (see `docs/SCHEMA_DRIFT_PROCESS.md`).

### Step 6: Run validation

```bash
cd analytics

# Compile to verify no syntax errors
dbt compile

# Run all tests
dbt test

# Run only the drift guard (if staging columns changed)
dbt test -s test_schema_drift_guard
```

### Step 7: Open a PR

```bash
git checkout -b feat/add-discount-amount-fact-orders
git add canonical/schema_registry.yml
git add models/facts/fact_orders.sql
git add models/facts/schema.yml
git commit -m "feat: add discount_amount to fact_orders (schema 1.2.0)"
git push -u origin feat/add-discount-amount-fact-orders
```

### Step 8: Get approval

| Change Type       | Required Approvers                          |
|-------------------|---------------------------------------------|
| PATCH             | Analytics Tech Lead                         |
| MINOR             | Analytics Tech Lead                         |
| MAJOR (breaking)  | Analytics Tech Lead + Product Manager       |
| Metric repoint    | Analytics Tech Lead + Product Manager       |

## Deprecation Process

When a table version is deprecated, consumers have a minimum of **90 days**
before it is removed (sunset).

### Timeline

```
Day 0:   Version deprecated (status: deprecated, deprecated_date set)
         - Dashboard banners activated
         - Email notification sent to affected merchants
Day 60:  30-day warning (queries on deprecated version show warnings)
Day 90:  Sunset (status: sunset, queries BLOCKED)
```

### How to deprecate a version

1. Set the old version's `status` to `deprecated` in the registry.
2. Set `deprecated_date` to today's date.
3. Set `sunset_date` to today + 90 days.
4. Write a migration guide at the path specified in `migration_guide`.
5. List all affected dashboards and merchants in the PR description.
6. Coordinate with Product to schedule merchant notifications.

### Example: fct_revenue v1 deprecation

```yaml
  - version: "1.0.0"
    released: "2025-06-01"
    status: deprecated
    deprecated_date: "2026-01-15"
    sunset_date: "2026-04-15"
    description: "Revenue excluding refunds (replaced by v2)"
    migration_guide: "docs/migrate_revenue_v1_to_v2.md"
```

The replacement v2 was released on 2026-01-15, giving merchants until
2026-04-15 to migrate.

## Writing a Migration Guide

Migration guides live in `analytics/docs/` and must include:

1. **What changed** - Concise description of the breaking change
2. **Why it changed** - Business or technical justification
3. **Before/after examples** - SQL showing old vs. new query patterns
4. **Action required** - Exact steps the consumer must take
5. **Timeline** - Deprecation date, sunset date, and key milestones

### Template

```markdown
# Migration: <table> v<old> to v<new>

## What Changed
<description>

## Why
<justification>

## Before (v<old>)
\`\`\`sql
SELECT ... FROM <old_model> WHERE ...
\`\`\`

## After (v<new>)
\`\`\`sql
SELECT ... FROM <new_model> WHERE ...
\`\`\`

## Action Required
1. Update your queries to use ...
2. Verify results match expectations
3. Remove references to deprecated columns

## Timeline
- Deprecated: YYYY-MM-DD
- Sunset: YYYY-MM-DD (queries will be blocked)
```

## Relationship to Other Governance Files

| File                                          | Purpose                                    |
|-----------------------------------------------|-------------------------------------------|
| `canonical/schema_registry.yml`               | Schema versions (this system)              |
| `config/governance/metrics_versions.yaml`     | Metric *formula* versions (calculation)    |
| `config/governance/consumers.yaml`            | Dashboard -> metric version bindings       |
| `config/governance/change_requests.yaml`      | Change request approval workflow           |
| `governance/approved_columns_*.yml`           | Column allowlists for staging drift guard  |

The schema registry tracks **structural changes** (columns, types, grain).
The metrics_versions.yaml tracks **semantic changes** (formula definitions).
Both must be updated when a metric model undergoes a breaking change.

## FAQ

**Q: Do I need to register staging models?**
No. Only models consumed by dashboards, APIs, or external systems belong
in the registry. Staging models are internal and governed by the column
allowlists instead.

**Q: What if I add a column that nobody uses yet?**
Still bump the MINOR version. The registry is an audit trail of every schema
change, regardless of immediate consumer impact.

**Q: Can I skip PATCH bumps?**
Yes, PATCH bumps are optional for documentation-only changes. They exist to
provide a complete audit trail when needed.

**Q: Who updates the registry?**
The engineer making the schema change. The PR reviewer verifies the registry
was updated correctly.

**Q: What happens if I forget to update the registry?**
The PR reviewer should catch it. If it reaches production, open a follow-up
PR to backfill the registry entry. The missing audit trail is a governance gap
that must be closed.
