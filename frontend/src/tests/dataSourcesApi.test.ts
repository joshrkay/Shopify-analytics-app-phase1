/**
 * Tests for Data Sources API Service (dataSourcesApi.ts)
 *
 * Tests the unified facade: re-exported functions from sourcesApi + new functions
 * for connection detail, accounts, sync progress, sync triggering, and global settings.
 *
 * Phase 3 — Subphase 3.2: Data Sources API
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/apiUtils', () => ({
  API_BASE_URL: '',
  createHeadersAsync: vi.fn().mockResolvedValue({
    'Content-Type': 'application/json',
    Authorization: 'Bearer test-token',
  }),
  handleResponse: vi.fn(async (res: Response) => res.json()),
}));

const mockHeaders = { 'Content-Type': 'application/json', Authorization: 'Bearer test-token' };

import {
  getConnections,
  getAvailableSources,
  initiateOAuth,
  completeOAuth,
  disconnectSource,
  testConnection,
  updateSyncConfig,
  getConnection,
  getAccounts,
  getSyncProgress,
  triggerSync,
  getGlobalSyncSettings,
  updateGlobalSyncSettings,
  getAvailableAccounts,
  getSyncProgressDetailed,
} from '../services/dataSourcesApi';

beforeEach(() => {
  vi.clearAllMocks();
});

function mockFetch(data: unknown) {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: vi.fn().mockResolvedValue(data),
  });
}

// =============================================================================
// Re-exported functions (verify they are callable)
// =============================================================================

describe('re-exported sourcesApi functions', () => {
  it('getConnections calls GET /api/sources', async () => {
    mockFetch({ sources: [], total: 0 });
    await getConnections();
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sources',
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('getAvailableSources calls GET /api/sources/catalog', async () => {
    mockFetch({ sources: [], total: 0 });
    await getAvailableSources();
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sources/catalog',
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('initiateOAuth calls POST /api/sources/{platform}/oauth/initiate', async () => {
    mockFetch({ authorization_url: 'https://fb.com/oauth', state: 'csrf-token' });
    await initiateOAuth('meta_ads');
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sources/meta_ads/oauth/initiate',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('completeOAuth calls POST /api/sources/oauth/callback', async () => {
    mockFetch({ success: true, connection_id: 'conn-1', message: 'OK' });
    await completeOAuth({ code: 'auth-code', state: 'csrf-token' });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sources/oauth/callback',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ code: 'auth-code', state: 'csrf-token' }),
      }),
    );
  });

  it('disconnectSource calls DELETE /api/sources/{sourceId}', async () => {
    mockFetch(undefined);
    await disconnectSource('conn-123');
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sources/conn-123',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('testConnection calls POST /api/sources/{sourceId}/test', async () => {
    mockFetch({ success: true, message: 'OK' });
    await testConnection('conn-123');
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sources/conn-123/test',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('updateSyncConfig calls PATCH /api/sources/{sourceId}/config', async () => {
    mockFetch(undefined);
    await updateSyncConfig('conn-123', { sync_frequency: 'daily' });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sources/conn-123/config',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ sync_frequency: 'daily' }),
      }),
    );
  });
});

// =============================================================================
// New functions
// =============================================================================

describe('getConnection', () => {
  it('calls GET /api/data-health/source/{connectionId} and normalizes response', async () => {
    mockFetch({
      connection_id: 'conn-1',
      connection_name: 'My Store',
      source_type: 'shopify',
      status: 'active',
      is_enabled: true,
      freshness_status: 'fresh',
      last_sync_at: '2025-06-15T10:30:00Z',
      last_sync_status: 'succeeded',
      sync_frequency_minutes: 60,
      minutes_since_sync: 15,
      expected_next_sync_at: '2025-06-15T11:30:00Z',
      is_stale: false,
      is_healthy: true,
      warning_message: null,
    });

    const result = await getConnection('conn-1');

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/data-health/source/conn-1',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(result.id).toBe('conn-1');
    expect(result.displayName).toBe('My Store');
    expect(result.platform).toBe('shopify');
    expect(result.isHealthy).toBe(true);
    expect(result.minutesSinceSync).toBe(15);
  });
});

describe('getAccounts', () => {
  it('calls GET /api/ad-platform-ingestion/connections/{connectionId} and normalizes', async () => {
    mockFetch({
      id: 'acc-1',
      platform: 'meta_ads',
      account_id: 'act_123',
      account_name: 'Summer Campaign',
      connection_id: 'conn-1',
      airbyte_connection_id: 'ab-123',
      status: 'active',
      is_enabled: true,
      last_sync_at: null,
      last_sync_status: null,
    });

    const result = await getAccounts('conn-1');

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/ad-platform-ingestion/connections/conn-1',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(result.accountName).toBe('Summer Campaign');
    expect(result.accountId).toBe('act_123');
    expect(result.airbyteConnectionId).toBe('ab-123');
  });
});

describe('getSyncProgress', () => {
  it('calls GET /api/sync/state/{connectionId} and normalizes', async () => {
    mockFetch({
      connection_id: 'conn-1',
      status: 'running',
      last_sync_at: '2025-06-15T10:30:00Z',
      last_sync_status: 'succeeded',
      is_enabled: true,
      can_sync: true,
    });

    const result = await getSyncProgress('conn-1');

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sync/state/conn-1',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(result.connectionId).toBe('conn-1');
    expect(result.status).toBe('running');
    expect(result.canSync).toBe(true);
  });
});

describe('triggerSync', () => {
  it('calls POST /api/sync/trigger/{connectionId}', async () => {
    mockFetch({});
    await triggerSync('conn-1');
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sync/trigger/conn-1',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});

describe('getGlobalSyncSettings', () => {
  it('calls GET /api/sources/sync-settings and normalizes', async () => {
    mockFetch({
      default_frequency: 'daily',
      pause_all_syncs: false,
      max_concurrent_syncs: 3,
    });

    const result = await getGlobalSyncSettings();

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sources/sync-settings',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(result.defaultFrequency).toBe('daily');
    expect(result.pauseAllSyncs).toBe(false);
    expect(result.maxConcurrentSyncs).toBe(3);
  });
});

describe('updateGlobalSyncSettings', () => {
  it('calls PUT /api/sources/sync-settings with snake_case body', async () => {
    mockFetch({
      default_frequency: 'hourly',
      pause_all_syncs: true,
      max_concurrent_syncs: 5,
    });

    const result = await updateGlobalSyncSettings({
      defaultFrequency: 'hourly',
      pauseAllSyncs: true,
      maxConcurrentSyncs: 5,
    });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sources/sync-settings',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({
          default_frequency: 'hourly',
          pause_all_syncs: true,
          max_concurrent_syncs: 5,
        }),
      }),
    );
    expect(result.defaultFrequency).toBe('hourly');
  });
});

// =============================================================================
// New wizard API functions
// =============================================================================

describe('getAvailableAccounts', () => {
  it('calls GET /api/ad-platform-ingestion/connections/{connectionId}/accounts and normalizes', async () => {
    mockFetch({
      accounts: [
        {
          id: 'acc-1',
          platform: 'meta_ads',
          account_id: 'act_123',
          account_name: 'Summer Campaign',
          connection_id: 'conn-1',
          airbyte_connection_id: 'ab-123',
          status: 'active',
          is_enabled: true,
          last_sync_at: null,
          last_sync_status: null,
        },
      ],
    });

    const result = await getAvailableAccounts('conn-1');

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/ad-platform-ingestion/connections/conn-1/accounts',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(result).toHaveLength(1);
    expect(result[0].accountName).toBe('Summer Campaign');
    expect(result[0].accountId).toBe('act_123');
  });
});

describe('getSyncProgressDetailed', () => {
  it('normalizes response with percentage derivation from status', async () => {
    mockFetch({
      connection_id: 'conn-1',
      status: 'running',
      last_sync_at: null,
      last_sync_status: null,
      is_enabled: true,
      can_sync: true,
    });

    const result = await getSyncProgressDetailed('conn-1');

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sync/state/conn-1',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(result.percentComplete).toBe(50); // running = 50%
    expect(result.currentStream).toBeNull();
  });

  it('uses backend percent_complete when provided', async () => {
    mockFetch({
      connection_id: 'conn-1',
      status: 'running',
      percent_complete: 75,
      current_stream: 'campaigns',
      message: 'Syncing campaigns...',
      last_sync_at: null,
      last_sync_status: null,
      is_enabled: true,
      can_sync: true,
    });

    const result = await getSyncProgressDetailed('conn-1');

    expect(result.percentComplete).toBe(75);
    expect(result.currentStream).toBe('campaigns');
    expect(result.message).toBe('Syncing campaigns...');
  });
});

describe('auth token inclusion', () => {
  it('includes auth headers in all requests', async () => {
    mockFetch({
      connection_id: 'conn-1',
      connection_name: 'Test',
      source_type: 'shopify',
      status: 'active',
      is_enabled: true,
      freshness_status: 'fresh',
      last_sync_at: null,
      last_sync_status: null,
      sync_frequency_minutes: 60,
      minutes_since_sync: null,
      expected_next_sync_at: null,
      is_stale: false,
      is_healthy: true,
      warning_message: null,
    });

    await getConnection('conn-1');

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ headers: mockHeaders }),
    );
  });
});
