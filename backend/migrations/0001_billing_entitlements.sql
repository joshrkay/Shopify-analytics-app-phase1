-- Migration: Billing and Entitlements Schema
-- Description: Creates tables for plans, features, subscriptions, and usage tracking
-- Tenant Isolation: All tenant-owned tables include tenant_id with composite keys

-- ============================================================
-- PLANS (Global - no tenant_id)
-- ============================================================
-- Plans are global definitions (Free, Growth, Pro, Enterprise)
-- They are not tenant-specific but define what features are available

CREATE TABLE IF NOT EXISTS plans (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,
    shopify_plan_id VARCHAR(255), -- Shopify Billing API plan ID
    price_monthly_cents INTEGER, -- Monthly price in cents (NULL for free)
    price_yearly_cents INTEGER, -- Yearly price in cents (NULL for free)
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_plans_name ON plans(name);
CREATE INDEX IF NOT EXISTS idx_plans_shopify_plan_id ON plans(shopify_plan_id);
CREATE INDEX IF NOT EXISTS idx_plans_is_active ON plans(is_active);

-- ============================================================
-- PLAN FEATURES (Global - no tenant_id)
-- ============================================================
-- Junction table linking plans to features
-- Features are defined as constants in code, this table enables/disables per plan

CREATE TABLE IF NOT EXISTS plan_features (
    id VARCHAR(255) PRIMARY KEY,
    plan_id VARCHAR(255) NOT NULL,
    feature_key VARCHAR(255) NOT NULL, -- e.g., 'ai_insights', 'custom_reports'
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    limits JSONB, -- Optional limits: {"ai_insights_per_month": 100, "custom_reports": 5}
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_plan_features_plan FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE,
    CONSTRAINT uk_plan_features_plan_feature UNIQUE (plan_id, feature_key)
);

CREATE INDEX IF NOT EXISTS idx_plan_features_plan_id ON plan_features(plan_id);
CREATE INDEX IF NOT EXISTS idx_plan_features_feature_key ON plan_features(feature_key);
CREATE INDEX IF NOT EXISTS idx_plan_features_plan_feature ON plan_features(plan_id, feature_key);

-- ============================================================
-- TENANT SUBSCRIPTIONS (Tenant-scoped)
-- ============================================================
-- Tracks active subscriptions per tenant
-- Links to Shopify Billing API subscription records

CREATE TABLE IF NOT EXISTS tenant_subscriptions (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL, -- From JWT org_id
    plan_id VARCHAR(255) NOT NULL,
    shopify_subscription_id VARCHAR(255) UNIQUE, -- Shopify Billing API subscription ID
    shopify_charge_id VARCHAR(255), -- Shopify charge ID for one-time charges
    status VARCHAR(50) NOT NULL DEFAULT 'active', -- active, cancelled, expired, trialing
    current_period_start TIMESTAMP WITH TIME ZONE,
    current_period_end TIMESTAMP WITH TIME ZONE,
    trial_end TIMESTAMP WITH TIME ZONE,
    cancelled_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB, -- Additional subscription metadata
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_tenant_subscriptions_plan FOREIGN KEY (plan_id) REFERENCES plans(id),
    CONSTRAINT uk_tenant_subscriptions_tenant_plan UNIQUE (tenant_id, plan_id, status) 
        DEFERRABLE INITIALLY DEFERRED -- Allow multiple subscriptions if status differs
);

CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_tenant_id ON tenant_subscriptions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_plan_id ON tenant_subscriptions(plan_id);
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_status ON tenant_subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_shopify_subscription_id ON tenant_subscriptions(shopify_subscription_id);
-- Composite index for common query: get active subscription for tenant
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_tenant_status ON tenant_subscriptions(tenant_id, status) 
    WHERE status = 'active';

-- ============================================================
-- USAGE METERS (Tenant-scoped)
-- ============================================================
-- Defines what usage is tracked per tenant
-- Maps to features that have usage limits

CREATE TABLE IF NOT EXISTS usage_meters (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL, -- From JWT org_id
    feature_key VARCHAR(255) NOT NULL, -- e.g., 'ai_insights', 'openrouter_tokens'
    meter_type VARCHAR(50) NOT NULL, -- 'counter', 'gauge', 'cumulative'
    period_type VARCHAR(50) NOT NULL, -- 'monthly', 'yearly', 'lifetime'
    current_value NUMERIC(20, 2) NOT NULL DEFAULT 0,
    limit_value NUMERIC(20, 2), -- NULL means unlimited
    reset_at TIMESTAMP WITH TIME ZONE, -- When meter resets
    metadata JSONB, -- Additional meter configuration
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_usage_meters_tenant_feature_period UNIQUE (tenant_id, feature_key, period_type)
);

CREATE INDEX IF NOT EXISTS idx_usage_meters_tenant_id ON usage_meters(tenant_id);
CREATE INDEX IF NOT EXISTS idx_usage_meters_feature_key ON usage_meters(feature_key);
CREATE INDEX IF NOT EXISTS idx_usage_meters_tenant_feature ON usage_meters(tenant_id, feature_key);
CREATE INDEX IF NOT EXISTS idx_usage_meters_reset_at ON usage_meters(reset_at) WHERE reset_at IS NOT NULL;

-- ============================================================
-- USAGE EVENTS (Tenant-scoped)
-- ============================================================
-- Append-only log of usage events for audit and analytics
-- Used to reconstruct usage_meters and for billing reconciliation

CREATE TABLE IF NOT EXISTS usage_events (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL, -- From JWT org_id
    feature_key VARCHAR(255) NOT NULL,
    meter_id VARCHAR(255), -- Reference to usage_meters.id (optional)
    event_type VARCHAR(50) NOT NULL, -- 'increment', 'set', 'reset'
    value NUMERIC(20, 2) NOT NULL,
    previous_value NUMERIC(20, 2), -- Value before this event
    period_type VARCHAR(50) NOT NULL, -- 'monthly', 'yearly', 'lifetime'
    period_start TIMESTAMP WITH TIME ZONE, -- Start of billing period
    metadata JSONB, -- Additional event context (user_id, request_id, etc.)
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_usage_events_meter FOREIGN KEY (meter_id) REFERENCES usage_meters(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_usage_events_tenant_id ON usage_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_usage_events_feature_key ON usage_events(feature_key);
CREATE INDEX IF NOT EXISTS idx_usage_events_meter_id ON usage_events(meter_id);
CREATE INDEX IF NOT EXISTS idx_usage_events_created_at ON usage_events(created_at);
CREATE INDEX IF NOT EXISTS idx_usage_events_tenant_feature_created ON usage_events(tenant_id, feature_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_events_period ON usage_events(tenant_id, period_type, period_start) 
    WHERE period_start IS NOT NULL;

-- ============================================================
-- TRIGGERS: Auto-update updated_at timestamps
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to all tables with updated_at
CREATE TRIGGER update_plans_updated_at
    BEFORE UPDATE ON plans
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_plan_features_updated_at
    BEFORE UPDATE ON plan_features
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tenant_subscriptions_updated_at
    BEFORE UPDATE ON tenant_subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_usage_meters_updated_at
    BEFORE UPDATE ON usage_meters
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- COMMENTS: Document schema
-- ============================================================

COMMENT ON TABLE plans IS 'Global plan definitions (Free, Growth, Pro, Enterprise). Not tenant-specific.';
COMMENT ON TABLE plan_features IS 'Junction table linking plans to enabled features with optional limits.';
COMMENT ON TABLE tenant_subscriptions IS 'Active subscriptions per tenant. Links to Shopify Billing API.';
COMMENT ON TABLE usage_meters IS 'Current usage counters per tenant per feature. Updated from usage_events.';
COMMENT ON TABLE usage_events IS 'Append-only audit log of usage events. Used for reconciliation and analytics.';

COMMENT ON COLUMN tenant_subscriptions.tenant_id IS 'Tenant identifier from JWT org_id. NEVER from client input.';
COMMENT ON COLUMN usage_meters.tenant_id IS 'Tenant identifier from JWT org_id. NEVER from client input.';
COMMENT ON COLUMN usage_events.tenant_id IS 'Tenant identifier from JWT org_id. NEVER from client input.';

COMMENT ON COLUMN plan_features.limits IS 'JSONB limits object: {"ai_insights_per_month": 100, "custom_reports": 5}';
COMMENT ON COLUMN usage_meters.meter_type IS 'counter: increments, gauge: current value, cumulative: never resets';
COMMENT ON COLUMN usage_meters.period_type IS 'monthly: resets monthly, yearly: resets yearly, lifetime: never resets';
