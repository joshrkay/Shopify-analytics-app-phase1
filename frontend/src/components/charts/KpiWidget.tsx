/**
 * KpiWidget
 *
 * Renders a single KPI metric as a large styled number with a label below.
 * Uses Shopify Polaris Text and BlockStack components for layout and typography.
 * Not a Recharts chart -- this is a pure Polaris display widget.
 */

import React from 'react';
import { BlockStack, Text } from '@shopify/polaris';
import type { ChartConfig } from '../../types/customDashboards';

interface KpiWidgetProps {
  data: Record<string, unknown>[];
  config: ChartConfig;
  width?: number;
  height?: number;
}

/**
 * Formats a raw metric value for display.
 * Applies the metric's format string if provided, otherwise
 * uses locale-aware number formatting for numeric values.
 */
function formatValue(value: unknown, format?: string): string {
  if (value === null || value === undefined) {
    return '--';
  }

  const numericValue = typeof value === 'string' ? parseFloat(value) : value;

  if (typeof numericValue === 'number' && !isNaN(numericValue)) {
    if (format === 'percent') {
      return `${(numericValue * 100).toFixed(1)}%`;
    }
    if (format === 'currency') {
      return numericValue.toLocaleString(undefined, {
        style: 'currency',
        currency: 'USD',
      });
    }
    return numericValue.toLocaleString();
  }

  return String(value);
}

export function KpiWidget({ data, config }: KpiWidgetProps): React.ReactElement {
  const metric = config.metrics[0];
  const valueKey = metric?.label ?? metric?.column;
  const rawValue = data.length > 0 && valueKey ? data[0][valueKey] : undefined;
  const displayValue = formatValue(rawValue, metric?.format);
  const label = metric?.label ?? metric?.column ?? 'Metric';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        padding: '16px',
      }}
    >
      <BlockStack align="center" inlineAlign="center" gap="200">
        <Text variant="heading2xl" as="p" alignment="center">
          {displayValue}
        </Text>
        <Text variant="bodyMd" as="p" tone="subdued" alignment="center">
          {label}
        </Text>
      </BlockStack>
    </div>
  );
}
