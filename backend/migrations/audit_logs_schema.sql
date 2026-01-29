-- Audit Logs Schema
-- Story 10.1 - Audit Event Schema & Logging Foundation
--
-- CRITICAL: This table is append-only. No UPDATE or DELETE operations are permitted.
-- Immutability is enforced via database trigger.

-- Create audit_logs table
CREATE TABLE IF NOT EXISTS audit_logs (
    -- Primary identifier (event_id in canonical schema)
    id VARCHAR(36) PRIMARY KEY,

    -- Tenant isolation (NEVER from client input, always from JWT)
    tenant_id VARCHAR(255) NOT NULL,

    -- Actor identification (NULL for system events)
    user_id VARCHAR(255),

    -- Event classification (event_type in canonical schema)
    action VARCHAR(100) NOT NULL,

    -- Timing
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Security context
    ip_address VARCHAR(45),  -- IPv6 compatible
    user_agent TEXT,

    -- Resource tracking
    resource_type VARCHAR(100),
    resource_id VARCHAR(255),

    -- Flexible payload (PII-redacted before storage)
    event_metadata JSONB NOT NULL DEFAULT '{}',

    -- Request tracing
    correlation_id VARCHAR(36) NOT NULL,

    -- Event source: api, worker, system, webhook
    source VARCHAR(50) NOT NULL DEFAULT 'api',

    -- Outcome tracking: success, failure, denied
    outcome VARCHAR(20) NOT NULL DEFAULT 'success',

    -- Error code if outcome is failure
    error_code VARCHAR(50)
);

-- Create indexes for common query patterns

-- Primary query: Recent logs by tenant
CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_timestamp
    ON audit_logs (tenant_id, timestamp DESC);

-- Query by action type within tenant
CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_action
    ON audit_logs (tenant_id, action);

-- User activity audit
CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_user
    ON audit_logs (tenant_id, user_id)
    WHERE user_id IS NOT NULL;

-- Request tracing
CREATE INDEX IF NOT EXISTS ix_audit_logs_correlation
    ON audit_logs (correlation_id);

-- Resource history
CREATE INDEX IF NOT EXISTS ix_audit_logs_resource
    ON audit_logs (tenant_id, resource_type, resource_id, timestamp DESC)
    WHERE resource_type IS NOT NULL;

-- Outcome filtering
CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_outcome
    ON audit_logs (tenant_id, outcome, timestamp DESC);

-- Immutability trigger (defense in depth)
-- Prevents UPDATE and DELETE operations at the database level
CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit logs are immutable. UPDATE and DELETE operations are not permitted.';
END;
$$ LANGUAGE plpgsql;

-- Drop existing trigger if it exists to allow re-running migration
DROP TRIGGER IF EXISTS audit_log_immutable ON audit_logs;

-- Create trigger to enforce immutability
CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_log_modification();

-- Add comments for documentation
COMMENT ON TABLE audit_logs IS
    'Immutable audit log for compliance and security tracking. Story 10.1.';
COMMENT ON COLUMN audit_logs.id IS
    'Unique event identifier (UUID).';
COMMENT ON COLUMN audit_logs.tenant_id IS
    'Tenant identifier from JWT org_id. NEVER from client input.';
COMMENT ON COLUMN audit_logs.user_id IS
    'Actor user ID. NULL for system-initiated events.';
COMMENT ON COLUMN audit_logs.action IS
    'Audit action type (e.g., auth.login, billing.plan_changed).';
COMMENT ON COLUMN audit_logs.event_metadata IS
    'Event-specific details. PII is automatically redacted before storage.';
COMMENT ON COLUMN audit_logs.correlation_id IS
    'Request trace ID for correlating events across services.';
COMMENT ON COLUMN audit_logs.source IS
    'Event origin: api, worker, system, or webhook.';
COMMENT ON COLUMN audit_logs.outcome IS
    'Action result: success, failure, or denied.';
