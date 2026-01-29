-- Add Configuration Column to tenant_airbyte_connections
-- Version: 1.0.0
-- Date: 2026-01-29
--
-- This migration adds the configuration JSONB column to tenant_airbyte_connections
-- which stores source-specific metadata (e.g., shop_domain for Shopify connections).
-- Required for secure multi-tenant data isolation via shop_domain joins.
--
-- Usage: psql $DATABASE_URL -f add_configuration_column.sql

-- =============================================================================
-- Add configuration column if it doesn't exist
-- =============================================================================

DO $$
BEGIN
    -- Add configuration column if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'platform'
        AND table_name = 'tenant_airbyte_connections'
        AND column_name = 'configuration'
    ) THEN
        ALTER TABLE platform.tenant_airbyte_connections
        ADD COLUMN configuration JSONB DEFAULT '{}'::jsonb;

        COMMENT ON COLUMN platform.tenant_airbyte_connections.configuration IS
            'Non-sensitive connection configuration metadata (e.g., shop_domain for Shopify)';

        RAISE NOTICE 'Added configuration column to tenant_airbyte_connections';
    ELSE
        RAISE NOTICE 'configuration column already exists';
    END IF;

    -- Add connection_name column if missing (for consistency)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'platform'
        AND table_name = 'tenant_airbyte_connections'
        AND column_name = 'connection_name'
    ) THEN
        ALTER TABLE platform.tenant_airbyte_connections
        ADD COLUMN connection_name VARCHAR(255);

        RAISE NOTICE 'Added connection_name column to tenant_airbyte_connections';
    ELSE
        RAISE NOTICE 'connection_name column already exists';
    END IF;
END$$;

-- =============================================================================
-- Backfill shop_domain for existing Shopify connections (if data available)
-- =============================================================================

-- Note: This requires manual backfill if shop_domain wasn't previously stored.
-- Run this query to identify connections needing backfill:
--
-- SELECT id, tenant_id, airbyte_connection_id, source_type, configuration
-- FROM platform.tenant_airbyte_connections
-- WHERE source_type IN ('shopify', 'source-shopify')
--   AND (configuration->>'shop_domain' IS NULL OR configuration->>'shop_domain' = '');

-- =============================================================================
-- Migration Complete
-- =============================================================================

SELECT 'Configuration column migration completed successfully' AS status;
