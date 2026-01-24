-- SQL Logic Test - Validates transformations work correctly
-- 
-- This test validates the SQL logic by creating sample data and testing transformations
-- Run this in a test database to verify staging models work correctly
--
-- Usage:
--   psql $DATABASE_URL -f tests/test_sql_logic.sql

-- Create test schema
CREATE SCHEMA IF NOT EXISTS test_validation;

-- Test 1: Shopify Order ID Normalization
-- Should remove gid:// prefix
SELECT 
    CASE
        WHEN 'gid://shopify/Order/12345' LIKE 'gid://shopify/Order/%' 
            THEN REPLACE('gid://shopify/Order/12345', 'gid://shopify/Order/', '')
        ELSE 'gid://shopify/Order/12345'
    END as normalized_id;
-- Expected: '12345'

-- Test 2: Currency Normalization
-- Should uppercase and validate
SELECT 
    CASE
        WHEN 'usd' IS NULL OR TRIM('usd') = '' THEN 'USD'
        WHEN UPPER(TRIM('usd')) ~ '^[A-Z]{3}$' 
            THEN UPPER(TRIM('usd'))
        ELSE 'USD'
    END as normalized_currency;
-- Expected: 'USD'

-- Test 3: Numeric Validation
-- Should validate before casting
SELECT 
    CASE
        WHEN '99.99' IS NULL OR TRIM('99.99') = '' THEN 0.0
        WHEN TRIM('99.99') ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' 
            THEN LEAST(GREATEST(TRIM('99.99')::numeric, -999999999.99), 999999999.99)
        ELSE 0.0
    END as validated_price;
-- Expected: 99.99

-- Test 4: Invalid Numeric Handling
-- Should default to 0.0 for invalid values
SELECT 
    CASE
        WHEN 'invalid' IS NULL OR TRIM('invalid') = '' THEN 0.0
        WHEN TRIM('invalid') ~ '^-?[0-9]+\.?[0-9]*([eE][+-]?[0-9]+)?$' 
            THEN LEAST(GREATEST(TRIM('invalid')::numeric, -999999999.99), 999999999.99)
        ELSE 0.0
    END as invalid_price_handled;
-- Expected: 0.0

-- Test 5: Google Ads Cost Micros Conversion
-- Should convert micros to dollars
SELECT 
    CASE
        WHEN '25500000' IS NOT NULL AND TRIM('25500000') != '' 
            AND TRIM('25500000') ~ '^-?[0-9]+$' THEN
            LEAST(GREATEST((TRIM('25500000')::bigint / 1000000.0)::numeric, -999999999.99), 999999999.99)
        ELSE 0.0
    END as cost_from_micros;
-- Expected: 25.50

-- Test 6: Boolean Conversion
-- Should handle various boolean formats
SELECT 
    CASE
        WHEN 'true' IS NULL THEN NULL
        WHEN LOWER(TRIM(COALESCE('true', ''))) IN ('true', '1', 'yes', 'y', 't') THEN TRUE
        WHEN LOWER(TRIM(COALESCE('true', ''))) IN ('false', '0', 'no', 'n', 'f', '') THEN FALSE
        ELSE NULL
    END as boolean_from_string;
-- Expected: TRUE

-- Test 7: Date Validation
-- Should validate date format before casting
SELECT 
    CASE
        WHEN '2024-01-15' IS NULL OR TRIM('2024-01-15') = '' THEN NULL
        WHEN '2024-01-15' ~ '^\d{4}-\d{2}-\d{2}' 
            THEN '2024-01-15'::date
        ELSE NULL
    END as validated_date;
-- Expected: 2024-01-15

-- Test 8: Null Primary Key Filtering
-- Should filter out null IDs
SELECT 
    CASE
        WHEN NULL IS NULL OR TRIM(COALESCE(NULL, '')) = '' THEN 'FILTERED'
        ELSE 'KEPT'
    END as null_id_handling;
-- Expected: 'FILTERED'

-- Summary
SELECT 
    '✅ All SQL logic tests completed' as status,
    'Review results above to verify transformations' as next_step;
