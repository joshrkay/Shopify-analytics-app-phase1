-- Data Quality Schema Migration
-- Version: 1.0.0
-- Date: 2026-01-27
--
-- This migration creates tables for data quality monitoring:
-- - dq_checks: Check definitions and thresholds
-- - dq_results: Per-run results for each check
-- - dq_incidents: Severe failures and blocks
-- - sync_runs: Sync run tracking with metrics
--
-- Retention: 13 months automated cleanup
--
-- Usage: psql $DATABASE_URL -f dq_schema.sql

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- Enums
-- =============================================================================

-- Check type enum
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'dq_check_type') THEN
        CREATE TYPE dq_check_type AS ENUM (
            'freshness',
            'row_count_drop',
            'zero_spend',
            'zero_orders',
            'missing_days',
            'negative_values',
            'duplicate_primary_key'
        );
    END IF;
END$$;

-- Severity enum
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'dq_severity') THEN
        CREATE TYPE dq_severity AS ENUM (
            'warning',
            'high',
            'critical'
        );
    END IF;
END$$;

-- Result status enum
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'dq_result_status') THEN
        CREATE TYPE dq_result_status AS ENUM (
            'passed',
            'failed',
            'skipped',
            'error'
        );
    END IF;
END$$;

-- Incident status enum
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'dq_incident_status') THEN
        CREATE TYPE dq_incident_status AS ENUM (
            'open',
            'acknowledged',
            'resolved',
            'auto_resolved'
        );
    END IF;
END$$;

-- Sync run status enum
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sync_run_status') THEN
        CREATE TYPE sync_run_status AS ENUM (
            'running',
            'success',
            'failed',
            'cancelled'
        );
    END IF;
END$$;

-- Source type enum for freshness SLAs
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'connector_source_type') THEN
        CREATE TYPE connector_source_type AS ENUM (
            'shopify_orders',
            'shopify_refunds',
            'recharge',
            'meta_ads',
            'google_ads',
            'tiktok_ads',
            'pinterest_ads',
            'snap_ads',
            'amazon_ads',
            'klaviyo',
            'postscript',
            'attentive',
            'ga4'
        );
    END IF;
END$$;

-- =============================================================================
-- DQ Checks Table (definitions)
-- Stores check configurations and thresholds
-- =============================================================================

