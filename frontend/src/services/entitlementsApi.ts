/**
 * Entitlements API Service
 *
 * Handles API calls for feature entitlements and billing state.
 */

import { API_BASE_URL, createHeadersAsync, fetchWithRetry, handleResponse } from './apiUtils';

/**
 * Feature entitlement information.
 */
export interface FeatureEntitlement {
  feature: string;
  is_entitled: boolean;
  billing_state: string;
  plan_id: string | null;
  plan_name: string | null;
  reason: string | null;
  required_plan: string | null;
  grace_period_ends_on: string | null;
}

/**
 * Complete entitlements response.
 */
export interface EntitlementsResponse {
  billing_state: 'active' | 'past_due' | 'grace_period' | 'canceled' | 'expired' | 'none';
  plan_id: string | null;
  plan_name: string | null;
  features: Record<string, FeatureEntitlement>;
  grace_period_days_remaining: number | null;
}

/**
 * Fetch current entitlements for the tenant.
 */
export async function fetchEntitlements(): Promise<EntitlementsResponse> {
  const response = await fetchWithRetry(`${API_BASE_URL}/api/billing/entitlements`, {
    method: 'GET',
    headers: await createHeadersAsync(),
  });

  return handleResponse<EntitlementsResponse>(response);
}

/**
 * Check if a specific feature is entitled.
 */
export function isFeatureEntitled(
  entitlements: EntitlementsResponse | null,
  feature: string
): boolean {
  if (!entitlements) {
    return false;
  }

  const featureEntitlement = entitlements.features[feature];
  return featureEntitlement?.is_entitled ?? false;
}

/**
 * Get billing state from entitlements.
 */
export function getBillingState(
  entitlements: EntitlementsResponse | null
): EntitlementsResponse['billing_state'] {
  return entitlements?.billing_state ?? 'none';
}
