/**
 * Tests for Data Health Context
 *
 * Story 9.5 - Data Freshness Indicators
 * Story 9.6 - Incident Communication
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AppProvider } from '@shopify/polaris';

import {
  DataHealthProvider,
  useDataHealth,
  useFreshnessStatus,
  useActiveIncidents,
} from '../contexts/DataHealthContext';
import type { CompactHealth, ActiveIncidentsResponse } from '../services/syncHealthApi';

// Mock translations
const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

// Mock health data
const createMockCompactHealth = (overrides?: Partial<CompactHealth>): CompactHealth => ({
  overall_status: 'healthy',
  health_score: 100,
  stale_count: 0,
  critical_count: 0,
  has_blocking_issues: false,
  oldest_sync_minutes: 30,
  last_checked_at: new Date().toISOString(),
  ...overrides,
});

const createMockIncidentsResponse = (
  overrides?: Partial<ActiveIncidentsResponse>
): ActiveIncidentsResponse => ({
  incidents: [],
  has_critical: false,
  has_blocking: false,
  ...overrides,
});

// Mock API module
const mockGetCompactHealth = vi.fn();
const mockGetActiveIncidents = vi.fn();
const mockAcknowledgeIncident = vi.fn();
const mockGetMerchantDataHealth = vi.fn();

vi.mock('../services/syncHealthApi', () => ({
  getCompactHealth: () => mockGetCompactHealth(),
  getActiveIncidents: () => mockGetActiveIncidents(),
  getMerchantDataHealth: () => mockGetMerchantDataHealth(),
  acknowledgeIncident: (id: string) => mockAcknowledgeIncident(id),
  formatTimeSinceSync: (minutes: number | null) => {
    if (minutes === null) return 'Never synced';
    if (minutes < 60) return `${minutes} minutes ago`;
    const hours = Math.floor(minutes / 60);
    return `${hours} hour${hours > 1 ? 's' : ''} ago`;
  },
}));

// Test component to access context
function TestConsumer() {
  const context = useDataHealth();
  return (
    <div>
      <span data-testid="status">{context.health?.overall_status ?? 'loading'}</span>
      <span data-testid="stale-count">{context.health?.stale_count ?? 0}</span>
      <span data-testid="has-stale">{String(context.hasStaleData)}</span>
      <span data-testid="freshness-label">{context.freshnessLabel}</span>
      <span data-testid="incidents-count">{context.activeIncidents.length}</span>
      <span data-testid="show-banner">{String(context.shouldShowBanner)}</span>
      <span data-testid="loading">{String(context.loading)}</span>
      <span data-testid="error">{context.error ?? 'none'}</span>
    </div>
  );
}

function FreshnessConsumer() {
  const { status, hasStaleData, freshnessLabel, loading } = useFreshnessStatus();
  return (
    <div>
      <span data-testid="status">{status ?? 'null'}</span>
      <span data-testid="has-stale">{String(hasStaleData)}</span>
      <span data-testid="freshness-label">{freshnessLabel}</span>
      <span data-testid="loading">{String(loading)}</span>
    </div>
  );
}

function IncidentsConsumer() {
  const { incidents, shouldShowBanner, mostSevereIncident } = useActiveIncidents();
  return (
    <div>
      <span data-testid="incidents-count">{incidents.length}</span>
      <span data-testid="show-banner">{String(shouldShowBanner)}</span>
      <span data-testid="most-severe">{mostSevereIncident?.severity ?? 'none'}</span>
    </div>
  );
}

// Helper to render with providers
const renderWithProviders = (ui: React.ReactElement) => {
  return render(
    <AppProvider i18n={mockTranslations as any}>
      <DataHealthProvider disablePolling>{ui}</DataHealthProvider>
    </AppProvider>
  );
};

describe('DataHealthContext', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetCompactHealth.mockResolvedValue(createMockCompactHealth());
    mockGetActiveIncidents.mockResolvedValue(createMockIncidentsResponse());
    mockGetMerchantDataHealth.mockResolvedValue({
      health_state: 'healthy',
      last_updated: new Date().toISOString(),
      user_safe_message: 'Your data is up to date.',
      ai_insights_enabled: true,
      dashboards_enabled: true,
      exports_enabled: true,
    });
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  describe('initial state', () => {
    it('fetches health data on mount', async () => {
      renderWithProviders(<TestConsumer />);

      await waitFor(() => {
        expect(mockGetCompactHealth).toHaveBeenCalledTimes(1);
        expect(mockGetActiveIncidents).toHaveBeenCalledTimes(1);
      });
    });

    it('shows loading state initially', async () => {
      mockGetCompactHealth.mockImplementation(
        () => new Promise((resolve) => setTimeout(() => resolve(createMockCompactHealth()), 100))
      );

      renderWithProviders(<TestConsumer />);

      expect(screen.getByTestId('loading').textContent).toBe('true');
    });

    it('displays health data after fetch', async () => {
      renderWithProviders(<TestConsumer />);

      await waitFor(() => {
        expect(screen.getByTestId('status').textContent).toBe('healthy');
      });
    });
  });

  describe('health status', () => {
    it('computes hasStaleData correctly when stale_count > 0', async () => {
      mockGetCompactHealth.mockResolvedValue(
        createMockCompactHealth({ stale_count: 2 })
      );

      renderWithProviders(<TestConsumer />);

      await waitFor(() => {
        expect(screen.getByTestId('has-stale').textContent).toBe('true');
      });
    });

    it('computes hasStaleData correctly when stale_count is 0', async () => {
      renderWithProviders(<TestConsumer />);

      await waitFor(() => {
        expect(screen.getByTestId('has-stale').textContent).toBe('false');
      });
    });

    it('formats freshness label from oldest_sync_minutes', async () => {
      mockGetCompactHealth.mockResolvedValue(
        createMockCompactHealth({ oldest_sync_minutes: 30 })
      );

      renderWithProviders(<TestConsumer />);

      await waitFor(() => {
        expect(screen.getByTestId('freshness-label').textContent).toBe('30 minutes ago');
      });
    });

    it('shows "All data fresh" when oldest_sync_minutes is null', async () => {
      mockGetCompactHealth.mockResolvedValue(
        createMockCompactHealth({ oldest_sync_minutes: null })
      );

      renderWithProviders(<TestConsumer />);

      await waitFor(() => {
        expect(screen.getByTestId('freshness-label').textContent).toBe('All data fresh');
      });
    });
  });

  describe('incidents', () => {
    it('shows incidents when returned from API', async () => {
      mockGetActiveIncidents.mockResolvedValue(
        createMockIncidentsResponse({
          incidents: [
            {
              id: 'inc-1',
              severity: 'warning',
              title: 'Test Incident',
              message: 'Test message',
              scope: 'Test connector',
              eta: '1-2 hours',
              status_page_url: null,
              started_at: new Date().toISOString(),
            },
          ],
          has_critical: false,
          has_blocking: false,
        })
      );

      renderWithProviders(<TestConsumer />);

      await waitFor(() => {
        expect(screen.getByTestId('incidents-count').textContent).toBe('1');
        expect(screen.getByTestId('show-banner').textContent).toBe('true');
      });
    });

    it('does not show banner when no incidents', async () => {
      renderWithProviders(<TestConsumer />);

      await waitFor(() => {
        expect(screen.getByTestId('show-banner').textContent).toBe('false');
      });
    });

    it('selects most severe incident correctly', async () => {
      mockGetActiveIncidents.mockResolvedValue(
        createMockIncidentsResponse({
          incidents: [
            {
              id: 'inc-1',
              severity: 'warning',
              title: 'Warning',
              message: 'Warning message',
              scope: 'Connector 1',
              eta: null,
              status_page_url: null,
              started_at: new Date().toISOString(),
            },
            {
              id: 'inc-2',
              severity: 'critical',
              title: 'Critical',
              message: 'Critical message',
              scope: 'Connector 2',
              eta: null,
              status_page_url: null,
              started_at: new Date().toISOString(),
            },
          ],
          has_critical: true,
          has_blocking: false,
        })
      );

      renderWithProviders(<IncidentsConsumer />);

      await waitFor(() => {
        expect(screen.getByTestId('most-severe').textContent).toBe('critical');
      });
    });
  });

  describe('error handling', () => {
    it('handles API errors gracefully', async () => {
      mockGetCompactHealth.mockRejectedValue(new Error('Network error'));

      renderWithProviders(<TestConsumer />);

      await waitFor(() => {
        expect(screen.getByTestId('error').textContent).toBe('Network error');
        expect(screen.getByTestId('loading').textContent).toBe('false');
      });
    });
  });

  describe('hooks', () => {
    it('useFreshnessStatus returns correct values', async () => {
      mockGetCompactHealth.mockResolvedValue(
        createMockCompactHealth({
          overall_status: 'degraded',
          stale_count: 1,
          oldest_sync_minutes: 120,
        })
      );

      renderWithProviders(<FreshnessConsumer />);

      await waitFor(() => {
        expect(screen.getByTestId('status').textContent).toBe('degraded');
        expect(screen.getByTestId('has-stale').textContent).toBe('true');
        expect(screen.getByTestId('freshness-label').textContent).toBe('2 hours ago');
      });
    });

    it('useActiveIncidents returns correct values', async () => {
      mockGetActiveIncidents.mockResolvedValue(
        createMockIncidentsResponse({
          incidents: [
            {
              id: 'inc-1',
              severity: 'high',
              title: 'High Priority',
              message: 'High message',
              scope: 'Connector',
              eta: null,
              status_page_url: null,
              started_at: new Date().toISOString(),
            },
          ],
        })
      );

      renderWithProviders(<IncidentsConsumer />);

      await waitFor(() => {
        expect(screen.getByTestId('incidents-count').textContent).toBe('1');
        expect(screen.getByTestId('show-banner').textContent).toBe('true');
        expect(screen.getByTestId('most-severe').textContent).toBe('high');
      });
    });
  });

  describe('context requirement', () => {
    it('throws error when useDataHealth is used outside provider', () => {
      // Suppress console.error for this test
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      expect(() => {
        render(
          <AppProvider i18n={mockTranslations as any}>
            <TestConsumer />
          </AppProvider>
        );
      }).toThrow('useDataHealth must be used within a DataHealthProvider');

      consoleSpy.mockRestore();
    });
  });
});
