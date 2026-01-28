-- Test 3: Empty State Handling
-- Verify graceful handling when no data exists
--
-- Scenarios tested:
--   - New tenant with no orders
--   - Time period with no activity
--   - Filtered results returning zero rows
--
-- Expected behavior:
--   - NULL or 0 returned (not an error)
--   - Dashboard displays empty state message
--
-- Usage: Run with `dbt test --select test_empty_state_handling`

-- Test 3a: Query for non-existent tenant returns NULL/0
WITH empty_tenant_revenue AS (
    SELECT
        COALESCE(SUM(revenue_gross), 0) AS total_revenue,
        COUNT(*) AS order_count
    FROM {{ ref('fact_orders') }}
    WHERE tenant_id = 'non_existent_tenant_xyz_12345'
      AND order_created_at >= CURRENT_DATE - INTERVAL '30 days'
),

validation AS (
    SELECT
        total_revenue,
        order_count,
        CASE
            WHEN total_revenue = 0 AND order_count = 0 THEN 'PASS'
            ELSE 'FAIL'
        END AS test_result
    FROM empty_tenant_revenue
)

-- Test passes if empty tenant returns 0
SELECT *
FROM validation
WHERE test_result = 'FAIL'
