/**
 * InsightsFeed Page
 *
 * Central feed for AI insights and recommendations.
 * Supports filtering, dismissing, and recovering dismissed items.
 *
 * Story 9.3 - Insight & Recommendation UX
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Page,
  Layout,
  Card,
  BlockStack,
  InlineStack,
  Text,
  Select,
  Tabs,
  Banner,
  Spinner,
  EmptyState,
  Pagination,
  Modal,
} from '@shopify/polaris';
import { InsightCard } from '../components/insights/InsightCard';
import { RecommendationCard } from '../components/recommendations/RecommendationCard';
import { IncidentBanner } from '../components/health/IncidentBanner';
import type { Insight, InsightType, InsightSeverity } from '../types/insights';
import type { Recommendation } from '../types/recommendations';
import {
  listInsights,
  markInsightRead,
  dismissInsight,
} from '../services/insightsApi';
import {
  getRecommendationsForInsight,
  acceptRecommendation,
  dismissRecommendation,
} from '../services/recommendationsApi';

const PAGE_SIZE = 10;

type TabId = 'active' | 'dismissed';

const insightTypeOptions = [
  { label: 'All Types', value: '' },
  { label: 'Spend Anomaly', value: 'spend_anomaly' },
  { label: 'ROAS Change', value: 'roas_change' },
  { label: 'CTR Change', value: 'ctr_change' },
  { label: 'CPC Change', value: 'cpc_change' },
  { label: 'Conversion Change', value: 'conversion_change' },
  { label: 'Budget Pacing', value: 'budget_pacing' },
  { label: 'Performance Trend', value: 'performance_trend' },
];

const severityOptions = [
  { label: 'All Severities', value: '' },
  { label: 'Critical', value: 'critical' },
  { label: 'Warning', value: 'warning' },
  { label: 'Info', value: 'info' },
];

export function InsightsFeed() {
  // State
  const [insights, setInsights] = useState<Insight[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTab, setSelectedTab] = useState<TabId>('active');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [severityFilter, setSeverityFilter] = useState<string>('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  // Recommendations modal state
  const [recommendationsModalOpen, setRecommendationsModalOpen] = useState(false);
  const [, setSelectedInsightId] = useState<string | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [isLoadingRecommendations, setIsLoadingRecommendations] = useState(false);

  // Action loading states
  const [actionLoadingIds, setActionLoadingIds] = useState<Set<string>>(new Set());

  // Fetch insights
  const fetchInsights = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await listInsights({
        insight_type: typeFilter as InsightType | undefined,
        severity: severityFilter as InsightSeverity | undefined,
        include_dismissed: selectedTab === 'dismissed',
        include_read: true,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      });

      // Filter based on tab
      const filtered = selectedTab === 'dismissed'
        ? response.insights.filter(i => i.is_dismissed)
        : response.insights.filter(i => !i.is_dismissed);

      setInsights(filtered);
      setTotal(response.total);
      setHasMore(response.has_more);
    } catch (err) {
      console.error('Failed to fetch insights:', err);
      setError('Failed to load insights. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, [typeFilter, severityFilter, selectedTab, page]);

  useEffect(() => {
    fetchInsights();
  }, [fetchInsights]);

  // Handle mark as read
  const handleMarkRead = async (insightId: string) => {
    setActionLoadingIds(prev => new Set(prev).add(insightId));
    try {
      await markInsightRead(insightId);
      setInsights(prev =>
        prev.map(i =>
          i.insight_id === insightId ? { ...i, is_read: true } : i
        )
      );
    } catch (err) {
      console.error('Failed to mark insight as read:', err);
    } finally {
      setActionLoadingIds(prev => {
        const next = new Set(prev);
        next.delete(insightId);
        return next;
      });
    }
  };

  // Handle dismiss
  const handleDismiss = async (insightId: string) => {
    setActionLoadingIds(prev => new Set(prev).add(insightId));
    try {
      await dismissInsight(insightId);
      // Remove from list if on active tab
      if (selectedTab === 'active') {
        setInsights(prev => prev.filter(i => i.insight_id !== insightId));
        setTotal(prev => prev - 1);
      } else {
        setInsights(prev =>
          prev.map(i =>
            i.insight_id === insightId ? { ...i, is_dismissed: true } : i
          )
        );
      }
    } catch (err) {
      console.error('Failed to dismiss insight:', err);
    } finally {
      setActionLoadingIds(prev => {
        const next = new Set(prev);
        next.delete(insightId);
        return next;
      });
    }
  };

  // Handle view recommendations
  const handleViewRecommendations = async (insightId: string) => {
    setSelectedInsightId(insightId);
    setRecommendationsModalOpen(true);
    setIsLoadingRecommendations(true);

    try {
      const response = await getRecommendationsForInsight(insightId);
      setRecommendations(response.recommendations);
    } catch (err) {
      console.error('Failed to fetch recommendations:', err);
      setRecommendations([]);
    } finally {
      setIsLoadingRecommendations(false);
    }
  };

  // Handle accept recommendation
  const handleAcceptRecommendation = async (recommendationId: string) => {
    try {
      await acceptRecommendation(recommendationId);
      setRecommendations(prev =>
        prev.map(r =>
          r.recommendation_id === recommendationId ? { ...r, is_accepted: true } : r
        )
      );
    } catch (err) {
      console.error('Failed to accept recommendation:', err);
    }
  };

  // Handle dismiss recommendation
  const handleDismissRecommendation = async (recommendationId: string) => {
    try {
      await dismissRecommendation(recommendationId);
      setRecommendations(prev =>
        prev.filter(r => r.recommendation_id !== recommendationId)
      );
    } catch (err) {
      console.error('Failed to dismiss recommendation:', err);
    }
  };

  // Tab change handler
  const handleTabChange = (selectedTabIndex: number) => {
    setSelectedTab(selectedTabIndex === 0 ? 'active' : 'dismissed');
    setPage(1);
  };

  // Pagination handlers
  const handleNextPage = () => {
    if (hasMore) {
      setPage(prev => prev + 1);
    }
  };

  const handlePreviousPage = () => {
    if (page > 1) {
      setPage(prev => prev - 1);
    }
  };

  const tabs = [
    {
      id: 'active',
      content: 'Active',
      accessibilityLabel: 'Active insights',
      panelID: 'active-insights-panel',
    },
    {
      id: 'dismissed',
      content: 'Dismissed',
      accessibilityLabel: 'Dismissed insights',
      panelID: 'dismissed-insights-panel',
    },
  ];

  return (
    <>
      {/* Incident banner at top of page */}
      <IncidentBanner />

      <Page
        title="AI Insights"
        subtitle="AI-generated insights about your advertising performance"
      >
      <Layout>
        <Layout.Section>
          <Card>
            <Tabs
              tabs={tabs}
              selected={selectedTab === 'active' ? 0 : 1}
              onSelect={handleTabChange}
            >
              <BlockStack gap="400">
                {/* Filters */}
                <InlineStack gap="400">
                  <Select
                    label="Type"
                    labelInline
                    options={insightTypeOptions}
                    value={typeFilter}
                    onChange={setTypeFilter}
                  />
                  <Select
                    label="Severity"
                    labelInline
                    options={severityOptions}
                    value={severityFilter}
                    onChange={setSeverityFilter}
                  />
                </InlineStack>

                {/* Error banner */}
                {error && (
                  <Banner tone="critical" onDismiss={() => setError(null)}>
                    {error}
                  </Banner>
                )}

                {/* Loading state */}
                {isLoading && (
                  <InlineStack align="center">
                    <Spinner size="large" />
                  </InlineStack>
                )}

                {/* Empty state */}
                {!isLoading && insights.length === 0 && (
                  <EmptyState
                    heading={
                      selectedTab === 'active'
                        ? 'No active insights'
                        : 'No dismissed insights'
                    }
                    image=""
                  >
                    <Text as="p" variant="bodyMd" tone="subdued">
                      {selectedTab === 'active'
                        ? 'Check back later for AI-generated insights about your advertising performance.'
                        : 'Dismissed insights will appear here. You can restore them if needed.'}
                    </Text>
                  </EmptyState>
                )}

                {/* Insights list */}
                {!isLoading && insights.length > 0 && (
                  <BlockStack gap="400">
                    {insights.map(insight => (
                      <InsightCard
                        key={insight.insight_id}
                        insight={insight}
                        onMarkRead={handleMarkRead}
                        onDismiss={selectedTab === 'active' ? handleDismiss : undefined}
                        onViewRecommendations={handleViewRecommendations}
                        isLoading={actionLoadingIds.has(insight.insight_id)}
                      />
                    ))}
                  </BlockStack>
                )}

                {/* Pagination */}
                {!isLoading && total > PAGE_SIZE && (
                  <InlineStack align="center">
                    <Pagination
                      hasPrevious={page > 1}
                      hasNext={hasMore}
                      onPrevious={handlePreviousPage}
                      onNext={handleNextPage}
                    />
                  </InlineStack>
                )}

                {/* Total count */}
                {!isLoading && insights.length > 0 && (
                  <Text as="p" variant="bodySm" tone="subdued" alignment="center">
                    Showing {insights.length} of {total} insights
                  </Text>
                )}
              </BlockStack>
            </Tabs>
          </Card>
        </Layout.Section>
      </Layout>

      {/* Recommendations Modal */}
      <Modal
        open={recommendationsModalOpen}
        onClose={() => setRecommendationsModalOpen(false)}
        title="Recommendations"
        size="large"
      >
        <Modal.Section>
          {isLoadingRecommendations ? (
            <InlineStack align="center">
              <Spinner size="large" />
            </InlineStack>
          ) : recommendations.length === 0 ? (
            <Text as="p" variant="bodyMd" tone="subdued">
              No recommendations available for this insight.
            </Text>
          ) : (
            <BlockStack gap="400">
              {recommendations.map(rec => (
                <RecommendationCard
                  key={rec.recommendation_id}
                  recommendation={rec}
                  onAccept={handleAcceptRecommendation}
                  onDismiss={handleDismissRecommendation}
                />
              ))}
            </BlockStack>
          )}
        </Modal.Section>
      </Modal>
    </Page>
    </>
  );
}

export default InsightsFeed;
