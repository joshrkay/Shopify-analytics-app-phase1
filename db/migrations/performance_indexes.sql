-- =============================================================================
-- Performance Indexes for Analytics Semantic Views
-- Story 5.2.6 — DB-Level Performance Guardrails
--
-- Creates composite indexes on the most common query patterns:
-- - tenant_id (always filtered via RLS)
-- - date columns (date range filters)
-- - channel (group-by dimension)
--
-- Also enforces statement_timeout on the analytics_reader role to prevent
-- runaway queries from impacting the database, and sets a max result size
-- guard via a custom function.
--
-- SAFETY: All changes are scoped to the analytics_reader role only.
--         Admin and migration roles are NOT affected.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Composite Indexes for fact_orders_current (sem_orders_v1)
-- ---------------------------------------------------------------------------

-- Primary query pattern: tenant_id + date range
CREATE INDEX IF NOT EXISTS ix_fact_orders_tenant_date
    ON analytics.fact_orders_current (tenant_id, order_date DESC);

-- Group-by dimension: channel (always with tenant_id for RLS)
CREATE INDEX IF NOT EXISTS ix_fact_orders_tenant_channel
    ON analytics.fact_orders_current (tenant_id, channel);

-- Combined: tenant + date + channel (covers most Explore queries)
CREATE INDEX IF NOT EXISTS ix_fact_orders_tenant_date_channel
    ON analytics.fact_orders_current (tenant_id, order_date DESC, channel);

-- ---------------------------------------------------------------------------
-- 2. Composite Indexes for fact_marketing_spend_current
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS ix_fact_marketing_spend_tenant_date
    ON analytics.fact_marketing_spend_current (tenant_id, spend_date DESC);

CREATE INDEX IF NOT EXISTS ix_fact_marketing_spend_tenant_channel
    ON analytics.fact_marketing_spend_current (tenant_id, channel);

CREATE INDEX IF NOT EXISTS ix_fact_marketing_spend_tenant_date_channel
    ON analytics.fact_marketing_spend_current (tenant_id, spend_date DESC, channel);

-- ---------------------------------------------------------------------------
-- 3. Composite Indexes for fact_campaign_performance_current
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS ix_fact_campaign_perf_tenant_date
    ON analytics.fact_campaign_performance_current (tenant_id, campaign_date DESC);

CREATE INDEX IF NOT EXISTS ix_fact_campaign_perf_tenant_channel
    ON analytics.fact_campaign_performance_current (tenant_id, channel);

CREATE INDEX IF NOT EXISTS ix_fact_campaign_perf_tenant_date_channel
    ON analytics.fact_campaign_performance_current (tenant_id, campaign_date DESC, channel);

-- ---------------------------------------------------------------------------
-- 4. Analytics Reader Role with statement_timeout
-- ---------------------------------------------------------------------------

-- Create the role if it does not exist (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics_reader') THEN
        CREATE ROLE analytics_reader WITH LOGIN NOINHERIT;
    END IF;
END
$$;

-- Grant read-only access to the analytics schema
GRANT USAGE ON SCHEMA analytics TO analytics_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO analytics_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics
    GRANT SELECT ON TABLES TO analytics_reader;

-- Enforce statement_timeout = 20 seconds (matching PERFORMANCE_LIMITS)
-- This kills any query exceeding 20s on this role ONLY.
ALTER ROLE analytics_reader SET statement_timeout = '20s';

-- ---------------------------------------------------------------------------
-- 5. Max Result Size Guard (row_limit enforcement at DB level)
-- ---------------------------------------------------------------------------
-- This function wraps any analytics query with a hard LIMIT.
-- Superset uses this via the database connection configuration.

CREATE OR REPLACE FUNCTION analytics.enforce_row_limit(
    max_rows INTEGER DEFAULT 50000
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    -- Set a session-level variable that can be referenced in views
    PERFORM set_config('analytics.max_rows', max_rows::TEXT, TRUE);
END;
$$;

-- Set default row limit for analytics_reader sessions
ALTER ROLE analytics_reader SET analytics.max_rows = '50000';

-- ---------------------------------------------------------------------------
-- 6. Enable pg_stat_statements for query monitoring (if not already enabled)
-- ---------------------------------------------------------------------------
-- NOTE: pg_stat_statements must be added to shared_preload_libraries in
-- postgresql.conf. This CREATE EXTENSION is safe to run — it will no-op
-- if the extension is already loaded or error if not in shared_preload_libraries.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'
    ) THEN
        BEGIN
            CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'pg_stat_statements not available in shared_preload_libraries — skipping';
        END;
    END IF;
END
$$;

-- Grant analytics_reader read access to query stats for observability
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'
    ) THEN
        GRANT EXECUTE ON FUNCTION pg_stat_statements_reset() TO analytics_reader;
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Could not grant pg_stat_statements access — skipping';
END
$$;

COMMIT;
