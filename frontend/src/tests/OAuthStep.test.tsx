/**
 * Tests for OAuthStep component
 *
 * Verifies OAuth authorization UI, loading state, error handling,
 * and button callbacks.
 *
 * Phase 3 — Subphase 3.4: Connection Wizard Steps 1-3
 */

import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { OAuthStep } from '../components/sources/steps/OAuthStep';
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

describe('OAuthStep', () => {
  it('renders authorization heading with platform name', () => {
    renderWithPolaris(
      <OAuthStep
        platform={mockPlatform}
        loading={false}
        error={null}
        onStartOAuth={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const elements = screen.getAllByText('Authorize Meta Ads');
    expect(elements.length).toBeGreaterThanOrEqual(1);
  });

  it('shows spinner when loading', () => {
    const { container } = renderWithPolaris(
      <OAuthStep
        platform={mockPlatform}
        loading={true}
        error={null}
        onStartOAuth={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(container.querySelector('[class*="Spinner"]')).toBeTruthy();
    expect(screen.getByText(/redirecting to meta ads/i)).toBeInTheDocument();
  });

  it('shows error banner when error is present', () => {
    renderWithPolaris(
      <OAuthStep
        platform={mockPlatform}
        loading={false}
        error="Popup was blocked"
        onStartOAuth={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('Popup was blocked')).toBeInTheDocument();
    expect(screen.getByText('Authorization Failed')).toBeInTheDocument();
  });

  it('calls onStartOAuth when Authorize button is clicked', async () => {
    const user = userEvent.setup();
    const onStartOAuth = vi.fn().mockResolvedValue(undefined);

    renderWithPolaris(
      <OAuthStep
        platform={mockPlatform}
        loading={false}
        error={null}
        onStartOAuth={onStartOAuth}
        onCancel={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: /authorize meta ads/i }));
    expect(onStartOAuth).toHaveBeenCalled();
  });

  it('shows "Try Again" text on button when error is present', () => {
    renderWithPolaris(
      <OAuthStep
        platform={mockPlatform}
        loading={false}
        error="Something went wrong"
        onStartOAuth={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('shows 4-step OAuth explanation when not loading', () => {
    renderWithPolaris(
      <OAuthStep
        platform={mockPlatform}
        loading={false}
        error={null}
        onStartOAuth={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText(/click "authorize" below/i)).toBeInTheDocument();
    expect(screen.getByText(/sign in and grant read-only access/i)).toBeInTheDocument();
    expect(screen.getByText(/redirected back here automatically/i)).toBeInTheDocument();
    expect(screen.getByText(/select which accounts to sync/i)).toBeInTheDocument();
  });

  it('retry button calls onStartOAuth again after error', async () => {
    const user = userEvent.setup();
    const onStartOAuth = vi.fn().mockResolvedValue(undefined);

    renderWithPolaris(
      <OAuthStep
        platform={mockPlatform}
        loading={false}
        error="Authorization failed"
        onStartOAuth={onStartOAuth}
        onCancel={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: /try again/i }));
    expect(onStartOAuth).toHaveBeenCalledTimes(1);
  });
});
