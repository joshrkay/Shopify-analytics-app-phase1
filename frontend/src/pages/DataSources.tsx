/**
 * Data Sources Page
 *
 * Displays all connected data sources (Shopify + ad platforms) in a unified list.
 * Each source shows: platform name, status badge, auth type, and last sync time.
 *
 * Includes connection wizard for adding new data sources.
 *
 * Story 2.1.1 — Unified Source domain model
 * Phase 3 — Subphase 3.5: Connection Wizard Integration
 */

import { useState, useEffect, useCallback } from 'react';
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
  EmptyState,
  Box,
  Button,
  Popover,
  ActionList,
  Toast,
  Frame,
} from '@shopify/polaris';
import { RefreshIcon, MenuVerticalIcon } from '@shopify/polaris-icons';

import { listSources } from '../services/sourcesApi';
import { PLATFORM_DISPLAY_NAMES } from '../types/sources';
import type { Source, SourceStatus } from '../types/sources';
import { ConnectSourceModal } from '../components/sources/ConnectSourceModal';
import { DisconnectConfirmationModal } from '../components/sources/DisconnectConfirmationModal';
import { SyncConfigModal } from '../components/sources/SyncConfigModal';
import { useDataHealth } from '../contexts/DataHealthContext';
import { useSourceMutations } from '../hooks/useSourceConnection';
import type { UpdateSyncConfigRequest } from '../types/sourceConnection';

function getStatusBadge(status: SourceStatus) {
  switch (status) {
    case 'active':
      return <Badge tone="success">Active</Badge>;
    case 'pending':
      return <Badge tone="attention">Pending</Badge>;
    case 'failed':
      return <Badge tone="critical">Failed</Badge>;
    case 'inactive':
      return <Badge>Inactive</Badge>;
    default:
      return <Badge>{status}</Badge>;
  }
}

function formatLastSync(lastSyncAt: string | null): string {
  if (!lastSyncAt) {
    return 'Never synced';
  }
  const date = new Date(lastSyncAt);
  return date.toLocaleString();
}

function formatAuthType(authType: string): string {
  switch (authType) {
    case 'oauth':
      return 'OAuth';
    case 'api_key':
      return 'API Key';
    default:
      return authType;
  }
}

