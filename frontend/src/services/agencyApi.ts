/**
 * Agency API Service
 *
 * Handles API calls for agency user functionality:
 * - Fetching assigned stores
 * - Switching active store
 * - Refreshing JWT with new tenant context
 */

import type {
  AssignedStoresResponse,
  SwitchStoreRequest,
  SwitchStoreResponse,
  UserContext,
} from '../types/agency';
import { API_BASE_URL, createHeadersAsync, fetchWithRetry, handleResponse, setAuthToken } from './apiUtils';

/**
 * Fetch assigned stores for the current agency user.
 */
export async function fetchAssignedStores(): Promise<AssignedStoresResponse> {
  const response = await fetchWithRetry(`${API_BASE_URL}/api/agency/stores`, {
    method: 'GET',
    headers: await createHeadersAsync(),
  });
  return handleResponse<AssignedStoresResponse>(response);
}

/**
 * Switch the active store for an agency user.
 *
 * This will refresh the JWT token with the new tenant context.
 */
export async function switchActiveStore(
  tenantId: string
): Promise<SwitchStoreResponse> {
  const request: SwitchStoreRequest = { tenant_id: tenantId };

  const response = await fetch(`${API_BASE_URL}/api/agency/stores/switch`, {
    method: 'POST',
    headers: await createHeadersAsync(),
    body: JSON.stringify(request),
  });

  const result = await handleResponse<SwitchStoreResponse>(response);

  // Update stored JWT token with new tenant context
  if (result.success && result.jwt_token) {
    setAuthToken(result.jwt_token);
  }

  return result;
}

/**
 * Get the current user context from JWT.
 */
export async function fetchUserContext(): Promise<UserContext> {
  const response = await fetchWithRetry(`${API_BASE_URL}/api/agency/me`, {
    method: 'GET',
    headers: await createHeadersAsync(),
  });
  return handleResponse<UserContext>(response);
}

/**
 * Refresh the JWT token (e.g., after switching stores).
 */
export async function refreshJwtToken(
  tenantId: string,
  allowedTenants: string[]
): Promise<{ jwt_token: string }> {
  const response = await fetch(`${API_BASE_URL}/api/auth/refresh-jwt`, {
    method: 'POST',
    headers: await createHeadersAsync(),
    body: JSON.stringify({
      tenant_id: tenantId,
      allowed_tenants: allowedTenants,
    }),
  });

  const result = await handleResponse<{ jwt_token: string }>(response);

  // Update stored JWT token
  if (result.jwt_token) {
    setAuthToken(result.jwt_token);
  }

  return result;
}

/**
 * Check if user has access to a specific store.
 */
export async function checkStoreAccess(
  tenantId: string
): Promise<{ has_access: boolean; reason?: string }> {
  const response = await fetchWithRetry(
    `${API_BASE_URL}/api/agency/stores/${tenantId}/access`,
    {
      method: 'GET',
      headers: await createHeadersAsync(),
    }
  );
  return handleResponse<{ has_access: boolean; reason?: string }>(response);
}
