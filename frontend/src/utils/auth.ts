/**
 * Auth utilities for tenant JWT refresh and access surface detection.
 *
 * Story 5.5.3 - Tenant Selector + JWT Refresh for Active Tenant Context
 */

import { refreshJwtToken } from '../services/agencyApi';
import { setAuthToken } from '../services/apiUtils';

export interface RefreshResult {
  jwt_token: string;
  active_tenant_id: string;
  access_surface: string;
  access_expiring_at: string | null;
}

/**
 * Detect the current access surface.
 *
 * Returns "shopify_embed" when running inside a Shopify Admin iframe,
 * "external_app" otherwise.
 */
export function detectAccessSurface(): 'shopify_embed' | 'external_app' {
  try {
    return window.top !== window.self ? 'shopify_embed' : 'external_app';
  } catch {
    // Cross-origin iframe check throws — assume embedded
    return 'shopify_embed';
  }
}

/**
 * Refresh the JWT token for a target tenant with access surface detection.
 *
 * - Detects access_surface automatically
 * - Updates the cached auth token on success
 * - Returns access_expiring_at if tenant is in grace-period revocation
 * - Throws on 403 (access expired)
 */
export async function refreshTenantToken(
  tenantId: string,
  allowedTenants: string[] = [],
): Promise<RefreshResult> {
  const result = await refreshJwtToken(tenantId, allowedTenants);

  // The agencyApi.refreshJwtToken already caches the token via setAuthToken
  // Cast to our richer result type
  const typedResult = result as unknown as RefreshResult;

  return {
    jwt_token: typedResult.jwt_token,
    active_tenant_id: typedResult.active_tenant_id ?? tenantId,
    access_surface: typedResult.access_surface ?? detectAccessSurface(),
    access_expiring_at: typedResult.access_expiring_at ?? null,
  };
}
