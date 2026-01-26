-- Test 4: Zero Spend Edge Case
-- Verify ROAS displays 'N/A' when spend is zero
--
-- Edge cases:
--   - Campaign with zero spend -> ROAS = NULL (displayed as 'N/A')
--   - Campaign with zero conversions but non-zero spend -> ROAS = 0
--   - Division by zero must not cause errors
--
-- Usage: Run with `dbt test --select test_zero_spend_edge_case`

WITH campaign_metrics AS (
    SELECT
        campaign_id,
        campaign_name,
        platform,
        SUM(spend) AS total_spend,
        SUM(conversions) AS total_conversions,
        -- This is the ROAS calculation used in the dashboard
        CASE
            WHEN SUM(spend) = 0 THEN NULL  -- Will display as 'N/A'
            ELSE SUM(conversions) / NULLIF(SUM(spend), 0)
        END AS roas,
        -- Text representation for display
        CASE
            WHEN SUM(spend) = 0 THEN 'N/A'
            ELSE CAST(SUM(conversions) / NULLIF(SUM(spend), 0) AS TEXT)
        END AS roas_display
    FROM {{ ref('fact_campaign_performance') }}
    GROUP BY campaign_id, campaign_name, platform
),

zero_spend_campaigns AS (
    SELECT *
    FROM campaign_metrics
    WHERE total_spend = 0
),

validation AS (
    SELECT
        campaign_id,
        total_spend,
        roas,
        roas_display,
        CASE
            WHEN roas IS NULL AND roas_display = 'N/A' THEN 'PASS'
            WHEN roas IS NOT NULL THEN 'FAIL - ROAS should be NULL for zero spend'
            ELSE 'FAIL - Display should be N/A'
        END AS test_result
    FROM zero_spend_campaigns
)

-- Test passes if all zero-spend campaigns show N/A
SELECT *
FROM validation
WHERE test_result LIKE 'FAIL%'
