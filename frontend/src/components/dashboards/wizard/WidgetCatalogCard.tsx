/**
 * Widget Catalog Card Component
 *
 * Displays an individual widget catalog item with chart type badge,
 * name, description, dataset, and add/added button.
 *
 * Phase 3 - Dashboard Builder Wizard UI
 */

import { Card, BlockStack, Badge, Text, Button } from '@shopify/polaris';
import type { WidgetCatalogItem } from '../../../types/customDashboards';
import { getChartTypeLabel } from '../../../types/customDashboards';

interface WidgetCatalogCardProps {
  item: WidgetCatalogItem;
  isSelected: boolean;
  onAdd: (item: WidgetCatalogItem) => void;
}

export function WidgetCatalogCard({ item, isSelected, onAdd }: WidgetCatalogCardProps) {
  const handleAdd = () => {
    if (!isSelected) {
      onAdd(item);
    }
  };

  return (
    <Card padding="400">
      <BlockStack gap="300">
        {/* Chart Type Badge */}
        <Badge tone="info">{getChartTypeLabel(item.chart_type)}</Badge>

        {/* Widget Name */}
        <Text as="h3" variant="headingSm" fontWeight="semibold">
          {item.name}
        </Text>

        {/* Widget Description */}
        <Text as="p" variant="bodySm" tone="subdued">
          {item.description}
        </Text>

        {/* Dataset Info */}
        <Text as="p" variant="bodySm">
          <Text as="span" variant="bodySm" fontWeight="medium">
            Dataset:
          </Text>{' '}
          {item.required_dataset}
        </Text>

        {/* Add/Added Button */}
        {isSelected ? (
          <Button variant="plain" tone="success" disabled fullWidth>
            Added ✓
          </Button>
        ) : (
          <Button variant="primary" onClick={handleAdd} fullWidth>
            Add Widget
          </Button>
        )}
      </BlockStack>
    </Card>
  );
}
