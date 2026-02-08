-- Migration: 0057_access_revocation
-- Version: 0057
-- Date: 2026-02-08
-- Story 5.5.4 - Grace-Period Access Removal

-- Ensure uuid-ossp extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create access_revocations table
CREATE TABLE IF NOT EXISTS access_revocations (
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::text,
    user_id VARCHAR(255) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id VARCHAR(255) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    revoked_by VARCHAR(255),
    revoked_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    grace_period_ends_at TIMESTAMP WITH TIME ZONE NOT NULL,
    grace_period_hours INTEGER NOT NULL DEFAULT 24,
    status VARCHAR(50) NOT NULL DEFAULT 'grace_period',
    expired_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE access_revocations IS 'Grace-period access revocation tracking (Story 5.5.4)';
COMMENT ON COLUMN access_revocations.grace_period_ends_at IS 'When access actually expires';
COMMENT ON COLUMN access_revocations.status IS 'grace_period | expired | cancelled';
COMMENT ON COLUMN access_revocations.expired_at IS 'When expiry was enforced by the worker';

-- Indexes
CREATE INDEX IF NOT EXISTS ix_access_revocations_user_id
    ON access_revocations(user_id);

CREATE INDEX IF NOT EXISTS ix_access_revocations_tenant_id
    ON access_revocations(tenant_id);

CREATE INDEX IF NOT EXISTS ix_access_revocations_status_ends
    ON access_revocations(status, grace_period_ends_at);

-- Partial unique: only one active grace_period per user-tenant pair
CREATE UNIQUE INDEX IF NOT EXISTS uq_access_revocation_active
    ON access_revocations(user_id, tenant_id)
    WHERE status = 'grace_period';

-- Updated_at trigger
CREATE OR REPLACE TRIGGER update_access_revocations_updated_at
    BEFORE UPDATE ON access_revocations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Verify
SELECT 'access_revocations' AS table_name, COUNT(*) AS row_count
FROM access_revocations;
