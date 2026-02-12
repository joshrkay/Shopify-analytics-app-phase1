/**
 * Category Sidebar Component
 *
 * Displays category filter buttons for the widget gallery.
 * Shows counts per category and highlights the selected category.
 *
 * Phase 3 - Dashboard Builder Wizard UI
 */

import { Card, BlockStack, Text, Button } from '@shopify/polaris';
import type { ChartType } from '../../../types/customDashboards';
import { getChartTypeLabel } from '../../../types/customDashboards';

interface CategorySidebarProps {
  selectedCategory?: ChartType;
  onSelectCategory: (category?: ChartType) => void;
  widgetCounts: Record<ChartType | 'all', number>;
}

const CHART_TYPES: ChartType[] = ['line', 'bar', 'area', 'pie', 'kpi', 'table'];

export function CategorySidebar({
  selectedCategory,
  onSelectCategory,
  widgetCounts,
}: CategorySidebarProps) {
  return (
    <Card padding="400">
      <BlockStack gap="300">
        {/* Header */}
        <Text as="p" variant="headingSm" fontWeight="semibold">
          Filter by type
        </Text>

        {/* Category Buttons */}
        <BlockStack gap="200">
          {/* All button */}
          <Button
            variant={selectedCategory === undefined ? 'primary' : 'plain'}
            onClick={() => onSelectCategory(undefined)}
            fullWidth
            textAlign="left"
          >
            All ({String(widgetCounts.all || 0)})
          </Button>

          {/* Chart type buttons */}
          {CHART_TYPES.map((type) => (
            <Button
              key={type}
              variant={selectedCategory === type ? 'primary' : 'plain'}
              onClick={() => onSelectCategory(type)}
              fullWidth
              textAlign="left"
            >
              {getChartTypeLabel(type)} ({String(widgetCounts[type] || 0)})
            </Button>
          ))}
        </BlockStack>
      </BlockStack>
    </Card>
  );
}
