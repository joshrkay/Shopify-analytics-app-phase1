/**
 * WhatChangedPanel Component
 *
 * Main debug panel showing what changed in the data.
 * Displays data freshness, recent syncs, AI actions, and connector status.
 *
 * Story 9.8 - "What Changed?" Debug Panel
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Modal,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  Card,
  Tabs,
  Spinner,
  Banner,
  Box,
} from '@shopify/polaris';
import {
  getSummary,
  getRecentSyncs,
  getAIActions,
  getConnectorStatusChanges,
} from '../../services/whatChangedApi';
import type {
  WhatChangedSummary,
  RecentSync,
  AIActionSummary,
  ConnectorStatusChange,
} from '../../types/whatChanged';
import {
  getFreshnessTone,
  getFreshnessLabel,
  formatRelativeTime,
  formatDuration,
  formatRowCount,
} from '../../types/whatChanged';

interface WhatChangedPanelProps {
  isOpen: boolean;
  onClose: () => void;
  days?: number;
}

type TabId = 'overview' | 'syncs' | 'ai-actions' | 'connectors';

export function WhatChangedPanel({
  isOpen,
  onClose,
  days = 7,
}: WhatChangedPanelProps) {
  const [selectedTab, setSelectedTab] = useState<TabId>('overview');
  const [summary, setSummary] = useState<WhatChangedSummary | null>(null);
  const [syncs, setSyncs] = useState<RecentSync[]>([]);
  const [aiActions, setAIActions] = useState<AIActionSummary[]>([]);
  const [connectorChanges, setConnectorChanges] = useState<ConnectorStatusChange[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const [summaryData, syncsData, actionsData, changesData] = await Promise.all([
        getSummary(days),
        getRecentSyncs(days),
        getAIActions(days),
        getConnectorStatusChanges(days),
      ]);

      setSummary(summaryData);
      setSyncs(syncsData.syncs);
      setAIActions(actionsData.actions);
      setConnectorChanges(changesData.changes);
    } catch (err) {
      console.error('Failed to fetch what changed data:', err);
      setError('Failed to load data. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, [days]);

  useEffect(() => {
    if (isOpen) {
      fetchData();
    }
  }, [isOpen, fetchData]);

  const handleTabChange = (tabIndex: number) => {
    const tabIds: TabId[] = ['overview', 'syncs', 'ai-actions', 'connectors'];
    setSelectedTab(tabIds[tabIndex]);
  };

  const tabs = [
    { id: 'overview', content: 'Overview', panelID: 'overview-panel' },
    { id: 'syncs', content: `Syncs (${syncs?.length ?? 0})`, panelID: 'syncs-panel' },
    { id: 'ai-actions', content: `AI Actions (${aiActions?.length ?? 0})`, panelID: 'ai-actions-panel' },
    { id: 'connectors', content: `Connectors (${connectorChanges?.length ?? 0})`, panelID: 'connectors-panel' },
  ];

  const renderOverview = () => {
    if (!summary) return null;

    const { data_freshness } = summary;

    return (
      <BlockStack gap="400">
        {/* Freshness Status */}
        <Card>
          <BlockStack gap="300">
            <InlineStack align="space-between" blockAlign="center">
              <Text as="h3" variant="headingSm">
                Data Freshness
              </Text>
              <Badge tone={getFreshnessTone(data_freshness.overall_status)}>
                {getFreshnessLabel(data_freshness.overall_status)}
              </Badge>
            </InlineStack>

            {data_freshness.last_sync_at && (
              <Text as="p" variant="bodySm" tone="subdued">
                Last sync: {formatRelativeTime(data_freshness.last_sync_at)}
                {data_freshness.hours_since_sync !== undefined &&
                  ` (${data_freshness.hours_since_sync} hours ago)`}
              </Text>
            )}

            {data_freshness.connectors.length > 0 && (
              <Box paddingBlockStart="200">
                <BlockStack gap="100">
                  {data_freshness.connectors.map((conn) => (
                    <InlineStack key={conn.connector_id} align="space-between">
                      <Text as="span" variant="bodySm">
                        {conn.connector_name}
                      </Text>
                      <Badge tone={getFreshnessTone(conn.status)} size="small">
                        {getFreshnessLabel(conn.status)}
                      </Badge>
                    </InlineStack>
                  ))}
                </BlockStack>
              </Box>
            )}
          </BlockStack>
        </Card>

        {/* Summary Stats */}
        <Card>
          <BlockStack gap="300">
            <Text as="h3" variant="headingSm">
              Last {days} Days
            </Text>
            <InlineStack gap="400" wrap>
              <Box>
                <Text as="p" variant="headingLg">
                  {summary.recent_syncs_count}
                </Text>
                <Text as="p" variant="bodySm" tone="subdued">
                  Syncs
                </Text>
              </Box>
              <Box>
                <Text as="p" variant="headingLg">
                  {summary.recent_ai_actions_count}
                </Text>
                <Text as="p" variant="bodySm" tone="subdued">
                  AI Actions
                </Text>
              </Box>
              <Box>
                <Text as="p" variant="headingLg">
                  {summary.metric_changes_count}
                </Text>
                <Text as="p" variant="bodySm" tone="subdued">
                  Data Updates
                </Text>
              </Box>
              {summary.open_incidents_count > 0 && (
                <Box>
                  <Text as="p" variant="headingLg" tone="critical">
                    {summary.open_incidents_count}
                  </Text>
                  <Text as="p" variant="bodySm" tone="subdued">
                    Open Issues
                  </Text>
                </Box>
              )}
            </InlineStack>
          </BlockStack>
        </Card>
      </BlockStack>
    );
  };

  const renderSyncs = () => {
    if (!syncs || syncs.length === 0) {
      return (
        <Text as="p" variant="bodyMd" tone="subdued">
          No sync activity in the last {days} days.
        </Text>
      );
    }

    return (
      <BlockStack gap="200">
        {syncs.map((sync) => (
          <Card key={sync.sync_id}>
            <InlineStack align="space-between" blockAlign="start">
              <BlockStack gap="100">
                <InlineStack gap="200" blockAlign="center">
                  <Text as="span" variant="bodyMd" fontWeight="semibold">
                    {sync.connector_name}
                  </Text>
                  <Badge
                    tone={
                      sync.status === 'success'
                        ? 'success'
                        : sync.status === 'failed'
                        ? 'critical'
                        : 'info'
                    }
                  >
                    {sync.status}
                  </Badge>
                </InlineStack>
                <Text as="p" variant="bodySm" tone="subdued">
                  {formatRelativeTime(sync.started_at)}
                  {sync.rows_synced !== undefined &&
                    ` · ${formatRowCount(sync.rows_synced)} rows`}
                  {sync.duration_seconds !== undefined &&
                    ` · ${formatDuration(sync.duration_seconds)}`}
                </Text>
                {sync.error_message && (
                  <Text as="p" variant="bodySm" tone="critical">
                    {sync.error_message}
                  </Text>
                )}
              </BlockStack>
            </InlineStack>
          </Card>
        ))}
      </BlockStack>
    );
  };

  const renderAIActions = () => {
    if (!aiActions || aiActions.length === 0) {
      return (
        <Text as="p" variant="bodyMd" tone="subdued">
          No AI action activity in the last {days} days.
        </Text>
      );
    }

    return (
      <BlockStack gap="200">
        {aiActions.map((action) => (
          <Card key={action.action_id}>
            <BlockStack gap="100">
              <InlineStack gap="200" blockAlign="center">
                <Text as="span" variant="bodyMd" fontWeight="semibold">
                  {action.action_type}
                </Text>
                <Badge
                  tone={
                    action.status === 'executed' || action.status === 'approved'
                      ? 'success'
                      : action.status === 'rejected'
                      ? 'attention'
                      : 'info'
                  }
                >
                  {action.status}
                </Badge>
              </InlineStack>
              <Text as="p" variant="bodySm">
                {action.target_name}
                {action.target_platform && ` on ${action.target_platform}`}
              </Text>
              <Text as="p" variant="bodySm" tone="subdued">
                {formatRelativeTime(action.performed_at)}
                {action.performed_by && ` by ${action.performed_by}`}
              </Text>
            </BlockStack>
          </Card>
        ))}
      </BlockStack>
    );
  };

  const renderConnectorChanges = () => {
    if (!connectorChanges || connectorChanges.length === 0) {
      return (
        <Text as="p" variant="bodyMd" tone="subdued">
          No connector status changes in the last {days} days.
        </Text>
      );
    }

    return (
      <BlockStack gap="200">
        {connectorChanges.map((change, idx) => (
          <Card key={`${change.connector_id}-${idx}`}>
            <BlockStack gap="100">
              <Text as="span" variant="bodyMd" fontWeight="semibold">
                {change.connector_name}
              </Text>
              <InlineStack gap="100" blockAlign="center">
                <Badge>{change.previous_status}</Badge>
                <Text as="span" variant="bodySm">
                  →
                </Text>
                <Badge>{change.new_status}</Badge>
              </InlineStack>
              <Text as="p" variant="bodySm" tone="subdued">
                {formatRelativeTime(change.changed_at)}
              </Text>
              {change.reason && (
                <Text as="p" variant="bodySm">
                  {change.reason}
                </Text>
              )}
            </BlockStack>
          </Card>
        ))}
      </BlockStack>
    );
  };

  const renderContent = () => {
    switch (selectedTab) {
      case 'overview':
        return renderOverview();
      case 'syncs':
        return renderSyncs();
      case 'ai-actions':
        return renderAIActions();
      case 'connectors':
        return renderConnectorChanges();
      default:
        return null;
    }
  };

  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="What Changed?"
      size="large"
    >
      <Modal.Section>
        {error && (
          <Box paddingBlockEnd="400">
            <Banner tone="critical" onDismiss={() => setError(null)}>
              {error}
            </Banner>
          </Box>
        )}

        {isLoading ? (
          <InlineStack align="center">
            <Spinner size="large" />
          </InlineStack>
        ) : (
          <Tabs
            tabs={tabs}
            selected={tabs.findIndex((t) => t.id === selectedTab)}
            onSelect={handleTabChange}
          >
            <Box paddingBlockStart="400">{renderContent()}</Box>
          </Tabs>
        )}
      </Modal.Section>
    </Modal>
  );
}

export default WhatChangedPanel;
