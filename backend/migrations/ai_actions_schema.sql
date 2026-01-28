-- AI Actions Schema
-- Version: 1.0.0
-- Date: 2026-01-28
-- Story: 8.5 - Action Execution (Scoped & Reversible)
--
-- Creates tables for:
--   - ai_actions: Stores executable actions derived from recommendations
--   - action_execution_logs: Detailed audit trail of all execution events
--   - action_jobs: Tracks action execution job processing
--
-- SECURITY:
--   - tenant_id column on all tables for tenant isolation
--   - RLS policies should be applied separately if needed
--   - No PII stored - actions reference campaign/entity IDs only
--
-- PRINCIPLES:
--   - External platform is source of truth
--   - No blind retries on failure
--   - Full auditability (request, response, before_state, after_state)
--   - Rollback support for all executed actions

-- Ensure uuid-ossp extension is available
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- ENUM TYPES
-- =============================================================================

-- Types of actions the system can execute
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'action_type') THEN
        CREATE TYPE action_type AS ENUM (
            'pause_campaign',
            'resume_campaign',
            'adjust_budget',
            'adjust_bid',
            'update_targeting',
            'update_schedule'
        );
    END IF;
END
$$;

-- Action execution status (extended lifecycle)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'action_status') THEN
        CREATE TYPE action_status AS ENUM (
            'pending_approval',    -- Waiting for user approval
            'approved',            -- User approved, ready for execution
            'queued',              -- In execution queue
            'executing',           -- Currently being executed
            'succeeded',           -- Execution confirmed by platform
            'failed',              -- Execution failed
            'partially_executed',  -- Some operations succeeded, some failed
            'rolled_back',         -- Successfully rolled back
            'rollback_failed'      -- Rollback attempted but failed
        );
    END IF;
END
$$;

-- Target entity types
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'action_target_entity_type') THEN
        CREATE TYPE action_target_entity_type AS ENUM (
            'campaign',
            'ad_set',
            'ad',
            'ad_group',
            'keyword'
        );
    END IF;
END
$$;

-- Execution log event types
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'action_log_event_type') THEN
        CREATE TYPE action_log_event_type AS ENUM (
            'created',
            'approved',
            'queued',
            'execution_started',
            'before_state_captured',
            'api_request_sent',
            'api_response_received',
            'after_state_captured',
            'execution_succeeded',
            'execution_failed',
            'rollback_started',
            'rollback_succeeded',
            'rollback_failed',
            'cancelled'
        );
    END IF;
END
$$;

-- Action job status
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'action_job_status') THEN
        CREATE TYPE action_job_status AS ENUM (
            'queued',
            'running',
            'succeeded',
            'failed',
            'partially_succeeded'
        );
    END IF;
END
$$;

-- =============================================================================
-- TABLES
-- =============================================================================

-- AI Actions table
-- Stores executable actions derived from AI recommendations
CREATE TABLE IF NOT EXISTS ai_actions (
    -- Primary key
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Tenant isolation (CRITICAL: never from client input, only from JWT)
    tenant_id VARCHAR(255) NOT NULL,

    -- Link to source recommendation (REQUIRED)
    recommendation_id VARCHAR(255) NOT NULL,

    -- Action specification
    action_type action_type NOT NULL,
    platform VARCHAR(50) NOT NULL,  -- 'meta', 'google', 'shopify'
    target_entity_id VARCHAR(255) NOT NULL,  -- campaign_id, ad_set_id, etc.
    target_entity_type action_target_entity_type NOT NULL,

    -- Action parameters (JSONB for flexibility)
    -- Examples:
    --   {"new_budget": 500.00, "currency": "USD"}
    --   {"status": "PAUSED"}
    --   {"bid_amount": 1.50, "bid_strategy": "LOWEST_COST"}
    action_params JSONB NOT NULL DEFAULT '{}'::JSONB,

    -- Status tracking
    status action_status NOT NULL DEFAULT 'pending_approval',

    -- Approval tracking
    approved_by VARCHAR(255),  -- User ID who approved
    approved_at TIMESTAMP WITH TIME ZONE,

    -- Execution tracking
    idempotency_key VARCHAR(255),  -- For safe retries
    execution_started_at TIMESTAMP WITH TIME ZONE,
    execution_completed_at TIMESTAMP WITH TIME ZONE,

    -- State capture (for audit and rollback)
    -- before_state: Platform state before execution
    -- after_state: Platform state after execution (confirmed by platform)
    before_state JSONB,
    after_state JSONB,

    -- Rollback support
    -- Instructions on how to reverse this action
    rollback_instructions JSONB,
    rollback_executed_at TIMESTAMP WITH TIME ZONE,

    -- Error tracking
    error_message TEXT,
    error_code VARCHAR(100),
    retry_count INTEGER NOT NULL DEFAULT 0,

    -- Job reference
    job_id VARCHAR(255),

    -- Determinism hash for deduplication
    content_hash VARCHAR(64) NOT NULL,

    -- Timestamps (from TimestampMixin)
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Foreign key to ai_recommendations
    CONSTRAINT fk_actions_recommendation
        FOREIGN KEY (recommendation_id)
        REFERENCES ai_recommendations(id)
        ON DELETE CASCADE
);

