/**
 * Category Sidebar Component
 *
 * Displays category filter buttons for the widget gallery.
 * Shows counts per category and highlights the selected category.
 * Shows selected widgets section with remove buttons and Continue CTA.
 *
 * Phase 2.3 - Added category icons for visual richness
 */

import { Card, BlockStack, Text, Button, InlineStack, Divider, Icon } from '@shopify/polaris';
import { XIcon, LayoutIcon } from '@shopify/polaris-icons';
import type { ChartType, Report } from '../../../types/customDashboards';
import { getChartTypeLabel } from '../../../types/customDashboards';
import { getChartIcon } from '../../../utils/chartIcons';

interface CategorySidebarProps {
  selectedCategory?: ChartType;
  onSelectCategory: (category?: ChartType) => void;
  widgetCounts: Record<ChartType | 'all', number>;
  selectedWidgets?: Report[];
  onRemoveWidget?: (reportId: string) => void;
  onContinueToLayout?: () => void;
}

const CHART_TYPES: ChartType[] = ['line', 'bar', 'area', 'pie', 'kpi', 'table'];

export function CategorySidebar({
  selectedCategory,
  onSelectCategory,
  widgetCounts,
  selectedWidgets = [],
  onRemoveWidget,
  onContinueToLayout,
}: CategorySidebarProps) {
  const hasSelectedWidgets = selectedWidgets.length > 0;

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
            <InlineStack gap="200" blockAlign="center">
              <Icon source={LayoutIcon} />
              <Text as="span">All ({String(widgetCounts.all || 0)})</Text>
            </InlineStack>
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
              <InlineStack gap="200" blockAlign="center">
                <Icon source={getChartIcon(type)} />
                <Text as="span">{getChartTypeLabel(type)} ({String(widgetCounts[type] || 0)})</Text>
              </InlineStack>
            </Button>
          ))}
        </BlockStack>

        {/* Selected Widgets Section */}
        {hasSelectedWidgets && (
          <>
            <Divider />
            <BlockStack gap="300">
              <Text as="p" variant="headingSm" fontWeight="semibold">
                Selected widgets
              </Text>

              {/* Selected widget items */}
              <BlockStack gap="200">
                {selectedWidgets.map((widget) => (
                  <InlineStack key={widget.id} align="space-between" blockAlign="center">
                    <Text
                      as="span"
                      variant="bodySm"
                      truncate
                      tone="subdued"
                    >
                      {widget.name}
                    </Text>
                    {onRemoveWidget && (
                      <Button
                        icon={XIcon}
                        size="slim"
                        variant="plain"
                        onClick={() => onRemoveWidget(widget.id)}
                        accessibilityLabel={`Remove ${widget.name}`}
                      />
                    )}
                  </InlineStack>
                ))}
              </BlockStack>

              {/* Continue to Layout button */}
              {onContinueToLayout && (
                <Button
                  variant="primary"
                  fullWidth
                  onClick={onContinueToLayout}
                >
                  Continue to Layout →
                </Button>
              )}
            </BlockStack>
          </>
        )}
      </BlockStack>
    </Card>
  );
}
