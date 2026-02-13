/**
 * Integration Tests for ConnectSourceWizard Steps 4-6
 *
 * Verifiable API->UI wiring tests for SyncConfig -> SyncProgress -> Success.
 * Mocks ONLY at the fetch boundary while keeping all real hooks and API services.
 *
 * Phase 3 -- Subphase 3.4/3.5: Steps 4-6 Integration Tests
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
// Mock only at the fetch boundary -- keeps real hooks and API service logic
vi.mock('../services/apiUtils', () => ({
  API_BASE_URL: '',
  createHeadersAsync: vi.fn().mockResolvedValue({
    'Content-Type': 'application/json',
    Authorization: 'Bearer test-token',
  }),
  handleResponse: vi.fn(async (res: Response) => res.json()),
  getErrorMessage: vi.fn((err: unknown, fallback: string) => {
    if (err instanceof Error) return err.message;
    return fallback;
  }),
}));

import { useConnectSourceWizard } from '../hooks/useConnectSourceWizard';
import type { DataSourceDefinition } from '../types/sourceConnection';

// ---------------------------------------------------------------------------
// Test Harness
// ---------------------------------------------------------------------------

let wizardRef: ReturnType<typeof useConnectSourceWizard>;

function TestHarness() {
  const wizard = useConnectSourceWizard();
  wizardRef = wizard;
  return (
    <div>
      <span data-testid="step">{wizard.state.step}</span>
      <span data-testid="connection-id">{wizard.state.connectionId ?? ''}</span>
      <span data-testid="error">{wizard.state.error ?? ''}</span>
      <span data-testid="loading">{String(wizard.state.loading)}</span>
      <span data-testid="percent">{wizard.state.syncProgress?.percentComplete ?? ''}</span>
      <span data-testid="sync-status">{wizard.state.syncProgress?.status ?? ''}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const shopifyPlatform: DataSourceDefinition = {
  id: 'shopify',
  platform: 'shopify',
  displayName: 'Shopify',
  description: 'Connect your Shopify store',
  authType: 'oauth',
  category: 'ecommerce',
  isEnabled: true,
};

/** Helper: create a mock Response whose .json() resolves to `body` */
function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

