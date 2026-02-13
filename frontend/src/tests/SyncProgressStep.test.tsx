/**
 * Tests for SyncProgressStep component
 *
 * Verifies progress bar, stage indicators, heading, error banner, and loading state.
 *
 * Phase 3 — Subphase 3.5: Connection Wizard Steps 4-6
 */

import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { SyncProgressStep } from '../components/sources/steps/SyncProgressStep';
import type { DataSourceDefinition, DetailedSyncProgress } from '../types/sourceConnection';

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

const mockProgress: DetailedSyncProgress = {
  connectionId: 'conn-1',
  status: 'running',
  lastSyncAt: null,
  lastSyncStatus: null,
  isEnabled: true,
  canSync: true,
  percentComplete: 50,
  currentStream: null,
  message: null,
};

describe('SyncProgressStep', () => {
  it('renders heading with platform name', () => {
    renderWithPolaris(
      <SyncProgressStep platform={mockPlatform} progress={mockProgress} error={null} />,
    );

    expect(screen.getByText(/syncing your meta ads data/i)).toBeInTheDocument();
  });

  it('renders progress bar', () => {
    const { container } = renderWithPolaris(
      <SyncProgressStep platform={mockPlatform} progress={mockProgress} error={null} />,
    );

    expect(container.querySelector('[class*="ProgressBar"]')).toBeTruthy();
  });

  it('shows stage checklist with status icons', () => {
    renderWithPolaris(
      <SyncProgressStep platform={mockPlatform} progress={mockProgress} error={null} />,
    );

    // Running state: first two completed, third in progress
    expect(screen.getByText('Connected to source')).toBeInTheDocument();
    expect(screen.getByText('Retrieved account information')).toBeInTheDocument();
    expect(screen.getByText('Fetching data')).toBeInTheDocument();
    expect(screen.getByText('Processing metrics')).toBeInTheDocument();
  });

  it('shows error banner when error is present', () => {
    renderWithPolaris(
      <SyncProgressStep
        platform={mockPlatform}
        progress={mockProgress}
        error="Sync failed. Please try again."
      />,
    );

    expect(screen.getByText('Sync failed. Please try again.')).toBeInTheDocument();
  });

  it('renders spinner when progress is null (loading)', () => {
    const { container } = renderWithPolaris(
      <SyncProgressStep platform={mockPlatform} progress={null} error={null} />,
    );

    expect(container.querySelector('[class*="Spinner"]')).toBeTruthy();
  });

  it('"Continue to Dashboard" button calls onNavigateDashboard', async () => {
    const user = userEvent.setup();
    const onNavigateDashboard = vi.fn();

    renderWithPolaris(
      <SyncProgressStep
        platform={mockPlatform}
        progress={mockProgress}
        error={null}
        onNavigateDashboard={onNavigateDashboard}
      />,
    );

    await user.click(screen.getByRole('button', { name: /continue to dashboard/i }));
    expect(onNavigateDashboard).toHaveBeenCalled();
  });

  it('completed stages show ✓ icon', () => {
    const completedProgress: DetailedSyncProgress = {
      ...mockProgress,
      status: 'completed',
      lastSyncStatus: 'succeeded',
      percentComplete: 100,
    };

    renderWithPolaris(
      <SyncProgressStep platform={mockPlatform} progress={completedProgress} error={null} />,
    );

    const checkmarks = screen.getAllByText('✓');
    expect(checkmarks.length).toBe(4);
  });

  it('in-progress stage shows ◎ icon', () => {
    renderWithPolaris(
      <SyncProgressStep platform={mockPlatform} progress={mockProgress} error={null} />,
    );

    expect(screen.getByText('◎')).toBeInTheDocument();
  });

  it('info banner shows explore message', () => {
    renderWithPolaris(
      <SyncProgressStep platform={mockPlatform} progress={mockProgress} error={null} />,
    );

    expect(screen.getByText(/feel free to explore/i)).toBeInTheDocument();
  });
});
