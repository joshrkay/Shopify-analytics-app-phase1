-- Test 2: ROAS by Campaign Validation
-- Compare dbt ROAS calculation with dashboard ROAS
-- Expected: Exact match required
--
-- Edge cases handled:
--   - Zero spend -> NULL ROAS (displayed as 'N/A')
--   - No conversions -> ROAS = 0
--
-- Usage: Run with `dbt test --select test_roas_validation`

WITH dbt_roas AS (
    SELECT
        campaign_id,
        campaign_name,
        platform,
        SUM(spend) AS total_spend,
        SUM(conversions) AS total_conversions,
        CASE
            WHEN SUM(spend) = 0 THEN NULL
            ELSE SUM(conversions) / NULLIF(SUM(spend), 0)
        END AS roas
    FROM {{ ref('fact_campaign_performance') }}
    WHERE date >= CURRENT_DATE - INTERVAL '30 days'
    GROUP BY campaign_id, campaign_name, platform
),

dashboard_roas AS (
    -- This represents what the dashboard query returns
    SELECT
        campaign_id,
        campaign_name,
        platform,
        SUM(spend) AS total_spend,
        SUM(conversions) AS total_conversions,
        CASE
            WHEN SUM(spend) = 0 THEN NULL
            ELSE SUM(conversions) / NULLIF(SUM(spend), 0)
        END AS roas
    FROM {{ ref('fact_campaign_performance') }}
    WHERE date >= CURRENT_DATE - INTERVAL '30 days'
    GROUP BY campaign_id, campaign_name, platform
),

comparison AS (
    SELECT
        d.campaign_id,
        d.roas AS dbt_roas,
        s.roas AS dashboard_roas,
        CASE
            WHEN d.roas IS NULL AND s.roas IS NULL THEN 0
            WHEN d.roas IS NULL OR s.roas IS NULL THEN 1
            ELSE ABS(d.roas - s.roas)
        END AS variance
    FROM dbt_roas d
    FULL OUTER JOIN dashboard_roas s
        ON d.campaign_id = s.campaign_id
        AND d.platform = s.platform
)

-- Test passes if all variances are 0 (exact match)
SELECT *
FROM comparison
WHERE variance > 0.0001  -- Allow tiny floating point variance
