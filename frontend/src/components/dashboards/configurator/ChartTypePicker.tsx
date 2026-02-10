/**
 * ChartTypePicker Component
 *
 * Renders a grid of selectable cards, one for each ChartType.
 * The currently selected chart type is visually highlighted with
 * a border style. Clicking a card triggers the onChange callback.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { InlineStack, Card, Text, BlockStack } from '@shopify/polaris';
import type { ChartType } from '../../../types/customDashboards';
import { getChartTypeLabel } from '../../../types/customDashboards';

const CHART_TYPES: ChartType[] = ['line', 'bar', 'area', 'pie', 'kpi', 'table'];

const CHART_TYPE_ICONS: Record<ChartType, string> = {
  line: '\u2014\u2571\u2014',
  bar: '\u2581\u2583\u2585\u2587',
  area: '\u2596\u2584\u2599',
  pie: '\u25D4',
  kpi: '#',
  table: '\u2261',
};

interface ChartTypePickerProps {
  value: ChartType;
  onChange: (type: ChartType) => void;
}

export function ChartTypePicker({ value, onChange }: ChartTypePickerProps) {
  return (
    <BlockStack gap="200">
      <Text as="p" variant="bodyMd" fontWeight="semibold">
        Chart type
      </Text>
      <InlineStack gap="300" wrap>
        {CHART_TYPES.map((type) => {
          const isSelected = type === value;
          return (
            <div
              key={type}
              role="button"
              tabIndex={0}
              onClick={() => onChange(type)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onChange(type);
                }
              }}
              style={{
                cursor: 'pointer',
                border: isSelected
                  ? '2px solid var(--p-color-border-interactive-focus, #2C6ECB)'
                  : '2px solid transparent',
                borderRadius: '8px',
                minWidth: '100px',
              }}
            >
              <Card>
                <BlockStack gap="100" inlineAlign="center">
                  <Text as="p" variant="headingLg" alignment="center">
                    {CHART_TYPE_ICONS[type]}
                  </Text>
                  <Text
                    as="p"
                    variant="bodySm"
                    alignment="center"
                    fontWeight={isSelected ? 'bold' : 'regular'}
                  >
                    {getChartTypeLabel(type)}
                  </Text>
                </BlockStack>
              </Card>
            </div>
          );
        })}
      </InlineStack>
    </BlockStack>
  );
}
