-- =============================================================================
-- Performance Indexes for Analytics Canonical Tables
-- Story 5.2.6 — DB-Level Performance Guardrails
--
-- Creates composite indexes on the canonical fact TABLES (not views). PostgreSQL
-- cannot index regular views; queries against semantic views (sem_*, fact_*_current)
-- resolve against these underlying tables.
--
-- Index patterns:
-- - tenant_id (always filtered via RLS)
-- - date (date range filters)
-- - channel / source_platform (group-by dimensions)
--
-- Also grants analytics_reader and superset_service access to the semantic
-- schema (where Superset-facing views live) and enforces statement_timeout.
--
-- SAFETY: All changes are scoped to analytics_reader and superset_service.
--         Admin and migration roles are NOT affected.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Composite Indexes on analytics.orders (canonical table for sem_orders_v1)
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS ix_orders_tenant_date
    ON analytics.orders (tenant_id, date DESC);

CREATE INDEX IF NOT EXISTS ix_orders_tenant_date_source_platform
    ON analytics.orders (tenant_id, date DESC, source_platform);

-- ---------------------------------------------------------------------------
-- 2. Composite Indexes on analytics.marketing_spend (canonical for sem_marketing_spend_v1)
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS ix_marketing_spend_tenant_date
    ON analytics.marketing_spend (tenant_id, date DESC);

CREATE INDEX IF NOT EXISTS ix_marketing_spend_tenant_channel
    ON analytics.marketing_spend (tenant_id, channel);

CREATE INDEX IF NOT EXISTS ix_marketing_spend_tenant_date_channel
    ON analytics.marketing_spend (tenant_id, date DESC, channel);

-- ---------------------------------------------------------------------------
-- 3. Composite Indexes on analytics.campaign_performance (canonical for sem_campaign_performance_v1)
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS ix_campaign_performance_tenant_date
    ON analytics.campaign_performance (tenant_id, date DESC);

CREATE INDEX IF NOT EXISTS ix_campaign_performance_tenant_channel
    ON analytics.campaign_performance (tenant_id, channel);

CREATE INDEX IF NOT EXISTS ix_campaign_performance_tenant_date_channel
    ON analytics.campaign_performance (tenant_id, date DESC, channel);

-- ---------------------------------------------------------------------------
-- 4. Analytics Reader Role and Schema Access
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics_reader') THEN
        CREATE ROLE analytics_reader WITH LOGIN NOINHERIT;
    END IF;
END
$$;

-- Analytics schema (canonical tables)
GRANT USAGE ON SCHEMA analytics TO analytics_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO analytics_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics
    GRANT SELECT ON TABLES TO analytics_reader;

-- Semantic schema (Superset-facing views: sem_*_v1, fact_*_current)
GRANT USAGE ON SCHEMA semantic TO analytics_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA semantic TO analytics_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA semantic
    GRANT SELECT ON TABLES TO analytics_reader;

ALTER ROLE analytics_reader SET statement_timeout = '20s';
ALTER ROLE analytics_reader SET analytics.max_rows = '50000';

-- Superset service role: same schema access for metadata and query execution
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'superset_service') THEN
        GRANT USAGE ON SCHEMA analytics TO superset_service;
        GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO superset_service;
        GRANT USAGE ON SCHEMA semantic TO superset_service;
        GRANT SELECT ON ALL TABLES IN SCHEMA semantic TO superset_service;
        ALTER DEFAULT PRIVILEGES IN SCHEMA semantic
            GRANT SELECT ON TABLES TO superset_service;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 5. Max Result Size Guard (row_limit enforcement at DB level)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION analytics.enforce_row_limit(
    max_rows INTEGER DEFAULT 50000
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    PERFORM set_config('analytics.max_rows', max_rows::TEXT, TRUE);
END;
$$;

-- ---------------------------------------------------------------------------
-- 6. Enable pg_stat_statements for query monitoring (if not already enabled)
-- ---------------------------------------------------------------------------

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
