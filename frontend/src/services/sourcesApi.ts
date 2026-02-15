/**
 * Sources API Service
 *
 * Fetches all data source connections from the unified /api/sources endpoint.
 * Includes connection management methods for catalog, OAuth, disconnect, test, and config.
 *
 * Story 2.1.1 — Unified Source domain model
 * Phase 3 — Subphase 3.2: Extended API Service
 */

import { API_BASE_URL, createHeadersAsync, fetchWithRetry, handleResponse } from './apiUtils';
import { normalizeApiSource, type RawApiSource } from './sourceNormalizer';
import type { Source, SourcePlatform } from '../types/sources';
import type {
  DataSourceDefinition,
  CatalogResponse,
  OAuthInitiateResponse,
  OAuthCallbackParams,
  OAuthCompleteResponse,
  ConnectionTestResult,
  UpdateSyncConfigRequest,
} from '../types/sourceConnection';

interface RawSourceListResponse {
  sources: RawApiSource[];
  total: number;
}

// =============================================================================
// Source List
// =============================================================================

/**
 * List all data source connections for the current tenant.
 *
 * Returns a unified list of Shopify and ad platform connections.
 */
export async function listSources(): Promise<Source[]> {
  const headers = await createHeadersAsync();
  const response = await fetchWithRetry(`${API_BASE_URL}/api/sources`, {
    method: 'GET',
    headers,
  });
  const data = await handleResponse<RawSourceListResponse>(response);
  return data.sources.map(normalizeApiSource);
}

// =============================================================================
// Source Catalog
// =============================================================================

/**
 * Get list of available data source platforms that can be connected.
 *
 * Returns catalog of all supported platforms (Shopify, Meta Ads, Google Ads, etc.)
 * with their display info, auth requirements, and availability status.
 */
export async function getAvailableSources(): Promise<DataSourceDefinition[]> {
  const headers = await createHeadersAsync();
  const response = await fetchWithRetry(`${API_BASE_URL}/api/sources/catalog`, {
    method: 'GET',
    headers,
  });
  const data = await handleResponse<CatalogResponse>(response);
  return data.sources;
}

// =============================================================================
// OAuth Flow
// =============================================================================

/**
 * Initiate OAuth flow for a platform.
 *
 * Returns authorization URL to redirect user to for OAuth consent.
 * Backend generates CSRF state token for security.
 *
 * @param platform - Platform identifier (e.g., 'meta_ads', 'google_ads')
 */
export async function initiateOAuth(platform: SourcePlatform): Promise<OAuthInitiateResponse> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/sources/${platform}/oauth/initiate`, {
    method: 'POST',
    headers,
  });
  return handleResponse<OAuthInitiateResponse>(response);
}

/**
 * Complete OAuth flow after callback redirect.
 *
 * Backend exchanges authorization code for access token, stores encrypted credentials,
 * and creates Airbyte connection.
 *
 * @param params - OAuth callback parameters (code, state)
 */
export async function completeOAuth(params: OAuthCallbackParams): Promise<OAuthCompleteResponse> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/sources/oauth/callback`, {
    method: 'POST',
    headers,
    body: JSON.stringify(params),
  });
  return handleResponse<OAuthCompleteResponse>(response);
}

// =============================================================================
// Connection Management
// =============================================================================

/**
 * Disconnect (soft delete) a data source connection.
 *
 * Marks connection as deleted, stops syncs, and schedules credential cleanup.
 *
 * @param sourceId - Connection ID to disconnect
 */
export async function disconnectSource(sourceId: string): Promise<void> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/sources/${sourceId}`, {
    method: 'DELETE',
    headers,
  });
  await handleResponse<void>(response);
}

/**
 * Test connection to external platform.
 *
 * Validates credentials and connectivity without triggering a full sync.
 *
 * @param sourceId - Connection ID to test
 */
export async function testConnection(sourceId: string): Promise<ConnectionTestResult> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/sources/${sourceId}/test`, {
    method: 'POST',
    headers,
  });
  return handleResponse<ConnectionTestResult>(response);
}

/**
 * Update sync configuration for a connection.
 *
 * Modifies sync frequency and/or enabled data streams.
 *
 * @param sourceId - Connection ID to configure
 * @param config - Updated sync configuration
 */
export async function updateSyncConfig(
  sourceId: string,
  config: UpdateSyncConfigRequest
): Promise<void> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/sources/${sourceId}/config`, {
    method: 'PATCH',
    headers,
    body: JSON.stringify(config),
  });
  await handleResponse<void>(response);
}
