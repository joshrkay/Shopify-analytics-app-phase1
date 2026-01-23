# Using Render Database Console - Setup Guide

## Overview

Since we're having network connectivity issues from your local machine, we'll use Render's built-in database console to set up test data and verify the connection.

## Step 1: Access Render Database Console

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Navigate to your database: **shopify-analytics-db**
3. Look for one of these options:
   - **"Connect"** button
   - **"Console"** tab
   - **"Query"** or **"SQL Editor"** option
   - **"psql"** or **"Shell"** option

4. Click to open the database console/editor

## Step 2: Set Up Test Data

Copy and paste the SQL from `render_console_setup.sql` (see below) into the Render console and execute it.

This will:
- Create test schema (`test_airbyte`)
- Create test tables matching Airbyte structure
- Insert sample test data
- Create tenant connection mappings

## Step 3: Verify Test Data

Run these queries in Render console to verify:

```sql
-- Check test data was created
SELECT COUNT(*) FROM test_airbyte._airbyte_raw_shopify_orders;
SELECT COUNT(*) FROM test_airbyte._airbyte_raw_shopify_customers;
SELECT COUNT(*) FROM test_airbyte._airbyte_raw_meta_ads;
SELECT COUNT(*) FROM test_airbyte._airbyte_raw_google_ads;
SELECT COUNT(*) FROM test_airbyte.tenant_airbyte_connections;
```

Expected results:
- Orders: 4 records (1 will be filtered out due to null ID)
- Customers: 2 records
- Meta Ads: 2 records
- Google Ads: 2 records
- Tenant Connections: 3 records

## Step 4: Run dbt Models (Alternative Methods)

### Option A: From Render Service (if available)

If you have a Render service that can run dbt:

1. SSH into the Render service
2. Set environment variables:
   ```bash
   export DB_HOST="dpg-d5o4ho4oud1c73ccl4mg-a.oregon-postgres.render.com"
   export DB_USER="shopify_analytics_db_00ga_user"
   export DB_PASSWORD="8xM3xBadc4yic3wNxyjKQleY851PRU61"
   export DB_PORT="5432"
   export DB_NAME="shopify_analytics_db_00ga"
   ```
3. Run dbt:
   ```bash
   cd analytics
   dbt run --select staging --vars '{"test_schema": "test_airbyte"}'
   dbt test --select staging --vars '{"test_schema": "test_airbyte"}'
   ```

### Option B: Manual SQL Validation

Run the compiled SQL from dbt models directly in Render console:

1. Compile dbt models locally (if possible):
   ```bash
   dbt compile --select staging --vars '{"test_schema": "test_airbyte"}'
   ```

2. Copy SQL from `target/compiled/shopify_analytics/models/staging/.../*.sql`

3. Paste and run in Render console

### Option C: Direct SQL Queries

Test the staging model logic directly in Render console using the SQL from the model files.

## Step 5: Verify Results

After running models, verify in Render console:

```sql
-- Check staging models were created
SELECT COUNT(*) FROM staging.stg_shopify_orders;
SELECT COUNT(*) FROM staging.stg_shopify_customers;
SELECT COUNT(*) FROM staging.stg_meta_ads;
SELECT COUNT(*) FROM staging.stg_google_ads;

-- Verify tenant isolation
SELECT tenant_id, COUNT(*) 
FROM staging.stg_shopify_orders 
GROUP BY tenant_id;
```

## Troubleshooting

### If Console Not Available

Some Render database plans don't include a console. Alternatives:

1. **Use Render Shell** (if available):
   - Go to your Render service
   - Use "Shell" option
   - Connect to database from there

2. **Use External Tool**:
   - Once network issues are resolved, use dbt locally
   - Or use a database GUI tool (pgAdmin, DBeaver, etc.) if you can connect

3. **Use Render API** (if available):
   - Some Render databases support API access
   - Check Render documentation

## Next Steps

Once test data is set up in Render console:
1. Test data is ready ✅
2. Models can be run when network connectivity is established
3. Or run models from Render service if available

---

**Note**: The SQL scripts below are ready to copy-paste into Render console.