CREATE TABLE IF NOT EXISTS dq_checks (
    -- Primary key
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Check identification
    check_name VARCHAR(255) NOT NULL,
    check_type dq_check_type NOT NULL,

    -- Source type for freshness SLAs
    source_type connector_source_type,

    -- Threshold configuration (in minutes for freshness)
    warning_threshold INTEGER,
    high_threshold INTEGER,
    critical_threshold INTEGER,

    -- For anomaly checks: percentage threshold (e.g., 50 for 50% drop)
    anomaly_threshold_percent DECIMAL(5,2),

    -- Check behavior
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    is_blocking BOOLEAN NOT NULL DEFAULT false,

    -- Description and documentation
    description TEXT,
    merchant_message TEXT,
    support_message TEXT,

    -- Recommended actions for merchants
    recommended_actions JSONB DEFAULT '[]'::JSONB,

    -- Standard timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Unique constraint on check_name + source_type
CREATE UNIQUE INDEX IF NOT EXISTS ix_dq_checks_name_source
    ON dq_checks(check_name, source_type) WHERE source_type IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ix_dq_checks_name_global
    ON dq_checks(check_name) WHERE source_type IS NULL;

-- Index for enabled checks
CREATE INDEX IF NOT EXISTS ix_dq_checks_enabled
    ON dq_checks(is_enabled) WHERE is_enabled = true;

-- =============================================================================
-- DQ Results Table (per run/per tenant/per connector)
-- Stores individual check execution results
-- =============================================================================

CREATE TABLE IF NOT EXISTS dq_results (
    -- Primary key
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Foreign keys
    check_id VARCHAR(255) NOT NULL REFERENCES dq_checks(id),

    -- Tenant isolation (CRITICAL: from JWT only)
    tenant_id VARCHAR(255) NOT NULL,

    -- Connector reference
    connector_id VARCHAR(255) NOT NULL,

    -- Run identification
    run_id VARCHAR(255) NOT NULL,
    correlation_id VARCHAR(255),

    -- Result data
    status dq_result_status NOT NULL,
    severity dq_severity,

    -- Observed values
    observed_value DECIMAL(20,4),
    expected_value DECIMAL(20,4),
    threshold_value DECIMAL(20,4),

    -- For freshness: minutes since last sync
    minutes_since_sync INTEGER,

    -- Messages
    message TEXT,
    merchant_message TEXT,
    support_details TEXT,

    -- Additional context
    context_metadata JSONB DEFAULT '{}'::JSONB,

    -- Standard timestamps
    executed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS ix_dq_results_tenant_id
    ON dq_results(tenant_id);

CREATE INDEX IF NOT EXISTS ix_dq_results_tenant_connector
    ON dq_results(tenant_id, connector_id);

CREATE INDEX IF NOT EXISTS ix_dq_results_run_id
    ON dq_results(run_id);

CREATE INDEX IF NOT EXISTS ix_dq_results_status
    ON dq_results(status) WHERE status = 'failed';

CREATE INDEX IF NOT EXISTS ix_dq_results_severity
    ON dq_results(severity) WHERE severity IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_dq_results_executed_at
    ON dq_results(executed_at);

-- Composite index for retention cleanup
CREATE INDEX IF NOT EXISTS ix_dq_results_cleanup
    ON dq_results(tenant_id, executed_at DESC);

-- =============================================================================
-- DQ Incidents Table (severe failures & rollback references)
-- Tracks critical issues that may block dashboards
-- =============================================================================

CREATE TABLE IF NOT EXISTS dq_incidents (
    -- Primary key
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Tenant isolation
    tenant_id VARCHAR(255) NOT NULL,

    -- Connector reference
    connector_id VARCHAR(255) NOT NULL,

    -- Related check and result
    check_id VARCHAR(255) NOT NULL REFERENCES dq_checks(id),
    result_id VARCHAR(255) REFERENCES dq_results(id),

    -- Run identification
    run_id VARCHAR(255),
    correlation_id VARCHAR(255),

    -- Incident details
    severity dq_severity NOT NULL,
    status dq_incident_status NOT NULL DEFAULT 'open',
    is_blocking BOOLEAN NOT NULL DEFAULT false,

    -- Description
    title VARCHAR(500) NOT NULL,
    description TEXT,

    -- Messages for different audiences
    merchant_message TEXT,
    support_details TEXT,

    -- Recommended actions
    recommended_actions JSONB DEFAULT '[]'::JSONB,

    -- Resolution tracking
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    acknowledged_by VARCHAR(255),
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by VARCHAR(255),
    resolution_notes TEXT,

    -- Standard timestamps
    opened_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for incidents
CREATE INDEX IF NOT EXISTS ix_dq_incidents_tenant_id
    ON dq_incidents(tenant_id);

CREATE INDEX IF NOT EXISTS ix_dq_incidents_tenant_connector
    ON dq_incidents(tenant_id, connector_id);

CREATE INDEX IF NOT EXISTS ix_dq_incidents_status
    ON dq_incidents(status) WHERE status IN ('open', 'acknowledged');

CREATE INDEX IF NOT EXISTS ix_dq_incidents_blocking
    ON dq_incidents(tenant_id, is_blocking) WHERE is_blocking = true;

CREATE INDEX IF NOT EXISTS ix_dq_incidents_severity
    ON dq_incidents(severity);

CREATE INDEX IF NOT EXISTS ix_dq_incidents_opened_at
    ON dq_incidents(opened_at);

-- Composite index for cleanup
CREATE INDEX IF NOT EXISTS ix_dq_incidents_cleanup
    ON dq_incidents(tenant_id, opened_at DESC);

-- =============================================================================
-- Sync Runs Table (if not already present)
-- Tracks individual sync executions with metrics
-- =============================================================================

CREATE TABLE IF NOT EXISTS sync_runs (
    -- Primary key
    run_id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Tenant isolation
    tenant_id VARCHAR(255) NOT NULL,

    -- Connector reference
    connector_id VARCHAR(255) NOT NULL,

    -- Run details
    status sync_run_status NOT NULL DEFAULT 'running',
    source_type connector_source_type,

    -- Timestamps
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Metrics
    rows_synced INTEGER,
    rows_updated INTEGER,
    rows_deleted INTEGER,
    bytes_synced BIGINT,
    duration_seconds DECIMAL(10,2),

    -- Error tracking
    error_message TEXT,
    error_code VARCHAR(50),

    -- Additional metadata
    run_metadata JSONB DEFAULT '{}'::JSONB,

    -- Standard timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for sync_runs
CREATE INDEX IF NOT EXISTS ix_sync_runs_tenant_id
    ON sync_runs(tenant_id);

CREATE INDEX IF NOT EXISTS ix_sync_runs_tenant_connector
    ON sync_runs(tenant_id, connector_id);

CREATE INDEX IF NOT EXISTS ix_sync_runs_status
    ON sync_runs(status);

CREATE INDEX IF NOT EXISTS ix_sync_runs_started_at
    ON sync_runs(started_at);

CREATE INDEX IF NOT EXISTS ix_sync_runs_source_type
    ON sync_runs(source_type);

-- Composite index for cleanup
CREATE INDEX IF NOT EXISTS ix_sync_runs_cleanup
    ON sync_runs(tenant_id, started_at DESC);

-- =============================================================================
-- Backfill Jobs Table
-- Tracks merchant-triggered backfill requests
-- =============================================================================

CREATE TABLE IF NOT EXISTS backfill_jobs (
    -- Primary key
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Tenant isolation
    tenant_id VARCHAR(255) NOT NULL,

    -- Connector reference
    connector_id VARCHAR(255) NOT NULL,

    -- Date range
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,

    -- Job status
    status VARCHAR(50) NOT NULL DEFAULT 'queued',

    -- Requesting user
    requested_by VARCHAR(255) NOT NULL,

    -- Execution tracking
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Results
    rows_backfilled INTEGER,
    error_message TEXT,

    -- Standard timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Partial unique index: only one active backfill per connector per tenant
CREATE UNIQUE INDEX IF NOT EXISTS ix_backfill_jobs_active_unique
    ON backfill_jobs(tenant_id, connector_id)
    WHERE status IN ('queued', 'running');

-- Indexes
CREATE INDEX IF NOT EXISTS ix_backfill_jobs_tenant_id
    ON backfill_jobs(tenant_id);

CREATE INDEX IF NOT EXISTS ix_backfill_jobs_tenant_connector
    ON backfill_jobs(tenant_id, connector_id);

CREATE INDEX IF NOT EXISTS ix_backfill_jobs_status
    ON backfill_jobs(status) WHERE status IN ('queued', 'running');

-- =============================================================================
-- Triggers for updated_at
-- =============================================================================

-- Apply update_updated_at_column trigger if function exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column') THEN
        -- dq_checks
        DROP TRIGGER IF EXISTS update_dq_checks_updated_at ON dq_checks;
        CREATE TRIGGER update_dq_checks_updated_at
            BEFORE UPDATE ON dq_checks
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

        -- dq_incidents
        DROP TRIGGER IF EXISTS update_dq_incidents_updated_at ON dq_incidents;
        CREATE TRIGGER update_dq_incidents_updated_at
            BEFORE UPDATE ON dq_incidents
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

        -- sync_runs
        DROP TRIGGER IF EXISTS update_sync_runs_updated_at ON sync_runs;
        CREATE TRIGGER update_sync_runs_updated_at
            BEFORE UPDATE ON sync_runs
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

        -- backfill_jobs
        DROP TRIGGER IF EXISTS update_backfill_jobs_updated_at ON backfill_jobs;
        CREATE TRIGGER update_backfill_jobs_updated_at
            BEFORE UPDATE ON backfill_jobs
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END$$;

-- =============================================================================
-- Seed Default DQ Check Definitions
-- =============================================================================

-- Freshness checks for each source type with appropriate SLAs
INSERT INTO dq_checks (check_name, check_type, source_type, warning_threshold, high_threshold, critical_threshold, description, merchant_message, support_message, recommended_actions)
VALUES
    -- Shopify orders/refunds: stale if > 2 hours
    ('freshness_shopify_orders', 'freshness', 'shopify_orders', 120, 240, 480,
     'Checks Shopify orders data freshness (stale if > 2 hours)',
     'Your Shopify orders data may be delayed. Recent orders might not appear in reports yet.',
     'Shopify orders sync is stale. Check Airbyte connection status and API rate limits.',
     '["Retry sync", "Check Shopify connection", "Contact support if issue persists"]'),

    ('freshness_shopify_refunds', 'freshness', 'shopify_refunds', 120, 240, 480,
     'Checks Shopify refunds data freshness (stale if > 2 hours)',
     'Your Shopify refunds data may be delayed.',
     'Shopify refunds sync is stale. Check Airbyte connection status.',
     '["Retry sync", "Check Shopify connection"]'),

    -- Recharge: stale if > 2 hours
    ('freshness_recharge', 'freshness', 'recharge', 120, 240, 480,
     'Checks Recharge subscription data freshness (stale if > 2 hours)',
     'Your Recharge subscription data may be delayed.',
     'Recharge sync is stale. Verify API credentials and connection.',
     '["Retry sync", "Reconnect Recharge"]'),

    -- Ads: stale if > 24 hours
    ('freshness_meta_ads', 'freshness', 'meta_ads', 1440, 2880, 5760,
     'Checks Meta Ads data freshness (stale if > 24 hours)',
     'Your Meta Ads data may be delayed. Recent ad performance might not be reflected.',
     'Meta Ads sync is stale. Check API access and rate limits.',
     '["Retry sync", "Reconnect Meta Ads", "Check ad account permissions"]'),

    ('freshness_google_ads', 'freshness', 'google_ads', 1440, 2880, 5760,
     'Checks Google Ads data freshness (stale if > 24 hours)',
     'Your Google Ads data may be delayed.',
     'Google Ads sync is stale. Check OAuth token and API quotas.',
     '["Retry sync", "Reconnect Google Ads"]'),

    ('freshness_tiktok_ads', 'freshness', 'tiktok_ads', 1440, 2880, 5760,
     'Checks TikTok Ads data freshness (stale if > 24 hours)',
     'Your TikTok Ads data may be delayed.',
     'TikTok Ads sync is stale.',
     '["Retry sync", "Reconnect TikTok Ads"]'),

    ('freshness_pinterest_ads', 'freshness', 'pinterest_ads', 1440, 2880, 5760,
     'Checks Pinterest Ads data freshness (stale if > 24 hours)',
     'Your Pinterest Ads data may be delayed.',
     'Pinterest Ads sync is stale.',
     '["Retry sync", "Reconnect Pinterest Ads"]'),

    ('freshness_snap_ads', 'freshness', 'snap_ads', 1440, 2880, 5760,
     'Checks Snap Ads data freshness (stale if > 24 hours)',
     'Your Snap Ads data may be delayed.',
     'Snap Ads sync is stale.',
     '["Retry sync", "Reconnect Snap Ads"]'),

    ('freshness_amazon_ads', 'freshness', 'amazon_ads', 1440, 2880, 5760,
     'Checks Amazon Ads data freshness (stale if > 24 hours)',
     'Your Amazon Ads data may be delayed.',
     'Amazon Ads sync is stale.',
     '["Retry sync", "Reconnect Amazon Ads"]'),

    -- Klaviyo + SMS: stale if > 24 hours
    ('freshness_klaviyo', 'freshness', 'klaviyo', 1440, 2880, 5760,
     'Checks Klaviyo data freshness (stale if > 24 hours)',
     'Your Klaviyo email marketing data may be delayed.',
     'Klaviyo sync is stale. Check API key.',
     '["Retry sync", "Reconnect Klaviyo"]'),

    ('freshness_postscript', 'freshness', 'postscript', 1440, 2880, 5760,
     'Checks Postscript SMS data freshness (stale if > 24 hours)',
     'Your Postscript SMS data may be delayed.',
     'Postscript sync is stale.',
     '["Retry sync", "Reconnect Postscript"]'),

    ('freshness_attentive', 'freshness', 'attentive', 1440, 2880, 5760,
     'Checks Attentive SMS data freshness (stale if > 24 hours)',
     'Your Attentive SMS data may be delayed.',
     'Attentive sync is stale.',
     '["Retry sync", "Reconnect Attentive"]'),

    -- GA4: stale if > 24 hours
    ('freshness_ga4', 'freshness', 'ga4', 1440, 2880, 5760,
     'Checks GA4 data freshness (stale if > 24 hours)',
     'Your Google Analytics data may be delayed.',
     'GA4 sync is stale. Check service account permissions.',
     '["Retry sync", "Reconnect GA4"]')
ON CONFLICT DO NOTHING;

-- Anomaly checks (global, not source-specific)
INSERT INTO dq_checks (check_name, check_type, anomaly_threshold_percent, description, merchant_message, support_message, recommended_actions)
VALUES
    ('row_count_drop', 'row_count_drop', 50.00,
     'Detects when row count drops >= 50% day-over-day',
     'We noticed a significant drop in data volume. This may indicate a sync issue.',
     'Row count dropped >= 50% DoD. Investigate potential data loss or API changes.',
     '["Verify source data", "Run backfill", "Contact support"]'),

    ('zero_spend', 'zero_spend', NULL,
     'Detects when ad spend becomes zero when previously non-zero',
     'Your ad spend is showing as zero. This may indicate a connection issue with your ad platform.',
     'Zero spend detected when previously non-zero. Check ad account status and API permissions.',
     '["Check ad account status", "Reconnect ad platform", "Verify billing"]'),

    ('zero_orders', 'zero_orders', NULL,
     'Detects when orders become zero when previously non-zero',
     'No orders detected. This may indicate a sync issue with Shopify.',
     'Zero orders detected when previously non-zero. Check Shopify connection.',
     '["Check Shopify connection", "Retry sync", "Verify store status"]'),

    ('missing_days', 'missing_days', NULL,
     'Detects missing days in time series data',
     'Some days are missing from your data. Reports may be incomplete.',
     'Missing days detected in time series. Run backfill for affected dates.',
     '["Run backfill for missing dates", "Verify sync schedule"]'),

    ('negative_values', 'negative_values', NULL,
     'Detects negative values where not allowed (revenue, spend, etc.)',
     'Unexpected negative values detected in your data.',
     'Negative values found in fields that should be positive. Investigate data quality.',
     '["Review source data", "Contact support"]'),

    ('duplicate_primary_key', 'duplicate_primary_key', NULL,
     'Detects duplicate primary keys in data',
     'Duplicate records detected. This may cause inaccurate reporting.',
     'Duplicate primary keys found. Check for sync or transformation issues.',
     '["Investigate duplicates", "Run deduplication", "Contact support"]')
ON CONFLICT DO NOTHING;

-- =============================================================================
-- Comments for Documentation
-- =============================================================================

COMMENT ON TABLE dq_checks IS
    'Data quality check definitions with configurable thresholds per source type';

COMMENT ON TABLE dq_results IS
    'Per-run data quality check results. Retained for 13 months.';

COMMENT ON TABLE dq_incidents IS
    'Severe DQ failures that may block dashboards. Tracks acknowledgment and resolution.';

COMMENT ON TABLE sync_runs IS
    'Individual sync run tracking with metrics. Retained for 13 months.';

COMMENT ON TABLE backfill_jobs IS
    'Merchant-triggered backfill requests. Max 90 days for merchants.';

COMMENT ON COLUMN dq_results.tenant_id IS
    'Tenant identifier from JWT org_id. NEVER from client input.';

COMMENT ON COLUMN dq_incidents.tenant_id IS
    'Tenant identifier from JWT org_id. NEVER from client input.';

COMMENT ON COLUMN sync_runs.tenant_id IS
    'Tenant identifier from JWT org_id. NEVER from client input.';

COMMENT ON COLUMN backfill_jobs.tenant_id IS
    'Tenant identifier from JWT org_id. NEVER from client input.';

-- =============================================================================
-- Migration Complete
-- =============================================================================

SELECT 'Data quality schema migration completed successfully' AS status;
