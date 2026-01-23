# Quick Start: Render Database Console

## 🚀 Fastest Way to Set Up Test Data

### Step 1: Open Render Console

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click on **shopify-analytics-db**
3. Look for:
   - **"Connect"** button
   - **"Console"** tab
   - **"Query"** or **"SQL Editor"**
   - **"psql"** option
4. Click to open the database console

### Step 2: Copy & Paste SQL

1. Open `render_console_setup.sql` in this directory
2. **Copy the entire file** (all SQL)
3. **Paste into Render console**
4. **Execute/Run** the SQL

### Step 3: Verify Setup

Run this query in Render console:

```sql
SELECT 'Shopify Orders' as table_name, COUNT(*) as record_count 
FROM test_airbyte._airbyte_raw_shopify_orders
UNION ALL
SELECT 'Shopify Customers', COUNT(*) 
FROM test_airbyte._airbyte_raw_shopify_customers
UNION ALL
SELECT 'Meta Ads', COUNT(*) 
FROM test_airbyte._airbyte_raw_meta_ads
UNION ALL
SELECT 'Google Ads', COUNT(*) 
FROM test_airbyte._airbyte_raw_google_ads
UNION ALL
SELECT 'Tenant Connections', COUNT(*) 
FROM test_airbyte.tenant_airbyte_connections;
```

**Expected Results:**
- Shopify Orders: **4**
- Shopify Customers: **2**
- Meta Ads: **2**
- Google Ads: **2**
- Tenant Connections: **3**

### Step 4: Next Steps

Once test data is set up:

**Option A: Run dbt from Render Service** (if available)
- SSH into your Render service
- Run dbt commands there (no network issues)

**Option B: Wait for Network Fix**
- Once DNS/network issues are resolved locally
- Run dbt from your local machine

**Option C: Use Render Console for Testing**
- Run SQL queries directly in console
- Test model logic manually

## 📁 Files Available

- **`render_console_setup.sql`** - Complete setup script (copy-paste ready)
- **`render_console_verify.sql`** - Verification queries
- **`RENDER_CONSOLE_SETUP.md`** - Detailed guide

## ✅ What Gets Created

- ✅ `test_airbyte` schema
- ✅ Test tables matching Airbyte structure
- ✅ Sample data with edge cases
- ✅ Tenant connection mappings

## 🔍 Troubleshooting

**Console not available?**
- Some Render plans don't include console
- Try "Shell" option from a Render service
- Or use external tool once network is fixed

**SQL errors?**
- Check if you have CREATE SCHEMA permissions
- Verify you're connected to the correct database
- Check Render database logs for errors

---

**Ready to go!** Copy `render_console_setup.sql` into Render console and execute.
