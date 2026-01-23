# Test Data Setup Guide

This guide explains how to set up and run test data for validating staging models.

## Quick Start

### Option 1: Using Python Script (Recommended)

```bash
cd analytics

# Install psycopg2 if needed
pip install psycopg2-binary

# Set database connection
export DATABASE_URL="postgresql://user:password@host:port/database"
# OR
export DB_HOST="localhost"
export DB_USER="postgres"
export DB_PASSWORD="your-password"
export DB_PORT="5432"
export DB_NAME="shopify_analytics"

# Run test data setup
python3 tests/validate_with_test_data.py
```

### Option 2: Using SQL Script

```bash
cd analytics

# Connect to database and run SQL
psql $DATABASE_URL -f tests/test_data_setup.sql
```

### Option 3: Using dbt Seeds (Future)

When dbt is available, you can use seed files for test data.

## Test Data Includes

### Shopify Orders
- Normal order with GID format
- Order with invalid price (edge case)
- Order with null ID (edge case - should be filtered)

### Shopify Customers
- Normal customer
- Customer with boolean as number (edge case)

### Meta Ads
- Normal ad performance data
- Ad with invalid spend (edge case)

### Google Ads
- Ad with cost_micros (micros format)
- Ad with cost (decimal format - edge case)

### Tenant Connections
- Shopify connection
- Meta Ads connection
- Google Ads connection

## Running dbt with Test Data

After setting up test data:

```bash
# Option 1: Temporarily update sources to use test_airbyte schema
# Edit models/staging/schema.yml to point to test_airbyte schema

# Option 2: Copy test data to main schema
# (Not recommended for production)

# Run staging models
dbt run --select staging

# Run tests
dbt test --select staging
```

## Validating Results

After running models, verify:

1. **Orders**: Should have 2 records (null ID filtered out)
2. **Customers**: Should have 2 records
3. **Meta Ads**: Should have 2 records (invalid spend defaults to 0.0)
4. **Google Ads**: Should have 2 records (both cost formats handled)
5. **Tenant Isolation**: All records should have tenant_id = 'tenant-test-123'

## Edge Cases Tested

- ✅ Null primary keys (filtered out)
- ✅ Invalid numeric values (default to 0.0)
- ✅ Invalid currency codes (default to USD)
- ✅ Boolean as string/number (converted correctly)
- ✅ Google Ads cost_micros vs cost (both handled)
- ✅ GID format normalization
- ✅ Date format validation

## Cleanup

To remove test data:

```sql
DROP SCHEMA IF EXISTS test_airbyte CASCADE;
```
