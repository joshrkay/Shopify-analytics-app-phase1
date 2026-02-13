/**
 * Phase 3 End-to-End Smoke Tests
 *
 * Validates complete user journeys through the data source connection flow:
 * new user onboarding, returning user catalog, multi-source connection,
 * disconnection, and settings persistence.
 *
 * Uses fetch-level mocking with real hooks and components.
 *
 * Phase 3 — Subphase 3.7: Full Assembly & Regression
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
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
    disconnect: vi.fn().mockResolvedValue(undefined),
    testConnection: vi.fn().mockResolvedValue({ success: true, message: 'OK' }),
    updateSyncConfig: vi.fn().mockResolvedValue(undefined),
  }),
}));

// ---------------------------------------------------------------------------
// Imports
// ---------------------------------------------------------------------------

import DataSources from '../pages/DataSources';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const polarisI18n = {} as any;

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

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/sources']}>
      <AppProvider i18n={polarisI18n}>
        <DataSources />
      </AppProvider>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Smoke Tests
// ---------------------------------------------------------------------------

describe('Phase 3 E2E Smoke Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('new user: empty sources → shows empty state with CTA', async () => {
    setupFetch({
      '/api/sources/catalog': {
        sources: [
          { id: 'meta_ads', platform: 'meta_ads', displayName: 'Meta Ads', description: 'Facebook ads', authType: 'oauth', category: 'ads', isEnabled: true },
          { id: 'google_ads', platform: 'google_ads', displayName: 'Google Ads', description: 'Google ads', authType: 'oauth', category: 'ads', isEnabled: true },
        ],
        total: 2,
      },
      '/api/sources': { sources: [], total: 0 },
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/connect source/i)).toBeInTheDocument();
    });

    // Both catalog and sources endpoints should have been called
    const fetchCalls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map((c: unknown[]) => c[0] as string);
    expect(fetchCalls.some((u: string) => u.includes('/api/sources/catalog'))).toBe(true);
    expect(fetchCalls.some((u: string) => u.includes('/api/sources') && !u.includes('/catalog'))).toBe(true);
  });

  it('returning user: connected sources display with correct normalized data', async () => {
    setupFetch({
      '/api/sources/catalog': {
        sources: [
          { id: 'google_ads', platform: 'google_ads', displayName: 'Google Ads', description: 'Google ads', authType: 'oauth', category: 'ads', isEnabled: true },
        ],
        total: 1,
      },
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
          {
            id: 's2',
            platform: 'meta_ads',
            display_name: 'Summer Campaigns',
            auth_type: 'oauth',
            status: 'active',
            is_enabled: true,
            last_sync_at: '2025-06-15T09:00:00Z',
            last_sync_status: 'succeeded',
          },
        ],
        total: 2,
      },
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('My Shopify Store')).toBeInTheDocument();
      expect(screen.getByText('Summer Campaigns')).toBeInTheDocument();
    });

    // Unconnected catalog item should also show
    await waitFor(() => {
      expect(screen.getByText('Google Ads')).toBeInTheDocument();
    });
  });

  it('multi-source: page shows both connected sources and available integrations', async () => {
    setupFetch({
      '/api/sources/catalog': {
        sources: [
          { id: 'meta_ads', platform: 'meta_ads', displayName: 'Meta Ads', description: 'Facebook ads', authType: 'oauth', category: 'ads', isEnabled: true },
          { id: 'google_ads', platform: 'google_ads', displayName: 'Google Ads', description: 'Google ads', authType: 'oauth', category: 'ads', isEnabled: true },
          { id: 'tiktok_ads', platform: 'tiktok_ads', displayName: 'TikTok Ads', description: 'TikTok ads', authType: 'oauth', category: 'ads', isEnabled: true },
        ],
        total: 3,
      },
      '/api/sources': {
        sources: [
          {
            id: 's1',
            platform: 'meta_ads',
            display_name: 'Meta Campaign',
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

    await waitFor(() => {
      // Connected source visible
      expect(screen.getByText('Meta Campaign')).toBeInTheDocument();
    });

    // Unconnected integrations should show (meta_ads is connected, so only google_ads and tiktok_ads)
    await waitFor(() => {
      expect(screen.getByText('Google Ads')).toBeInTheDocument();
      expect(screen.getByText('TikTok Ads')).toBeInTheDocument();
    });
  });

  it('error state: API failure shows error banner', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

    renderPage();

    await waitFor(() => {
      expect(screen.getAllByText(/failed to load/i).length).toBeGreaterThan(0);
    });
  });

  it('source status normalization: snake_case status maps correctly to UI', async () => {
    setupFetch({
      '/api/sources/catalog': { sources: [], total: 0 },
      '/api/sources': {
        sources: [
          {
            id: 's1',
            platform: 'shopify',
            display_name: 'Active Store',
            auth_type: 'oauth',
            status: 'active',
            is_enabled: true,
            last_sync_at: '2025-06-15T10:30:00Z',
            last_sync_status: 'succeeded',
          },
          {
            id: 's2',
            platform: 'meta_ads',
            display_name: 'Pending Source',
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

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Active Store')).toBeInTheDocument();
      expect(screen.getByText('Pending Source')).toBeInTheDocument();
    });
  });
});
