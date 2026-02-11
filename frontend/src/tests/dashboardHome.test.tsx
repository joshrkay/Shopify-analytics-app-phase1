/**
 * Tests for DashboardHome
 *
 * Phase 1 — Dashboard Home Page
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AppProvider } from '@shopify/polaris';
import { MemoryRouter } from 'react-router-dom';
import '@shopify/polaris/build/esm/styles.css';

import { DashboardHome } from '../pages/DashboardHome';
import { listInsights, getUnreadInsightsCount } from '../services/insightsApi';
import { listRecommendations, getActiveRecommendationsCount } from '../services/recommendationsApi';
import { getCompactHealth } from '../services/syncHealthApi';
import type { Insight } from '../types/insights';
import type { Recommendation } from '../types/recommendations';
import type { CompactHealth } from '../services/syncHealthApi';

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../services/insightsApi');
vi.mock('../services/recommendationsApi');
vi.mock('../services/syncHealthApi');
vi.mock('../services/apiUtils');

// ---------------------------------------------------------------------------
// Factories
// ---------------------------------------------------------------------------

const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

const renderWithProviders = (ui: React.ReactElement) => {
  return render(
    <AppProvider i18n={mockTranslations as any}>
      <MemoryRouter>
        {ui}
      </MemoryRouter>
    </AppProvider>,
  );
};

const createMockInsight = (overrides?: Partial<Insight>): Insight => ({
  insight_id: 'ins-1',
  insight_type: 'spend_anomaly',
  severity: 'warning',
  summary: 'Spend increased 40% on Campaign Alpha',
  why_it_matters: null,
  supporting_metrics: [],
  timeframe: 'last_7d',
  confidence_score: 0.85,
  platform: 'meta',
  campaign_id: null,
  currency: 'USD',
  generated_at: '2025-01-15T00:00:00Z',
  is_read: false,
  is_dismissed: false,
  ...overrides,
});

const createMockRecommendation = (overrides?: Partial<Recommendation>): Recommendation => ({
  recommendation_id: 'rec-1',
  related_insight_id: 'ins-1',
  recommendation_type: 'decrease_budget',
  priority: 'high',
  recommendation_text: 'Consider reducing spend on Campaign Alpha',
  rationale: null,
  estimated_impact: 'significant',
  risk_level: 'low',
  confidence_score: 0.8,
  affected_entity: null,
  affected_entity_type: null,
  currency: null,
  generated_at: '2025-01-15T00:00:00Z',
  is_accepted: false,
  is_dismissed: false,
  ...overrides,
});

const createMockHealth = (overrides?: Partial<CompactHealth>): CompactHealth => ({
  overall_status: 'healthy',
  health_score: 95,
  stale_count: 0,
  critical_count: 0,
  has_blocking_issues: false,
  oldest_sync_minutes: null,
  last_checked_at: '2025-01-15T00:00:00Z',
  ...overrides,
});

// ---------------------------------------------------------------------------
// Default mock setup
// ---------------------------------------------------------------------------

function setupMocksWithData() {
  vi.mocked(getUnreadInsightsCount).mockResolvedValue(3);
  vi.mocked(getActiveRecommendationsCount).mockResolvedValue(2);
  vi.mocked(getCompactHealth).mockResolvedValue(createMockHealth());
  vi.mocked(listInsights).mockResolvedValue({
    insights: [createMockInsight()],
    total: 1,
    has_more: false,
  });
  vi.mocked(listRecommendations).mockResolvedValue({
    recommendations: [createMockRecommendation()],
    total: 1,
    has_more: false,
  });
}

function setupMocksEmpty() {
  vi.mocked(getUnreadInsightsCount).mockResolvedValue(0);
  vi.mocked(getActiveRecommendationsCount).mockResolvedValue(0);
  vi.mocked(getCompactHealth).mockResolvedValue(createMockHealth({ health_score: 100 }));
  vi.mocked(listInsights).mockResolvedValue({
    insights: [],
    total: 0,
    has_more: false,
  });
  vi.mocked(listRecommendations).mockResolvedValue({
    recommendations: [],
    total: 0,
    has_more: false,
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DashboardHome', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders 'Home' page title after loading", async () => {
    setupMocksWithData();
    renderWithProviders(<DashboardHome />);

    await waitFor(() => {
      expect(screen.getByText('Home')).toBeInTheDocument();
    });
  });

  it('shows loading spinner initially', () => {
    // Never resolve the promises to keep loading state
    vi.mocked(getUnreadInsightsCount).mockReturnValue(new Promise(() => {}));
    vi.mocked(getActiveRecommendationsCount).mockReturnValue(new Promise(() => {}));
    vi.mocked(getCompactHealth).mockReturnValue(new Promise(() => {}));
    vi.mocked(listInsights).mockReturnValue(new Promise(() => {}));
    vi.mocked(listRecommendations).mockReturnValue(new Promise(() => {}));

    renderWithProviders(<DashboardHome />);

    expect(screen.getByText('Home')).toBeInTheDocument();
    // Polaris Spinner renders with role="status"
    expect(document.querySelector('.Polaris-Spinner') || screen.getByRole('status')).toBeInTheDocument();
  });

  it('shows empty state when all APIs return no data (graceful degradation)', async () => {
    // Individual API calls have .catch() fallbacks so they degrade gracefully
    // to zero/empty values rather than showing an error banner
    vi.mocked(getUnreadInsightsCount).mockRejectedValue(new Error('Network error'));
    vi.mocked(getActiveRecommendationsCount).mockRejectedValue(new Error('Network error'));
    vi.mocked(getCompactHealth).mockRejectedValue(new Error('Network error'));
    vi.mocked(listInsights).mockRejectedValue(new Error('Network error'));
    vi.mocked(listRecommendations).mockRejectedValue(new Error('Network error'));

    renderWithProviders(<DashboardHome />);

    // Falls through to empty state since all fallback values are zero/empty
    await waitFor(() => {
      expect(screen.getByText('Welcome to your analytics dashboard')).toBeInTheDocument();
    });
  });

  it('shows empty state when no data exists', async () => {
    setupMocksEmpty();
    renderWithProviders(<DashboardHome />);

    await waitFor(() => {
      expect(screen.getByText('Welcome to your analytics dashboard')).toBeInTheDocument();
    });

    expect(screen.getByText('Connect data sources')).toBeInTheDocument();
  });

  it('empty state CTA navigates to /data-sources', async () => {
    setupMocksEmpty();
    renderWithProviders(<DashboardHome />);

    await waitFor(() => {
      expect(screen.getByText('Connect data sources')).toBeInTheDocument();
    });

    screen.getByText('Connect data sources').click();
    expect(mockNavigate).toHaveBeenCalledWith('/data-sources');
  });

  it('shows unread insights count in metric card', async () => {
    setupMocksWithData();
    renderWithProviders(<DashboardHome />);

    await waitFor(() => {
      expect(screen.getByText('Unread Insights')).toBeInTheDocument();
    });

    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('shows active recommendations count in metric card', async () => {
    setupMocksWithData();
    renderWithProviders(<DashboardHome />);

    await waitFor(() => {
      expect(screen.getByText('Active Recommendations')).toBeInTheDocument();
    });

    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('shows health score and status badge', async () => {
    setupMocksWithData();
    renderWithProviders(<DashboardHome />);

    await waitFor(() => {
      expect(screen.getByText('Data Health')).toBeInTheDocument();
    });

    expect(screen.getByText('95%')).toBeInTheDocument();
    expect(screen.getByText('Healthy')).toBeInTheDocument();
  });

  it('shows degraded health badge when status is degraded', async () => {
    vi.mocked(getUnreadInsightsCount).mockResolvedValue(1);
    vi.mocked(getActiveRecommendationsCount).mockResolvedValue(0);
    vi.mocked(getCompactHealth).mockResolvedValue(createMockHealth({
      overall_status: 'degraded',
      health_score: 60,
    }));
    vi.mocked(listInsights).mockResolvedValue({
      insights: [createMockInsight()],
      total: 1,
      has_more: false,
    });
    vi.mocked(listRecommendations).mockResolvedValue({
      recommendations: [],
      total: 0,
      has_more: false,
    });

    renderWithProviders(<DashboardHome />);

    await waitFor(() => {
      expect(screen.getByText('60%')).toBeInTheDocument();
    });

    expect(screen.getByText('Degraded')).toBeInTheDocument();
  });

  it('shows recent insights DataTable with data', async () => {
    setupMocksWithData();
    renderWithProviders(<DashboardHome />);

    await waitFor(() => {
      expect(screen.getByText('Recent Insights')).toBeInTheDocument();
    });

    // Insight data renders in table
    expect(screen.getByText('Spend Anomaly')).toBeInTheDocument();
    expect(screen.getByText('Spend increased 40% on Campaign Alpha')).toBeInTheDocument();
  });

  it('shows recommendations DataTable with data', async () => {
    setupMocksWithData();
    renderWithProviders(<DashboardHome />);

    await waitFor(() => {
      expect(screen.getByText('Recommendations')).toBeInTheDocument();
    });

    // Recommendation data renders in table
    expect(screen.getByText('Decrease Budget')).toBeInTheDocument();
    expect(screen.getByText('Consider reducing spend on Campaign Alpha')).toBeInTheDocument();
  });

  it('renders TimeframeSelector', async () => {
    setupMocksWithData();
    renderWithProviders(<DashboardHome />);

    await waitFor(() => {
      expect(screen.getByText('Unread Insights')).toBeInTheDocument();
    });

    // TimeframeSelector renders a Polaris Select — check for the default option
    const select = document.querySelector('select');
    expect(select).toBeInTheDocument();
    expect(select?.value).toBe('30d');
  });
});
