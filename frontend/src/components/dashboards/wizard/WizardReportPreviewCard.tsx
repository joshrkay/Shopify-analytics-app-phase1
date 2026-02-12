/**
 * Wizard Report Preview Card
 *
 * Displays a widget preview in the customize step grid with:
 * - Drag handle for repositioning
 * - Widget name and chart type
 * - Empty state with icon (no real data)
 * - Remove button
 *
 * Phase 3 - Dashboard Builder Wizard Enhancements
 */

import { Card, BlockStack, InlineStack, Text, Button, Icon } from '@shopify/polaris';
import {
  ChartVerticalFilledIcon,
  ChartHorizontalIcon,
} from '@shopify/polaris-icons';
import type { Report } from '../../../types/customDashboards';
import { getChartTypeLabel } from '../../../types/customDashboards';

// Icon mapping per chart type
const CHART_ICONS = {
  line: ChartVerticalFilledIcon,
  bar: ChartHorizontalIcon,
  area: ChartVerticalFilledIcon,
  pie: ChartHorizontalIcon,
  kpi: ChartVerticalFilledIcon,
  table: ChartVerticalFilledIcon,
};

interface WizardReportPreviewCardProps {
  widget: Report;
  onRemove: (reportId: string) => void;
}

export function WizardReportPreviewCard({ widget, onRemove }: WizardReportPreviewCardProps) {
  const ChartIcon = CHART_ICONS[widget.chart_type] || ChartVerticalFilledIcon;

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Card padding="300">
        <BlockStack gap="300">
          {/* Header with drag handle and remove button */}
          <InlineStack align="space-between" blockAlign="center">
            <InlineStack gap="200" blockAlign="center">
              <div
                className="wizard-report-drag-handle"
                style={{ cursor: 'grab', padding: '0 4px', fontSize: '16px', color: '#8c9196' }}
              >
                ::
              </div>
              <BlockStack gap="050">
                <Text as="h3" variant="headingSm" fontWeight="semibold">
                  {widget.name}
                </Text>
                <Text as="span" variant="bodySm" tone="subdued">
                  {getChartTypeLabel(widget.chart_type)}
                </Text>
              </BlockStack>
            </InlineStack>

            <Button
              variant="plain"
              tone="critical"
              size="slim"
              onClick={() => onRemove(widget.id)}
            >
              Remove
            </Button>
          </InlineStack>

          {/* Empty state with chart icon (no real data in customize step) */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: '120px',
              padding: '20px',
              backgroundColor: '#f6f6f7',
              borderRadius: '8px',
            }}
          >
            <div style={{ marginBottom: '8px' }}>
              <Icon source={ChartIcon} tone="subdued" />
            </div>
            <Text as="p" variant="bodySm" tone="subdued" alignment="center">
              {getChartTypeLabel(widget.chart_type)} preview
            </Text>
          </div>
        </BlockStack>
      </Card>
    </div>
  );
}
