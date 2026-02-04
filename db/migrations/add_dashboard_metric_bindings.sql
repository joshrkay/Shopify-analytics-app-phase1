-- Migration: Add dashboard_metric_bindings table (Story 2.3)
-- Purpose: Tracks which dashboards bind to which metric versions,
--          supporting governed repoints, tenant-level pins, and rollback.
--
-- This table works alongside config/governance/consumers.yaml:
-- - consumers.yaml defines global defaults
-- - This table stores runtime overrides and tenant-level pins
-- - Resolution priority: tenant pin > global override > YAML default

CREATE TABLE IF NOT EXISTS dashboard_metric_bindings (
    id              VARCHAR(255) PRIMARY KEY,

    -- Binding scope
    dashboard_id    VARCHAR(255) NOT NULL,
    metric_name     VARCHAR(255) NOT NULL,
    metric_version  VARCHAR(50)  NOT NULL,

    -- Governance
    pinned_by       VARCHAR(255),
    pinned_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    reason          TEXT,

    -- Tenant scope: NULL = global default, set = tenant-level pin
    tenant_id       VARCHAR(255),

    -- Rollback support
    previous_version VARCHAR(50),

    -- Timestamps
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,

    -- Each dashboard+metric+tenant has exactly one binding
    CONSTRAINT uq_dashboard_metric_tenant_binding
        UNIQUE (dashboard_id, metric_name, tenant_id)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS ix_binding_dashboard_metric
    ON dashboard_metric_bindings (dashboard_id, metric_name);

CREATE INDEX IF NOT EXISTS ix_binding_tenant_dashboard
    ON dashboard_metric_bindings (tenant_id, dashboard_id);

CREATE INDEX IF NOT EXISTS ix_binding_metric_name
    ON dashboard_metric_bindings (metric_name);

-- RLS: Tenant-level pins are scoped to tenant_id
-- Global bindings (tenant_id IS NULL) are visible to admins only
-- This aligns with the existing RLS patterns in db/rls/

COMMENT ON TABLE dashboard_metric_bindings IS
    'Story 2.3: Tracks dashboard-to-metric-version bindings. '
    'Global defaults come from consumers.yaml; this table stores overrides.';

COMMENT ON COLUMN dashboard_metric_bindings.tenant_id IS
    'NULL = global default binding. Set = tenant-level pin override.';

COMMENT ON COLUMN dashboard_metric_bindings.previous_version IS
    'Previous metric_version before last repoint. Used for fast rollback.';
