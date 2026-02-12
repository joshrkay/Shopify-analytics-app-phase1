/**
 * Data Sources Page
 *
 * Displays connected data sources with ConnectedSourceCard components,
 * available integrations grid with IntegrationCard components,
 * and an enhanced empty state when no connections exist.
 *
 * Uses useDataSources hook for 30s-polled connection list and
 * useDataSourceCatalog for available platforms.
 *
 * Story 2.1.1 — Unified Source domain model
 * Phase 3 — Subphase 3.3: Source Catalog Page
 */

import { useState, useCallback } from 'react';
import {
  Page,
  Layout,
  Card,
  Banner,
  SkeletonPage,
  SkeletonBodyText,
  BlockStack,
  InlineStack,
  InlineGrid,
  Text,
  Box,
  Button,
  Toast,
  Frame,
} from '@shopify/polaris';
import { RefreshIcon } from '@shopify/polaris-icons';

import type { Source } from '../types/sources';
import { ConnectSourceModal } from '../components/sources/ConnectSourceModal';
import { DisconnectConfirmationModal } from '../components/sources/DisconnectConfirmationModal';
import { SyncConfigModal } from '../components/sources/SyncConfigModal';
import { ConnectedSourceCard } from '../components/sources/ConnectedSourceCard';
import { IntegrationCard } from '../components/sources/IntegrationCard';
import { EmptySourcesState } from '../components/sources/EmptySourcesState';
import { useDataHealth } from '../contexts/DataHealthContext';
import { useSourceMutations } from '../hooks/useSourceConnection';
import { useDataSources, useDataSourceCatalog } from '../hooks/useDataSources';
import type { UpdateSyncConfigRequest } from '../types/sourceConnection';

export default function DataSources() {
  const {
    connections: sources,
    isLoading: loading,
    error,
    hasConnectedSources,
    refetch,
  } = useDataSources();
  const { catalog } = useDataSourceCatalog();

  const [refreshing, setRefreshing] = useState(false);
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [selectedSource, setSelectedSource] = useState<Source | null>(null);
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const { refresh: refreshHealth } = useDataHealth();
  const { disconnecting, testing, configuring, disconnect, testConnection, updateSyncConfig } =
    useSourceMutations();

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await refetch();
    } finally {
      setRefreshing(false);
    }
  }, [refetch]);

  const handleConnectionSuccess = useCallback(async () => {
    setShowConnectModal(false);
    await refetch();
    await refreshHealth();
  }, [refetch, refreshHealth]);

  const handleTestConnection = useCallback(
    async (source: Source) => {
      try {
        const result = await testConnection(source.id);
        setToastMessage(
          result.success
            ? `Connection to ${source.displayName} is working`
            : `Connection test failed: ${result.message}`,
        );
      } catch {
        setToastMessage(`Failed to test connection to ${source.displayName}`);
      }
    },
    [testConnection],
  );

  const handleConfigureSync = useCallback((source: Source) => {
    setSelectedSource(source);
    setShowConfigModal(true);
  }, []);

  const handleDisconnect = useCallback((source: Source) => {
    setSelectedSource(source);
    setShowDisconnectModal(true);
  }, []);

  const handleDisconnectConfirm = useCallback(
    async (sourceId: string) => {
      try {
        await disconnect(sourceId);
        setShowDisconnectModal(false);
        setSelectedSource(null);
        setToastMessage('Data source disconnected successfully');
        await refetch();
        await refreshHealth();
      } catch {
        setToastMessage('Failed to disconnect data source');
      }
    },
    [disconnect, refetch, refreshHealth],
  );

  const handleSyncConfigSave = useCallback(
    async (sourceId: string, config: UpdateSyncConfigRequest) => {
      try {
        await updateSyncConfig(sourceId, config);
        setShowConfigModal(false);
        setSelectedSource(null);
        setToastMessage('Sync configuration updated successfully');
        await refetch();
      } catch {
        setToastMessage('Failed to update sync configuration');
      }
    },
    [updateSyncConfig, refetch],
  );

  const handleConnectFromCatalog = useCallback(() => {
    setShowConnectModal(true);
  }, []);

  // Derive set of connected platform IDs for IntegrationCard badges
  const connectedPlatforms = new Set(sources.map((s) => s.platform));
  const unconnectedCatalog = catalog.filter((p) => !connectedPlatforms.has(p.platform));

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
              <p>Failed to load data sources. Please try again.</p>
            </Banner>
          </Layout.Section>
        </Layout>
      </Page>
    );
  }

  if (!hasConnectedSources) {
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
            <EmptySourcesState
              catalog={catalog}
              onConnect={() => setShowConnectModal(true)}
              onBrowseAll={() => setShowConnectModal(true)}
            />
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
        content: 'Add Source',
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
          <BlockStack gap="600">
            {/* Connected Sources */}
            <Card>
              <BlockStack gap="400">
                <Text as="h2" variant="headingMd">
                  Connected Sources ({sources.length})
                </Text>

                <BlockStack gap="300">
                  {sources.map((source) => (
                    <ConnectedSourceCard
                      key={source.id}
                      source={source}
                      onManage={handleConfigureSync}
                      onDisconnect={handleDisconnect}
                      onTestConnection={handleTestConnection}
                      testing={testing}
                    />
                  ))}
                </BlockStack>

                {/* Dashed CTA to add new source */}
                <Box
                  background="bg-surface"
                  borderColor="border-secondary"
                  borderWidth="025"
                  borderRadius="200"
                  padding="400"
                >
                  <InlineStack align="center" blockAlign="center">
                    <Button variant="plain" onClick={handleConnectFromCatalog}>
                      + Add New Data Source
                    </Button>
                  </InlineStack>
                </Box>
              </BlockStack>
            </Card>

            {/* Available Integrations */}
            {unconnectedCatalog.length > 0 && (
              <BlockStack gap="400">
                <Text as="h2" variant="headingMd">
                  Available Integrations
                </Text>
                <InlineGrid columns={{ xs: 1, sm: 2, md: 3 }} gap="400">
                  {unconnectedCatalog.map((platform) => (
                    <IntegrationCard
                      key={platform.id}
                      platform={platform}
                      isConnected={false}
                      onConnect={() => setShowConnectModal(true)}
                    />
                  ))}
                </InlineGrid>
              </BlockStack>
            )}
          </BlockStack>
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
