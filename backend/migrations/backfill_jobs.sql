-- Migration: Create historical_backfill_jobs table
-- Story 3.4 - Backfill Execution (chunk tracking)
-- Each row tracks one 7-day execution chunk of a HistoricalBackfillRequest.
-- Named historical_backfill_jobs to avoid conflict with DQ backfill_jobs table.

CREATE TABLE IF NOT EXISTS historical_backfill_jobs (
    id VARCHAR(255) PRIMARY KEY,
    backfill_request_id VARCHAR(255) NOT NULL,
    tenant_id VARCHAR(255) NOT NULL,
    source_system VARCHAR(50) NOT NULL,
    chunk_start_date DATE NOT NULL,
    chunk_end_date DATE NOT NULL,
    chunk_index INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    next_retry_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    rows_affected INTEGER,
    duration_seconds DOUBLE PRECISION,
    error_message TEXT,
    job_metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_hist_backfill_jobs_request_status
    ON historical_backfill_jobs(backfill_request_id, status);

CREATE INDEX IF NOT EXISTS idx_hist_backfill_jobs_tenant_status
    ON historical_backfill_jobs(tenant_id, status);

CREATE INDEX IF NOT EXISTS idx_hist_backfill_jobs_retry
    ON historical_backfill_jobs(status, next_retry_at);

-- Status constraint
ALTER TABLE historical_backfill_jobs
    ADD CONSTRAINT chk_hist_backfill_jobs_status
    CHECK (status IN ('queued', 'running', 'success', 'failed', 'cancelled', 'paused'));

-- Auto-update updated_at trigger
DROP TRIGGER IF EXISTS update_historical_backfill_jobs_updated_at ON historical_backfill_jobs;
CREATE TRIGGER update_historical_backfill_jobs_updated_at
    BEFORE UPDATE ON historical_backfill_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
