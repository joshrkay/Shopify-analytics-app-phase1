/**
 * Integration Tests for ConnectSourceWizard
 *
 * Tests wizard modal rendering, step progression, error handling,
 * platform-conditional routing, and callbacks.
 *
 * Phase 3 — Subphase 3.4/3.5: Connection Wizard Integration
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

import { AppProvider } from '@shopify/polaris';
import { MemoryRouter } from 'react-router-dom';
import '@shopify/polaris/build/esm/styles.css';

import type { DataSourceDefinition } from '../types/sourceConnection';

// Mock the wizard hook
const mockWizardState = {
  step: 'intro' as const,
  platform: null as DataSourceDefinition | null,
  connectionId: null as string | null,
  oauthState: null,
  accounts: [],
  selectedAccountIds: [],
  syncConfig: { historicalRange: '90d' as const, frequency: 'hourly' as const, enabledMetrics: [] },
  syncProgress: null,
  error: null as string | null,
  loading: false,
};

const mockWizardActions = {
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

let currentState = { ...mockWizardState };

vi.mock('../hooks/useConnectSourceWizard', () => ({
  useConnectSourceWizard: () => ({
    state: currentState,
    ...mockWizardActions,
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

beforeEach(() => {
  vi.clearAllMocks();
  currentState = { ...mockWizardState, platform: mockPlatform };
});

describe('ConnectSourceWizard', () => {
  it('renders intro step when open with platform', () => {
    renderWithProviders(
      <ConnectSourceWizard
        open={true}
        platform={mockPlatform}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );

    expect(screen.getByText('Meta Ads')).toBeInTheDocument();
    expect(screen.getByText(/connect your facebook/i)).toBeInTheDocument();
  });

  it('calls initWithPlatform when modal opens', () => {
    renderWithProviders(
      <ConnectSourceWizard
        open={true}
        platform={mockPlatform}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );

    expect(mockWizardActions.initWithPlatform).toHaveBeenCalledWith(mockPlatform);
  });

  it('renders oauth step when state.step is oauth', () => {
    currentState = { ...mockWizardState, platform: mockPlatform, step: 'oauth' };

    renderWithProviders(
      <ConnectSourceWizard
        open={true}
        platform={mockPlatform}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );

    const authorizeElements = screen.getAllByText('Authorize Meta Ads');
    expect(authorizeElements.length).toBeGreaterThanOrEqual(1);
  });

  it('renders accounts step when state.step is accounts', () => {
    currentState = {
      ...mockWizardState,
      platform: mockPlatform,
      step: 'accounts',
      accounts: [
        { id: 'acc-1', accountId: 'act_111', accountName: 'Test Account', platform: 'meta_ads', isEnabled: true, last30dSpend: 250.00 },
      ],
      selectedAccountIds: ['acc-1'],
    };

    renderWithProviders(
      <ConnectSourceWizard
        open={true}
        platform={mockPlatform}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );

    expect(screen.getByText('Select Accounts')).toBeInTheDocument();
    expect(screen.getByText('Test Account')).toBeInTheDocument();
  });

  it('renders syncConfig step when state.step is syncConfig', () => {
    currentState = { ...mockWizardState, platform: mockPlatform, step: 'syncConfig' };

    renderWithProviders(
      <ConnectSourceWizard
        open={true}
        platform={mockPlatform}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );

    expect(screen.getByText('Configure Sync')).toBeInTheDocument();
  });

  it('renders success step when state.step is success', () => {
    currentState = {
      ...mockWizardState,
      platform: mockPlatform,
      step: 'success',
      connectionId: 'conn-123',
    };

    renderWithProviders(
      <ConnectSourceWizard
        open={true}
        platform={mockPlatform}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );

    expect(screen.getByText('Successfully Connected!')).toBeInTheDocument();
  });

  it('shows error banner when state.error is set', () => {
    currentState = {
      ...mockWizardState,
      platform: mockPlatform,
      step: 'oauth',
      error: 'Something went wrong',
    };

    renderWithProviders(
      <ConnectSourceWizard
        open={true}
        platform={mockPlatform}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );

    // Error shown in both the wizard banner and the OAuthStep error
    const errorElements = screen.getAllByText('Something went wrong');
    expect(errorElements.length).toBeGreaterThanOrEqual(1);
  });

  it('does not render modal content when open is false', () => {
    renderWithProviders(
      <ConnectSourceWizard
        open={false}
        platform={mockPlatform}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );

    // Modal should not be visible when open=false
    expect(screen.queryByText('Meta Ads')).not.toBeInTheDocument();
  });
});
