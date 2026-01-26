-- Ingestion Jobs Schema Migration
-- Version: 1.0.0
-- Date: 2026-01-26
--
-- This migration creates the ingestion jobs table for orchestrating Airbyte syncs.
-- Run this migration against PostgreSQL database.
--
-- Usage: psql $DATABASE_URL -f ingestion_jobs.sql

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- Job Status Enum
-- =============================================================================

-- Create enum type for job status if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'job_status') THEN
        CREATE TYPE job_status AS ENUM (
            'queued',
            'running',
            'failed',
            'dead_letter',
            'success'
        );
    END IF;
END$$;

-- =============================================================================
-- Ingestion Jobs Table
-- Tracks Airbyte sync job execution with tenant isolation
-- =============================================================================

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    -- Primary key
    job_id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Tenant isolation (CRITICAL: from JWT only, never from client input)
    tenant_id VARCHAR(255) NOT NULL,

    -- Connection identifiers
    connector_id VARCHAR(255) NOT NULL,
    external_account_id VARCHAR(255) NOT NULL,

    -- Status tracking
    status job_status NOT NULL DEFAULT 'queued',

    -- Retry tracking
    retry_count INTEGER NOT NULL DEFAULT 0,

    -- Airbyte integration
    run_id VARCHAR(255),

    -- Observability
    correlation_id VARCHAR(255),

    -- Error tracking
    error_message TEXT,
    error_code VARCHAR(50),

    -- Lifecycle timestamps
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    next_retry_at TIMESTAMP WITH TIME ZONE,

    -- Additional job metadata
    job_metadata JSONB DEFAULT '{}'::JSONB,

    -- Standard timestamps (from TimestampMixin)
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- Indexes for Performance and Isolation
-- =============================================================================

-- Index for tenant isolation queries
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_tenant_id
    ON ingestion_jobs(tenant_id);

-- Composite index for tenant-scoped status queries
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_tenant_status
    ON ingestion_jobs(tenant_id, status);

-- Composite index for tenant + connector queries
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_tenant_connector
    ON ingestion_jobs(tenant_id, connector_id);

-- Index for Airbyte run ID lookups
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_run_id
    ON ingestion_jobs(run_id)
    WHERE run_id IS NOT NULL;

-- Index for correlation ID tracing
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_correlation_id
    ON ingestion_jobs(correlation_id)
    WHERE correlation_id IS NOT NULL;

-- Index for error code filtering
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_error_code
    ON ingestion_jobs(error_code)
    WHERE error_code IS NOT NULL;

-- Index for finding jobs to retry
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_retry_pending
    ON ingestion_jobs(status, next_retry_at)
    WHERE status = 'failed' AND next_retry_at IS NOT NULL;

-- Index for dead letter queue queries
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_dlq
    ON ingestion_jobs(tenant_id, created_at DESC)
    WHERE status = 'dead_letter';

-- =============================================================================
-- CRITICAL: Partial Unique Index for Job Isolation
-- Only ONE active job (queued or running) per tenant + connector combination
-- =============================================================================

CREATE UNIQUE INDEX IF NOT EXISTS ix_ingestion_jobs_active_unique
    ON ingestion_jobs(tenant_id, connector_id)
    WHERE status IN ('queued', 'running');

-- =============================================================================
-- Trigger for updated_at
-- =============================================================================

-- Apply the existing update_updated_at_column trigger if it exists
DO $$
BEGIN
    -- Check if the function exists before creating trigger
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column') THEN
        -- Drop existing trigger if present
        DROP TRIGGER IF EXISTS update_ingestion_jobs_updated_at ON ingestion_jobs;

        -- Create trigger
        CREATE TRIGGER update_ingestion_jobs_updated_at
            BEFORE UPDATE ON ingestion_jobs
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END$$;

-- =============================================================================
-- Comments for Documentation
-- =============================================================================

COMMENT ON TABLE ingestion_jobs IS
    'Tracks Airbyte sync job execution with tenant isolation and retry logic';

COMMENT ON COLUMN ingestion_jobs.job_id IS
    'Primary key (UUID)';

COMMENT ON COLUMN ingestion_jobs.tenant_id IS
    'Tenant identifier from JWT org_id. NEVER from client input.';

COMMENT ON COLUMN ingestion_jobs.connector_id IS
    'Internal connector/connection ID (references tenant_airbyte_connections.id)';

COMMENT ON COLUMN ingestion_jobs.external_account_id IS
    'External platform account ID (e.g., Shopify shop ID)';

COMMENT ON COLUMN ingestion_jobs.status IS
    'Job status: queued (waiting), running (in progress), failed (retryable), dead_letter (exhausted retries), success (completed)';

COMMENT ON COLUMN ingestion_jobs.retry_count IS
    'Number of retry attempts (max 5 before dead letter)';

COMMENT ON COLUMN ingestion_jobs.run_id IS
    'Airbyte Cloud job run ID';

COMMENT ON COLUMN ingestion_jobs.correlation_id IS
    'Request correlation ID for distributed tracing';

COMMENT ON COLUMN ingestion_jobs.error_message IS
    'Last error message for failed/dead_letter jobs';

COMMENT ON COLUMN ingestion_jobs.error_code IS
    'Error classification: auth_error, rate_limit, server_error, timeout, connection, sync_failed, unknown';

COMMENT ON COLUMN ingestion_jobs.next_retry_at IS
    'Scheduled time for next retry attempt (only for failed status)';

COMMENT ON COLUMN ingestion_jobs.job_metadata IS
    'Additional job metadata: sync type, records_synced, bytes_synced, duration_seconds, requeued_from, etc.';

COMMENT ON INDEX ix_ingestion_jobs_active_unique IS
    'CRITICAL: Enforces only ONE active job per tenant + connector. Prevents concurrent syncs.';

-- =============================================================================
-- Migration Complete
-- =============================================================================

SELECT 'Ingestion jobs schema migration completed successfully' AS status;
