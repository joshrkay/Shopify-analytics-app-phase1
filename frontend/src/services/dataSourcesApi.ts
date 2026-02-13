/**
 * Unified Data Sources API Service
 *
 * Facade that re-exports from sourcesApi.ts and adds functions for:
 * - Single connection detail (merged with health data)
 * - Ad platform account management
 * - Sync progress and triggering
 * - Global sync settings
 *
 * Phase 3 — Subphase 3.2: Unified Data Sources API
 */

import { API_BASE_URL, createHeadersAsync, handleResponse } from './apiUtils';
import type {
  DataSourceConnection,
  SyncProgress,
  DetailedSyncProgress,
  GlobalSyncSettings,
  ConnectedAccount,
  AccountOption,
} from '../types/sourceConnection';

// Re-exports from sourcesApi — callers can import from either module
export {
  listSources,
  listSources as getConnections,
  getAvailableSources,
  initiateOAuth,
  completeOAuth,
  disconnectSource,
  testConnection,
  updateSyncConfig,
} from './sourcesApi';

// =============================================================================
// Raw backend response shapes (snake_case)
// =============================================================================

interface RawSourceHealthResponse {
  connection_id: string;
  connection_name: string;
  source_type: string | null;
  status: string;
  is_enabled: boolean;
  freshness_status: string;
  last_sync_at: string | null;
  last_sync_status: string | null;
  sync_frequency_minutes: number;
  minutes_since_sync: number | null;
  expected_next_sync_at: string | null;
  is_stale: boolean;
  is_healthy: boolean;
  warning_message: string | null;
}

interface RawSyncStateResponse {
  connection_id: string;
  status: string;
  last_sync_at: string | null;
  last_sync_status: string | null;
  is_enabled: boolean;
  can_sync: boolean;
}

interface RawConnectionSummary {
  id: string;
  platform: string;
  account_id: string;
  account_name: string;
  connection_id: string;
  airbyte_connection_id: string;
  status: string;
  is_enabled: boolean;
  last_sync_at: string | null;
  last_sync_status: string | null;
}

interface RawGlobalSyncSettings {
  default_frequency: string;
  pause_all_syncs: boolean;
  max_concurrent_syncs: number;
}

// =============================================================================
// Normalizers (snake_case → camelCase)
// =============================================================================

const PLATFORM_AUTH_TYPES: Record<string, 'oauth' | 'api_key'> = {
  shopify: 'oauth',
  meta_ads: 'oauth',
  google_ads: 'oauth',
  tiktok_ads: 'oauth',
  snapchat_ads: 'oauth',
  klaviyo: 'api_key',
  shopify_email: 'oauth',
  attentive: 'api_key',
  postscript: 'api_key',
  smsbump: 'api_key',
};

function normalizeSourceHealth(raw: RawSourceHealthResponse): DataSourceConnection {
  const platform = (raw.source_type ?? 'shopify') as DataSourceConnection['platform'];
  return {
    id: raw.connection_id,
    platform,
    displayName: raw.connection_name,
    authType: PLATFORM_AUTH_TYPES[platform] ?? 'api_key',
    status: raw.status as DataSourceConnection['status'],
    isEnabled: raw.is_enabled,
    lastSyncAt: raw.last_sync_at,
    lastSyncStatus: raw.last_sync_status,
    freshnessStatus: raw.freshness_status,
    minutesSinceSync: raw.minutes_since_sync,
    isStale: raw.is_stale,
    isHealthy: raw.is_healthy,
    warningMessage: raw.warning_message,
    syncFrequencyMinutes: raw.sync_frequency_minutes,
    expectedNextSyncAt: raw.expected_next_sync_at,
  };
}

function normalizeSyncState(raw: RawSyncStateResponse): SyncProgress {
  return {
    connectionId: raw.connection_id,
    status: raw.status,
    lastSyncAt: raw.last_sync_at,
    lastSyncStatus: raw.last_sync_status,
    isEnabled: raw.is_enabled,
    canSync: raw.can_sync,
  };
}

function normalizeAccount(raw: RawConnectionSummary): ConnectedAccount {
  return {
    id: raw.id,
    platform: raw.platform,
    accountId: raw.account_id,
    accountName: raw.account_name,
    connectionId: raw.connection_id,
    airbyteConnectionId: raw.airbyte_connection_id,
    status: raw.status,
    isEnabled: raw.is_enabled,
    lastSyncAt: raw.last_sync_at,
    lastSyncStatus: raw.last_sync_status,
  };
}

function normalizeGlobalSettings(raw: RawGlobalSyncSettings): GlobalSyncSettings {
  return {
    defaultFrequency: raw.default_frequency as GlobalSyncSettings['defaultFrequency'],
    pauseAllSyncs: raw.pause_all_syncs,
    maxConcurrentSyncs: raw.max_concurrent_syncs,
  };
}

// =============================================================================
// Single Connection Detail
// =============================================================================

/**
 * Get detailed health information for a single data source connection.
 *
 * Merges source metadata with health/freshness data from the data health API.
 */
