-- Root Cause Signals Schema Migration
-- Story 4.2 - Data Quality Root Cause Signals
--
-- Stores ranked root cause hypotheses for data quality anomalies.
-- Each row represents a single analysis run, with hypotheses stored as JSONB.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS root_cause_signals (
    id              VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    tenant_id       VARCHAR(255) NOT NULL,
    dataset         VARCHAR(255) NOT NULL,
    connector_id    VARCHAR(255),
    correlation_id  VARCHAR(255),
    anomaly_type    VARCHAR(100) NOT NULL,
    detected_at     TIMESTAMP WITH TIME ZONE NOT NULL,
    hypotheses      JSONB NOT NULL DEFAULT '[]'::JSONB,
    top_cause_type  VARCHAR(50),
    top_confidence  DECIMAL(4,3),
    hypothesis_count INTEGER NOT NULL DEFAULT 0,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Tenant-scoped queries
CREATE INDEX IF NOT EXISTS ix_root_cause_signals_tenant_id
    ON root_cause_signals(tenant_id);

-- Tenant + dataset composite
CREATE INDEX IF NOT EXISTS ix_root_cause_signals_tenant_dataset
    ON root_cause_signals(tenant_id, dataset);

-- Time-range queries
CREATE INDEX IF NOT EXISTS ix_root_cause_signals_detected_at
    ON root_cause_signals(detected_at);

-- Correlation tracing
CREATE INDEX IF NOT EXISTS ix_root_cause_signals_correlation
    ON root_cause_signals(correlation_id);

-- Active signals for a tenant
CREATE INDEX IF NOT EXISTS ix_root_cause_signals_active
    ON root_cause_signals(tenant_id, is_active);

-- Cleanup / retention queries
CREATE INDEX IF NOT EXISTS ix_root_cause_signals_cleanup
    ON root_cause_signals(tenant_id, detected_at DESC);

-- Auto-update updated_at timestamp
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column') THEN
        DROP TRIGGER IF EXISTS update_root_cause_signals_updated_at ON root_cause_signals;
        CREATE TRIGGER update_root_cause_signals_updated_at
            BEFORE UPDATE ON root_cause_signals
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END$$;

COMMENT ON TABLE root_cause_signals IS
    'Root cause hypotheses for data quality anomalies. Story 4.2.';
COMMENT ON COLUMN root_cause_signals.tenant_id IS
    'Tenant identifier from JWT org_id. NEVER from client input.';
COMMENT ON COLUMN root_cause_signals.hypotheses IS
    'JSON array of {cause_type, confidence_score, evidence, first_seen_at, suggested_next_step}';
COMMENT ON COLUMN root_cause_signals.top_cause_type IS
    'Denormalized: cause_type of highest-confidence hypothesis for efficient filtering.';
COMMENT ON COLUMN root_cause_signals.top_confidence IS
    'Denormalized: confidence score of highest-confidence hypothesis (0.000 - 1.000).';