-- Action Execution Logs table
-- Detailed audit trail of all execution events
CREATE TABLE IF NOT EXISTS action_execution_logs (
    -- Primary key
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Tenant isolation (CRITICAL: never from client input, only from JWT)
    tenant_id VARCHAR(255) NOT NULL,

    -- Link to parent action
    action_id VARCHAR(255) NOT NULL,

    -- Event details
    event_type action_log_event_type NOT NULL,
    event_timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Full audit data
    request_payload JSONB,   -- What we sent to the platform
    response_payload JSONB,  -- What the platform returned
    http_status_code INTEGER,

    -- State snapshots
    state_snapshot JSONB,    -- Platform state at this point

    -- Error details if applicable
    error_details JSONB,

    -- Actor tracking
    triggered_by VARCHAR(255),  -- 'system', 'user:<id>', 'worker:<job_id>'

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Foreign key to ai_actions
    CONSTRAINT fk_logs_action
        FOREIGN KEY (action_id)
        REFERENCES ai_actions(id)
        ON DELETE CASCADE
);

-- Action Jobs table
-- Tracks action execution job processing
CREATE TABLE IF NOT EXISTS action_jobs (
    -- Primary key
    job_id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Tenant isolation (CRITICAL: never from client input, only from JWT)
    tenant_id VARCHAR(255) NOT NULL,

    -- Status tracking
    status action_job_status NOT NULL DEFAULT 'queued',

    -- What actions are being processed (array of action IDs)
    action_ids JSONB NOT NULL DEFAULT '[]'::JSONB,

    -- Results tracking
    actions_attempted INTEGER NOT NULL DEFAULT 0,
    actions_succeeded INTEGER NOT NULL DEFAULT 0,
    actions_failed INTEGER NOT NULL DEFAULT 0,

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Error summary
    error_summary JSONB,

    -- Job metadata (worker info, execution context, etc.)
    job_metadata JSONB DEFAULT '{}'::JSONB,

    -- Timestamps (from TimestampMixin)
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- INDEXES FOR ai_actions
-- =============================================================================

-- Single column indexes
CREATE INDEX IF NOT EXISTS ix_ai_actions_tenant_id
    ON ai_actions(tenant_id);

CREATE INDEX IF NOT EXISTS ix_ai_actions_status
    ON ai_actions(status);

CREATE INDEX IF NOT EXISTS ix_ai_actions_recommendation_id
    ON ai_actions(recommendation_id);

CREATE INDEX IF NOT EXISTS ix_ai_actions_platform
    ON ai_actions(platform);

CREATE INDEX IF NOT EXISTS ix_ai_actions_action_type
    ON ai_actions(action_type);

CREATE INDEX IF NOT EXISTS ix_ai_actions_target_entity_id
    ON ai_actions(target_entity_id);

CREATE INDEX IF NOT EXISTS ix_ai_actions_job_id
    ON ai_actions(job_id);

CREATE INDEX IF NOT EXISTS ix_ai_actions_content_hash
    ON ai_actions(content_hash);

CREATE INDEX IF NOT EXISTS ix_ai_actions_created_at
    ON ai_actions(created_at);

-- Composite indexes for common query patterns
-- Tenant + status for listing actions by status
CREATE INDEX IF NOT EXISTS ix_ai_actions_tenant_status
    ON ai_actions(tenant_id, status);

-- Tenant + created_at for listing recent actions
CREATE INDEX IF NOT EXISTS ix_ai_actions_tenant_created
    ON ai_actions(tenant_id, created_at DESC);

-- Tenant + platform for filtering by platform
CREATE INDEX IF NOT EXISTS ix_ai_actions_tenant_platform
    ON ai_actions(tenant_id, platform);

-- Idempotency key lookup (unique per non-null value)
CREATE UNIQUE INDEX IF NOT EXISTS ix_ai_actions_idempotency_key
    ON ai_actions(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- =============================================================================
-- INDEXES FOR action_execution_logs
-- =============================================================================

-- Single column indexes
CREATE INDEX IF NOT EXISTS ix_action_logs_tenant_id
    ON action_execution_logs(tenant_id);

CREATE INDEX IF NOT EXISTS ix_action_logs_action_id
    ON action_execution_logs(action_id);

CREATE INDEX IF NOT EXISTS ix_action_logs_event_type
    ON action_execution_logs(event_type);

CREATE INDEX IF NOT EXISTS ix_action_logs_event_timestamp
    ON action_execution_logs(event_timestamp);

-- Composite indexes
-- Tenant + timestamp for listing recent logs
CREATE INDEX IF NOT EXISTS ix_action_logs_tenant_timestamp
    ON action_execution_logs(tenant_id, event_timestamp DESC);

-- Action + timestamp for getting logs for specific action
CREATE INDEX IF NOT EXISTS ix_action_logs_action_timestamp
    ON action_execution_logs(action_id, event_timestamp ASC);

-- =============================================================================
-- INDEXES FOR action_jobs
-- =============================================================================

-- Single column indexes
CREATE INDEX IF NOT EXISTS ix_action_jobs_tenant_id
    ON action_jobs(tenant_id);

CREATE INDEX IF NOT EXISTS ix_action_jobs_status
    ON action_jobs(status);

-- Composite indexes
-- Tenant + status for filtered status queries
CREATE INDEX IF NOT EXISTS ix_action_jobs_tenant_status
    ON action_jobs(tenant_id, status);

-- Tenant + created_at for finding recent jobs
CREATE INDEX IF NOT EXISTS ix_action_jobs_tenant_created
    ON action_jobs(tenant_id, created_at DESC);

-- =============================================================================
-- CONSTRAINTS
-- =============================================================================

-- Deduplication: prevent identical actions for same recommendation
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_ai_actions_dedup'
    ) THEN
        ALTER TABLE ai_actions ADD CONSTRAINT uq_ai_actions_dedup
            UNIQUE (tenant_id, content_hash, recommendation_id);
    END IF;
END
$$;

-- Partial unique: only ONE executing action per target entity at a time
-- This prevents concurrent modifications to the same campaign/ad_set
CREATE UNIQUE INDEX IF NOT EXISTS ix_ai_actions_executing_unique
    ON ai_actions(tenant_id, platform, target_entity_id)
    WHERE status IN ('queued', 'executing');

-- Partial unique: only ONE queued/running job per tenant at a time
CREATE UNIQUE INDEX IF NOT EXISTS ix_action_jobs_active_unique
    ON action_jobs(tenant_id)
    WHERE status IN ('queued', 'running');

-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- Trigger for ai_actions (uses shared update_updated_at_column function)
DROP TRIGGER IF EXISTS tr_ai_actions_updated_at ON ai_actions;
CREATE TRIGGER tr_ai_actions_updated_at
    BEFORE UPDATE ON ai_actions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Trigger for action_jobs
DROP TRIGGER IF EXISTS tr_action_jobs_updated_at ON action_jobs;
CREATE TRIGGER tr_action_jobs_updated_at
    BEFORE UPDATE ON action_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON TABLE ai_actions IS 'Executable actions derived from AI recommendations. Story 8.5 - Action Execution.';
COMMENT ON TABLE action_execution_logs IS 'Detailed audit trail of all action execution events. Story 8.5.';
COMMENT ON TABLE action_jobs IS 'Tracks action execution job processing. Story 8.5.';

COMMENT ON COLUMN ai_actions.tenant_id IS 'Tenant isolation key - ONLY from JWT, never client input';
COMMENT ON COLUMN ai_actions.recommendation_id IS 'FK to ai_recommendations - actions are always tied to recommendations';
COMMENT ON COLUMN ai_actions.action_type IS 'Type of action to execute (pause_campaign, adjust_budget, etc.)';
COMMENT ON COLUMN ai_actions.platform IS 'Target platform: meta, google, or shopify';
COMMENT ON COLUMN ai_actions.target_entity_id IS 'External platform ID of the entity being modified';
COMMENT ON COLUMN ai_actions.action_params IS 'JSONB parameters for the action (new_budget, status, etc.)';
COMMENT ON COLUMN ai_actions.idempotency_key IS 'Unique key for safe retries - prevents duplicate executions';
COMMENT ON COLUMN ai_actions.before_state IS 'Platform state captured BEFORE execution for audit/rollback';
COMMENT ON COLUMN ai_actions.after_state IS 'Platform state captured AFTER execution (source of truth confirmation)';
COMMENT ON COLUMN ai_actions.rollback_instructions IS 'Instructions to reverse this action if needed';
COMMENT ON COLUMN ai_actions.content_hash IS 'SHA256 hash of action parameters for deduplication';

COMMENT ON COLUMN action_execution_logs.event_type IS 'Type of event being logged';
COMMENT ON COLUMN action_execution_logs.request_payload IS 'Full API request sent to external platform';
COMMENT ON COLUMN action_execution_logs.response_payload IS 'Full API response from external platform';
COMMENT ON COLUMN action_execution_logs.state_snapshot IS 'Platform state at the time of this event';
COMMENT ON COLUMN action_execution_logs.triggered_by IS 'Who/what triggered this event (system, user:id, worker:job_id)';

COMMENT ON COLUMN action_jobs.action_ids IS 'Array of action IDs being processed in this job';
COMMENT ON COLUMN action_jobs.actions_attempted IS 'Total actions attempted in this job run';
COMMENT ON COLUMN action_jobs.actions_succeeded IS 'Actions that completed successfully';
COMMENT ON COLUMN action_jobs.actions_failed IS 'Actions that failed during execution';
