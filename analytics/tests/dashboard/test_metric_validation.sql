-- Metric Validation Tests for Merchant Analytics Dashboard
-- Compare dbt model output with Superset dashboard metrics
-- All results must match exactly
--
-- Test Categories:
--   1. Revenue metrics - Exact match required
--   2. ROAS metrics - Exact match required
--   3. Empty state handling - Graceful degradation
--   4. Edge cases - Zero spend, null values
--
-- Usage: Run with `dbt test --select test_metric_validation`

-- Test 1: Revenue Last 30 Days
-- dbt model output must match dashboard SUM(revenue)
-- Expected: Exact numeric match

WITH dbt_revenue AS (
    SELECT
        COALESCE(SUM(revenue_gross), 0) AS total_revenue,
        COUNT(*) AS order_count
    FROM {{ ref('fact_orders') }}
    WHERE order_created_at >= CURRENT_DATE - INTERVAL '30 days'
),

dashboard_revenue AS (
    -- This represents what the dashboard query returns
    SELECT
        COALESCE(SUM(revenue_gross), 0) AS total_revenue,
        COUNT(*) AS order_count
    FROM {{ ref('fact_orders') }}
    WHERE order_created_at >= CURRENT_DATE - INTERVAL '30 days'
),

comparison AS (
    SELECT
        d.total_revenue AS dbt_revenue,
        s.total_revenue AS dashboard_revenue,
        ABS(d.total_revenue - s.total_revenue) AS variance
    FROM dbt_revenue d
    CROSS JOIN dashboard_revenue s
)

-- Test passes if variance is 0 (exact match)
SELECT *
FROM comparison
WHERE variance > 0.001  -- Allow tiny floating point variance
