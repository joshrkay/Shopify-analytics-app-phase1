/**
 * Tests for Insight Components
 *
 * Story 9.3 - Insight & Recommendation UX
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { InsightCard } from '../components/insights/InsightCard';
import { InsightBadge } from '../components/insights/InsightBadge';
import { RecommendationCard } from '../components/recommendations/RecommendationCard';
import type { Insight } from '../types/insights';
import type { Recommendation } from '../types/recommendations';

// Mock translations
const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

// Helper to render with Polaris provider
const renderWithPolaris = (ui: React.ReactElement) => {
  return render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);
};

// Mock insight data
const createMockInsight = (overrides?: Partial<Insight>): Insight => ({
  insight_id: 'insight-123',
  insight_type: 'spend_anomaly',
  severity: 'warning',
  summary: 'Ad spend increased 25% week-over-week',
  why_it_matters: 'This could indicate increased competition or budget issues',
  supporting_metrics: [
    {
      metric: 'Ad Spend',
      previous: 1000,
      current: 1250,
      change: 250,
      change_pct: 25,
    },
  ],
  timeframe: 'Last 7 days',
  confidence_score: 0.85,
  platform: 'meta',
  campaign_id: 'camp-456',
  currency: 'USD',
  generated_at: new Date().toISOString(),
  is_read: false,
  is_dismissed: false,
  ...overrides,
});

// Mock recommendation data
const createMockRecommendation = (overrides?: Partial<Recommendation>): Recommendation => ({
  recommendation_id: 'rec-123',
  related_insight_id: 'insight-123',
  recommendation_type: 'decrease_budget',
  priority: 'medium',
  recommendation_text: 'Consider reducing budget by 10% to optimize ROAS',
  rationale: 'Based on declining conversion rates over the past week',
  estimated_impact: 'moderate',
  risk_level: 'low',
  confidence_score: 0.78,
  affected_entity: 'Summer Sale Campaign',
  affected_entity_type: 'campaign',
  currency: 'USD',
  generated_at: new Date().toISOString(),
  is_accepted: false,
  is_dismissed: false,
  ...overrides,
});

// Mock API
vi.mock('../services/insightsApi', () => ({
  getUnreadInsightsCount: vi.fn().mockResolvedValue(5),
}));

describe('InsightCard', () => {
  describe('rendering', () => {
    it('displays insight summary and details', () => {
      const insight = createMockInsight();
      renderWithPolaris(<InsightCard insight={insight} />);

      expect(screen.getByText('Ad spend increased 25% week-over-week')).toBeInTheDocument();
      expect(screen.getByText(/This could indicate/)).toBeInTheDocument();
    });

    it('shows severity badge', () => {
      const insight = createMockInsight({ severity: 'critical' });
      renderWithPolaris(<InsightCard insight={insight} />);

      expect(screen.getByText('Critical')).toBeInTheDocument();
    });

    it('shows insight type badge', () => {
      const insight = createMockInsight({ insight_type: 'roas_change' });
      renderWithPolaris(<InsightCard insight={insight} />);

      expect(screen.getByText('ROAS Change')).toBeInTheDocument();
    });

    it('shows platform badge when available', () => {
      const insight = createMockInsight({ platform: 'google' });
      renderWithPolaris(<InsightCard insight={insight} />);

      expect(screen.getByText('Google')).toBeInTheDocument();
    });

    it('shows "New" badge for unread insights', () => {
      const insight = createMockInsight({ is_read: false });
      renderWithPolaris(<InsightCard insight={insight} />);

      expect(screen.getByText('New')).toBeInTheDocument();
    });

    it('does not show "New" badge for read insights', () => {
      const insight = createMockInsight({ is_read: true });
      renderWithPolaris(<InsightCard insight={insight} />);

      expect(screen.queryByText('New')).not.toBeInTheDocument();
    });

    it('shows confidence score', () => {
      const insight = createMockInsight({ confidence_score: 0.85 });
      renderWithPolaris(<InsightCard insight={insight} />);

      expect(screen.getByText(/Confidence: 85%/)).toBeInTheDocument();
    });

    it('shows timeframe', () => {
      const insight = createMockInsight({ timeframe: 'Last 7 days' });
      renderWithPolaris(<InsightCard insight={insight} />);

      expect(screen.getByText(/Timeframe: Last 7 days/)).toBeInTheDocument();
    });
  });

  describe('metrics expansion', () => {
    it('shows expandable metrics section', async () => {
      const user = userEvent.setup();
      const insight = createMockInsight();
      renderWithPolaris(<InsightCard insight={insight} />);

      // Initially collapsed
      expect(screen.getByText(/View 1 metrics/)).toBeInTheDocument();

      // Expand
      await user.click(screen.getByText(/View 1 metrics/));

      // Check metric is visible
      expect(screen.getByText('Ad Spend')).toBeInTheDocument();
    });
  });

  describe('actions', () => {
    it('calls onMarkRead when mark read button clicked', async () => {
      const user = userEvent.setup();
      const onMarkRead = vi.fn();
      const insight = createMockInsight({ is_read: false });

      renderWithPolaris(
        <InsightCard insight={insight} onMarkRead={onMarkRead} />
      );

      const markReadButton = screen.getByLabelText('Mark as read');
      await user.click(markReadButton);

      expect(onMarkRead).toHaveBeenCalledWith('insight-123');
    });

    it('calls onDismiss when dismiss button clicked', async () => {
      const user = userEvent.setup();
      const onDismiss = vi.fn();
      const insight = createMockInsight();

      renderWithPolaris(
        <InsightCard insight={insight} onDismiss={onDismiss} />
      );

      const dismissButton = screen.getByLabelText('Dismiss insight');
      await user.click(dismissButton);

      expect(onDismiss).toHaveBeenCalledWith('insight-123');
    });

    it('calls onViewRecommendations when link clicked', async () => {
      const user = userEvent.setup();
      const onViewRecommendations = vi.fn();
      const insight = createMockInsight();

      renderWithPolaris(
        <InsightCard
          insight={insight}
          onViewRecommendations={onViewRecommendations}
        />
      );

      await user.click(screen.getByText('View recommendations'));

      expect(onViewRecommendations).toHaveBeenCalledWith('insight-123');
    });

    it('hides mark read button for already read insights', () => {
      const onMarkRead = vi.fn();
      const insight = createMockInsight({ is_read: true });

      renderWithPolaris(
        <InsightCard insight={insight} onMarkRead={onMarkRead} />
      );

      expect(screen.queryByLabelText('Mark as read')).not.toBeInTheDocument();
    });
  });
});

describe('InsightBadge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows count of unread insights', async () => {
    renderWithPolaris(<InsightBadge refreshInterval={0} />);

    await waitFor(() => {
      expect(screen.getByText('5')).toBeInTheDocument();
    });
  });

  it('calls onClick when clicked', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();

    renderWithPolaris(<InsightBadge onClick={onClick} refreshInterval={0} />);

    await waitFor(() => {
      expect(screen.getByText('5')).toBeInTheDocument();
    });

    await user.click(screen.getByLabelText(/unread insights/i));
    expect(onClick).toHaveBeenCalled();
  });

  it('shows label when showLabel is true', async () => {
    renderWithPolaris(
      <InsightBadge showLabel label="My Insights" refreshInterval={0} />
    );

    await waitFor(() => {
      expect(screen.getByText('My Insights')).toBeInTheDocument();
    });
  });
});

describe('RecommendationCard', () => {
  describe('rendering', () => {
    it('displays recommendation text', () => {
      const recommendation = createMockRecommendation();
      renderWithPolaris(<RecommendationCard recommendation={recommendation} />);

      expect(
        screen.getByText('Consider reducing budget by 10% to optimize ROAS')
      ).toBeInTheDocument();
    });

    it('shows priority badge', () => {
      const recommendation = createMockRecommendation({ priority: 'high' });
      renderWithPolaris(<RecommendationCard recommendation={recommendation} />);

      expect(screen.getByText('High Priority')).toBeInTheDocument();
    });

    it('shows estimated impact badge', () => {
      const recommendation = createMockRecommendation({
        estimated_impact: 'significant',
      });
      renderWithPolaris(<RecommendationCard recommendation={recommendation} />);

      expect(screen.getByText('Significant')).toBeInTheDocument();
    });

    it('shows risk level badge', () => {
      const recommendation = createMockRecommendation({ risk_level: 'medium' });
      renderWithPolaris(<RecommendationCard recommendation={recommendation} />);

      expect(screen.getByText('Medium')).toBeInTheDocument();
    });

    it('shows rationale when not compact', () => {
      const recommendation = createMockRecommendation();
      renderWithPolaris(<RecommendationCard recommendation={recommendation} />);

      expect(
        screen.getByText(/Based on declining conversion rates/)
      ).toBeInTheDocument();
    });

    it('hides rationale in compact mode', () => {
      const recommendation = createMockRecommendation();
      renderWithPolaris(
        <RecommendationCard recommendation={recommendation} compact />
      );

      expect(
        screen.queryByText(/Based on declining conversion rates/)
      ).not.toBeInTheDocument();
    });

    it('shows warning banner for high risk recommendations', () => {
      const recommendation = createMockRecommendation({ risk_level: 'high' });
      renderWithPolaris(<RecommendationCard recommendation={recommendation} />);

      expect(
        screen.getByText(/high risk level. Consider carefully/)
      ).toBeInTheDocument();
    });

    it('shows "Accepted" badge when accepted', () => {
      const recommendation = createMockRecommendation({ is_accepted: true });
      renderWithPolaris(<RecommendationCard recommendation={recommendation} />);

      expect(screen.getByText('Accepted')).toBeInTheDocument();
    });

    it('shows "Dismissed" badge when dismissed', () => {
      const recommendation = createMockRecommendation({ is_dismissed: true });
      renderWithPolaris(<RecommendationCard recommendation={recommendation} />);

      expect(screen.getByText('Dismissed')).toBeInTheDocument();
    });
  });

  describe('actions', () => {
    it('calls onAccept when accept button clicked', async () => {
      const user = userEvent.setup();
      const onAccept = vi.fn();
      const recommendation = createMockRecommendation();

      renderWithPolaris(
        <RecommendationCard recommendation={recommendation} onAccept={onAccept} />
      );

      await user.click(screen.getByRole('button', { name: /accept/i }));

      expect(onAccept).toHaveBeenCalledWith('rec-123');
    });

    it('calls onDismiss when dismiss button clicked', async () => {
      const user = userEvent.setup();
      const onDismiss = vi.fn();
      const recommendation = createMockRecommendation();

      renderWithPolaris(
        <RecommendationCard
          recommendation={recommendation}
          onDismiss={onDismiss}
        />
      );

      await user.click(screen.getByRole('button', { name: /dismiss/i }));

      expect(onDismiss).toHaveBeenCalledWith('rec-123');
    });

    it('hides action buttons for accepted recommendations', () => {
      const recommendation = createMockRecommendation({ is_accepted: true });
      renderWithPolaris(
        <RecommendationCard
          recommendation={recommendation}
          onAccept={vi.fn()}
          onDismiss={vi.fn()}
        />
      );

      expect(
        screen.queryByRole('button', { name: /accept/i })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /dismiss/i })
      ).not.toBeInTheDocument();
    });

    it('hides action buttons for dismissed recommendations', () => {
      const recommendation = createMockRecommendation({ is_dismissed: true });
      renderWithPolaris(
        <RecommendationCard
          recommendation={recommendation}
          onAccept={vi.fn()}
          onDismiss={vi.fn()}
        />
      );

      expect(
        screen.queryByRole('button', { name: /accept/i })
      ).not.toBeInTheDocument();
    });
  });
});
