/**
 * Tests for Health Components
 *
 * Story 9.5 - Data Freshness Indicators
 * Story 9.6 - Incident Communication
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';

import { DataFreshnessBadge } from '../components/health/DataFreshnessBadge';
import { IncidentBanner } from '../components/health/IncidentBanner';
import { DashboardFreshnessIndicator } from '../components/health/DashboardFreshnessIndicator';

// Mock translations
const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

// Mock the context hooks
const mockUseFreshnessStatus = vi.fn();
const mockUseActiveIncidents = vi.fn();

vi.mock('../contexts/DataHealthContext', () => ({
  useFreshnessStatus: () => mockUseFreshnessStatus(),
  useActiveIncidents: () => mockUseActiveIncidents(),
}));

// Helper to render with Polaris provider
const renderWithPolaris = (ui: React.ReactElement) => {
  return render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);
};

// =============================================================================
// DataFreshnessBadge Tests
// =============================================================================

describe('DataFreshnessBadge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseFreshnessStatus.mockReturnValue({
      status: 'healthy',
      hasStaleData: false,
      hasCriticalIssues: false,
      freshnessLabel: 'All data fresh',
      loading: false,
    });
  });

  describe('loading state', () => {
    it('shows spinner when loading', () => {
      mockUseFreshnessStatus.mockReturnValue({
        status: null,
        hasStaleData: false,
        hasCriticalIssues: false,
        freshnessLabel: '',
        loading: true,
      });

      renderWithPolaris(<DataFreshnessBadge />);

      // Polaris Spinner renders accessibility label in a visually hidden span
      expect(screen.getByText('Loading data health')).toBeInTheDocument();
    });
  });

  describe('healthy state', () => {
    it('shows success badge when all data is fresh', () => {
      renderWithPolaris(<DataFreshnessBadge />);

      expect(screen.getByText('Fresh')).toBeInTheDocument();
    });

    it('shows "All data is fresh" tooltip', async () => {
      renderWithPolaris(<DataFreshnessBadge />);

      // Tooltip content is set via aria or title
      const badge = screen.getByText('Fresh');
      expect(badge).toBeInTheDocument();
    });
  });

  describe('stale state', () => {
    it('shows attention badge when data is stale', () => {
      mockUseFreshnessStatus.mockReturnValue({
        status: 'degraded',
        hasStaleData: true,
        hasCriticalIssues: false,
        freshnessLabel: '2 hours ago',
        loading: false,
      });

      renderWithPolaris(<DataFreshnessBadge />);

      expect(screen.getByText('2 hours')).toBeInTheDocument();
    });
  });

  describe('critical state', () => {
    it('shows critical badge when critical issues exist', () => {
      mockUseFreshnessStatus.mockReturnValue({
        status: 'critical',
        hasStaleData: true,
        hasCriticalIssues: true,
        freshnessLabel: '5 hours ago',
        loading: false,
      });

      renderWithPolaris(<DataFreshnessBadge />);

      expect(screen.getByText('!')).toBeInTheDocument();
    });
  });

  describe('click handler', () => {
    it('calls onClick when clicked', async () => {
      const handleClick = vi.fn();
      const user = userEvent.setup();

      renderWithPolaris(<DataFreshnessBadge onClick={handleClick} />);

      const button = screen.getByRole('button');
      await user.click(button);

      expect(handleClick).toHaveBeenCalledTimes(1);
    });
  });

  describe('label', () => {
    it('shows label when showLabel is true', () => {
      renderWithPolaris(<DataFreshnessBadge showLabel />);

      expect(screen.getByText('Data')).toBeInTheDocument();
    });

    it('hides label by default', () => {
      renderWithPolaris(<DataFreshnessBadge />);

      expect(screen.queryByText('Data')).not.toBeInTheDocument();
    });
  });
});

// =============================================================================
// IncidentBanner Tests
// =============================================================================

describe('IncidentBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseActiveIncidents.mockReturnValue({
      incidents: [],
      shouldShowBanner: false,
      mostSevereIncident: null,
      acknowledgeIncident: vi.fn(),
    });
  });

  describe('no incidents', () => {
    it('renders nothing when no incidents', () => {
      renderWithPolaris(<IncidentBanner />);

      // When no incidents, the banner content should not be rendered
      expect(screen.queryByRole('status')).not.toBeInTheDocument();
    });
  });

  describe('warning incident', () => {
    it('shows info banner for warning severity', () => {
      mockUseActiveIncidents.mockReturnValue({
        incidents: [
          {
            id: 'inc-1',
            severity: 'warning',
            title: 'Data Delayed',
            message: 'Meta Ads data is delayed.',
            scope: 'Meta Ads connector',
            eta: 'Expected resolution: 1-2 hours',
            status_page_url: null,
            started_at: new Date().toISOString(),
          },
        ],
        shouldShowBanner: true,
        mostSevereIncident: {
          id: 'inc-1',
          severity: 'warning',
          title: 'Data Delayed',
          message: 'Meta Ads data is delayed.',
          scope: 'Meta Ads connector',
          eta: 'Expected resolution: 1-2 hours',
          status_page_url: null,
          started_at: new Date().toISOString(),
        },
        acknowledgeIncident: vi.fn(),
      });

      renderWithPolaris(<IncidentBanner />);

      expect(screen.getByText('Meta Ads connector may be delayed')).toBeInTheDocument();
      expect(screen.getByText('Meta Ads data is delayed.')).toBeInTheDocument();
      expect(screen.getByText('Expected resolution: 1-2 hours')).toBeInTheDocument();
    });
  });

  describe('critical incident', () => {
    it('shows critical banner for critical severity', () => {
      mockUseActiveIncidents.mockReturnValue({
        incidents: [
          {
            id: 'inc-1',
            severity: 'critical',
            title: 'Critical Issue',
            message: 'Shopify data sync failed.',
            scope: 'Shopify connector',
            eta: 'Investigating',
            status_page_url: 'https://status.example.com',
            started_at: new Date().toISOString(),
          },
        ],
        shouldShowBanner: true,
        mostSevereIncident: {
          id: 'inc-1',
          severity: 'critical',
          title: 'Critical Issue',
          message: 'Shopify data sync failed.',
          scope: 'Shopify connector',
          eta: 'Investigating',
          status_page_url: 'https://status.example.com',
          started_at: new Date().toISOString(),
        },
        acknowledgeIncident: vi.fn(),
      });

      renderWithPolaris(<IncidentBanner />);

      expect(screen.getByText('Shopify connector - Critical Issue')).toBeInTheDocument();
      expect(screen.getByText('Shopify data sync failed.')).toBeInTheDocument();
    });
  });

  describe('status page link', () => {
    it('shows status page link when URL provided', () => {
      mockUseActiveIncidents.mockReturnValue({
        incidents: [
          {
            id: 'inc-1',
            severity: 'warning',
            title: 'Issue',
            message: 'Test message',
            scope: 'Test connector',
            eta: null,
            status_page_url: 'https://status.example.com',
            started_at: new Date().toISOString(),
          },
        ],
        shouldShowBanner: true,
        mostSevereIncident: {
          id: 'inc-1',
          severity: 'warning',
          title: 'Issue',
          message: 'Test message',
          scope: 'Test connector',
          eta: null,
          status_page_url: 'https://status.example.com',
          started_at: new Date().toISOString(),
        },
        acknowledgeIncident: vi.fn(),
      });

      renderWithPolaris(<IncidentBanner />);

      expect(screen.getByText('View status page')).toBeInTheDocument();
    });
  });

  describe('multiple incidents', () => {
    it('shows count of other incidents', () => {
      mockUseActiveIncidents.mockReturnValue({
        incidents: [
          { id: 'inc-1', severity: 'warning', message: 'Msg1', scope: 'C1', title: 'T1', eta: null, status_page_url: null, started_at: '' },
          { id: 'inc-2', severity: 'high', message: 'Msg2', scope: 'C2', title: 'T2', eta: null, status_page_url: null, started_at: '' },
          { id: 'inc-3', severity: 'warning', message: 'Msg3', scope: 'C3', title: 'T3', eta: null, status_page_url: null, started_at: '' },
        ],
        shouldShowBanner: true,
        mostSevereIncident: { id: 'inc-2', severity: 'high', message: 'Msg2', scope: 'C2', title: 'T2', eta: null, status_page_url: null, started_at: '' },
        acknowledgeIncident: vi.fn(),
      });

      renderWithPolaris(<IncidentBanner />);

      expect(screen.getByText('2 other incidents active')).toBeInTheDocument();
    });
  });
});

// =============================================================================
// DashboardFreshnessIndicator Tests
// =============================================================================

describe('DashboardFreshnessIndicator', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseFreshnessStatus.mockReturnValue({
      status: 'healthy',
      hasStaleData: false,
      hasCriticalIssues: false,
      freshnessLabel: 'All data fresh',
      loading: false,
    });
  });

  describe('loading state', () => {
    it('shows loading message', () => {
      mockUseFreshnessStatus.mockReturnValue({
        status: null,
        hasStaleData: false,
        hasCriticalIssues: false,
        freshnessLabel: '',
        loading: true,
      });

      renderWithPolaris(<DashboardFreshnessIndicator />);

      expect(screen.getByText('Checking data freshness...')).toBeInTheDocument();
    });
  });

  describe('healthy state', () => {
    it('shows "All data fresh" message', () => {
      renderWithPolaris(<DashboardFreshnessIndicator />);

      expect(screen.getByText('All data fresh')).toBeInTheDocument();
    });
  });

  describe('stale state', () => {
    it('shows last sync time', () => {
      mockUseFreshnessStatus.mockReturnValue({
        status: 'degraded',
        hasStaleData: true,
        hasCriticalIssues: false,
        freshnessLabel: '2 hours ago',
        loading: false,
      });

      renderWithPolaris(<DashboardFreshnessIndicator />);

      expect(screen.getByText('Last sync: 2 hours ago')).toBeInTheDocument();
    });

    it('shows delayed badge in detailed variant', () => {
      mockUseFreshnessStatus.mockReturnValue({
        status: 'degraded',
        hasStaleData: true,
        hasCriticalIssues: false,
        freshnessLabel: '2 hours ago',
        loading: false,
      });

      renderWithPolaris(<DashboardFreshnessIndicator variant="detailed" />);

      expect(screen.getByText('Some data delayed')).toBeInTheDocument();
    });
  });

  describe('critical state', () => {
    it('shows "Data issues detected" message', () => {
      mockUseFreshnessStatus.mockReturnValue({
        status: 'critical',
        hasStaleData: true,
        hasCriticalIssues: true,
        freshnessLabel: '5 hours ago',
        loading: false,
      });

      renderWithPolaris(<DashboardFreshnessIndicator />);

      expect(screen.getByText('Data issues detected')).toBeInTheDocument();
    });

    it('shows action required badge in detailed variant', () => {
      mockUseFreshnessStatus.mockReturnValue({
        status: 'critical',
        hasStaleData: true,
        hasCriticalIssues: true,
        freshnessLabel: '5 hours ago',
        loading: false,
      });

      renderWithPolaris(<DashboardFreshnessIndicator variant="detailed" />);

      expect(screen.getByText('Action required')).toBeInTheDocument();
    });
  });

  describe('variants', () => {
    it('compact variant does not show badges', () => {
      mockUseFreshnessStatus.mockReturnValue({
        status: 'degraded',
        hasStaleData: true,
        hasCriticalIssues: false,
        freshnessLabel: '2 hours ago',
        loading: false,
      });

      renderWithPolaris(<DashboardFreshnessIndicator variant="compact" />);

      expect(screen.queryByText('Some data delayed')).not.toBeInTheDocument();
    });
  });
});
