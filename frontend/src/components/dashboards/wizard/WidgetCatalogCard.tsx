/**
 * Widget Catalog Card Component
 *
 * Displays an individual widget catalog item with chart type icon and badge,
 * name, description, dataset, and add/added button.
 *
 * Phase 2.3 - Enhanced with icons, hover states, and visual richness
 */

import { Card, BlockStack, Badge, Text, Button, Icon, InlineStack } from '@shopify/polaris';
import type { WidgetCatalogItem } from '../../../types/customDashboards';
import { getChartTypeLabel } from '../../../types/customDashboards';
import { getChartIcon } from '../../../utils/chartIcons';
import styles from './WidgetCatalogCard.module.css';

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

  const cardClassName = `${styles.catalogCard} ${
    isSelected ? styles.catalogCardSelected : ''
  }`;

  return (
    <div className={cardClassName} onClick={handleAdd}>
      <Card padding="400">
        <BlockStack gap="300">
          {/* Chart Type Icon and Badge */}
          <InlineStack gap="200" blockAlign="center">
            <div className={styles.iconWrapper}>
              <Icon source={getChartIcon(item.chart_type)} tone="info" />
            </div>
            <Badge tone="info">{getChartTypeLabel(item.chart_type)}</Badge>
          </InlineStack>

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

          {/* Add/Added State */}
          {isSelected ? (
            <Badge tone="success" size="large">
              Added ✓
            </Badge>
          ) : (
            <Button variant="primary" onClick={handleAdd} fullWidth>
              Add Widget
            </Button>
          )}
        </BlockStack>
      </Card>
    </div>
  );
}
