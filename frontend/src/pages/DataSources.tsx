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
import { useDataSources, useDataSourceCatalog } from '../hooks/useDataSources';
import type { DataSourceDefinition, UpdateSyncConfigRequest } from '../types/sourceConnection';

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
  const [connectPlatform, setConnectPlatform] = useState<DataSourceDefinition | null>(null);
  const [selectedSource, setSelectedSource] = useState<Source | null>(null);
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [activePopover, setActivePopover] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const { refresh: refreshHealth } = useDataHealth();
  const { disconnecting, testingSourceId, configuring, disconnect, testConnection, updateSyncConfig } =
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

  const openConnectModal = useCallback((platform?: DataSourceDefinition) => {
    setConnectPlatform(platform ?? null);
    setShowConnectModal(true);
  }, []);

  const closeConnectModal = useCallback(() => {
    setShowConnectModal(false);
    setConnectPlatform(null);
  }, []);

  const handleConnectionSuccess = useCallback(async () => {
    closeConnectModal();
    await refetch();
    await refreshHealth();
  }, [closeConnectModal, refetch, refreshHealth]);

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

  const handleConnectFromCatalog = useCallback(() => {
    openConnectModal();
  }, [openConnectModal]);

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
          onAction: () => openConnectModal(),
        }}
      >
        <Layout>
          <Layout.Section>
            <EmptySourcesState
              catalog={catalog}
              onConnect={(platform) => openConnectModal(platform)}
              onBrowseAll={() => openConnectModal()}
            />
          </Layout.Section>
        </Layout>

        <ConnectSourceModal
          open={showConnectModal}
          onClose={closeConnectModal}
          onSuccess={handleConnectionSuccess}
          initialPlatform={connectPlatform}
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
        onAction: () => openConnectModal(),
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
                    <ConnectedSourceCard
                      key={source.id}
                      source={source}
                      onManage={handleConfigureSync}
                      onDisconnect={handleDisconnect}
                      onTestConnection={handleTestConnection}
                      testing={testingSourceId === source.id}
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
                      onConnect={() => openConnectModal(platform)}
                    />
                  ))}
                </InlineGrid>
              </BlockStack>
            </BlockStack>
          </Card>
        </Layout.Section>
      </Layout>

      <ConnectSourceModal
        open={showConnectModal}
        onClose={closeConnectModal}
        onSuccess={handleConnectionSuccess}
        initialPlatform={connectPlatform}
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
