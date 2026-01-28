-- AI Insights Explainability Schema Extension
-- Version: 1.1.0
-- Date: 2026-01-28
-- Story: 8.2 - Insight Explainability & Evidence
--
-- Adds explainability metadata to ai_insights table:
--   - why_it_matters: Business-friendly explanation of insight importance
--
-- SECURITY:
--   - No changes to tenant isolation
--   - No PII stored

-- =============================================================================
-- SCHEMA CHANGES
-- =============================================================================

-- Add why_it_matters column for explainability (Story 8.2)
ALTER TABLE ai_insights ADD COLUMN IF NOT EXISTS
    why_it_matters TEXT;

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON COLUMN ai_insights.why_it_matters IS
    'Business-friendly explanation of why this insight is important. Generated from templates. Story 8.2.';

-- =============================================================================
-- VERIFICATION
-- =============================================================================

-- Verify column was added
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'ai_insights'
        AND column_name = 'why_it_matters'
    ) THEN
        RAISE EXCEPTION 'Migration failed: why_it_matters column not created';
    END IF;

    RAISE NOTICE 'Story 8.2 migration completed successfully: why_it_matters column added';
END
$$;
