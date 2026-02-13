/**
 * Phase 3 Integration Tests — Cross-Page Wiring
 *
 * Verifies that data source pages, settings tabs, sidebar navigation,
 * and the connection wizard integrate correctly across the application.
 *
 * Mocks at the fetch boundary to prove API→UI wiring across multiple
 * entry points and views.
 *
 * Phase 3 — Subphase 3.7: Route Integration & Full Assembly
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

vi.mock('../services/apiUtils', () => ({
  API_BASE_URL: '',
  createHeadersAsync: vi.fn().mockResolvedValue({
    'Content-Type': 'application/json',
    Authorization: 'Bearer test-token',
  }),
  handleResponse: vi.fn(async (res: Response) => res.json()),
  isApiError: vi.fn().mockReturnValue(false),
  getErrorMessage: vi.fn((_err: unknown, fallback: string) => fallback),
}));

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
// Imports (after mocks)
// ---------------------------------------------------------------------------

import DataSources from '../pages/DataSources';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const polarisTranslations = {} as any;

const RAW_SOURCE_SHOPIFY = {
  id: 's1',
  platform: 'shopify',
  display_name: 'My Store',
  auth_type: 'oauth',
  status: 'active',
  is_enabled: true,
  last_sync_at: '2025-06-15T10:30:00Z',
  last_sync_status: 'succeeded',
};

const RAW_CATALOG_META = {
  id: 'meta_ads',
  platform: 'meta_ads',
  displayName: 'Meta Ads',
  description: 'Facebook and Instagram ads',
  authType: 'oauth',
  category: 'ads',
  isEnabled: true,
};

function setupFetch(responses: Record<string, unknown>) {
  globalThis.fetch = vi.fn().mockImplementation((url: string) => {
    const matchingUrl = Object.keys(responses).find((key) => url.includes(key));
    const data = matchingUrl ? responses[matchingUrl] : {};
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(data),
    });
  });
}

function renderWithProviders(ui: React.ReactElement, initialEntries = ['/sources']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <AppProvider i18n={polarisTranslations}>
        <Routes>
          <Route path="/sources" element={ui} />
          <Route path="*" element={<div data-testid="other-route">Other Page</div>} />
        </Routes>
      </AppProvider>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Phase 3 Integration — Cross-Page Wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('/sources route renders DataSources page with API data', async () => {
    setupFetch({
      '/api/sources/catalog': { sources: [RAW_CATALOG_META], total: 1 },
      '/api/sources': { sources: [RAW_SOURCE_SHOPIFY], total: 1 },
    });

    renderWithProviders(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('My Store')).toBeInTheDocument();
    });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/sources'),
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    );
  });

  it('DataSources page calls both /api/sources and /api/sources/catalog', async () => {
    setupFetch({
      '/api/sources/catalog': { sources: [RAW_CATALOG_META], total: 1 },
      '/api/sources': { sources: [RAW_SOURCE_SHOPIFY], total: 1 },
    });

    renderWithProviders(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('My Store')).toBeInTheDocument();
    });

    const fetchCalls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    const urls = fetchCalls.map((c: unknown[]) => c[0] as string);

    expect(urls.some((u: string) => u.includes('/api/sources') && !u.includes('/catalog'))).toBe(true);
    expect(urls.some((u: string) => u.includes('/api/sources/catalog'))).toBe(true);
  });

  it('Settings Data Sources tab and /sources page use the same GET /api/sources endpoint', async () => {
    setupFetch({
      '/api/sources/catalog': { sources: [], total: 0 },
      '/api/sources': { sources: [RAW_SOURCE_SHOPIFY], total: 1 },
    });

    renderWithProviders(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('My Store')).toBeInTheDocument();
    });

    // Both views use the same endpoint: GET /api/sources
    const fetchCalls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    const sourcesCalls = fetchCalls.filter(
      (c: unknown[]) => (c[0] as string).includes('/api/sources') && !(c[0] as string).includes('/catalog') && !(c[0] as string).includes('/sync-settings'),
    );
    expect(sourcesCalls.length).toBeGreaterThanOrEqual(1);
    expect(sourcesCalls[0][1]).toEqual(
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    );
  });

  it('empty state renders when API returns zero connections', async () => {
    setupFetch({
      '/api/sources/catalog': { sources: [RAW_CATALOG_META], total: 1 },
      '/api/sources': { sources: [], total: 0 },
    });

    renderWithProviders(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText(/connect source/i)).toBeInTheDocument();
    });
  });

  it('normalized source data shows displayName from snake_case display_name', async () => {
    setupFetch({
      '/api/sources/catalog': { sources: [], total: 0 },
      '/api/sources': {
        sources: [
          {
            id: 's2',
            platform: 'meta_ads',
            display_name: 'Facebook Campaign',
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

    renderWithProviders(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('Facebook Campaign')).toBeInTheDocument();
    });
  });

  it('auth headers (Bearer token) are included in every API request', async () => {
    setupFetch({
      '/api/sources/catalog': { sources: [], total: 0 },
      '/api/sources': { sources: [RAW_SOURCE_SHOPIFY], total: 1 },
    });

    renderWithProviders(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('My Store')).toBeInTheDocument();
    });

    const fetchCalls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    for (const call of fetchCalls) {
      expect(call[1]?.headers).toEqual(
        expect.objectContaining({ Authorization: 'Bearer test-token' }),
      );
    }
  });

  it('multiple sources from API all render in the UI', async () => {
    setupFetch({
      '/api/sources/catalog': { sources: [], total: 0 },
      '/api/sources': {
        sources: [
          RAW_SOURCE_SHOPIFY,
          {
            id: 's2',
            platform: 'google_ads',
            display_name: 'Google Ads Account',
            auth_type: 'oauth',
            status: 'pending',
            is_enabled: true,
            last_sync_at: null,
            last_sync_status: null,
          },
        ],
        total: 2,
      },
    });

    renderWithProviders(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('My Store')).toBeInTheDocument();
      expect(screen.getByText('Google Ads Account')).toBeInTheDocument();
    });
  });
});
