/**
 * Integration Tests for DataSources Page
 *
 * Tests end-to-end data flow with mocked API at the service level:
 * - Page loads connections from API and renders cards
 * - Clicking Connect opens wizard modal
 * - Test Connection button calls API and shows result
 *
 * Phase 3 — Subphase 3.3: Source Catalog Page
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import type { Source } from '../types/sources';

// Mock at service level — hooks use real code
vi.mock('../services/dataSourcesApi', () => ({
  getConnections: vi.fn(),
  getAvailableSources: vi.fn(),
  listSources: vi.fn(),
  getConnection: vi.fn(),
  getSyncProgress: vi.fn(),
  initiateOAuth: vi.fn(),
  completeOAuth: vi.fn(),
  disconnectSource: vi.fn(),
  testConnection: vi.fn(),
  updateSyncConfig: vi.fn(),
  getGlobalSyncSettings: vi.fn(),
  updateGlobalSyncSettings: vi.fn(),
}));

vi.mock('../services/sourcesApi', () => ({
  listSources: vi.fn(),
  getAvailableSources: vi.fn(),
  initiateOAuth: vi.fn(),
  completeOAuth: vi.fn(),
  disconnectSource: vi.fn(),
  testConnection: vi.fn(),
  updateSyncConfig: vi.fn(),
}));

vi.mock('../contexts/DataHealthContext', () => ({
  useDataHealth: () => ({
    refresh: vi.fn(),
  }),
}));

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}));

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

import * as dataSourcesApi from '../services/dataSourcesApi';
import DataSources from '../pages/DataSources';

const mockedApi = vi.mocked(dataSourcesApi);

const mockTranslations = {
  Polaris: { Common: { ok: 'OK', cancel: 'Cancel' } },
};

const renderWithPolaris = (ui: React.ReactElement) => {
  return render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);
};

const createMockSource = (overrides?: Partial<Source>): Source => ({
  id: 'src-001',
  platform: 'shopify',
  displayName: 'My Shopify Store',
  authType: 'oauth',
  status: 'active',
  isEnabled: true,
  lastSyncAt: '2025-06-15T10:30:00Z',
  lastSyncStatus: 'succeeded',
  ...overrides,
});

const mockCatalogItem = {
  id: 'meta_ads',
  platform: 'meta_ads' as const,
  displayName: 'Meta Ads',
  description: 'Connect your Facebook ad accounts',
  authType: 'oauth' as const,
  category: 'ads' as const,
  isEnabled: true,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('DataSources Page Integration', () => {
  it('page loads connections from API and renders cards', async () => {
    const sources = [
      createMockSource({ id: 'src-1', displayName: 'Main Store' }),
      createMockSource({ id: 'src-2', displayName: 'Ad Account', platform: 'meta_ads' }),
    ];

    mockedApi.getConnections.mockResolvedValue(sources);
    mockedApi.getAvailableSources.mockResolvedValue([mockCatalogItem]);

    renderWithPolaris(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('Main Store')).toBeInTheDocument();
    });

    expect(screen.getByText('Ad Account')).toBeInTheDocument();
    expect(screen.getByText('Connected Sources (2)')).toBeInTheDocument();
  });

  it('clicking Add Source button opens wizard modal', async () => {
    const user = userEvent.setup();

    mockedApi.getConnections.mockResolvedValue([createMockSource()]);
    mockedApi.getAvailableSources.mockResolvedValue([mockCatalogItem]);

    renderWithPolaris(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('My Shopify Store')).toBeInTheDocument();
    });

    // Click the "Add Source" primary action
    await user.click(screen.getByRole('button', { name: 'Add Source' }));

    expect(screen.getByTestId('connect-wizard')).toBeInTheDocument();
  });

  it('empty state renders when no connections and shows catalog', async () => {
    mockedApi.getConnections.mockResolvedValue([]);
    mockedApi.getAvailableSources.mockResolvedValue([mockCatalogItem]);

    renderWithPolaris(<DataSources />);

    await waitFor(() => {
      expect(screen.getByText('No data sources connected yet')).toBeInTheDocument();
    });

    expect(screen.getByText('Meta Ads')).toBeInTheDocument();
  });
});