/** Default snake_case sync state payload */
function syncStatePayload(overrides: Record<string, unknown> = {}) {
  return {
    connection_id: 'conn-1',
    status: 'running',
    percent_complete: 50,
    current_stream: null,
    message: null,
    last_sync_at: null,
    last_sync_status: null,
    is_enabled: true,
    can_sync: true,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Helpers to drive the wizard to syncConfig step via real hook methods
// ---------------------------------------------------------------------------

/**
 * Drive the wizard through intro -> oauth -> handleOAuthComplete so it
 * lands on 'syncConfig' with connectionId='conn-1'.
 *
 * `mockFetch` must be provided so we can set up ordered responses.
 */
async function driveToSyncConfig(mockFetch: ReturnType<typeof vi.fn>) {
  // 1. Init with non-ads platform (ecommerce skips accounts step)
  await act(async () => {
    wizardRef.initWithPlatform(shopifyPlatform);
  });

  // 2. Proceed from intro to oauth
  await act(async () => {
    wizardRef.proceedFromIntro();
  });

  // 3. startOAuth -- needs initiateOAuth fetch
  //    POST /api/sources/shopify/oauth/initiate
  mockFetch.mockResolvedValueOnce(
    jsonResponse({ authorization_url: 'https://oauth.example.com', state: 'csrf-token' }),
  );

  // Stub window.open so the popup doesn't actually open
  const originalOpen = window.open;
  window.open = vi.fn(() => ({ closed: false } as Window));

  await act(async () => {
    await wizardRef.startOAuth();
  });

  window.open = originalOpen;

  // 4. handleOAuthComplete -- needs completeOAuth fetch
  //    POST /api/sources/oauth/callback
  mockFetch.mockResolvedValueOnce(
    jsonResponse({ success: true, connection_id: 'conn-1', message: 'OK' }),
  );

  await act(async () => {
    await wizardRef.handleOAuthComplete({ code: 'auth-code', state: 'csrf-token' });
  });

  // Now step should be 'syncConfig' and connectionId should be 'conn-1'
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ConnectSourceWizard Steps 4-6 Integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // =========================================================================
  // Test 1: SyncConfig confirm calls PATCH config and POST trigger endpoints
  // =========================================================================
  it('SyncConfig confirm calls PATCH config and POST trigger endpoints', async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;

    render(<TestHarness />);

    // Drive wizard to syncConfig step
    await driveToSyncConfig(mockFetch);

    expect(screen.getByTestId('step').textContent).toBe('syncConfig');
    expect(screen.getByTestId('connection-id').textContent).toBe('conn-1');

    // Mock the two calls that confirmSyncConfig makes:
    // 1. PATCH /api/sources/conn-1/config  (updateSyncConfig)
    // 2. POST /api/sync/trigger/conn-1     (triggerSync)
    mockFetch.mockResolvedValueOnce(jsonResponse({}));
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    // Also mock the immediate poll that fires when step becomes 'syncing'
    // (the useEffect polls immediately on entering the syncing step)
    mockFetch.mockResolvedValueOnce(
      jsonResponse(syncStatePayload({ status: 'running', percent_complete: 10 })),
    );

    await act(async () => {
      await wizardRef.confirmSyncConfig();
    });

    // Find the PATCH config call
    const allCalls = mockFetch.mock.calls;
    const patchCall = allCalls.find(
      (call: any[]) =>
        typeof call[0] === 'string' && call[0].includes('/api/sources/conn-1/config'),
    );
    expect(patchCall).toBeDefined();
    expect(patchCall![1].method).toBe('PATCH');
    const patchBody = JSON.parse(patchCall![1].body);
    expect(patchBody).toHaveProperty('sync_frequency');

    // Find the POST trigger call
    const postCall = allCalls.find(
      (call: any[]) =>
        typeof call[0] === 'string' && call[0].includes('/api/sync/trigger/conn-1'),
    );
    expect(postCall).toBeDefined();
    expect(postCall![1].method).toBe('POST');

    // Step should have transitioned to 'syncing'
    await waitFor(() => {
      expect(screen.getByTestId('step').textContent).toBe('syncing');
    });
  });

  // =========================================================================
  // Test 2: Sync progress polling calls GET and auto-advances on completion
  // =========================================================================
  it('Sync progress polling calls GET /api/sync/state/{id} and auto-advances on completion', async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;

    render(<TestHarness />);

    // Drive wizard to syncConfig with real timers
    await driveToSyncConfig(mockFetch);
    expect(screen.getByTestId('step').textContent).toBe('syncConfig');

    // Now switch to fake timers for controlling the polling
    vi.useFakeTimers();

    // confirmSyncConfig calls: PATCH config, POST trigger
    mockFetch.mockResolvedValueOnce(jsonResponse({}));
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    // Immediate poll (fires when step transitions to 'syncing') -- return running
    mockFetch.mockResolvedValueOnce(
      jsonResponse(syncStatePayload({ status: 'running', percent_complete: 50 })),
    );

    await act(async () => {
      await wizardRef.confirmSyncConfig();
    });

    // Flush microtasks to let the immediate poll fire and resolve
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.getByTestId('step').textContent).toBe('syncing');

    // Advance timer by 3 seconds -- next poll interval fires
    // Return running again at 75%
    mockFetch.mockResolvedValueOnce(
      jsonResponse(syncStatePayload({ status: 'running', percent_complete: 75 })),
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    // Now mock the next poll to return completed
    mockFetch.mockResolvedValueOnce(
      jsonResponse(syncStatePayload({ status: 'completed', percent_complete: 100 })),
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    // Verify fetch was called multiple times with the sync state endpoint
    const syncStateCalls = mockFetch.mock.calls.filter(
      (call: any[]) =>
        typeof call[0] === 'string' && call[0].includes('/api/sync/state/conn-1'),
    );
    expect(syncStateCalls.length).toBeGreaterThanOrEqual(2);

    // Step should auto-advance to 'success'
    expect(screen.getByTestId('step').textContent).toBe('success');

    vi.useRealTimers();
  });

  // =========================================================================
  // Test 3: Sync failure sets error and stops polling
  // =========================================================================
  it('Sync failure: API returns failed status -> error is set and polling stops', async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;

    render(<TestHarness />);

    // Drive wizard to syncConfig with real timers
    await driveToSyncConfig(mockFetch);
    expect(screen.getByTestId('step').textContent).toBe('syncConfig');

    // Switch to fake timers for controlling the polling
    vi.useFakeTimers();

    // confirmSyncConfig calls: PATCH config, POST trigger
    mockFetch.mockResolvedValueOnce(jsonResponse({}));
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    // Immediate poll returns failed status
    mockFetch.mockResolvedValueOnce(
      jsonResponse(syncStatePayload({ status: 'failed', percent_complete: 0 })),
    );

    await act(async () => {
      await wizardRef.confirmSyncConfig();
    });

    // Flush microtasks to let the immediate poll fire and resolve
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Error should be set
    expect(screen.getByTestId('error').textContent).toContain('Sync failed');

    // Step stays at 'syncing' (does not auto-advance to success)
    expect(screen.getByTestId('step').textContent).toBe('syncing');

    // Record fetch call count and advance timer to verify polling stopped
    const callCountAfterFailure = mockFetch.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });

    // No new fetch calls should have been made (polling stopped)
    expect(mockFetch.mock.calls.length).toBe(callCountAfterFailure);

    vi.useRealTimers();
  });

  // =========================================================================
  // Test 4: Success step has correct connectionId proving full pipeline flow
  // =========================================================================
  it('Success step: data flows through full pipeline with correct connectionId', async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;

    render(<TestHarness />);

    // Drive wizard to syncConfig with real timers
    await driveToSyncConfig(mockFetch);

    // Switch to fake timers for controlling the polling
    vi.useFakeTimers();

    // confirmSyncConfig: PATCH config + POST trigger
    mockFetch.mockResolvedValueOnce(jsonResponse({}));
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    // Immediate poll returns completed immediately
    mockFetch.mockResolvedValueOnce(
      jsonResponse(syncStatePayload({ status: 'completed', percent_complete: 100 })),
    );

    await act(async () => {
      await wizardRef.confirmSyncConfig();
    });

    // Flush microtasks to let the immediate poll resolve
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Verify wizard reached success step
    expect(screen.getByTestId('step').textContent).toBe('success');

    // Verify the connectionId flowed through the entire pipeline
    expect(screen.getByTestId('connection-id').textContent).toBe('conn-1');

    // Verify the wizard state directly
    expect(wizardRef.state.step).toBe('success');
    expect(wizardRef.state.connectionId).toBe('conn-1');

    vi.useRealTimers();
  });
});
