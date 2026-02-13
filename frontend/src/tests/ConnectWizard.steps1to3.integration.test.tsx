/**
 * Integration Tests: Connect Source Wizard Steps 1-3
 *
 * Verifiable API-to-UI wiring tests for the connection wizard flow:
 * Intro (Step 1) -> OAuth (Step 2) -> Accounts (Step 3).
 *
 * Approach:
 * - Mock ONLY at the `fetch` boundary (globalThis.fetch)
 * - Mock `apiUtils` to bypass Clerk auth
 * - Keep all real hooks, API services, and components
 * - Verify data flows from fetch mock -> normalization -> hooks -> components -> rendered UI
 *
 * Phase 3 — Subphase 3.4/3.5: Connection Wizard Integration Tests
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { useConnectSourceWizard } from '../hooks/useConnectSourceWizard';
import { ConnectSourceWizard } from '../components/sources/ConnectSourceWizard';
import type { DataSourceDefinition } from '../types/sourceConnection';

// =============================================================================
// Mock apiUtils at module boundary — bypasses Clerk auth
// =============================================================================

vi.mock('../services/apiUtils', () => ({
  API_BASE_URL: '',
  createHeadersAsync: vi.fn().mockResolvedValue({
    'Content-Type': 'application/json',
    Authorization: 'Bearer test-token',
  }),
  handleResponse: vi.fn(async (res: Response) => res.json()),
  getErrorMessage: vi.fn(
    (err: unknown, fallback: string) =>
      err instanceof Error ? err.message : fallback,
  ),
}));

// =============================================================================
// Shared Fixtures
// =============================================================================

const metaAdsPlatform: DataSourceDefinition = {
  id: 'meta-ads-def',
  platform: 'meta_ads',
  displayName: 'Meta Ads',
  description: 'Connect your Meta Ads account for campaign analytics.',
  authType: 'oauth',
  category: 'ads',
  isEnabled: true,
};

const accountsResponse = {
  accounts: [
    {
      id: 'acc-1',
      account_id: 'act_111',
      account_name: 'Summer Campaign',
      platform: 'meta_ads',
      connection_id: 'conn-1',
      airbyte_connection_id: 'ab-1',
      status: 'active',
      is_enabled: true,
      last_sync_at: null,
      last_sync_status: null,
    },
  ],
};

// =============================================================================
// TestHarness — exposes useConnectSourceWizard for direct method testing
// =============================================================================

let wizardRef: ReturnType<typeof useConnectSourceWizard>;

function TestHarness({ platform: _platform }: { platform: DataSourceDefinition }) {
  const wizard = useConnectSourceWizard();
  wizardRef = wizard;
  return (
    <div>
      <span data-testid="step">{wizard.state.step}</span>
      <span data-testid="connection-id">{wizard.state.connectionId ?? ''}</span>
      {wizard.state.accounts.map((a) => (
        <span key={a.id} data-testid={`account-${a.id}`}>
          {a.accountName}
        </span>
      ))}
      {wizard.state.error && (
        <span data-testid="error">{wizard.state.error}</span>
      )}
    </div>
  );
}

// =============================================================================
// Helpers
// =============================================================================

function wrapProviders(ui: React.ReactElement) {
  return (
    <MemoryRouter>
      <AppProvider i18n={{} as any}>{ui}</AppProvider>
    </MemoryRouter>
  );
}

function mockFetchSequence(responses: Array<{ ok?: boolean; data?: unknown; error?: Error }>) {
  const fn = vi.fn();
  for (const resp of responses) {
    if (resp.error) {
      fn.mockRejectedValueOnce(resp.error);
    } else {
      fn.mockResolvedValueOnce({
        ok: resp.ok ?? true,
        json: vi.fn().mockResolvedValue(resp.data),
      });
    }
  }
  globalThis.fetch = fn;
  return fn;
}

function mockFetchOnce(data: unknown) {
  return mockFetchSequence([{ data }]);
}

// =============================================================================
// Tests
// =============================================================================

describe('ConnectWizard Steps 1-3 Integration', () => {
  const originalOpen = window.open;

  beforeEach(() => {
    vi.clearAllMocks();
    window.open = vi.fn().mockReturnValue({ closed: false });
  });

  afterEach(() => {
    window.open = originalOpen;
  });

  // ---------------------------------------------------------------------------
  // Test 1: Intro -> OAuth: initiateOAuth calls correct endpoint with auth headers
  // ---------------------------------------------------------------------------
  it('Intro -> OAuth: initiateOAuth calls correct endpoint with auth headers', async () => {
    const user = userEvent.setup();

    // Mock fetch for the initiateOAuth POST call
    const fetchMock = mockFetchOnce({
      authorization_url: 'https://facebook.com/oauth',
      state: 'csrf-123',
    });

    render(
      wrapProviders(
        <ConnectSourceWizard
          open={true}
          platform={metaAdsPlatform}
          onClose={vi.fn()}
        />,
      ),
    );

    // Wait for the intro step to render with the "Continue with Meta Ads" button
    const continueButton = await screen.findByRole('button', {
      name: /Continue with Meta Ads/i,
    });

    // Click to proceed from intro to oauth step
    await user.click(continueButton);

    // Wait for OAuth step to render with the "Authorize Meta Ads" button
    const authorizeButton = await screen.findByRole('button', {
      name: /Authorize Meta Ads/i,
    });

    // Click to initiate OAuth
    await user.click(authorizeButton);

    // Assert: fetch was called with the correct OAuth initiate endpoint
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/sources/meta_ads/oauth/initiate'),
        expect.objectContaining({ method: 'POST' }),
      );
    });

    // Assert: Headers include Authorization Bearer token
    const call = fetchMock.mock.calls.find((c: any[]) =>
      String(c[0]).includes('/api/sources/meta_ads/oauth/initiate'),
    );
    expect(call).toBeDefined();
    expect(call![1].headers).toEqual(
      expect.objectContaining({ Authorization: 'Bearer test-token' }),
    );
  });

  // ---------------------------------------------------------------------------
  // Test 2: OAuth completion loads accounts from real API endpoint
  // ---------------------------------------------------------------------------
  it('OAuth completion loads accounts from real API endpoint', async () => {
    // Mock fetch for two sequential calls:
    // 1. completeOAuth -> POST /api/sources/oauth/callback
    // 2. getAvailableAccounts -> GET /api/ad-platform-ingestion/connections/conn-1/accounts
    const fetchMock = mockFetchSequence([
      {
        data: {
          success: true,
          connection_id: 'conn-1',
          message: 'OK',
        },
      },
      {
        data: accountsResponse,
      },
    ]);

    render(<TestHarness platform={metaAdsPlatform} />);

    // Initialize the wizard with the meta ads platform
    await act(async () => {
      wizardRef.initWithPlatform(metaAdsPlatform);
    });

    // Simulate OAuth completion (this triggers completeOAuth + auto-loads accounts)
    await act(async () => {
      await wizardRef.handleOAuthComplete({
        code: 'auth-code',
        state: 'csrf-123',
      });
    });

    // Assert: fetch was called with the OAuth callback endpoint
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/sources/oauth/callback'),
        expect.objectContaining({ method: 'POST' }),
      );
    });

    // Assert: fetch was called with the accounts endpoint using the connection ID
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining(
          '/api/ad-platform-ingestion/connections/conn-1/accounts',
        ),
        expect.objectContaining({ method: 'GET' }),
      );
    });

    // Assert: Account name "Summer Campaign" appears in rendered DOM
    await waitFor(() => {
      expect(screen.getByText('Summer Campaign')).toBeInTheDocument();
    });

    // Verify the step moved to 'accounts'
    expect(screen.getByTestId('step')).toHaveTextContent('accounts');

    // Verify the connection ID was set
    expect(screen.getByTestId('connection-id')).toHaveTextContent('conn-1');
  });

  // ---------------------------------------------------------------------------
  // Test 3: Account selection calls updateSelectedAccounts with correct endpoint
  // ---------------------------------------------------------------------------
  it('Account selection calls updateSelectedAccounts with correct endpoint', async () => {
    // First set up the wizard at the accounts step with loaded accounts
    // via completeOAuth + getAvailableAccounts
    const fetchMock = mockFetchSequence([
      // 1. completeOAuth
      {
        data: {
          success: true,
          connection_id: 'conn-1',
          message: 'OK',
        },
      },
      // 2. getAvailableAccounts (auto-loaded for ads platforms)
      {
        data: accountsResponse,
      },
      // 3. updateSelectedAccounts (PUT)
      {
        data: undefined,
      },
    ]);

    render(<TestHarness platform={metaAdsPlatform} />);

    // Initialize and complete OAuth to get to accounts step
    await act(async () => {
      wizardRef.initWithPlatform(metaAdsPlatform);
    });

    await act(async () => {
      await wizardRef.handleOAuthComplete({
        code: 'auth-code',
        state: 'csrf-123',
      });
    });

    // Wait for accounts to be loaded
    await waitFor(() => {
      expect(screen.getByTestId('step')).toHaveTextContent('accounts');
    });

    // Confirm accounts (triggers updateSelectedAccounts PUT call)
    await act(async () => {
      await wizardRef.confirmAccounts();
    });

    // Assert: fetch was called with the correct PUT endpoint and body containing account_ids
    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(
        (c: any[]) =>
          String(c[0]).includes(
            '/api/ad-platform-ingestion/connections/conn-1/accounts',
          ) && c[1]?.method === 'PUT',
      );
      expect(putCalls).toHaveLength(1);

      const body = JSON.parse(putCalls[0][1].body);
      expect(body).toHaveProperty('account_ids');
      expect(body.account_ids).toContain('acc-1');
    });
  });

  // ---------------------------------------------------------------------------
  // Test 4: OAuth failure shows error and retry re-initiates the endpoint call
  // ---------------------------------------------------------------------------
  it('OAuth failure shows error and retry re-initiates the endpoint call', async () => {
    const user = userEvent.setup();

    // First fetch call: network error for initiateOAuth
    const fetchMock = vi.fn();
    fetchMock.mockRejectedValueOnce(new Error('Network error'));
    globalThis.fetch = fetchMock;

    render(
      wrapProviders(
        <ConnectSourceWizard
          open={true}
          platform={metaAdsPlatform}
          onClose={vi.fn()}
        />,
      ),
    );

    // Navigate to OAuth step
    const continueButton = await screen.findByRole('button', {
      name: /Continue with Meta Ads/i,
    });
    await user.click(continueButton);

    // Wait for OAuth step
    const authorizeButton = await screen.findByRole('button', {
      name: /Authorize Meta Ads/i,
    });

    // Click Authorize — this will fail with network error
    await user.click(authorizeButton);

    // Assert: Error message appears in the UI (appears in both parent Banner and OAuthStep Banner)
    await waitFor(() => {
      const errorElements = screen.getAllByText(/Network error/i);
      expect(errorElements.length).toBeGreaterThanOrEqual(1);
    });

    // Now mock fetch to succeed on the retry
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: vi.fn().mockResolvedValue({
        authorization_url: 'https://facebook.com/oauth',
        state: 'csrf-456',
      }),
    });

    // The button should now say "Try Again" since there is an error
    const retryButton = await screen.findByRole('button', {
      name: /Try Again/i,
    });
    await user.click(retryButton);

    // Assert: fetch was called again with the initiate endpoint
    await waitFor(() => {
      const initiateCalls = fetchMock.mock.calls.filter((c: any[]) =>
        String(c[0]).includes('/api/sources/meta_ads/oauth/initiate'),
      );
      expect(initiateCalls.length).toBeGreaterThanOrEqual(2);
    });
  });
});
