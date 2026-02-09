/**
 * Sync Health Page
 *
 * Displays overall sync health and per-connector status.
 * Shopify-embedded React component using Polaris.
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  Page,
  Layout,
  Card,
  Banner,
  SkeletonPage,
  SkeletonBodyText,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  ProgressBar,
  EmptyState,
  Box,
} from '@shopify/polaris';
import {
  RefreshIcon,
} from '@shopify/polaris-icons';

import ConnectorHealthCard from '../components/ConnectorHealthCard';
import BackfillModal from '../components/BackfillModal';
import {
  getSyncHealthSummary,
  getDashboardBlockStatus,
  type SyncHealthSummary,
  type ConnectorHealth,
  type DashboardBlockStatus,
} from '../services/syncHealthApi';

const SyncHealth: React.FC = () => {
  // State
  const [summary, setSummary] = useState<SyncHealthSummary | null>(null);
  const [blockStatus, setBlockStatus] = useState<DashboardBlockStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Backfill modal state
  const [backfillModalOpen, setBackfillModalOpen] = useState(false);
  const [selectedConnector, setSelectedConnector] = useState<ConnectorHealth | null>(null);

  // Load data
  const loadData = useCallback(async (showRefreshing = false) => {
    if (showRefreshing) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);

    try {
      const [summaryData, blockData] = await Promise.all([
        getSyncHealthSummary(),
        getDashboardBlockStatus(),
      ]);

      setSummary(summaryData);
      setBlockStatus(blockData);
    } catch (err) {
      console.error('Failed to load sync health:', err);
      setError('Failed to load sync health data. Please try again.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadData();
  }, [loadData]);

  // Handle refresh
  const handleRefresh = () => {
    loadData(true);
  };

  // Handle backfill
  const handleBackfillClick = (connector: ConnectorHealth) => {
    setSelectedConnector(connector);
    setBackfillModalOpen(true);
  };

  // Handle backfill modal close
  const handleBackfillClose = () => {
    setBackfillModalOpen(false);
    setSelectedConnector(null);
  };

  // Handle backfill success
  const handleBackfillSuccess = () => {
    setBackfillModalOpen(false);
    setSelectedConnector(null);
    loadData(true);
  };

  // Get status badge
  const getOverallStatusBadge = () => {
    if (!summary) return null;

    switch (summary.overall_status) {
      case 'healthy':
        return <Badge tone="success">Healthy</Badge>;
      case 'degraded':
        return <Badge tone="attention">Degraded</Badge>;
      case 'critical':
        return <Badge tone="critical">Critical</Badge>;
      default:
        return null;
    }
  };

  // Loading state
  if (loading) {
    return (
      <SkeletonPage primaryAction>
        <Layout>
          <Layout.Section>
            <Card>
              <SkeletonBodyText lines={4} />
            </Card>
          </Layout.Section>
          <Layout.Section>
            <Card>
              <SkeletonBodyText lines={10} />
            </Card>
          </Layout.Section>
        </Layout>
      </SkeletonPage>
    );
  }

  // Error state
  if (error) {
    return (
      <Page title="Sync Health">
        <Layout>
          <Layout.Section>
            <Banner
              title="Failed to Load Sync Health"
              tone="critical"
              action={{ content: 'Retry', onAction: handleRefresh }}
            >
              <p>{error}</p>
            </Banner>
          </Layout.Section>
        </Layout>
      </Page>
    );
  }

  // Empty state
  if (!summary || summary.total_connectors === 0) {
    return (
      <Page title="Sync Health">
        <Layout>
          <Layout.Section>
            <Card>
              <EmptyState
                heading="No data sources connected"
                image="https://cdn.shopify.com/s/files/1/0262/4071/2726/files/emptystate-files.png"
              >
                <p>Connect your data sources to start monitoring sync health.</p>
              </EmptyState>
            </Card>
          </Layout.Section>
        </Layout>
      </Page>
    );
  }

  return (
    <Page
      title="Sync Health"
      subtitle="Monitor data freshness and sync status"
      primaryAction={{
        content: 'Refresh',
        icon: RefreshIcon,
        loading: refreshing,
        onAction: handleRefresh,
      }}
    >
      <Layout>
        {/* Blocking Issues Banner */}
        {blockStatus?.is_blocked && (
          <Layout.Section>
            <Banner
              title="Dashboard Access Blocked"
              tone="critical"
            >
              <BlockStack gap="200">
                <Text as="p">
                  Some dashboards are blocked due to critical data quality issues:
                </Text>
                <ul>
                  {blockStatus.blocking_messages.map((msg, index) => (
                    <li key={index}>{msg}</li>
                  ))}
                </ul>
                <Text as="p">
                  Please resolve these issues to restore dashboard access.
                </Text>
              </BlockStack>
            </Banner>
          </Layout.Section>
        )}

        {/* Warning Banner for Degraded Status */}
        {summary.overall_status === 'degraded' && !blockStatus?.is_blocked && (
          <Layout.Section>
            <Banner
              title="Some Data Sources Are Delayed"
              tone="warning"
            >
              <p>
                {summary.delayed_count} data source{summary.delayed_count > 1 ? 's are' : ' is'} delayed.
                Reports may not reflect the most recent data.
              </p>
            </Banner>
          </Layout.Section>
        )}

        {/* Health Summary Card */}
        <Layout.Section>
          <Card>
            <BlockStack gap="400">
              <InlineStack align="space-between" blockAlign="center">
                <Text as="h2" variant="headingMd">
                  Overall Health
                </Text>
                {getOverallStatusBadge()}
              </InlineStack>

              {/* Health Score */}
              <BlockStack gap="200">
                <InlineStack align="space-between">
                  <Text as="span" variant="bodyMd">
                    Health Score
                  </Text>
                  <Text as="span" variant="bodyMd" fontWeight="semibold">
                    {summary.health_score.toFixed(0)}%
                  </Text>
                </InlineStack>
                <ProgressBar
                  progress={summary.health_score}
                  tone={
                    summary.health_score >= 80
                      ? 'success'
                      : summary.health_score >= 50
                      ? 'highlight'
                      : 'critical'
                  }
                />
              </BlockStack>

              {/* Summary Stats */}
              <InlineStack gap="400" wrap={false}>
                <Box
                  background="bg-surface-secondary"
                  padding="300"
                  borderRadius="200"
                  minWidth="100px"
                >
                  <BlockStack gap="100">
                    <Text as="span" variant="headingLg" fontWeight="bold">
                      {summary.healthy_count}
                    </Text>
                    <Text as="span" variant="bodySm" tone="subdued">
                      Healthy
                    </Text>
                  </BlockStack>
                </Box>

                <Box
                  background="bg-surface-secondary"
                  padding="300"
                  borderRadius="200"
                  minWidth="100px"
                >
                  <BlockStack gap="100">
                    <Text
                      as="span"
                      variant="headingLg"
                      fontWeight="bold"
                      tone={summary.delayed_count > 0 ? 'caution' : undefined}
                    >
                      {summary.delayed_count}
                    </Text>
                    <Text as="span" variant="bodySm" tone="subdued">
                      Delayed
                    </Text>
                  </BlockStack>
                </Box>

                <Box
                  background="bg-surface-secondary"
                  padding="300"
                  borderRadius="200"
                  minWidth="100px"
                >
                  <BlockStack gap="100">
                    <Text
                      as="span"
                      variant="headingLg"
                      fontWeight="bold"
                      tone={summary.error_count > 0 ? 'critical' : undefined}
                    >
                      {summary.error_count}
                    </Text>
                    <Text as="span" variant="bodySm" tone="subdued">
                      Errors
                    </Text>
                  </BlockStack>
                </Box>

                <Box
                  background="bg-surface-secondary"
                  padding="300"
                  borderRadius="200"
                  minWidth="100px"
                >
                  <BlockStack gap="100">
                    <Text as="span" variant="headingLg" fontWeight="bold">
                      {summary.total_connectors}
                    </Text>
                    <Text as="span" variant="bodySm" tone="subdued">
                      Total
                    </Text>
                  </BlockStack>
                </Box>
              </InlineStack>
            </BlockStack>
          </Card>
        </Layout.Section>

        {/* Connectors List */}
        <Layout.Section>
          <Card>
            <BlockStack gap="400">
              <Text as="h2" variant="headingMd">
                Data Sources ({summary.total_connectors})
              </Text>

              <BlockStack gap="300">
                {summary.connectors.map((connector) => (
                  <ConnectorHealthCard
                    key={connector.connector_id}
                    connector={connector}
                    onBackfillClick={() => handleBackfillClick(connector)}
                  />
                ))}
              </BlockStack>
            </BlockStack>
          </Card>
        </Layout.Section>
      </Layout>

      {/* Backfill Modal */}
      {selectedConnector && (
        <BackfillModal
          open={backfillModalOpen}
          connector={selectedConnector}
          onClose={handleBackfillClose}
          onSuccess={handleBackfillSuccess}
        />
      )}
    </Page>
  );
};

export default SyncHealth;
