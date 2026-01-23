# Quick Test Guide - Story 4.2 & 4.3

## Option 1: SQL Logic Tests (No Database Required)

Test the SQL transformation logic:

```bash
cd analytics

# If you have psql installed
export DATABASE_URL="postgresql://user:pass@host:port/db"
./tests/run_sql_tests.sh

# Or manually
psql $DATABASE_URL -f tests/test_sql_logic.sql
```

## Option 2: Full Test Data Setup (Requires Database)

Set up complete test data and run dbt:

```bash
cd analytics

# Install dependencies
pip install psycopg2-binary

# Set database connection
export DATABASE_URL="postgresql://user:pass@host:port/db"

# Setup test data
python3 tests/validate_with_test_data.py

# Then run dbt (when available)
dbt run --select staging
dbt test --select staging
```

## Option 3: Manual SQL Test

Run the test data setup SQL directly:

```bash
psql $DATABASE_URL -f tests/test_data_setup.sql
```

## What Gets Tested

### Edge Cases
- ✅ Null primary keys (filtered out)
- ✅ Invalid numeric values (default to 0.0)
- ✅ Invalid currency codes (default to USD)
- ✅ Boolean conversion (string/number formats)
- ✅ Google Ads cost_micros conversion
- ✅ GID format normalization
- ✅ Date format validation

### Data Quality
- ✅ Type conversions work correctly
- ✅ Bounds checking prevents overflow
- ✅ Tenant isolation enforced
- ✅ Required fields validated

## Expected Results

After running tests, you should see:
- Orders: 2 valid records (1 filtered due to null ID)
- Customers: 2 valid records
- Meta Ads: 2 valid records (invalid spend defaults to 0.0)
- Google Ads: 2 valid records (both cost formats handled)

## Troubleshooting

**"psql: command not found"**
- Install PostgreSQL client tools
- Or use Python script instead

**"psycopg2 not found"**
- Install: `pip install psycopg2-binary`

**"Database connection failed"**
- Verify DATABASE_URL or DB_* environment variables
- Check database is accessible
- Verify credentials are correct
