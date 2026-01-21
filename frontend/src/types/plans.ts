/**
 * Types for Plan Management API
 */

export interface PlanFeature {
  feature_key: string;
  is_enabled: boolean;
  limit_value?: number | null;
  limits?: Record<string, unknown> | null;
}

export interface Plan {
  id: string;
  name: string;
  display_name: string;
  description?: string | null;
  price_monthly_cents?: number | null;
  price_yearly_cents?: number | null;
  shopify_plan_id?: string | null;
  is_active: boolean;
  features: PlanFeature[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface PlansListResponse {
  plans: Plan[];
  total: number;
  limit: number;
  offset: number;
}

export interface CreatePlanRequest {
  name: string;
  display_name: string;
  description?: string;
  price_monthly_cents?: number;
  price_yearly_cents?: number;
  shopify_plan_id?: string;
  is_active?: boolean;
  features?: PlanFeature[];
}

export interface UpdatePlanRequest {
  name?: string;
  display_name?: string;
  description?: string;
  price_monthly_cents?: number;
  price_yearly_cents?: number;
  shopify_plan_id?: string;
  is_active?: boolean;
  features?: PlanFeature[];
}

export interface ToggleFeatureRequest {
  feature_key: string;
  is_enabled: boolean;
}

export interface ShopifyValidationRequest {
  shop_domain: string;
  shopify_subscription_id?: string;
}

export interface ShopifyValidationResponse {
  is_valid: boolean;
  shopify_plan_id?: string | null;
  plan_name?: string | null;
  price_amount?: number | null;
  currency_code?: string | null;
  error?: string | null;
}

// Common feature keys for reference
export const FEATURE_KEYS = {
  AI_INSIGHTS: 'ai_insights',
  CUSTOM_REPORTS: 'custom_reports',
  EXPORT_DATA: 'export_data',
  API_ACCESS: 'api_access',
  TEAM_MEMBERS: 'team_members',
  PRIORITY_SUPPORT: 'priority_support',
  CUSTOM_BRANDING: 'custom_branding',
  ADVANCED_ANALYTICS: 'advanced_analytics',
} as const;

export type FeatureKey = typeof FEATURE_KEYS[keyof typeof FEATURE_KEYS];
