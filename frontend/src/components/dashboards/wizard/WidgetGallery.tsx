/**
 * Widget Gallery Component
 *
 * Displays a grid of widget catalog cards. Handles loading, error, and empty states.
 *
 * Phase 3 - Dashboard Builder Wizard UI
 */

import { BlockStack, Spinner, Banner, EmptyState, Box, Button, Text } from '@shopify/polaris';
import type { WidgetCatalogItem } from '../../../types/customDashboards';
import { WidgetCatalogCard } from './WidgetCatalogCard';

interface WidgetGalleryProps {
  items: WidgetCatalogItem[];
  selectedIds: Set<string>;
  onAddWidget: (item: WidgetCatalogItem) => void;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
}

export function WidgetGallery({
  items,
  selectedIds,
  onAddWidget,
  loading,
  error,
  onRetry,
}: WidgetGalleryProps) {
  // Loading state
  if (loading) {
    return (
      <Box paddingBlockStart="800">
        <BlockStack gap="400" inlineAlign="center">
          <Spinner size="large" />
          <Text as="p">Loading widgets...</Text>
        </BlockStack>
      </Box>
    );
  }

  // Error state
  if (error) {
    return (
      <Banner tone="critical">
        <BlockStack gap="300">
          <Text as="p">{error}</Text>
          {onRetry && (
            <div>
              <Button onClick={onRetry}>Retry</Button>
            </div>
          )}
        </BlockStack>
      </Banner>
    );
  }

  // Empty state
  if (items.length === 0) {
    return (
      <Box paddingBlockStart="800">
        <EmptyState
          heading="No widgets match your filters"
          image=""
        >
          <p>Try selecting a different category or clearing your filters.</p>
        </EmptyState>
      </Box>
    );
  }

  // Grid of widget cards
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
        gap: 'var(--p-space-400)',
      }}
    >
      {items.map((item) => (
        <WidgetCatalogCard
          key={item.id}
          item={item}
          isSelected={selectedIds.has(item.id)}
          onAdd={onAddWidget}
        />
      ))}
    </div>
  );
}
