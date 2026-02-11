/**
 * DashboardHome Page
 *
 * Native dashboard home page with:
 * - Metric summary cards (insights count, recommendations count, data health)
 * - Timeframe selector
 * - Recent insights table
 * - Recommendations overview
 * - Data health status
 * - Empty state for new users
 *
 * Wires to existing APIs: insightsApi, recommendationsApi, syncHealthApi.
 *
 * Phase 1 — Dashboard Home
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Page,
  Card,
  Text,
  BlockStack,
  InlineStack,
  InlineGrid,
  Badge,
  DataTable,
  Spinner,
  Banner,
  EmptyState,
  Button,
} from '@shopify/polaris';
import { useNavigate } from 'react-router-dom';
import { TimeframeSelector, type TimeframeOption } from '../components/common/TimeframeSelector';
import { listInsights, getUnreadInsightsCount } from '../services/insightsApi';
import { listRecommendations, getActiveRecommendationsCount } from '../services/recommendationsApi';
import { getCompactHealth } from '../services/syncHealthApi';
import type { Insight } from '../types/insights';
import type { Recommendation } from '../types/recommendations';
import type { CompactHealth } from '../services/syncHealthApi';
import { getInsightTypeLabel } from '../types/insights';
import { getRecommendationTypeLabel } from '../types/recommendations';

interface DashboardMetrics {
  unreadInsights: number;
  activeRecommendations: number;
  healthScore: number;
  healthStatus: 'healthy' | 'degraded' | 'critical';
}

export function DashboardHome() {
  const navigate = useNavigate();
  const [timeframe, setTimeframe] = useState<TimeframeOption>('30d');
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      let cancelled = false;

      const [
        unreadCount,
        activeRecCount,
        health,
        insightsResponse,
        recsResponse,
      ] = await Promise.all([
        getUnreadInsightsCount().catch(() => 0),
        getActiveRecommendationsCount().catch(() => 0),
        getCompactHealth().catch((): CompactHealth => ({
          overall_status: 'healthy',
          health_score: 100,
          stale_count: 0,
          critical_count: 0,
          has_blocking_issues: false,
          oldest_sync_minutes: null,
          last_checked_at: new Date().toISOString(),
        })),
        listInsights({ limit: 5, include_dismissed: false }).catch(() => ({
          insights: [],
          total: 0,
          has_more: false,
        })),
        listRecommendations({ limit: 5, include_dismissed: false }).catch(() => ({
          recommendations: [],
          total: 0,
          has_more: false,
        })),
      ]);

      if (cancelled) return;

      setMetrics({
        unreadInsights: unreadCount,
        activeRecommendations: activeRecCount,
        healthScore: health.health_score,
        healthStatus: health.overall_status,
      });
      setInsights(insightsResponse.insights);
      setRecommendations(recsResponse.recommendations);

      return () => { cancelled = true; };
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (loading) {
    return (
      <Page title="Home">
        <div style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
          <Spinner size="large" />
        </div>
      </Page>
    );
  }

  if (error) {
    return (
      <Page title="Home">
        <Banner tone="critical" title="Failed to load dashboard">
          <p>{error}</p>
        </Banner>
      </Page>
    );
  }

  const hasData = metrics && (metrics.unreadInsights > 0 || metrics.activeRecommendations > 0 || insights.length > 0);

  if (!hasData && !loading) {
    return (
      <Page title="Home">
        <Card>
          <EmptyState
            heading="Welcome to your analytics dashboard"
            image=""
          >
            <p>
              Connect your data sources to start seeing insights, recommendations,
              and performance metrics here.
            </p>
            <Button variant="primary" onClick={() => navigate('/data-sources')}>
              Connect data sources
            </Button>
          </EmptyState>
        </Card>
      </Page>
    );
  }

  const healthBadgeTone = metrics?.healthStatus === 'healthy'
    ? 'success'
    : metrics?.healthStatus === 'degraded'
      ? 'attention'
      : 'critical';

  const healthLabel = metrics?.healthStatus === 'healthy'
    ? 'Healthy'
    : metrics?.healthStatus === 'degraded'
      ? 'Degraded'
      : 'Critical';

  // Build insights table rows
  const insightRows = insights.map((insight) => [
    getInsightTypeLabel(insight.insight_type),
    insight.summary.length > 80 ? `${insight.summary.slice(0, 80)}...` : insight.summary,
    insight.severity,
    insight.timeframe,
  ]);

  // Build recommendations table rows
  const recRows = recommendations.map((rec) => [
    getRecommendationTypeLabel(rec.recommendation_type),
    rec.recommendation_text.length > 80 ? `${rec.recommendation_text.slice(0, 80)}...` : rec.recommendation_text,
    rec.priority,
    rec.estimated_impact,
  ]);

  return (
    <Page title="Home">
      <BlockStack gap="600">
        {/* Timeframe selector */}
        <InlineStack align="end">
          <TimeframeSelector value={timeframe} onChange={setTimeframe} />
        </InlineStack>

        {/* Metric summary cards */}
        <InlineGrid columns={{ xs: 1, sm: 2, md: 3 }} gap="400">
          <Card>
            <BlockStack gap="200">
              <Text as="p" variant="bodySm" tone="subdued">Unread Insights</Text>
              <Text as="p" variant="heading2xl">{metrics?.unreadInsights ?? 0}</Text>
              {(metrics?.unreadInsights ?? 0) > 0 && (
                <Button variant="plain" onClick={() => navigate('/insights')}>View all</Button>
              )}
            </BlockStack>
          </Card>
          <Card>
            <BlockStack gap="200">
              <Text as="p" variant="bodySm" tone="subdued">Active Recommendations</Text>
              <Text as="p" variant="heading2xl">{metrics?.activeRecommendations ?? 0}</Text>
              {(metrics?.activeRecommendations ?? 0) > 0 && (
                <Button variant="plain" onClick={() => navigate('/insights')}>Review</Button>
              )}
            </BlockStack>
          </Card>
          <Card>
            <BlockStack gap="200">
              <Text as="p" variant="bodySm" tone="subdued">Data Health</Text>
              <InlineStack gap="200" blockAlign="center">
                <Text as="p" variant="heading2xl">{metrics?.healthScore ?? 0}%</Text>
                <Badge tone={healthBadgeTone}>{healthLabel}</Badge>
              </InlineStack>
              <Button variant="plain" onClick={() => navigate('/data-sources')}>Details</Button>
            </BlockStack>
          </Card>
        </InlineGrid>

        {/* Recent insights table */}
        {insights.length > 0 && (
          <Card>
            <BlockStack gap="400">
              <InlineStack align="space-between" blockAlign="center">
                <Text as="h2" variant="headingMd">Recent Insights</Text>
                <Button variant="plain" onClick={() => navigate('/insights')}>View all</Button>
              </InlineStack>
              <DataTable
                columnContentTypes={['text', 'text', 'text', 'text']}
                headings={['Type', 'Summary', 'Severity', 'Timeframe']}
                rows={insightRows}
                hoverable
              />
            </BlockStack>
          </Card>
        )}

        {/* Recommendations table */}
        {recommendations.length > 0 && (
          <Card>
            <BlockStack gap="400">
              <InlineStack align="space-between" blockAlign="center">
                <Text as="h2" variant="headingMd">Recommendations</Text>
                <Button variant="plain" onClick={() => navigate('/insights')}>View all</Button>
              </InlineStack>
              <DataTable
                columnContentTypes={['text', 'text', 'text', 'text']}
                headings={['Type', 'Description', 'Priority', 'Impact']}
                rows={recRows}
                hoverable
              />
            </BlockStack>
          </Card>
        )}
      </BlockStack>
    </Page>
  );
}

export default DashboardHome;
