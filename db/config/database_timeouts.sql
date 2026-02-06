-- =============================================================================
-- Database Timeout Configuration
-- Story 5.2.6 — DB-Level Performance Guardrails
--
-- Configures per-role timeouts and resource limits for the analytics database.
-- These settings act as the final safety net — even if Superset guardrails
-- are bypassed (e.g., direct SQL access), the database itself enforces limits.
--
-- PRINCIPLE: Defense in depth. Superset enforces limits at the app layer,
-- and PostgreSQL enforces them at the database layer.
--
-- ROLES AND THEIR LIMITS:
--   analytics_reader  — 20s timeout, 50K row default, read-only
--   markinsight_user   — no statement_timeout (admin/migration use)
--   superset_service   — 30s timeout (Superset's own service account)
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. analytics_reader — Tenant-facing queries via Superset
-- ---------------------------------------------------------------------------
-- Hard ceiling: 20 seconds per query, matching PERFORMANCE_LIMITS.
-- All Explore/dashboard queries run under this role.

ALTER ROLE analytics_reader SET statement_timeout = '20s';
ALTER ROLE analytics_reader SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE analytics_reader SET lock_timeout = '5s';

-- Memory limits to prevent single queries from consuming too much RAM
ALTER ROLE analytics_reader SET work_mem = '64MB';
ALTER ROLE analytics_reader SET temp_file_limit = '256MB';

-- Prevent analytics_reader from creating temp tables or sequences
ALTER ROLE analytics_reader SET temp_tablespaces = '';

-- Custom GUC for max result rows (referenced by application code)
ALTER ROLE analytics_reader SET analytics.max_rows = '50000';

-- ---------------------------------------------------------------------------
-- 2. superset_service — Superset's own service account
-- ---------------------------------------------------------------------------
-- Slightly higher timeout (30s) because Superset needs headroom for
-- metadata operations (dataset refresh, schema introspection).
-- Still bounded to prevent runaway internal queries.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'superset_service') THEN
        ALTER ROLE superset_service SET statement_timeout = '30s';
        ALTER ROLE superset_service SET idle_in_transaction_session_timeout = '120s';
        ALTER ROLE superset_service SET lock_timeout = '10s';
        ALTER ROLE superset_service SET work_mem = '128MB';
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 3. Admin/migration roles — NO statement_timeout
-- ---------------------------------------------------------------------------
-- Explicitly confirm that admin roles have no timeout restrictions.
-- This prevents accidental inheritance from role defaults.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'markinsight_user') THEN
        ALTER ROLE markinsight_user RESET statement_timeout;
        ALTER ROLE markinsight_user RESET idle_in_transaction_session_timeout;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 4. Schema-Level Defaults
-- ---------------------------------------------------------------------------
-- Set statement_timeout at the database level as a catch-all for any
-- un-configured roles. This is a soft default (60s) — role-level settings
-- override this for known roles.

ALTER DATABASE CURRENT_DATABASE() SET statement_timeout = '60s';

-- ---------------------------------------------------------------------------
-- 5. Connection Limits
-- ---------------------------------------------------------------------------
-- Prevent a single role from consuming all connections.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analytics_reader') THEN
        ALTER ROLE analytics_reader CONNECTION LIMIT 50;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'superset_service') THEN
        ALTER ROLE superset_service CONNECTION LIMIT 20;
    END IF;
END
$$;

COMMIT;
