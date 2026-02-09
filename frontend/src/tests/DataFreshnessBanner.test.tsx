/**
 * Tests for DataFreshnessBanner component
 *
 * Validates merchant-visible freshness banner rendering:
 * - Returns null for fresh state (no banner shown)
 * - Shows warning banner for stale state
 * - Shows critical banner for unavailable state
 * - Displays affected sources
 * - Shows retry action for unavailable + onRetry
 * - Shows tooltip with reason explanation
 */

import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AppProvider } from '@shopify/polaris';

import { DataFreshnessBanner } from '../components/DataFreshnessBanner';

const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

const renderWithPolaris = (ui: React.ReactElement) => {
  return render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);
};

// =============================================================================
// Fresh state (no banner)
// =============================================================================

describe('DataFreshnessBanner - fresh state', () => {
  it('returns null and renders no banner', () => {
    renderWithPolaris(<DataFreshnessBanner state="fresh" />);
    // Banner component returns null for fresh — no alert role rendered
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

// =============================================================================
// Stale state
// =============================================================================

describe('DataFreshnessBanner - stale state', () => {
  it('renders a banner with stale title', () => {
    renderWithPolaris(<DataFreshnessBanner state="stale" />);
    expect(screen.getByText('Data Update in Progress')).toBeInTheDocument();
  });

  it('shows default stale message when no reason provided', () => {
    renderWithPolaris(<DataFreshnessBanner state="stale" />);
    expect(screen.getByText(/refreshed/)).toBeInTheDocument();
  });

  it('shows SLA-specific message for sla_exceeded reason', () => {
    renderWithPolaris(
      <DataFreshnessBanner state="stale" reason="sla_exceeded" />
    );
    expect(screen.getByText(/updated/)).toBeInTheDocument();
  });

  it('does not show retry action', () => {
    const onRetry = vi.fn();
    renderWithPolaris(
      <DataFreshnessBanner state="stale" onRetry={onRetry} />
    );
    expect(screen.queryByText('Retry')).not.toBeInTheDocument();
  });

  it('shows "Why am I seeing this?" tooltip', () => {
    renderWithPolaris(<DataFreshnessBanner state="stale" />);
    expect(screen.getByText('Why am I seeing this?')).toBeInTheDocument();
  });
});

// =============================================================================
// Unavailable state
// =============================================================================

describe('DataFreshnessBanner - unavailable state', () => {
  it('renders a banner with unavailable title', () => {
    renderWithPolaris(<DataFreshnessBanner state="unavailable" />);
    expect(screen.getByText('Data Temporarily Unavailable')).toBeInTheDocument();
  });

  it('shows default unavailable message when no reason', () => {
    renderWithPolaris(<DataFreshnessBanner state="unavailable" />);
    expect(screen.getByText(/temporarily unavailable/)).toBeInTheDocument();
  });

  it('shows never_synced message', () => {
    renderWithPolaris(
      <DataFreshnessBanner state="unavailable" reason="never_synced" />
    );
    expect(screen.getByText(/first time/)).toBeInTheDocument();
  });

  it('shows retry action when onRetry is provided', () => {
    const onRetry = vi.fn();
    renderWithPolaris(
      <DataFreshnessBanner state="unavailable" onRetry={onRetry} />
    );
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });

  it('does not show retry action without onRetry', () => {
    renderWithPolaris(<DataFreshnessBanner state="unavailable" />);
    expect(screen.queryByText('Retry')).not.toBeInTheDocument();
  });
});

// =============================================================================
// Affected sources
// =============================================================================

describe('DataFreshnessBanner - affected sources', () => {
  it('shows affected sources list', () => {
    renderWithPolaris(
      <DataFreshnessBanner
        state="stale"
        affectedSources={['Shopify Orders', 'Facebook Ads']}
      />
    );
    expect(screen.getByText('Affected:')).toBeInTheDocument();
    expect(screen.getByText('Shopify Orders, Facebook Ads')).toBeInTheDocument();
  });

  it('does not show affected section when list is empty', () => {
    renderWithPolaris(
      <DataFreshnessBanner state="stale" affectedSources={[]} />
    );
    expect(screen.queryByText('Affected:')).not.toBeInTheDocument();
  });

  it('does not show affected section when not provided', () => {
    renderWithPolaris(<DataFreshnessBanner state="stale" />);
    expect(screen.queryByText('Affected:')).not.toBeInTheDocument();
  });
});

// =============================================================================
// Dismiss handler
// =============================================================================

describe('DataFreshnessBanner - dismiss', () => {
  it('renders a dismiss button when onDismiss is provided', () => {
    const onDismiss = vi.fn();

    renderWithPolaris(
      <DataFreshnessBanner state="stale" onDismiss={onDismiss} />
    );

    // Polaris Banner renders an icon-only button for dismiss
    const buttons = screen.getAllByRole('button');
    expect(buttons.length).toBeGreaterThan(0);
  });

  it('does not render dismiss button when onDismiss is not provided', () => {
    renderWithPolaris(<DataFreshnessBanner state="stale" />);

    // Without onDismiss, Polaris Banner should not render a dismiss button
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
