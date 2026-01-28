-- LLM Routing Schema for Story 8.8
-- Model routing, prompt governance, and usage logging
--
-- NO DOWN MIGRATION: Append-only schema design for compliance

-- Model registry: Available LLM models via OpenRouter
-- No hardcoded models - all models configured here
CREATE TABLE IF NOT EXISTS llm_model_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id VARCHAR(255) NOT NULL UNIQUE,  -- OpenRouter model ID (e.g., 'openai/gpt-4-turbo')
    display_name VARCHAR(255) NOT NULL,
    provider VARCHAR(100) NOT NULL,  -- 'openai', 'anthropic', 'meta', etc.
    context_window INTEGER NOT NULL DEFAULT 4096,
    max_output_tokens INTEGER NOT NULL DEFAULT 4096,
    cost_per_input_token DECIMAL(12, 10) NOT NULL DEFAULT 0,  -- Cost in USD
    cost_per_output_token DECIMAL(12, 10) NOT NULL DEFAULT 0,
    capabilities JSONB DEFAULT '[]',  -- ['chat', 'function_calling', 'vision']
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    tier_restriction VARCHAR(50),  -- NULL=all tiers, 'growth', 'enterprise'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_llm_model_registry_enabled
    ON llm_model_registry(is_enabled) WHERE is_enabled = true;
CREATE INDEX IF NOT EXISTS ix_llm_model_registry_provider
    ON llm_model_registry(provider);

-- Organization LLM configuration
-- Per-tenant model selection and preferences
CREATE TABLE IF NOT EXISTS llm_org_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(255) NOT NULL UNIQUE,
    primary_model_id VARCHAR(255) NOT NULL REFERENCES llm_model_registry(model_id),
    fallback_model_id VARCHAR(255) REFERENCES llm_model_registry(model_id),
    max_tokens_per_request INTEGER DEFAULT 2048,
    temperature DECIMAL(3, 2) DEFAULT 0.7,
    monthly_token_budget INTEGER,  -- NULL = unlimited based on tier
    preferences JSONB DEFAULT '{}',  -- Additional preferences
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_llm_org_config_tenant
    ON llm_org_config(tenant_id);

-- Versioned prompt templates
-- Allows prompt governance and version tracking
CREATE TABLE IF NOT EXISTS llm_prompt_template (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(255),  -- NULL = system template, non-NULL = custom template
    template_key VARCHAR(100) NOT NULL,  -- 'insight_generation', 'recommendation', etc.
    version INTEGER NOT NULL DEFAULT 1,
    template_content TEXT NOT NULL,
    variables JSONB DEFAULT '[]',  -- Expected variables: ['metric_name', 'value']
    is_active BOOLEAN NOT NULL DEFAULT true,
    is_system BOOLEAN NOT NULL DEFAULT false,  -- System templates cannot be modified by users
    created_by VARCHAR(255),  -- User ID who created (NULL for system)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Unique: one active version per template_key per tenant (or system)
    UNIQUE(tenant_id, template_key, version)
);

CREATE INDEX IF NOT EXISTS ix_llm_prompt_template_key
    ON llm_prompt_template(template_key);
CREATE INDEX IF NOT EXISTS ix_llm_prompt_template_tenant_active
    ON llm_prompt_template(tenant_id, is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS ix_llm_prompt_template_system
    ON llm_prompt_template(is_system) WHERE is_system = true;

-- LLM usage logging
-- Audit trail for all LLM calls with cost tracking
CREATE TABLE IF NOT EXISTS llm_usage_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(255) NOT NULL,
    model_id VARCHAR(255) NOT NULL,
    prompt_template_key VARCHAR(100),
    prompt_template_version INTEGER,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    cost_usd DECIMAL(10, 6) NOT NULL,
    was_fallback BOOLEAN NOT NULL DEFAULT false,
    fallback_reason VARCHAR(255),
    request_metadata JSONB DEFAULT '{}',  -- Correlation ID, feature context, etc.
    response_status VARCHAR(50) NOT NULL,  -- 'success', 'error', 'timeout', 'rate_limited'
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for usage analytics and audit
CREATE INDEX IF NOT EXISTS ix_llm_usage_log_tenant
    ON llm_usage_log(tenant_id);
CREATE INDEX IF NOT EXISTS ix_llm_usage_log_tenant_created
    ON llm_usage_log(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_llm_usage_log_model
    ON llm_usage_log(model_id);
CREATE INDEX IF NOT EXISTS ix_llm_usage_log_created
    ON llm_usage_log(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_llm_usage_log_status
    ON llm_usage_log(response_status);

-- Insert default models (OpenRouter model IDs)
-- These are representative models; actual availability depends on OpenRouter
INSERT INTO llm_model_registry (model_id, display_name, provider, context_window, max_output_tokens, cost_per_input_token, cost_per_output_token, capabilities, tier_restriction)
VALUES
    ('openai/gpt-4-turbo', 'GPT-4 Turbo', 'openai', 128000, 4096, 0.00001, 0.00003, '["chat", "function_calling", "vision"]', 'enterprise'),
    ('openai/gpt-4o-mini', 'GPT-4o Mini', 'openai', 128000, 16384, 0.00000015, 0.0000006, '["chat", "function_calling", "vision"]', NULL),
    ('anthropic/claude-3-5-sonnet', 'Claude 3.5 Sonnet', 'anthropic', 200000, 8192, 0.000003, 0.000015, '["chat", "function_calling", "vision"]', 'growth'),
    ('anthropic/claude-3-haiku', 'Claude 3 Haiku', 'anthropic', 200000, 4096, 0.00000025, 0.00000125, '["chat", "function_calling", "vision"]', NULL),
    ('meta-llama/llama-3.1-70b-instruct', 'Llama 3.1 70B', 'meta', 131072, 4096, 0.00000052, 0.00000075, '["chat"]', NULL)
ON CONFLICT (model_id) DO NOTHING;

-- Insert default system prompt templates
INSERT INTO llm_prompt_template (tenant_id, template_key, version, template_content, variables, is_active, is_system)
VALUES
    (NULL, 'insight_analysis', 1,
     'Analyze the following marketing metrics and provide insights:\n\nMetric: {{metric_name}}\nCurrent Value: {{current_value}}\nPrevious Value: {{previous_value}}\nChange: {{change_pct}}%\n\nProvide a brief, actionable insight about this metric change. Use conditional language (e.g., "may indicate", "could suggest") rather than definitive statements.',
     '["metric_name", "current_value", "previous_value", "change_pct"]',
     true, true),
    (NULL, 'recommendation_generation', 1,
     'Based on the following insight, generate a recommendation:\n\nInsight: {{insight_text}}\nAffected Entity: {{entity_type}} - {{entity_name}}\n\nProvide a recommendation using conditional language (e.g., "Consider...", "You may want to..."). Never use imperative commands.',
     '["insight_text", "entity_type", "entity_name"]',
     true, true)
ON CONFLICT (tenant_id, template_key, version) DO NOTHING;
