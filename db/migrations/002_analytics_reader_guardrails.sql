-- =============================================================================
-- Analytics Reader Role — Statement Timeout and Row Limit (Story 5.2)
--
-- Ensures analytics_reader role exists and has DB-level performance guardrails.
-- Scoped strictly to analytics_reader; admin/migration roles are unaffected.
--
-- Run after 000_create_superset_db and schema creation. Idempotent.
-- =============================================================================

BEGIN;

-- Create role if not present
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics_reader') THEN
        CREATE ROLE analytics_reader WITH LOGIN NOINHERIT;
    END IF;
END
$$;

-- Enforce 20s statement timeout (matches Superset PERFORMANCE_LIMITS)
ALTER ROLE analytics_reader SET statement_timeout = '20s';

-- Optional: row limit GUC for application use
ALTER ROLE analytics_reader SET analytics.max_rows = '50000';

COMMIT;
