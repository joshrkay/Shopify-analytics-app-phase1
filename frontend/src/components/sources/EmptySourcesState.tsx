/**
 * Empty Sources State Component
 *
 * Enhanced empty state for the Data Sources page when no connections exist.
 * Shows a hero CTA, a 2x2 grid of popular integrations, and a browse-all button.
 *
 * Phase 3 — Subphase 3.3: Source Catalog Page
 */

import {
  Card,
  EmptyState,
  BlockStack,
  InlineStack,
  InlineGrid,
  Text,
  Button,
} from '@shopify/polaris';
import type { DataSourceDefinition } from '../../types/sourceConnection';
import { IntegrationCard } from './IntegrationCard';

interface EmptySourcesStateProps {
  catalog: DataSourceDefinition[];
  onConnect: (platform: DataSourceDefinition) => void;
  onBrowseAll: () => void;
}

export function EmptySourcesState({ catalog, onConnect, onBrowseAll }: EmptySourcesStateProps) {
  const popularSources = catalog.slice(0, 4);

  return (
    <BlockStack gap="800">
      <Card>
        <EmptyState
          heading="No data sources connected yet"
          action={{
            content: 'Connect Your First Source',
            onAction: onBrowseAll,
          }}
          image="https://cdn.shopify.com/s/files/1/0262/4071/2726/files/emptystate-files.png"
        >
          <p>
            Connect your Shopify store or ad platforms to start syncing data and unlocking
            insights.
          </p>
        </EmptyState>
      </Card>

      {popularSources.length > 0 && (
        <BlockStack gap="400">
          <Text as="h2" variant="headingMd">
            Popular Integrations
          </Text>
          <InlineGrid columns={{ xs: 1, sm: 2, md: 2 }} gap="400">
            {popularSources.map((platform) => (
              <IntegrationCard
                key={platform.id}
                platform={platform}
                isConnected={false}
                onConnect={onConnect}
              />
            ))}
          </InlineGrid>
        </BlockStack>
      )}

      {catalog.length > 4 && (
        <InlineStack align="center">
          <Button onClick={onBrowseAll}>
            {`Browse all ${catalog.length}+ sources`}
          </Button>
        </InlineStack>
      )}
    </BlockStack>
  );
}
