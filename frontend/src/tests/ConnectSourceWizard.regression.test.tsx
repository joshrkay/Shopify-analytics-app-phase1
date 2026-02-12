/**
 * Regression Tests for ConnectSourceWizard
 *
 * Verifies the new wizard doesn't break existing functionality:
 * - Popup blocked handling
 * - Empty accounts handling
 * - Sync failure handling
 * - API timeout handling
 *
 * Phase 3 — Subphase 3.4/3.5: Regression Tests
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AppProvider } from '@shopify/polaris';
import { MemoryRouter } from 'react-router-dom';
import '@shopify/polaris/build/esm/styles.css';

import type { DataSourceDefinition } from '../types/sourceConnection';

// Mock the wizard hook with configurable state
let currentState: any;
const mockActions = {
  initWithPlatform: vi.fn(),
  proceedFromIntro: vi.fn(),
  startOAuth: vi.fn().mockResolvedValue(undefined),
  handleOAuthComplete: vi.fn().mockResolvedValue(undefined),
  loadAccounts: vi.fn().mockResolvedValue(undefined),
  toggleAccount: vi.fn(),
  selectAllAccounts: vi.fn(),
  deselectAllAccounts: vi.fn(),
  confirmAccounts: vi.fn().mockResolvedValue(undefined),
  updateWizardSyncConfig: vi.fn(),
  confirmSyncConfig: vi.fn().mockResolvedValue(undefined),
  goBack: vi.fn(),
  setError: vi.fn(),
  reset: vi.fn(),
};

vi.mock('../hooks/useConnectSourceWizard', () => ({
  useConnectSourceWizard: () => ({
    state: currentState,
    ...mockActions,
  }),
}));

vi.mock('../hooks/useDataSources', () => ({
  useSyncProgress: () => ({
    progress: null,
    isLoading: false,
    error: null,
  }),
}));

import { ConnectSourceWizard } from '../components/sources/ConnectSourceWizard';

const mockTranslations = {
  Polaris: { Common: { ok: 'OK', cancel: 'Cancel' } },
};

const renderWithProviders = (ui: React.ReactElement) => {
  return render(
    <MemoryRouter>
      <AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>
    </MemoryRouter>,
  );
};

const mockPlatform: DataSourceDefinition = {
  id: 'meta_ads',
  platform: 'meta_ads',
  displayName: 'Meta Ads',
  description: 'Connect your Facebook and Instagram ad accounts',
  authType: 'oauth',
  category: 'ads',
  isEnabled: true,
};

const baseState = {
  platform: mockPlatform,
  connectionId: null,
  oauthState: null,
  accounts: [],
  selectedAccountIds: [],
  syncConfig: { historicalRange: '90d' as const, frequency: 'hourly' as const, enabledMetrics: [] },
  error: null,
  loading: false,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ConnectSourceWizard Regression', () => {
  it('R1: handles popup blocked gracefully with error state', () => {
    currentState = {
      ...baseState,
      step: 'oauth',
      error: 'Popup was blocked. Please allow popups and try again.',
    };

    renderWithProviders(
      <ConnectSourceWizard
        open={true}
        platform={mockPlatform}
        onClose={vi.fn()}
      />,
    );

    const popupErrors = screen.getAllByText(/popup was blocked/i);
    expect(popupErrors.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('R2: handles empty accounts list gracefully', () => {
    currentState = {
      ...baseState,
      step: 'accounts',
      connectionId: 'conn-123',
      accounts: [],
      selectedAccountIds: [],
    };

    renderWithProviders(
      <ConnectSourceWizard
        open={true}
        platform={mockPlatform}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText(/no accounts found/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /back/i })).toBeInTheDocument();
  });

  it('R3: handles sync failure with error banner', () => {
    currentState = {
      ...baseState,
      step: 'syncing',
      connectionId: 'conn-123',
      error: 'Sync failed. Please try again or check your connection.',
    };

    renderWithProviders(
      <ConnectSourceWizard
        open={true}
        platform={mockPlatform}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText(/sync failed/i)).toBeInTheDocument();
  });

  it('R4: handles API timeout on OAuth with error state', () => {
    currentState = {
      ...baseState,
      step: 'oauth',
      error: 'Failed to start authorization',
      loading: false,
    };

    renderWithProviders(
      <ConnectSourceWizard
        open={true}
        platform={mockPlatform}
        onClose={vi.fn()}
      />,
    );

    const errorElements = screen.getAllByText('Failed to start authorization');
    expect(errorElements.length).toBeGreaterThanOrEqual(1);
    // Retry button should be available
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });
});
