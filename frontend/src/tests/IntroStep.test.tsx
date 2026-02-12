/**
 * Tests for IntroStep component
 *
 * Verifies rendering of platform info, features, permissions, security notice,
 * and Continue/Cancel button callbacks.
 *
 * Phase 3 — Subphase 3.4: Connection Wizard Steps 1-3
 */

import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { IntroStep } from '../components/sources/steps/IntroStep';
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

describe('IntroStep', () => {
  it('renders platform name and description', () => {
    renderWithPolaris(
      <IntroStep platform={mockPlatform} onContinue={vi.fn()} onCancel={vi.fn()} />,
    );

    expect(screen.getByText('Meta Ads')).toBeInTheDocument();
    expect(screen.getByText('Connect your Facebook and Instagram ad accounts')).toBeInTheDocument();
  });

  it('renders feature list items', () => {
    renderWithPolaris(
      <IntroStep platform={mockPlatform} onContinue={vi.fn()} onCancel={vi.fn()} />,
    );

    expect(screen.getByText('Campaign performance metrics')).toBeInTheDocument();
    expect(screen.getByText('Ad spend tracking and ROAS')).toBeInTheDocument();
  });

  it('renders permission list items', () => {
    renderWithPolaris(
      <IntroStep platform={mockPlatform} onContinue={vi.fn()} onCancel={vi.fn()} />,
    );

    expect(screen.getByText('Read access to ad campaigns')).toBeInTheDocument();
    expect(screen.getByText('Read access to ad insights and reporting')).toBeInTheDocument();
  });

  it('renders security notice', () => {
    renderWithPolaris(
      <IntroStep platform={mockPlatform} onContinue={vi.fn()} onCancel={vi.fn()} />,
    );

    expect(screen.getByText(/encrypted and secure/i)).toBeInTheDocument();
  });

  it('calls onContinue when Continue button is clicked', async () => {
    const user = userEvent.setup();
    const onContinue = vi.fn();

    renderWithPolaris(
      <IntroStep platform={mockPlatform} onContinue={onContinue} onCancel={vi.fn()} />,
    );

    await user.click(screen.getByRole('button', { name: /continue with meta ads/i }));
    expect(onContinue).toHaveBeenCalled();
  });

  it('calls onCancel when Cancel button is clicked', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();

    renderWithPolaris(
      <IntroStep platform={mockPlatform} onContinue={vi.fn()} onCancel={onCancel} />,
    );

    await user.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalled();
  });
});
