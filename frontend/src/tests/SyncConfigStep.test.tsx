/**
 * Tests for SyncConfigStep component
 *
 * Verifies historical range and frequency dropdowns, default values,
 * config change callbacks, and Start Sync button.
 *
 * Phase 3 — Subphase 3.5: Connection Wizard Steps 4-6
 */

import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { SyncConfigStep } from '../components/sources/steps/SyncConfigStep';
import type { DataSourceDefinition, WizardSyncConfig } from '../types/sourceConnection';

const mockTranslations = {
  Polaris: { Common: { ok: 'OK', cancel: 'Cancel' } },
};

const renderWithPolaris = (ui: React.ReactElement) => {
  return render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);
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

const defaultConfig: WizardSyncConfig = {
  historicalRange: '90d',
  frequency: 'hourly',
  enabledMetrics: [],
};

const defaultProps = {
  platform: mockPlatform,
  syncConfig: defaultConfig,
  onUpdateConfig: vi.fn(),
  onConfirm: vi.fn(),
  onBack: vi.fn(),
  loading: false,
};

describe('SyncConfigStep', () => {
  it('renders historical range dropdown', () => {
    renderWithPolaris(<SyncConfigStep {...defaultProps} />);

    expect(screen.getByLabelText(/historical data range/i)).toBeInTheDocument();
  });

  it('renders frequency dropdown', () => {
    renderWithPolaris(<SyncConfigStep {...defaultProps} />);

    expect(screen.getByLabelText(/sync frequency/i)).toBeInTheDocument();
  });

  it('has 90d as default historical range', () => {
    renderWithPolaris(<SyncConfigStep {...defaultProps} />);

    const rangeSelect = screen.getByLabelText(/historical data range/i) as HTMLSelectElement;
    expect(rangeSelect.value).toBe('90d');
  });

  it('calls onConfirm when Start Sync button is clicked', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();

    renderWithPolaris(<SyncConfigStep {...defaultProps} onConfirm={onConfirm} />);

    await user.click(screen.getByRole('button', { name: /start sync/i }));
    expect(onConfirm).toHaveBeenCalled();
  });

  it('shows rate limit info banner', () => {
    renderWithPolaris(<SyncConfigStep {...defaultProps} />);

    expect(screen.getByText(/rate limits and costs/i)).toBeInTheDocument();
  });

  it('"Back" button calls onBack', async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();

    renderWithPolaris(<SyncConfigStep {...defaultProps} onBack={onBack} />);

    await user.click(screen.getByRole('button', { name: /back/i }));
    expect(onBack).toHaveBeenCalled();
  });

  it('frequency default is hourly', () => {
    renderWithPolaris(<SyncConfigStep {...defaultProps} />);

    const frequencySelect = screen.getByLabelText(/sync frequency/i) as HTMLSelectElement;
    expect(frequencySelect.value).toBe('hourly');
  });

  it('shows sync time estimate', () => {
    renderWithPolaris(<SyncConfigStep {...defaultProps} />);

    expect(screen.getByText(/5-10 minutes/i)).toBeInTheDocument();
  });
});
