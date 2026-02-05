# Ingestion & Normalization Operator Guide

This guide walks you through operating the MarkInsight data pipeline
end-to-end: how raw data arrives, how dbt transforms it, and what to do when
something breaks.

---

## Table of contents

1. [How raw schemas are organized](#1-how-raw-schemas-are-organized)
2. [How to run dbt locally](#2-how-to-run-dbt-locally)
3. [How rolling rebuild works](#3-how-rolling-rebuild-works)
4. [How schema drift approvals work](#4-how-schema-drift-approvals-work)
5. [How to troubleshoot failed models](#5-how-to-troubleshoot-failed-models)
6. [Quick-reference commands](#6-quick-reference-commands)

---

## 1. How raw schemas are organized

### 1.1 The big picture

Data flows through three layers before it reaches dashboards:

```
External APIs          Airbyte             PostgreSQL
==============    ================    =====================
Shopify       -->  Airbyte sync   -->  airbyte_raw schema
Meta Ads      -->  Airbyte sync   -->  airbyte_raw schema
Google Ads    -->  Airbyte sync   -->  airbyte_raw schema
TikTok Ads    -->  Airbyte sync   -->  airbyte_raw schema
Snapchat Ads  -->  Airbyte sync   -->  airbyte_raw schema
Klaviyo       -->  Airbyte sync   -->  airbyte_raw schema
SMS platforms -->  Airbyte sync   -->  airbyte_raw schema

                                     Then dbt picks up:
                                     airbyte_raw --> staging --> canonical --> semantic
```

You do not manage the Airbyte-to-raw step directly. Airbyte runs on a
schedule and writes new records into the `airbyte_raw` schema. Your job
starts at the dbt layer.

### 1.2 Raw tables

Every raw table follows the same three-column structure created by Airbyte:

| Column               | Type      | Description                                  |
|----------------------|-----------|----------------------------------------------|
| `_airbyte_ab_id`     | text      | Unique ID assigned by Airbyte to each record |
| `_airbyte_emitted_at`| timestamp | When Airbyte emitted the record              |
| `_airbyte_data`      | jsonb     | The actual payload from the source API        |

All the real data lives inside `_airbyte_data` as a JSON blob. The staging
models extract and type-cast individual fields out of it.

### 1.3 Source-to-table mapping

The file `models/raw_sources/sources.yml` maps each source to its physical
table. Here is every source in the project:

| dbt source name   | Table (logical) | Physical table name              | What it contains          |
|-------------------|-----------------|----------------------------------|---------------------------|
| `raw_shopify`     | `orders`        | `_airbyte_raw_shopify_orders`    | Shopify orders            |
| `raw_shopify`     | `customers`     | `_airbyte_raw_shopify_customers` | Shopify customers         |
| `raw_facebook_ads`| `ad_insights`   | `_airbyte_raw_meta_ads`          | Meta (FB/IG) ad metrics   |
| `raw_google_ads`  | `ad_stats`      | `_airbyte_raw_google_ads`        | Google Ads metrics        |
| `raw_tiktok_ads`  | `ad_reports`    | `_airbyte_raw_tiktok_ads`        | TikTok ad metrics         |
| `raw_snapchat_ads`| `ad_reports`    | `_airbyte_raw_snapchat_ads`      | Snapchat ad metrics       |
| `raw_email`       | `klaviyo_events`| `_airbyte_raw_klaviyo_events`    | Klaviyo email events      |
| `raw_email`       | `shopify_email_activities` | `_airbyte_raw_shopify_email_activities` | Shopify Email events |
| `raw_sms`         | `attentive_events`  | `_airbyte_raw_attentive_events`  | Attentive SMS events |
| `raw_sms`         | `postscript_events` | `_airbyte_raw_postscript_events` | Postscript SMS events|
| `raw_sms`         | `smsbump_events`    | `_airbyte_raw_smsbump_events`    | SMSBump SMS events   |
| `platform`        | `tenant_airbyte_connections` | `tenant_airbyte_connections` | Tenant-to-connection map |

### 1.4 Schema configuration

All raw tables default to the `airbyte_raw` schema. If your environment uses
separate schemas per source, override them in your dbt invocation:

```bash
dbt run --vars '{raw_shopify_schema: raw_shopify, raw_facebook_ads_schema: raw_facebook}'
```

The full list of schema variables and their defaults is in `dbt_project.yml`:

| Variable                   | Default       |
|----------------------------|---------------|
| `raw_shopify_schema`       | `airbyte_raw` |
| `raw_facebook_ads_schema`  | `airbyte_raw` |
| `raw_google_ads_schema`    | `airbyte_raw` |
| `raw_tiktok_ads_schema`    | `airbyte_raw` |
| `raw_snapchat_ads_schema`  | `airbyte_raw` |
| `raw_email_schema`         | `airbyte_raw` |
| `raw_sms_schema`           | `airbyte_raw` |
| `platform_schema`          | `platform`    |

### 1.5 Freshness monitoring

Every source (except `platform`) has freshness checks configured:

- **Warn** if no new records in **24 hours**
- **Error** if no new records in **48 hours**

Freshness is measured by `_airbyte_emitted_at`. To check freshness:

```bash
cd analytics
dbt source freshness
```

If a source shows `ERROR`, it means Airbyte has not delivered data for over
48 hours. Check the Airbyte UI for failed syncs or connection issues.

### 1.6 Tenant isolation

This is a multi-tenant system. Every staging and canonical model filters on
`tenant_id`. The mapping from Airbyte connections to tenants lives in the
`platform.tenant_airbyte_connections` table, exposed via the
`_tenant_airbyte_connections` dbt model. Rows without a valid `tenant_id` are
always dropped.

---

## 2. How to run dbt locally

### 2.1 Prerequisites

- Python 3.9+
- PostgreSQL running locally (or a remote connection)
- dbt-core 1.11.x with dbt-postgres adapter

### 2.2 First-time setup

```bash
# 1. Clone the repo and enter the analytics directory
git clone <repo-url>
cd Shopify-analytics-app/analytics

# 2. Install dbt and the postgres adapter
pip install dbt-core==1.11.2 dbt-postgres==1.10.0

# 3. Install dbt packages (dbt_utils)
dbt deps

# 4. Create your profiles.yml (this file is git-ignored)
mkdir -p ~/.dbt
cat > ~/.dbt/profiles.yml << 'EOF'
markinsight:
  target: dev
  outputs:
    dev:
      type: postgres
      host: localhost
      port: 5432
      user: postgres
      password: <your-password>
      dbname: shopify_analytics
      schema: public
      threads: 4
EOF
```

Replace `<your-password>` with your actual database password. The database
connection values can also be found in the `.env.example` file at the project
root.

### 2.3 Verify the connection

```bash
cd analytics
dbt debug
```

You should see `All checks passed!` at the end. If not, double-check your
`profiles.yml` credentials and make sure PostgreSQL is running.

### 2.4 Common run commands

All commands below should be run from the `analytics/` directory.

**Build everything (models + tests):**

```bash
dbt build
```

**Run only models (no tests):**

```bash
dbt run
```

**Run a single model and its upstream dependencies:**

```bash
dbt run --select +fact_orders_v1
```

The `+` prefix means "run all ancestors first." This is the safest way to
run a single model because it ensures staging inputs are up-to-date.

**Run only staging models:**

```bash
dbt run --select staging
```

**Run only canonical models:**

```bash
dbt run --select canonical
```

**Run only tests:**

```bash
dbt test
```

**Run a specific test:**

```bash
dbt test --select test_schema_drift_guard
```

**Full refresh (rebuild from scratch, ignoring incremental windows):**

```bash
dbt run --select fact_orders_v1 --full-refresh
```

Use `--full-refresh` when:
- A model's SQL logic has changed significantly
- You suspect data corruption in the target table
- You are setting up a new environment for the first time

### 2.5 What each dbt layer does

| Layer          | Directory              | Materialized as | What it does                                          |
|----------------|------------------------|-----------------|-------------------------------------------------------|
| Raw sources    | `models/raw_sources/`  | (not models)    | Source definitions pointing to Airbyte tables          |
| Staging        | `models/staging/`      | Views           | Extracts fields from `_airbyte_data` JSON, deduplicates, type-casts, adds tenant_id |
| Canonical      | `models/canonical/`    | Incremental tables | Business-logic fact tables (revenue, spend, performance) |
| Semantic views | `models/semantic_views/`| Views          | Immutable versioned views (`_v1`) and governed aliases (`_current`) |
| Metrics        | `models/metrics/`      | Views           | Derived metrics (ROAS, CAC, etc.)                     |
| Marts          | `models/marts/`        | Tables          | Pre-aggregated dashboard tables                        |

### 2.6 Feature flags

Some staging models can be disabled if you do not use the source platform.
Set the corresponding variable to `false`:

| Variable               | Controls                   | Default |
|------------------------|----------------------------|---------|
| `enable_tiktok_ads`    | `stg_tiktok_ads_performance` | `true`  |
| `enable_snapchat_ads`  | `stg_snapchat_ads`          | `true`  |
| `enable_klaviyo`       | `stg_klaviyo_events`         | `true`  |
| `enable_shopify_email` | `stg_shopify_email_events`   | `true`  |
| `enable_attentive`     | `stg_attentive_events`       | `true`  |
| `enable_smsbump`       | `stg_smsbump_events`         | `true`  |
| `enable_postscript`    | `stg_postscript_events`      | `true`  |

Example disabling TikTok:

```bash
dbt run --vars '{enable_tiktok_ads: false}'
```

---

## 3. How rolling rebuild works

### 3.1 The problem it solves

Source platforms revise historical data after the initial sync:

- Shopify may record a refund weeks after the original order
- Ad platforms revise attribution and conversion data within their
  attribution window (typically 7-28 days)
- Late-arriving records may be ingested after the original batch

If canonical models only processed newly-ingested records, these corrections
would be missed. The rolling rebuild re-processes a configurable window of
historical data on every run.

### 3.2 How it works, step by step

Take `fact_orders_v1` as an example (90-day window):

1. dbt checks: is the target table already populated? If yes, this is an
   **incremental run**.
2. The model's SQL adds a filter:
   ```sql
   WHERE report_date >= current_date - 90
   ```
   This selects all staging orders from the last 90 days.
3. dbt uses the `delete+insert` strategy:
   - **Delete** all rows in the target table whose `id` matches the
     incoming 90-day set.
   - **Insert** the fresh rows from the query.
4. Rows older than 90 days are **untouched** in the target table.

On the **first run** (empty table) or with `--full-refresh`, the date filter
is skipped and all historical data is loaded.

### 3.3 Window configuration

Windows are configured as dbt variables in `dbt_project.yml`:

| Variable               | Default | Applies to                           | Why this window size                          |
|------------------------|---------|--------------------------------------|-----------------------------------------------|
| `shopify_rebuild_days` | 90      | `fact_orders_v1`                     | Covers refund/chargeback dispute timelines    |
| `ads_rebuild_days`     | 30      | `fact_marketing_spend_v1`, `fact_campaign_performance_v1` | Covers ad platform attribution windows |
| `email_rebuild_days`   | 30      | (Future email canonical models)      | Covers email open/click attribution lags      |

### 3.4 Overriding the window at runtime

```bash
# Widen Shopify window to catch a backlog of late refunds
dbt run --select fact_orders_v1 --vars '{shopify_rebuild_days: 120}'

# Narrow ads window for a quick refresh
dbt run --select fact_marketing_spend_v1 --vars '{ads_rebuild_days: 7}'

# Skip the window entirely and rebuild everything
dbt run --select fact_orders_v1 --full-refresh
```

### 3.5 Business date vs. ingestion date

The rolling rebuild filters on **business date** (when the event occurred),
not ingestion date (when Airbyte delivered it). This is a deliberate choice:

- A refund processed today for an order placed 15 days ago updates the
  *order record*, not the refund date.
- If we filtered on ingestion date, we would miss updates to old orders
  that were re-synced by Airbyte.

| Model                         | Business date column | Source column |
|-------------------------------|----------------------|---------------|
| `fact_orders_v1`              | `order_date`         | `report_date` from `stg_shopify_orders` |
| `fact_marketing_spend_v1`     | `spend_date`         | `date` from staging ad models |
| `fact_campaign_performance_v1`| `campaign_date`      | `date` from staging ad models |

### 3.6 How to verify the rebuild is working

```sql
-- Check that rows within the window were updated on the last run
SELECT
    min(dbt_updated_at) AS oldest_update,
    max(dbt_updated_at) AS newest_update,
    count(*)            AS row_count
FROM analytics.fact_orders_v1
WHERE order_date >= current_date - 90;

-- Compare against rows outside the window (should have older dbt_updated_at)
SELECT
    min(dbt_updated_at) AS oldest_update,
    max(dbt_updated_at) AS newest_update,
    count(*)            AS row_count
FROM analytics.fact_orders_v1
WHERE order_date < current_date - 90;
```

If `newest_update` in the first query is recent (from the last run) and in
the second query is older, the rolling rebuild is working correctly.

---

## 4. How schema drift approvals work

### 4.1 What is schema drift?

Schema drift happens when a source API (Shopify, Meta, etc.) adds a new
field to its response. Airbyte ingests it into the raw JSON automatically.
The danger is if someone starts using that field in staging or canonical
models without review, which could:

- Expose PII (emails, phone numbers, addresses)
- Break downstream dashboards that expect a fixed set of columns
- Invalidate metric calculations

### 4.2 The allowlist system

Every staging model has an **approved column list**. If a column exists in
the database but is not on the list, a dbt test fails and blocks deployment.

The system has three parts:

```
governance/                      macros/                        tests/
===========================      ===========================    ==========================
approved_columns_shopify.yml     get_approved_columns.sql       test_schema_drift_guard.sql
approved_columns_facebook.yml    assert_columns_approved.sql
approved_columns_google.yml
approved_columns_tiktok.yml
approved_columns_email.yml
```

**Governance YAML files** — Human-readable reference lists of approved
columns per model and source. One file per source platform.

**`get_approved_columns.sql` macro** — Returns a Jinja dictionary of all
approved columns at compile time. This is the file that dbt actually reads.
It must be kept in sync with the YAML files.

**`assert_columns_approved.sql` macro** — Queries `information_schema` to
find the actual columns in a model's table, then checks each one against the
allowlist. Returns a row for each unapproved column.

**`test_schema_drift_guard.sql`** — A singular dbt test that calls
`assert_columns_approved()` for all 8 governed staging models.

### 4.3 Governed models

| Model                   | Governance file                        |
|-------------------------|----------------------------------------|
| `stg_shopify_orders`    | `governance/approved_columns_shopify.yml`  |
| `stg_shopify_customers` | `governance/approved_columns_shopify.yml`  |
| `stg_meta_ads`          | `governance/approved_columns_facebook.yml` |
| `stg_google_ads`        | `governance/approved_columns_google.yml`   |
| `stg_tiktok_ads`        | `governance/approved_columns_tiktok.yml`   |
| `stg_klaviyo_events`    | `governance/approved_columns_email.yml`    |
| `stg_klaviyo_campaigns` | `governance/approved_columns_email.yml`    |
| `stg_shopify_email_events` | `governance/approved_columns_email.yml` |

### 4.4 Step-by-step: Approving a new column

Suppose a new field `discount_codes` appears in Shopify order data and you
want to use it.

**Step 1 — Confirm the field exists in raw data:**

```sql
SELECT _airbyte_data->>'discount_codes'
FROM airbyte_raw._airbyte_raw_shopify_orders
LIMIT 5;
```

**Step 2 — Add the column to the staging SQL:**

Edit `models/staging/shopify/stg_shopify_orders.sql` and add the column
extraction logic in the appropriate CTE.

**Step 3 — Add the column to both allowlist files:**

First, the governance YAML (`governance/approved_columns_shopify.yml`):

```yaml
models:
  stg_shopify_orders:
    - tenant_id
    - order_id
    # ... existing columns ...
    - discount_codes    # <-- add here
```

Then, the compiled macro (`macros/get_approved_columns.sql`):

```sql
'stg_shopify_orders': [
  'tenant_id',
  'order_id',
  ...
  'discount_codes'    {# <-- add here #}
],
```

Both files must stay in sync. The YAML is the human-readable reference; the
macro is what dbt actually uses at compile time.

**Step 4 — Add the column to `models/staging/schema.yml`:**

```yaml
- name: discount_codes
  description: Discount codes applied to the order
```

**Step 5 — Run the drift guard test locally:**

```bash
dbt run --select stg_shopify_orders
dbt test --select test_schema_drift_guard
```

Expected output on success:

```
Completed successfully
Done. PASS=1 WARN=0 ERROR=0 SKIP=0 TOTAL=1
```

**Step 6 — Open a PR for review:**

The PR requires sign-off from the Analytics Tech Lead. The reviewer checks:

- [ ] Column has a clear business purpose
- [ ] No PII exposure (email, phone, address) without hashing
- [ ] Column is documented in `schema.yml`
- [ ] Both allowlist files updated (YAML and macro)
- [ ] `dbt test` passes

### 4.5 Running the drift guard on its own

```bash
# Run only the schema drift test
dbt test --select test_schema_drift_guard

# Run all tests (drift guard is included)
dbt test
```

### 4.6 What a drift failure looks like

```
FAIL 1
model_name: stg_shopify_orders
unapproved_column: discount_codes
allowlist_file: governance/approved_columns_shopify.yml
error_message: SCHEMA DRIFT DETECTED: Column "discount_codes" in model
  "stg_shopify_orders" is not in the approved allowlist...
```

This tells you exactly which column is unapproved and which governance file
to update.

---

## 5. How to troubleshoot failed models

### 5.1 General approach

When a dbt run or test fails:

1. Read the error message carefully. dbt almost always tells you the exact
   file and line.
2. Check which layer failed (staging, canonical, test).
3. Use the sections below to find the specific failure pattern.

### 5.2 "Relation does not exist"

```
Database Error in model fact_orders_v1
  relation "staging.stg_shopify_orders" does not exist
```

**Cause:** The upstream model has not been materialized yet.

**Fix:** Run the upstream model first, or use `+` to include dependencies:

```bash
dbt run --select +fact_orders_v1
```

The `+` prefix tells dbt to run all ancestors of `fact_orders_v1` (i.e.
the staging models) before running `fact_orders_v1` itself.

### 5.3 "Source table does not exist"

```
Compilation Error
  source('raw_tiktok_ads', 'ad_reports') does not exist
```

**Cause:** Airbyte has never synced this source, so the raw table does not
exist in the database.

**Fix (option A):** Wait for the first Airbyte sync to complete.

**Fix (option B):** Disable the source if you do not use it:

```bash
dbt run --vars '{enable_tiktok_ads: false}'
```

Most staging models use the `source_exists()` macro to gracefully return an
empty result set when the raw table is missing. If you see this error, the
model may not have that guard. Ask a team member to add it.

### 5.4 Schema drift test failure

```
FAIL 1  test_schema_drift_guard
```

**Cause:** A column exists in a staging model's materialized table that is
not in the approved column allowlist.

**This is expected behavior.** The drift guard is doing its job.

**Fix:** Follow the column approval process in [section 4.4](#44-step-by-step-approving-a-new-column).
If the column was added intentionally, add it to both allowlist files and
re-run the test. If it was not intentional, investigate why the staging
model is outputting an unexpected column.

### 5.5 Reconciliation test failure

```
FAIL 1  test_reconcile_shopify_orders
```

**Cause:** The aggregate totals in a canonical fact table differ from the
staging totals by more than the configured tolerance (default: 1%).

The test output includes diagnostic columns:

| Column          | What it tells you                                 |
|-----------------|---------------------------------------------------|
| `metric`        | Which metric failed (e.g. `revenue_gross`, `spend`) |
| `staging_total` | Total from staging models                         |
| `fact_total`    | Total from the canonical fact table               |
| `abs_diff`      | Absolute difference                               |
| `pct_diff`      | Percentage difference                             |
| `staging_rows`  | Row count in staging                              |
| `fact_rows`     | Row count in the canonical table                  |

**If `staging_rows` is much larger than `fact_rows`:** The canonical table
probably needs a full refresh:

```bash
dbt run --select fact_orders_v1 --full-refresh
```

**If row counts match but totals differ:** A transformation bug may exist
in the canonical model. Compare a sample of rows between staging and
canonical to find the discrepancy.

**If you are running a large backfill:** Temporarily widen the tolerance:

```bash
dbt test --select test_reconcile_shopify_orders \
  --vars '{reconciliation_tolerance_pct: 5.0}'
```

### 5.6 Freshness error

```
ERROR   source raw_shopify.orders
  ERROR: loaded_at is more than 48 hours old
```

**Cause:** Airbyte has not delivered new data for this source in over 48
hours.

**Fix:**

1. Check the Airbyte UI for failed or stuck sync jobs.
2. Check the source system (e.g., is the Shopify store still connected?).
3. If the sync is genuinely stalled, trigger a manual sync in Airbyte.
4. After new data arrives, re-run `dbt source freshness` to confirm.

### 5.7 Duplicate key violation (canonical models)

```
Database Error in model fact_orders_v1
  duplicate key value violates unique constraint
```

**Cause:** The surrogate key (`id`) is producing collisions. This usually
means the grain of the canonical model does not match the data.

**Fix:**

1. Check whether the staging data has unexpected duplicates:
   ```sql
   SELECT tenant_id, order_id, count(*)
   FROM staging.stg_shopify_orders
   GROUP BY tenant_id, order_id
   HAVING count(*) > 1;
   ```
2. If duplicates exist in staging, investigate the deduplication logic in
   the staging model.
3. If the staging data is clean, the canonical model's unique key formula
   may need adjusting. Escalate to the analytics engineering team.

### 5.8 "Column X is ambiguous"

**Cause:** A join in the model produces two columns with the same name.

**Fix:** Check the canonical model's SQL for a `SELECT *` or unqualified
column reference in a join. Prefix the column with the correct table alias.

### 5.9 Incremental model has wrong data

Symptoms: row counts are off, totals look wrong, but no error was raised.

**Fix — Full refresh the model:**

```bash
dbt run --select fact_marketing_spend_v1 --full-refresh
```

This drops the existing table and rebuilds it from scratch, ignoring
incremental logic. Use this as a first resort when an incremental model
seems to have drifted.

### 5.10 dbt compile error

```
Compilation Error in model ...
  'some_macro' is undefined
```

**Cause:** A macro is missing or misspelled, or `dbt deps` was not run.

**Fix:**

```bash
dbt deps    # install packages (dbt_utils, etc.)
dbt compile # check for compile errors without running anything
```

If the error persists, check that the macro exists in the `macros/`
directory and that its name matches the call in the model SQL.

### 5.11 Test failure: tenant isolation

```
FAIL 1  tenant_isolation
```

**Cause:** A model contains rows with a NULL `tenant_id`.

**Fix:** Check the staging model's tenant join logic. Ensure the
`_tenant_airbyte_connections` model has a mapping for the Airbyte connection
that produced the data. If the connection is new, add it to the
`platform.tenant_airbyte_connections` table.

---

## 6. Quick-reference commands

All commands run from the `analytics/` directory.

### Daily operations

```bash
# Full pipeline build (models + tests)
dbt build

# Check source freshness
dbt source freshness

# Run all tests
dbt test
```

### Selective runs

```bash
# One model and all its upstream dependencies
dbt run --select +fact_orders_v1

# All staging models
dbt run --select staging

# All canonical models
dbt run --select canonical

# All semantic views
dbt run --select tag:semantic
```

### Debugging

```bash
# Compile SQL without running (see target/ for compiled output)
dbt compile --select fact_orders_v1

# Run with debug logging
dbt --debug run --select fact_orders_v1

# Check connection and config
dbt debug
```

### Recovery

```bash
# Full refresh a model that has drifted
dbt run --select fact_orders_v1 --full-refresh

# Widen rolling rebuild window temporarily
dbt run --select fact_orders_v1 --vars '{shopify_rebuild_days: 180}'

# Relax reconciliation tolerance during backfill
dbt test --select test_reconcile_shopify_orders \
  --vars '{reconciliation_tolerance_pct: 5.0}'
```

### Schema drift

```bash
# Run the drift guard
dbt test --select test_schema_drift_guard

# After updating allowlists, verify the fix
dbt run --select stg_shopify_orders
dbt test --select test_schema_drift_guard
```
