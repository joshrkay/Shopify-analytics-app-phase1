/**
 * Tests for SuccessStep component
 *
 * Verifies success banner, next steps list, Done and View Dashboard buttons.
 *
 * Phase 3 — Subphase 3.5: Connection Wizard Steps 4-6
 */

import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { SuccessStep } from '../components/sources/steps/SuccessStep';
import type { DataSourceDefinition } from '../types/sourceConnection';

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

const defaultProps = {
  platform: mockPlatform,
  onConnectAnother: vi.fn(),
  onViewDashboard: vi.fn(),
};

describe('SuccessStep', () => {
  it('renders success banner with platform name', () => {
    renderWithPolaris(<SuccessStep {...defaultProps} />);

    expect(screen.getByText('Successfully Connected!')).toBeInTheDocument();
    expect(screen.getByText(/meta ads is now connected/i)).toBeInTheDocument();
  });

  it('calls onConnectAnother when Connect Another Source button is clicked', async () => {
    const user = userEvent.setup();
    const onConnectAnother = vi.fn();

    renderWithPolaris(<SuccessStep {...defaultProps} onConnectAnother={onConnectAnother} />);

    await user.click(screen.getByRole('button', { name: /connect another source/i }));
    expect(onConnectAnother).toHaveBeenCalled();
  });

  it('calls onViewDashboard when Go to Dashboard button is clicked', async () => {
    const user = userEvent.setup();
    const onViewDashboard = vi.fn();

    renderWithPolaris(
      <SuccessStep {...defaultProps} onViewDashboard={onViewDashboard} />,
    );

    await user.click(screen.getByRole('button', { name: /go to dashboard/i }));
    expect(onViewDashboard).toHaveBeenCalled();
  });

  it('renders next steps list', () => {
    renderWithPolaris(<SuccessStep {...defaultProps} />);

    expect(screen.getByText("What's next?")).toBeInTheDocument();
    expect(screen.getByText(/view your dashboard/i)).toBeInTheDocument();
    expect(screen.getByText(/connect another data source/i)).toBeInTheDocument();
  });
});
