-- Data Availability State Machine Schema
-- Version: 1.0.0
-- Date: 2026-02-05
--
-- Stores the latest computed availability state per tenant + source.
-- States: fresh, stale, unavailable
-- State is computed by DataAvailabilityService, never set manually.
--
-- Usage: psql $DATABASE_URL -f data_availability.sql

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- Table: data_availability
-- One row per (tenant_id, source_type). Upserted on each evaluation.
-- =============================================================================

CREATE TABLE IF NOT EXISTS data_availability (
    -- Primary key
    id              VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Tenant isolation (CRITICAL: from JWT only)
    tenant_id       VARCHAR(255) NOT NULL,

    -- Source identification (SLA config key, e.g. shopify_orders)
    source_type     VARCHAR(100) NOT NULL,

    -- Computed state
    state           VARCHAR(20)  NOT NULL,
    reason          VARCHAR(50)  NOT NULL,

    -- Thresholds captured at evaluation time
    warn_threshold_minutes  INTEGER NOT NULL,
    error_threshold_minutes INTEGER NOT NULL,

    -- Sync metadata
    last_sync_at     TIMESTAMP WITH TIME ZONE,
    last_sync_status VARCHAR(50),
    minutes_since_sync INTEGER,

    -- State transition tracking
    state_changed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    previous_state   VARCHAR(20),

    -- Evaluation metadata
    evaluated_at     TIMESTAMP WITH TIME ZONE NOT NULL,
    billing_tier     VARCHAR(50) NOT NULL DEFAULT 'free',

    -- Standard timestamps
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- One row per tenant + source (upsert target)
CREATE UNIQUE INDEX IF NOT EXISTS ix_data_availability_tenant_source
    ON data_availability(tenant_id, source_type);

-- Query by state across tenants (ops dashboard)
CREATE INDEX IF NOT EXISTS ix_data_availability_state
    ON data_availability(state);

-- Query all sources for a tenant filtered by state
CREATE INDEX IF NOT EXISTS ix_data_availability_tenant_state
    ON data_availability(tenant_id, state);

-- Tenant isolation index
CREATE INDEX IF NOT EXISTS ix_data_availability_tenant_id
    ON data_availability(tenant_id);

COMMENT ON TABLE data_availability IS
    'Computed availability state per tenant and ingestion source. '
    'States: fresh (within SLA), stale (SLA exceeded, within grace), '
    'unavailable (grace exceeded or sync failed). '
    'Updated by DataAvailabilityService.evaluate().';
