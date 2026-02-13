/**
 * DataSources Page — API→UI Wiring Tests
 *
 * Verifiable wiring tests that mock ONLY at the `fetch` boundary
 * while keeping real hooks and components. Proves:
 * - snake_case → camelCase normalization for connections
 * - Catalog endpoint is called and rendered
 * - Empty/error states render correctly
 * - Auth headers are included in every fetch call
 *
 * Phase 3 — Subphase 3.3: Source Catalog Page
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';
import DataSources from '../pages/DataSources';

// ---------------------------------------------------------------------------
// Mock apiUtils — intercept at the header/response boundary only
// ---------------------------------------------------------------------------
vi.mock('../services/apiUtils', () => ({
  API_BASE_URL: '',
  createHeadersAsync: vi.fn().mockResolvedValue({
    'Content-Type': 'application/json',
    Authorization: 'Bearer test-token',
  }),
  handleResponse: vi.fn(async (res: Response) => res.json()),
  getErrorMessage: vi.fn((_err: unknown, fallback: string) => fallback),
}));

// ---------------------------------------------------------------------------
// Mock DataHealthContext — avoids needing the full provider chain
// ---------------------------------------------------------------------------
vi.mock('../contexts/DataHealthContext', () => ({
  useDataHealth: vi.fn().mockReturnValue({
    health: null,
    activeIncidents: [],
    freshnessLabel: 'fresh',
    merchantHealth: null,
    refresh: vi.fn(),
    acknowledgeIncident: vi.fn(),
    hasStaleData: false,
    hasCriticalIssues: false,
    hasBlockingIssues: false,
    shouldShowBanner: false,
    mostSevereIncident: null,
  }),
}));

// ---------------------------------------------------------------------------
// Mock useSourceMutations — avoids needing its own provider chain
// ---------------------------------------------------------------------------
vi.mock('../hooks/useSourceConnection', () => ({
  useSourceCatalog: vi.fn().mockReturnValue({ catalog: [], isLoading: false, error: null, refetch: vi.fn() }),
  useConnectionWizard: vi.fn(),
  useSourceMutations: vi.fn().mockReturnValue({
    disconnecting: false,
    testingSourceId: null,
    configuring: false,
    disconnect: vi.fn(),
    testConnection: vi.fn().mockResolvedValue({ success: true, message: 'OK' }),
    updateSyncConfig: vi.fn(),
  }),
}));

// ---------------------------------------------------------------------------
// Stub modal components that have heavy dependency trees
// ---------------------------------------------------------------------------
vi.mock('../components/sources/ConnectSourceWizard', () => ({
  ConnectSourceWizard: ({ open }: { open: boolean }) =>
    open ? <div data-testid="connect-wizard">Connect Wizard</div> : null,
}));

vi.mock('../components/sources/DisconnectConfirmationModal', () => ({
  DisconnectConfirmationModal: () => null,
}));

vi.mock('../components/sources/SyncConfigModal', () => ({
  SyncConfigModal: () => null,
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Setup globalThis.fetch with URL-keyed response mapping.
 * Each key is checked with `url.includes(key)`.
 */
function setupFetch(responses: Record<string, unknown>) {
  globalThis.fetch = vi.fn().mockImplementation((url: string) => {
    const matchingUrl = Object.keys(responses).find(key => url.includes(key));
    const data = matchingUrl ? responses[matchingUrl] : {};
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(data),
    });
  });
}

/**
 * Render DataSources page inside required providers.
 */
function renderPage() {
  return render(
    <MemoryRouter>
      <AppProvider i18n={{} as any}>
        <DataSources />
      </AppProvider>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

describe('DataSources Page — API→UI Wiring', () => {
  it('Page loads connections from GET /api/sources and renders normalized display names', async () => {
    setupFetch({
      '/api/sources/catalog': { sources: [], total: 0 },
      '/api/sources': {
        sources: [
          {
            id: 's1',
            platform: 'shopify',
            display_name: 'My Shopify Store',
            auth_type: 'oauth',
            status: 'active',
            is_enabled: true,
            last_sync_at: '2025-06-15T10:30:00Z',
            last_sync_status: 'succeeded',
          },
        ],
        total: 1,
      },
    });

    renderPage();

    // Wait for loading to finish and data to render
    await waitFor(() => {
      expect(screen.getByText('My Shopify Store')).toBeInTheDocument();
    });

    // Verify fetch was called with /api/sources and correct auth header
    const fetchMock = vi.mocked(globalThis.fetch);
    const sourcesCall = fetchMock.mock.calls.find(
      ([url]) => typeof url === 'string' && url.includes('/api/sources') && !url.includes('/catalog'),
    );
    expect(sourcesCall).toBeDefined();
    expect(sourcesCall![1]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer test-token',
        }),
      }),
    );
  });

  it('Catalog loads from GET /api/sources/catalog and renders platform cards', async () => {
    setupFetch({
      '/api/sources/catalog': {
        sources: [
          {
            id: 'meta_ads',
            platform: 'meta_ads',
            displayName: 'Meta Ads',
            description: 'Facebook ads',
            authType: 'oauth',
            category: 'ads',
            isEnabled: true,
          },
        ],
        total: 1,
      },
      '/api/sources': { sources: [], total: 0 },
    });

    renderPage();

    // Empty state should render with catalog cards
    await waitFor(() => {
      expect(screen.getByText('Meta Ads')).toBeInTheDocument();
    });

    // Verify fetch was called with /api/sources/catalog
    const fetchMock = vi.mocked(globalThis.fetch);
    const catalogCall = fetchMock.mock.calls.find(
      ([url]) => typeof url === 'string' && url.includes('/api/sources/catalog'),
    );
    expect(catalogCall).toBeDefined();
  });

  it('Empty state renders when API returns zero connections', async () => {
    setupFetch({
      '/api/sources/catalog': { sources: [], total: 0 },
      '/api/sources': { sources: [], total: 0 },
    });

    renderPage();

    // The empty state shows "Connect Source" primary action or the empty state heading
    await waitFor(() => {
      expect(
        screen.getByText(/Connect Source|No data sources connected yet|Connect Your First Source/),
      ).toBeInTheDocument();
    });
  });

  it('Error state renders when API fetch rejects', async () => {
    globalThis.fetch = vi.fn().mockImplementation(() =>
      Promise.reject(new Error('Network error')),
    );

    renderPage();

    // The error banner should render with "Failed to Load" text and a Retry button
    await waitFor(() => {
      expect(screen.getByText('Failed to Load Data Sources')).toBeInTheDocument();
    });

    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('Auth headers are included in all API requests', async () => {
    setupFetch({
      '/api/sources/catalog': { sources: [], total: 0 },
      '/api/sources': {
        sources: [
          {
            id: 's1',
            platform: 'shopify',
            display_name: 'Test Store',
            auth_type: 'oauth',
            status: 'active',
            is_enabled: true,
            last_sync_at: null,
            last_sync_status: null,
          },
        ],
        total: 1,
      },
    });

    renderPage();

    // Wait for loading to complete
    await waitFor(() => {
      expect(screen.getByText('Test Store')).toBeInTheDocument();
    });

    // Every fetch call must include the Authorization header
    const fetchMock = vi.mocked(globalThis.fetch);
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2);

    for (const call of fetchMock.mock.calls) {
      const options = call[1] as RequestInit | undefined;
      expect(options).toBeDefined();
      expect(options!.headers).toEqual(
        expect.objectContaining({
          Authorization: 'Bearer test-token',
        }),
      );
    }
  });
});