export async function getConnection(connectionId: string): Promise<DataSourceConnection> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/data-health/source/${encodeURIComponent(connectionId)}`,
    { method: 'GET', headers },
  );
  const data = await handleResponse<RawSourceHealthResponse>(response);
  return normalizeSourceHealth(data);
}

// =============================================================================
// Account Management
// =============================================================================

/**
 * Get ad accounts/stores for a connected platform.
 */
export async function getAccounts(connectionId: string): Promise<ConnectedAccount> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/ad-platform-ingestion/connections/${encodeURIComponent(connectionId)}`,
    { method: 'GET', headers },
  );
  const data = await handleResponse<RawConnectionSummary>(response);
  return normalizeAccount(data);
}

/**
 * Update the selected ad accounts for a connection.
 */
export async function updateSelectedAccounts(
  connectionId: string,
  accountIds: string[],
): Promise<void> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/ad-platform-ingestion/connections/${encodeURIComponent(connectionId)}/accounts`,
    {
      method: 'PUT',
      headers,
      body: JSON.stringify({ account_ids: accountIds }),
    },
  );
  await handleResponse<void>(response);
}

// =============================================================================
// Sync Operations
// =============================================================================

/**
 * Get current sync progress/state for a connection.
 */
export async function getSyncProgress(connectionId: string): Promise<SyncProgress> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/sync/state/${encodeURIComponent(connectionId)}`,
    { method: 'GET', headers },
  );
  const data = await handleResponse<RawSyncStateResponse>(response);
  return normalizeSyncState(data);
}

/**
 * Trigger a sync for a connection.
 */
export async function triggerSync(connectionId: string): Promise<void> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/sync/trigger/${encodeURIComponent(connectionId)}`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify({}),
    },
  );
  await handleResponse<void>(response);
}

// =============================================================================
// Global Sync Settings
// =============================================================================

/**
 * Get global sync settings for the tenant.
 */
export async function getGlobalSyncSettings(): Promise<GlobalSyncSettings> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/sources/sync-settings`,
    { method: 'GET', headers },
  );
  const data = await handleResponse<RawGlobalSyncSettings>(response);
  return normalizeGlobalSettings(data);
}

/**
 * Update global sync settings.
 */
export async function updateGlobalSyncSettings(
  settings: Partial<GlobalSyncSettings>,
): Promise<GlobalSyncSettings> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/sources/sync-settings`,
    {
      method: 'PUT',
      headers,
      body: JSON.stringify({
        ...(settings.defaultFrequency !== undefined && {
          default_frequency: settings.defaultFrequency,
        }),
        ...(settings.pauseAllSyncs !== undefined && {
          pause_all_syncs: settings.pauseAllSyncs,
        }),
        ...(settings.maxConcurrentSyncs !== undefined && {
          max_concurrent_syncs: settings.maxConcurrentSyncs,
        }),
      }),
    },
  );
  const data = await handleResponse<RawGlobalSyncSettings>(response);
  return normalizeGlobalSettings(data);
}

// =============================================================================
// Available Accounts (Wizard Step 3)
// =============================================================================

interface RawAccountListResponse {
  accounts: RawConnectionSummary[];
}

function normalizeAccountOption(raw: RawConnectionSummary): AccountOption {
  return {
    id: raw.id,
    accountId: raw.account_id,
    accountName: raw.account_name,
    platform: raw.platform,
    isEnabled: raw.is_enabled,
  };
}

/**
 * Get available ad accounts for a connection after OAuth.
 */
export async function getAvailableAccounts(connectionId: string): Promise<AccountOption[]> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/ad-platform-ingestion/connections/${encodeURIComponent(connectionId)}/accounts`,
    { method: 'GET', headers },
  );
  const data = await handleResponse<RawAccountListResponse>(response);
  return data.accounts.map(normalizeAccountOption);
}

// =============================================================================
// Detailed Sync Progress (Wizard Step 5)
// =============================================================================

interface RawSyncProgressDetailed {
  connection_id: string;
  status: string;
  percent_complete?: number;
  current_stream?: string | null;
  message?: string | null;
  last_sync_at: string | null;
  last_sync_status: string | null;
  is_enabled: boolean;
  can_sync: boolean;
}

function derivePercentComplete(status: string, raw?: number): number {
  if (raw !== undefined) return raw;
  switch (status) {
    case 'completed': return 100;
    case 'running': return 50;
    case 'failed': return 0;
    default: return 0;
  }
}

/**
 * Get detailed sync progress for the wizard progress bar.
 * Falls back to deriving percentage from status if backend doesn't provide it.
 */
export async function getSyncProgressDetailed(connectionId: string): Promise<DetailedSyncProgress> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/sync/state/${encodeURIComponent(connectionId)}`,
    { method: 'GET', headers },
  );
  const data = await handleResponse<RawSyncProgressDetailed>(response);
  return {
    connectionId: data.connection_id,
    status: data.status,
    lastSyncAt: data.last_sync_at,
    lastSyncStatus: data.last_sync_status,
    isEnabled: data.is_enabled,
    canSync: data.can_sync,
    percentComplete: derivePercentComplete(data.status, data.percent_complete),
    currentStream: data.current_stream ?? null,
    message: data.message ?? null,
  };
}
