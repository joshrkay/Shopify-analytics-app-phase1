/**
 * Selected Widgets List Component
 *
 * Displays a list of widgets selected for the dashboard with remove buttons.
 *
 * Phase 3 - Dashboard Builder Wizard UI
 */

import { BlockStack, Text, Card, InlineStack, Badge, Button } from '@shopify/polaris';
import type { Report } from '../../../types/customDashboards';
import { getChartTypeLabel } from '../../../types/customDashboards';

interface SelectedWidgetsListProps {
  widgets: Report[];
  onRemove: (reportId: string) => void;
}

export function SelectedWidgetsList({ widgets, onRemove }: SelectedWidgetsListProps) {
  return (
    <BlockStack gap="300">
      {/* Header */}
      <Text as="p" variant="headingSm" fontWeight="semibold">
        Selected widgets ({widgets.length})
      </Text>

      {/* Empty state */}
      {widgets.length === 0 && (
        <Text as="p" variant="bodySm" tone="subdued">
          No widgets selected yet
        </Text>
      )}

      {/* Widget list */}
      {widgets.length > 0 && (
        <BlockStack gap="200">
          {widgets.map((widget) => (
            <Card key={widget.id} padding="300">
              <InlineStack align="space-between" blockAlign="center">
                {/* Widget info */}
                <BlockStack gap="050">
                  <Text as="p" variant="bodyMd" fontWeight="medium">
                    {widget.name}
                  </Text>
                  <Badge tone="info">{getChartTypeLabel(widget.chart_type)}</Badge>
                </BlockStack>

                {/* Remove button */}
                <Button
                  size="slim"
                  variant="plain"
                  tone="critical"
                  onClick={() => onRemove(widget.id)}
                >
                  Remove
                </Button>
              </InlineStack>
            </Card>
          ))}
        </BlockStack>
      )}
    </BlockStack>
  );
}
