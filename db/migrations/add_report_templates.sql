-- Migration: Add report_templates table
-- Purpose: System-defined report templates for the template gallery.
--          Templates use abstract chart types that get mapped to
--          Superset viz_type plugins at instantiation time.
-- Phase 2C - Template System Backend

CREATE TABLE IF NOT EXISTS report_templates (
    id                VARCHAR(255) PRIMARY KEY,

    -- Template metadata
    name              VARCHAR(255) NOT NULL,
    description       TEXT,
    category          VARCHAR(50)  NOT NULL,
    thumbnail_url     VARCHAR(500),

    -- Billing
    min_billing_tier  VARCHAR(50)  NOT NULL DEFAULT 'free',

    -- State
    is_active         BOOLEAN      NOT NULL DEFAULT TRUE,

    -- Template config (abstract chart types, report definitions)
    config_json       JSONB        NOT NULL,

    -- Versioning
    version           INTEGER      NOT NULL DEFAULT 1,

    -- Timestamps
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at        TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS ix_report_template_category
    ON report_templates (category);

CREATE INDEX IF NOT EXISTS ix_report_template_is_active
    ON report_templates (is_active);

CREATE INDEX IF NOT EXISTS ix_report_template_active_category
    ON report_templates (is_active, category);
