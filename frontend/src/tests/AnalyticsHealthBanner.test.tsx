/**
 * Tests for AnalyticsHealthBanner
 *
 * Phase 4 (5.6.4) — Fallback UX: Health Banner + Retry
 *
 * Verifies:
 * - Renders warning banner with correct title
 * - Retry button calls onRetry callback
 * - Shows spinner when isRetrying=true
 * - Reports health incident on mount (fire-and-forget)
 * - Does not leak error details to user
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';

import { AnalyticsHealthBanner } from '../components/AnalyticsHealthBanner';

// Mock fetch for the fire-and-forget health incident report
const mockFetch = vi.fn().mockResolvedValue({ ok: true });
vi.stubGlobal('fetch', mockFetch);

const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

const renderWithPolaris = (ui: React.ReactElement) => {
  return render(
    <AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>
  );
};

describe('AnalyticsHealthBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders warning banner with correct title', () => {
    renderWithPolaris(
      <AnalyticsHealthBanner onRetry={() => {}} />
    );

    expect(
      screen.getByText('Analytics temporarily unavailable')
    ).toBeTruthy();
  });

  it('renders retry button', () => {
    renderWithPolaris(
      <AnalyticsHealthBanner onRetry={() => {}} />
    );

    expect(screen.getByText('Retry')).toBeTruthy();
  });

  it('calls onRetry when retry button is clicked', async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();

    renderWithPolaris(
      <AnalyticsHealthBanner onRetry={onRetry} />
    );

    await user.click(screen.getByText('Retry'));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('shows retrying text when isRetrying is true', () => {
    renderWithPolaris(
      <AnalyticsHealthBanner onRetry={() => {}} isRetrying={true} />
    );

    expect(screen.getByText('Retrying...')).toBeTruthy();
  });

  it('disables retry button when isRetrying is true', () => {
    renderWithPolaris(
      <AnalyticsHealthBanner onRetry={() => {}} isRetrying={true} />
    );

    const button = screen.getByRole('button');
    expect(button).toHaveAttribute('aria-disabled', 'true');
  });

  it('reports health incident on mount via fetch', () => {
    renderWithPolaris(
      <AnalyticsHealthBanner
        onRetry={() => {}}
        errorType="superset_unavailable"
        accessSurface="shopify_embed"
      />
    );

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, options] = mockFetch.mock.calls[0];
    expect(url).toContain('/embed/health/incident');
    expect(options.method).toBe('POST');

    const body = JSON.parse(options.body);
    expect(body.error_type).toBe('superset_unavailable');
    expect(body.access_surface).toBe('shopify_embed');
  });

  it('does not leak error details to the user', () => {
    renderWithPolaris(
      <AnalyticsHealthBanner
        onRetry={() => {}}
        errorType="redis_connection_refused_at_10.0.0.1:6379"
      />
    );

    // The error type should NOT appear in the rendered output
    expect(
      screen.queryByText(/redis_connection_refused/)
    ).toBeNull();
    // Only generic message should appear
    expect(screen.getByText(/retrying/i)).toBeTruthy();
  });
});