export default function DataSources() {
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [selectedSource, setSelectedSource] = useState<Source | null>(null);
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [activePopover, setActivePopover] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const { refresh: refreshHealth } = useDataHealth();
  const { disconnecting, testing, configuring, disconnect, testConnection, updateSyncConfig } =
    useSourceMutations();

  const loadSources = useCallback(async (showRefreshing = false) => {
    if (showRefreshing) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);

    try {
      const data = await listSources();
      setSources(data);
    } catch (err) {
      console.error('Failed to load data sources:', err);
      setError('Failed to load data sources. Please try again.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await listSources();
        if (!cancelled) {
          setSources(data);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to load data sources:', err);
          setError('Failed to load data sources. Please try again.');
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, []);

  const handleRefresh = () => {
    loadSources(true);
  };

  const handleConnectionSuccess = useCallback(async () => {
    setShowConnectModal(false);
    // Refresh sources list and health monitoring
    await loadSources(true);
    await refreshHealth();
  }, [loadSources, refreshHealth]);

  const handleTestConnection = useCallback(
    async (source: Source) => {
      setActivePopover(null);
      try {
        const result = await testConnection(source.id);
        setToastMessage(
          result.success
            ? `Connection to ${source.displayName} is working`
            : `Connection test failed: ${result.message}`
        );
      } catch (err) {
        setToastMessage(`Failed to test connection to ${source.displayName}`);
      }
    },
    [testConnection]
  );

  const handleConfigureSync = useCallback((source: Source) => {
    setSelectedSource(source);
    setShowConfigModal(true);
    setActivePopover(null);
  }, []);

  const handleDisconnect = useCallback((source: Source) => {
    setSelectedSource(source);
    setShowDisconnectModal(true);
    setActivePopover(null);
  }, []);

  const handleDisconnectConfirm = useCallback(
    async (sourceId: string) => {
      try {
        await disconnect(sourceId);
        setShowDisconnectModal(false);
        setSelectedSource(null);
        setToastMessage('Data source disconnected successfully');
        // Refresh list
        await loadSources(true);
        await refreshHealth();
      } catch (err) {
        setToastMessage('Failed to disconnect data source');
      }
    },
    [disconnect, loadSources, refreshHealth]
  );

  const handleSyncConfigSave = useCallback(
    async (sourceId: string, config: UpdateSyncConfigRequest) => {
      try {
        await updateSyncConfig(sourceId, config);
        setShowConfigModal(false);
        setSelectedSource(null);
        setToastMessage('Sync configuration updated successfully');
        // Refresh list
        await loadSources(true);
      } catch (err) {
        setToastMessage('Failed to update sync configuration');
      }
    },
    [updateSyncConfig, loadSources]
  );

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
              <SkeletonBodyText lines={8} />
            </Card>
          </Layout.Section>
        </Layout>
      </SkeletonPage>
    );
  }

  if (error) {
    return (
      <Page title="Data Sources">
        <Layout>
          <Layout.Section>
            <Banner
              title="Failed to Load Data Sources"
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

  if (sources.length === 0) {
    return (
      <Page
        title="Data Sources"
        primaryAction={{
          content: 'Connect Source',
          onAction: () => setShowConnectModal(true),
        }}
      >
        <Layout>
          <Layout.Section>
            <Card>
              <EmptyState
                heading="No data sources connected"
                action={{
                  content: 'Connect Your First Source',
                  onAction: () => setShowConnectModal(true),
                }}
                image="https://cdn.shopify.com/s/files/1/0262/4071/2726/files/emptystate-files.png"
              >
                <p>Connect your Shopify store or ad platforms to start syncing data.</p>
              </EmptyState>
            </Card>
          </Layout.Section>
        </Layout>

        <ConnectSourceModal
          open={showConnectModal}
          onClose={() => setShowConnectModal(false)}
          onSuccess={handleConnectionSuccess}
        />
      </Page>
    );
  }

  return (
    <Page
      title="Data Sources"
      subtitle="Manage your connected data sources"
      primaryAction={{
        content: 'Connect Source',
        onAction: () => setShowConnectModal(true),
      }}
      secondaryActions={[
        {
          content: 'Refresh',
          icon: RefreshIcon,
          loading: refreshing,
          onAction: handleRefresh,
        },
      ]}
    >
      <Layout>
        <Layout.Section>
          <Card>
            <BlockStack gap="400">
              <Text as="h2" variant="headingMd">
                Connected Sources ({sources.length})
              </Text>

              <BlockStack gap="300">
                {sources.map((source) => (
                  <Box
                    key={source.id}
                    background="bg-surface"
                    borderColor="border"
                    borderWidth="025"
                    borderRadius="200"
                    padding="300"
                  >
                    <InlineStack align="space-between" blockAlign="center" wrap={false}>
                      <BlockStack gap="100">
                        <Text as="span" variant="bodyMd" fontWeight="semibold">
                          {source.displayName}
                        </Text>
                        <InlineStack gap="200">
                          <Text as="span" variant="bodySm" tone="subdued">
                            {PLATFORM_DISPLAY_NAMES[source.platform] ?? source.platform}
                          </Text>
                          <Text as="span" variant="bodySm" tone="subdued">
                            {formatAuthType(source.authType)}
                          </Text>
                        </InlineStack>
                      </BlockStack>

                      <InlineStack gap="300" blockAlign="center">
                        <BlockStack gap="100" inlineAlign="end">
                          <Text as="span" variant="bodySm" tone="subdued">
                            Last synced
                          </Text>
                          <Text as="span" variant="bodySm">
                            {formatLastSync(source.lastSyncAt)}
                          </Text>
                        </BlockStack>
                        {getStatusBadge(source.status)}
                        <Popover
                          active={activePopover === source.id}
                          activator={
                            <Button
                              icon={MenuVerticalIcon}
                              variant="plain"
                              onClick={() =>
                                setActivePopover(activePopover === source.id ? null : source.id)
                              }
                            />
                          }
                          onClose={() => setActivePopover(null)}
                        >
                          <ActionList
                            items={[
                              {
                                content: 'Test Connection',
                                onAction: () => handleTestConnection(source),
                                disabled: testing,
                              },
                              {
                                content: 'Configure Sync',
                                onAction: () => handleConfigureSync(source),
                              },
                              {
                                content: 'Disconnect',
                                destructive: true,
                                onAction: () => handleDisconnect(source),
                              },
                            ]}
                          />
                        </Popover>
                      </InlineStack>
                    </InlineStack>
                  </Box>
                ))}
              </BlockStack>
            </BlockStack>
          </Card>
        </Layout.Section>
      </Layout>

      <ConnectSourceModal
        open={showConnectModal}
        onClose={() => setShowConnectModal(false)}
        onSuccess={handleConnectionSuccess}
      />

      <DisconnectConfirmationModal
        open={showDisconnectModal}
        source={selectedSource}
        disconnecting={disconnecting}
        onConfirm={handleDisconnectConfirm}
        onCancel={() => {
          setShowDisconnectModal(false);
          setSelectedSource(null);
        }}
      />

      <SyncConfigModal
        open={showConfigModal}
        source={selectedSource}
        configuring={configuring}
        onSave={handleSyncConfigSave}
        onCancel={() => {
          setShowConfigModal(false);
          setSelectedSource(null);
        }}
      />

      {toastMessage && (
        <Frame>
          <Toast content={toastMessage} onDismiss={() => setToastMessage(null)} />
        </Frame>
      )}
    </Page>
  );
}
