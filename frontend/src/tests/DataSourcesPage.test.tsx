/**
 * Unit Tests for DataSources Page
 *
 * Tests the page component with mocked hooks to verify:
 * - Empty state rendering with EmptySourcesState
 * - Connected state rendering with ConnectedSourceCard
 * - Loading skeleton state
 * - Error banner state
 * - Add source CTA visibility
 *
 * Phase 3 — Subphase 3.3: Source Catalog Page
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import type { Source } from '../types/sources';

// Mock hooks
const mockUseDataSources = vi.fn();
const mockUseDataSourceCatalog = vi.fn();

vi.mock('../hooks/useDataSources', () => ({
  useDataSources: () => mockUseDataSources(),
  useDataSourceCatalog: () => mockUseDataSourceCatalog(),
}));

vi.mock('../contexts/DataHealthContext', () => ({
  useDataHealth: () => ({
    refresh: vi.fn(),
  }),
}));

vi.mock('../hooks/useSourceConnection', () => ({
  useSourceMutations: () => ({
    disconnecting: false,
    testing: false,
    configuring: false,
    disconnect: vi.fn(),
    testConnection: vi.fn().mockResolvedValue({ success: true, message: 'OK' }),
    updateSyncConfig: vi.fn(),
    clearError: vi.fn(),
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

import DataSources from '../pages/DataSources';

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
  id: 'shopify',
  platform: 'shopify' as const,
  displayName: 'Shopify',
  description: 'Connect your Shopify store',
  authType: 'oauth' as const,
  category: 'ecommerce' as const,
  isEnabled: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  mockUseDataSourceCatalog.mockReturnValue({
    catalog: [mockCatalogItem],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
});

describe('DataSources Page', () => {
  it('shows empty state when no connections exist', () => {
    mockUseDataSources.mockReturnValue({
      connections: [],
      isLoading: false,
      error: null,
      hasConnectedSources: false,
      refetch: vi.fn(),
    });

    renderWithPolaris(<DataSources />);

    expect(screen.getByText('No data sources connected yet')).toBeInTheDocument();
  });

  it('renders connected source cards when connections exist', () => {
    mockUseDataSources.mockReturnValue({
      connections: [
        createMockSource({ id: 'src-1', displayName: 'Main Store' }),
        createMockSource({ id: 'src-2', displayName: 'Ad Campaign', platform: 'meta_ads' }),
      ],
      isLoading: false,
      error: null,
      hasConnectedSources: true,
      refetch: vi.fn(),
    });

    renderWithPolaris(<DataSources />);

    expect(screen.getByText('Main Store')).toBeInTheDocument();
    expect(screen.getByText('Ad Campaign')).toBeInTheDocument();
    expect(screen.getByText('Connected Sources (2)')).toBeInTheDocument();
  });

  it('shows skeleton loading state', () => {
    mockUseDataSources.mockReturnValue({
      connections: [],
      isLoading: true,
      error: null,
      hasConnectedSources: false,
      refetch: vi.fn(),
    });

    const { container } = renderWithPolaris(<DataSources />);

    // SkeletonPage renders skeleton body text placeholders
    expect(container.querySelector('[class*="SkeletonBodyText"]')).toBeTruthy();
  });

  it('shows error banner on API failure', () => {
    mockUseDataSources.mockReturnValue({
      connections: [],
      isLoading: false,
      error: new Error('Network error'),
      hasConnectedSources: false,
      refetch: vi.fn(),
    });

    renderWithPolaris(<DataSources />);

    expect(screen.getByText('Failed to Load Data Sources')).toBeInTheDocument();
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });

  it('shows "Add New Data Source" CTA when connections exist', () => {
    mockUseDataSources.mockReturnValue({
      connections: [createMockSource()],
      isLoading: false,
      error: null,
      hasConnectedSources: true,
      refetch: vi.fn(),
    });

    renderWithPolaris(<DataSources />);

    expect(screen.getByText('+ Add New Data Source')).toBeInTheDocument();
  });
});
