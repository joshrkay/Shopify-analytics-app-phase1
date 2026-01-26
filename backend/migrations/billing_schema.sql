-- Billing Schema Migration
-- Version: 1.0.0
-- Date: 2024-01-15
--
-- This migration creates the complete billing schema for Shopify Billing API integration.
-- Run this migration against PostgreSQL database.
--
-- Usage: psql $DATABASE_URL -f billing_schema.sql

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- Plans Table
-- Global plan definitions (not tenant-scoped)
-- =============================================================================

CREATE TABLE IF NOT EXISTS plans (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,
    shopify_plan_id VARCHAR(255),
    price_monthly_cents INTEGER,
    price_yearly_cents INTEGER,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plans_name ON plans(name);
CREATE INDEX IF NOT EXISTS idx_plans_active ON plans(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_plans_shopify_id ON plans(shopify_plan_id) WHERE shopify_plan_id IS NOT NULL;

COMMENT ON TABLE plans IS 'Global billing plan definitions';
COMMENT ON COLUMN plans.shopify_plan_id IS 'Shopify Billing API plan ID (NULL until configured)';
COMMENT ON COLUMN plans.price_monthly_cents IS 'Monthly price in cents (NULL for free/enterprise)';

-- =============================================================================
-- Plan Features Table
-- Feature enablement per plan with optional limits
-- =============================================================================

CREATE TABLE IF NOT EXISTS plan_features (
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    plan_id VARCHAR(255) NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    feature_key VARCHAR(255) NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    limit_value INTEGER,
    limits JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_plan_features_plan_feature UNIQUE (plan_id, feature_key)
);

CREATE INDEX IF NOT EXISTS idx_plan_features_plan ON plan_features(plan_id);
CREATE INDEX IF NOT EXISTS idx_plan_features_key ON plan_features(feature_key);

COMMENT ON TABLE plan_features IS 'Feature enablement and limits per plan';
COMMENT ON COLUMN plan_features.limit_value IS 'Usage limit value (NULL means unlimited)';
COMMENT ON COLUMN plan_features.limits IS 'Additional limits as JSON (e.g., {"ai_insights_per_month": 100})';

-- =============================================================================
-- Tenant Subscriptions Table
-- Per-tenant subscription to a plan
-- =============================================================================

CREATE TABLE IF NOT EXISTS tenant_subscriptions (
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    tenant_id VARCHAR(255) NOT NULL,
    store_id VARCHAR(255) REFERENCES shopify_stores(id),
    plan_id VARCHAR(255) NOT NULL REFERENCES plans(id),
    shopify_subscription_id VARCHAR(255) UNIQUE,
    shopify_charge_id VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    current_period_start TIMESTAMP WITH TIME ZONE,
    current_period_end TIMESTAMP WITH TIME ZONE,
    trial_end TIMESTAMP WITH TIME ZONE,
    cancelled_at TIMESTAMP WITH TIME ZONE,
    grace_period_ends_on TIMESTAMP WITH TIME ZONE,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_tenant ON tenant_subscriptions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_store ON tenant_subscriptions(store_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_plan ON tenant_subscriptions(plan_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_shopify ON tenant_subscriptions(shopify_subscription_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON tenant_subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_tenant_status ON tenant_subscriptions(tenant_id, status)
    WHERE status = 'active';

-- Constraint to ensure one active subscription per tenant (excluding cancelled/expired)
CREATE UNIQUE INDEX IF NOT EXISTS uk_tenant_active_subscription
    ON tenant_subscriptions(tenant_id)
    WHERE status IN ('active', 'pending', 'frozen');

COMMENT ON TABLE tenant_subscriptions IS 'Per-tenant subscription records';
COMMENT ON COLUMN tenant_subscriptions.status IS 'Status: pending, active, frozen, cancelled, declined, expired';
COMMENT ON COLUMN tenant_subscriptions.grace_period_ends_on IS 'When grace period expires for frozen subscriptions';

-- =============================================================================
-- Billing Events Table (Audit Log)
-- Append-only audit log for all billing events
-- =============================================================================

CREATE TABLE IF NOT EXISTS billing_events (
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    tenant_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    store_id VARCHAR(255) REFERENCES shopify_stores(id),
    subscription_id VARCHAR(255),
    from_plan_id VARCHAR(255),
    to_plan_id VARCHAR(255),
    amount_cents INTEGER,
    shopify_subscription_id VARCHAR(255),
    shopify_charge_id VARCHAR(255),
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Note: No updated_at - this is append-only

CREATE INDEX IF NOT EXISTS idx_billing_events_tenant ON billing_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_billing_events_type ON billing_events(event_type);
CREATE INDEX IF NOT EXISTS idx_billing_events_subscription ON billing_events(subscription_id);
CREATE INDEX IF NOT EXISTS idx_billing_events_shopify_sub ON billing_events(shopify_subscription_id);
CREATE INDEX IF NOT EXISTS idx_billing_events_tenant_created ON billing_events(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_billing_events_tenant_type ON billing_events(tenant_id, event_type);

COMMENT ON TABLE billing_events IS 'Append-only audit log for billing events';
COMMENT ON COLUMN billing_events.event_type IS 'Event type: subscription_created, subscription_updated, charge_failed, etc.';

-- =============================================================================
-- Webhook Events Table (Idempotency)
-- Tracks processed webhooks to ensure exactly-once processing
-- =============================================================================

CREATE TABLE IF NOT EXISTS webhook_events (
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    shopify_event_id VARCHAR(255) NOT NULL UNIQUE,
    topic VARCHAR(255) NOT NULL,
    shop_domain VARCHAR(255) NOT NULL,
    payload_hash VARCHAR(64),
    processed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_shopify_id ON webhook_events(shopify_event_id);
CREATE INDEX IF NOT EXISTS idx_webhook_events_shop_topic ON webhook_events(shop_domain, topic);
CREATE INDEX IF NOT EXISTS idx_webhook_events_processed ON webhook_events(processed_at DESC);

-- Auto-cleanup old webhook events (retention: 30 days)
-- This should be run as a scheduled job
-- DELETE FROM webhook_events WHERE created_at < NOW() - INTERVAL '30 days';

COMMENT ON TABLE webhook_events IS 'Tracks processed webhooks for idempotency';
COMMENT ON COLUMN webhook_events.shopify_event_id IS 'X-Shopify-Webhook-Id header value';
COMMENT ON COLUMN webhook_events.payload_hash IS 'SHA-256 hash of payload for debugging';

-- =============================================================================
-- Usage Records Table (High-volume API usage tracking)
-- =============================================================================

CREATE TABLE IF NOT EXISTS usage_records (
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    tenant_id VARCHAR(255) NOT NULL,
    store_id VARCHAR(255),
    endpoint VARCHAR(255) NOT NULL,
    method VARCHAR(10) NOT NULL,
    usage_type VARCHAR(50) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    metadata JSONB
);

-- Partition-friendly index for time-based queries
CREATE INDEX IF NOT EXISTS idx_usage_records_tenant_time
    ON usage_records(tenant_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_records_store_time
    ON usage_records(store_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_records_type_time
    ON usage_records(usage_type, recorded_at DESC);

COMMENT ON TABLE usage_records IS 'High-volume API call and feature usage tracking';
COMMENT ON COLUMN usage_records.usage_type IS 'Type: api_call, ai_insight, export, etc.';

-- =============================================================================
-- Usage Aggregates Table (Pre-aggregated usage for billing)
-- =============================================================================

CREATE TABLE IF NOT EXISTS usage_aggregates (
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    tenant_id VARCHAR(255) NOT NULL,
    store_id VARCHAR(255),
    usage_type VARCHAR(50) NOT NULL,
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    period_type VARCHAR(20) NOT NULL, -- 'hourly', 'daily', 'monthly'
    total_quantity BIGINT NOT NULL DEFAULT 0,
    success_count BIGINT NOT NULL DEFAULT 0,
    error_count BIGINT NOT NULL DEFAULT 0,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_usage_aggregates UNIQUE (tenant_id, store_id, usage_type, period_start, period_type)
);

CREATE INDEX IF NOT EXISTS idx_usage_aggregates_tenant_period
    ON usage_aggregates(tenant_id, period_start DESC);
CREATE INDEX IF NOT EXISTS idx_usage_aggregates_type_period
    ON usage_aggregates(usage_type, period_start DESC);

COMMENT ON TABLE usage_aggregates IS 'Pre-aggregated usage for efficient billing queries';
COMMENT ON COLUMN usage_aggregates.period_type IS 'Aggregation period: hourly, daily, monthly';

-- =============================================================================
-- Billing Audit Log Table (Enhanced)
-- Comprehensive audit trail for compliance
-- =============================================================================

CREATE TABLE IF NOT EXISTS billing_audit_log (
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    tenant_id VARCHAR(255) NOT NULL,
    shop_id VARCHAR(255),
    event_type VARCHAR(100) NOT NULL,
    previous_state JSONB,
    new_state JSONB,
    raw_payload JSONB,
    actor_id VARCHAR(255), -- User or system that triggered the event
    actor_type VARCHAR(50), -- 'user', 'system', 'webhook'
    ip_address VARCHAR(45),
    user_agent TEXT,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_tenant ON billing_audit_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_type ON billing_audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_tenant_time ON billing_audit_log(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_shop_time ON billing_audit_log(shop_id, timestamp DESC);

COMMENT ON TABLE billing_audit_log IS 'Comprehensive billing audit trail for compliance (7-year retention)';
COMMENT ON COLUMN billing_audit_log.raw_payload IS 'Original webhook/API payload for debugging';

-- =============================================================================
-- Default Plans Seed Data
-- =============================================================================

INSERT INTO plans (id, name, display_name, description, price_monthly_cents, price_yearly_cents, is_active)
VALUES
    ('plan_free', 'free', 'Free', 'Basic analytics for small stores', 0, 0, TRUE),
    ('plan_growth', 'growth', 'Growth', 'For growing businesses with advanced analytics', 2900, 29000, TRUE),
    ('plan_pro', 'pro', 'Pro', 'Professional tier with all features', 7900, 79000, TRUE),
    ('plan_enterprise', 'enterprise', 'Enterprise', 'Custom solutions with dedicated support', NULL, NULL, TRUE)
ON CONFLICT (id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    price_monthly_cents = EXCLUDED.price_monthly_cents,
    price_yearly_cents = EXCLUDED.price_yearly_cents,
    updated_at = NOW();

-- =============================================================================
-- Default Plan Features Seed Data
-- =============================================================================

-- Free Plan Features
INSERT INTO plan_features (id, plan_id, feature_key, is_enabled, limit_value, limits)
VALUES
    (uuid_generate_v4()::TEXT, 'plan_free', 'dashboard_basic', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_free', 'dashboard_advanced', FALSE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_free', 'data_export_csv', TRUE, 100, '{"rows_per_export": 100}'),
    (uuid_generate_v4()::TEXT, 'plan_free', 'ai_insights', FALSE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_free', 'api_access', FALSE, NULL, NULL)
ON CONFLICT (plan_id, feature_key) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    limit_value = EXCLUDED.limit_value,
    limits = EXCLUDED.limits,
    updated_at = NOW();

-- Growth Plan Features
INSERT INTO plan_features (id, plan_id, feature_key, is_enabled, limit_value, limits)
VALUES
    (uuid_generate_v4()::TEXT, 'plan_growth', 'dashboard_basic', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_growth', 'dashboard_advanced', TRUE, 10, '{"max_dashboards": 10}'),
    (uuid_generate_v4()::TEXT, 'plan_growth', 'data_export_csv', TRUE, 10000, '{"rows_per_export": 10000}'),
    (uuid_generate_v4()::TEXT, 'plan_growth', 'ai_insights', TRUE, 50, '{"monthly_limit": 50}'),
    (uuid_generate_v4()::TEXT, 'plan_growth', 'api_access', TRUE, 10000, '{"monthly_calls": 10000}')
ON CONFLICT (plan_id, feature_key) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    limit_value = EXCLUDED.limit_value,
    limits = EXCLUDED.limits,
    updated_at = NOW();

-- Pro Plan Features
INSERT INTO plan_features (id, plan_id, feature_key, is_enabled, limit_value, limits)
VALUES
    (uuid_generate_v4()::TEXT, 'plan_pro', 'dashboard_basic', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_pro', 'dashboard_advanced', TRUE, 50, '{"max_dashboards": 50}'),
    (uuid_generate_v4()::TEXT, 'plan_pro', 'dashboard_custom', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_pro', 'data_export_csv', TRUE, 100000, '{"rows_per_export": 100000}'),
    (uuid_generate_v4()::TEXT, 'plan_pro', 'data_export_api', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_pro', 'ai_insights', TRUE, 500, '{"monthly_limit": 500}'),
    (uuid_generate_v4()::TEXT, 'plan_pro', 'ai_actions', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_pro', 'api_access', TRUE, 100000, '{"monthly_calls": 100000}'),
    (uuid_generate_v4()::TEXT, 'plan_pro', 'multi_store', TRUE, NULL, NULL)
ON CONFLICT (plan_id, feature_key) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    limit_value = EXCLUDED.limit_value,
    limits = EXCLUDED.limits,
    updated_at = NOW();

-- Enterprise Plan Features (Unlimited)
INSERT INTO plan_features (id, plan_id, feature_key, is_enabled, limit_value, limits)
VALUES
    (uuid_generate_v4()::TEXT, 'plan_enterprise', 'dashboard_basic', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_enterprise', 'dashboard_advanced', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_enterprise', 'dashboard_custom', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_enterprise', 'data_export_csv', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_enterprise', 'data_export_api', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_enterprise', 'ai_insights', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_enterprise', 'ai_actions', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_enterprise', 'api_access', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_enterprise', 'multi_store', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_enterprise', 'agency_features', TRUE, NULL, NULL),
    (uuid_generate_v4()::TEXT, 'plan_enterprise', 'dedicated_support', TRUE, NULL, NULL)
ON CONFLICT (plan_id, feature_key) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    limit_value = EXCLUDED.limit_value,
    limits = EXCLUDED.limits,
    updated_at = NOW();

-- =============================================================================
-- Functions for Audit Logging
-- =============================================================================

-- Function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to relevant tables
DROP TRIGGER IF EXISTS update_plans_updated_at ON plans;
CREATE TRIGGER update_plans_updated_at
    BEFORE UPDATE ON plans
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_plan_features_updated_at ON plan_features;
CREATE TRIGGER update_plan_features_updated_at
    BEFORE UPDATE ON plan_features
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_subscriptions_updated_at ON tenant_subscriptions;
CREATE TRIGGER update_subscriptions_updated_at
    BEFORE UPDATE ON tenant_subscriptions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Migration Complete
-- =============================================================================

SELECT 'Billing schema migration completed successfully' AS status;
