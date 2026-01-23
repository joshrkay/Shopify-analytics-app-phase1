-- ============================================================================
-- Render Console - Verification Queries
-- 
-- Run these queries in Render console to verify test data and model results
-- ============================================================================

-- 1. Verify test data exists
SELECT 
    'test_airbyte._airbyte_raw_shopify_orders' as table_name,
    COUNT(*) as record_count
FROM test_airbyte._airbyte_raw_shopify_orders
UNION ALL
SELECT 
    'test_airbyte._airbyte_raw_shopify_customers',
    COUNT(*)
FROM test_airbyte._airbyte_raw_shopify_customers
UNION ALL
SELECT 
    'test_airbyte._airbyte_raw_meta_ads',
    COUNT(*)
FROM test_airbyte._airbyte_raw_meta_ads
UNION ALL
SELECT 
    'test_airbyte._airbyte_raw_google_ads',
    COUNT(*)
FROM test_airbyte._airbyte_raw_google_ads
UNION ALL
SELECT 
    'test_airbyte.tenant_airbyte_connections',
    COUNT(*)
FROM test_airbyte.tenant_airbyte_connections;

-- 2. Check if staging models exist (after running dbt)
SELECT 
    schemaname,
    tablename,
    tableowner
FROM pg_tables
WHERE schemaname = 'staging'
ORDER BY tablename;

-- 3. Verify staging model data (if models were created)
-- Uncomment these after running dbt models:

-- SELECT COUNT(*) as order_count FROM staging.stg_shopify_orders;
-- SELECT COUNT(*) as customer_count FROM staging.stg_shopify_customers;
-- SELECT COUNT(*) as meta_ads_count FROM staging.stg_meta_ads;
-- SELECT COUNT(*) as google_ads_count FROM staging.stg_google_ads;

-- 4. Verify tenant isolation
-- SELECT 
--     tenant_id,
--     COUNT(*) as record_count
-- FROM staging.stg_shopify_orders
-- GROUP BY tenant_id;

-- 5. Sample data from test tables
SELECT 
    _airbyte_ab_id,
    _airbyte_emitted_at,
    _airbyte_data->>'id' as order_id,
    _airbyte_data->>'name' as order_name,
    _airbyte_data->>'total_price' as total_price
FROM test_airbyte._airbyte_raw_shopify_orders
LIMIT 5;
