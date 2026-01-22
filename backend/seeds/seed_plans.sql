-- Seed script: Plans and Features
-- Description: Inserts default plans (Free, Growth, Pro, Enterprise) and their features
-- Run this after applying migration 0001_billing_entitlements.sql

-- ============================================================
-- PLANS
-- ============================================================

INSERT INTO plans (id, name, display_name, description, shopify_plan_id, price_monthly_cents, price_yearly_cents, is_active)
VALUES
    ('plan_free', 'free', 'Free', 'Basic analytics with limited features', NULL, 0, 0, true),
    ('plan_growth', 'growth', 'Growth', 'Advanced analytics for growing businesses', NULL, 2900, 29000, true), -- $29/month or $290/year
    ('plan_pro', 'pro', 'Pro', 'Professional analytics with AI insights', NULL, 9900, 99000, true), -- $99/month or $990/year
    ('plan_enterprise', 'enterprise', 'Enterprise', 'Full-featured analytics with custom integrations', NULL, NULL, NULL, true) -- Custom pricing
ON CONFLICT (id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    shopify_plan_id = EXCLUDED.shopify_plan_id,
    price_monthly_cents = EXCLUDED.price_monthly_cents,
    price_yearly_cents = EXCLUDED.price_yearly_cents,
    updated_at = CURRENT_TIMESTAMP;

-- ============================================================
-- FEATURES
-- ============================================================
-- Feature keys match constants in /backend/src/constants/permissions.py

-- Free Plan Features
INSERT INTO plan_features (id, plan_id, feature_key, is_enabled, limits)
VALUES
    ('pf_free_basic_reports', 'plan_free', 'basic_reports', true, '{"max_reports": 3}'),
    ('pf_free_data_export', 'plan_free', 'data_export', true, '{"exports_per_month": 5}')
ON CONFLICT (plan_id, feature_key) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    limits = EXCLUDED.limits,
    updated_at = CURRENT_TIMESTAMP;

-- Growth Plan Features
INSERT INTO plan_features (id, plan_id, feature_key, is_enabled, limits)
VALUES
    ('pf_growth_basic_reports', 'plan_growth', 'basic_reports', true, '{"max_reports": 10}'),
    ('pf_growth_custom_reports', 'plan_growth', 'custom_reports', true, '{"max_reports": 20}'),
    ('pf_growth_data_export', 'plan_growth', 'data_export', true, '{"exports_per_month": 50}'),
    ('pf_growth_ai_insights', 'plan_growth', 'ai_insights', true, '{"insights_per_month": 50}'),
    ('pf_growth_openrouter_byollm', 'plan_growth', 'openrouter_byollm', false, NULL)
ON CONFLICT (plan_id, feature_key) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    limits = EXCLUDED.limits,
    updated_at = CURRENT_TIMESTAMP;

-- Pro Plan Features
INSERT INTO plan_features (id, plan_id, feature_key, is_enabled, limits)
VALUES
    ('pf_pro_basic_reports', 'plan_pro', 'basic_reports', true, NULL), -- Unlimited
    ('pf_pro_custom_reports', 'plan_pro', 'custom_reports', true, NULL), -- Unlimited
    ('pf_pro_data_export', 'plan_pro', 'data_export', true, NULL), -- Unlimited
    ('pf_pro_ai_insights', 'plan_pro', 'ai_insights', true, '{"insights_per_month": 500}'),
    ('pf_pro_ai_actions', 'plan_pro', 'ai_actions', true, '{"actions_per_month": 100}'),
    ('pf_pro_agency_mode', 'plan_pro', 'agency_mode', true, '{"max_clients": 10}'),
    ('pf_pro_openrouter_byollm', 'plan_pro', 'openrouter_byollm', true, NULL),
    ('pf_pro_robyn_mmm', 'plan_pro', 'robyn_mmm', true, '{"models_per_month": 2}')
ON CONFLICT (plan_id, feature_key) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    limits = EXCLUDED.limits,
    updated_at = CURRENT_TIMESTAMP;

-- Enterprise Plan Features (all enabled, mostly unlimited)
INSERT INTO plan_features (id, plan_id, feature_key, is_enabled, limits)
VALUES
    ('pf_enterprise_basic_reports', 'plan_enterprise', 'basic_reports', true, NULL),
    ('pf_enterprise_custom_reports', 'plan_enterprise', 'custom_reports', true, NULL),
    ('pf_enterprise_data_export', 'plan_enterprise', 'data_export', true, NULL),
    ('pf_enterprise_ai_insights', 'plan_enterprise', 'ai_insights', true, NULL),
    ('pf_enterprise_ai_actions', 'plan_enterprise', 'ai_actions', true, NULL),
    ('pf_enterprise_agency_mode', 'plan_enterprise', 'agency_mode', true, NULL),
    ('pf_enterprise_openrouter_byollm', 'plan_enterprise', 'openrouter_byollm', true, NULL),
    ('pf_enterprise_robyn_mmm', 'plan_enterprise', 'robyn_mmm', true, NULL)
ON CONFLICT (plan_id, feature_key) DO UPDATE SET
    is_enabled = EXCLUDED.is_enabled,
    limits = EXCLUDED.limits,
    updated_at = CURRENT_TIMESTAMP;

-- ============================================================
-- VERIFICATION QUERIES
-- ============================================================
-- Run these to verify seed data:

-- SELECT p.name, p.display_name, COUNT(pf.feature_key) as feature_count
-- FROM plans p
-- LEFT JOIN plan_features pf ON p.id = pf.plan_id AND pf.is_enabled = true
-- GROUP BY p.id, p.name, p.display_name
-- ORDER BY p.name;

-- SELECT p.name, pf.feature_key, pf.is_enabled, pf.limits
-- FROM plans p
-- JOIN plan_features pf ON p.id = pf.plan_id
-- ORDER BY p.name, pf.feature_key;
