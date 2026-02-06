-- Migration: Create historical_backfill_requests table
-- Story 3.4 - Backfill Request API
-- Admin-initiated historical data backfill tracking

CREATE TABLE IF NOT EXISTS historical_backfill_requests (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    source_system VARCHAR(50) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    reason TEXT NOT NULL,
    requested_by VARCHAR(255) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_hist_backfill_tenant_id
    ON historical_backfill_requests(tenant_id);

CREATE INDEX IF NOT EXISTS idx_hist_backfill_status
    ON historical_backfill_requests(status);

CREATE INDEX IF NOT EXISTS idx_hist_backfill_tenant_source_status
    ON historical_backfill_requests(tenant_id, source_system, status);

CREATE INDEX IF NOT EXISTS idx_hist_backfill_tenant_created
    ON historical_backfill_requests(tenant_id, created_at);

-- Status constraint
ALTER TABLE historical_backfill_requests
    ADD CONSTRAINT chk_hist_backfill_status
    CHECK (status IN ('pending', 'approved', 'running', 'completed', 'failed', 'cancelled', 'rejected'));

-- Auto-update updated_at trigger
DROP TRIGGER IF EXISTS update_historical_backfill_requests_updated_at ON historical_backfill_requests;
CREATE TRIGGER update_historical_backfill_requests_updated_at
    BEFORE UPDATE ON historical_backfill_requests
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
