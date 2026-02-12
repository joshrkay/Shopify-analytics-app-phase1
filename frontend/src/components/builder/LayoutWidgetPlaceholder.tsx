/**
 * LayoutWidgetPlaceholder Component
 *
 * Individual widget preview in the layout customizer grid.
 * Shows widget name, type, size badge, and action buttons on hover.
 *
 * Phase 2.5 - Layout Customizer UI
 */

import { useState } from 'react';
import { BlockStack, InlineStack, Text, Button, Icon } from '@shopify/polaris';
import {
  ChartBarIcon,
  ChartLineIcon,
  ChartPieIcon,
  TableIcon,
  TrendingUpIcon,
} from '@shopify/polaris-icons';
import type { Report } from '../../types/customDashboards';
import { getWidgetSize } from '../../utils/layoutHelpers';
import './LayoutWidgetPlaceholder.css';

interface LayoutWidgetPlaceholderProps {
  widget: Report;
  onSettings: () => void;
  onMaximize: () => void;
  onDelete: () => void;
}

/**
 * Get chart icon based on chart type
 */
function getChartIcon(chartType: string) {
  switch (chartType) {
    case 'line':
      return ChartLineIcon;
    case 'bar':
      return ChartBarIcon;
    case 'area':
      return ChartLineIcon; // Use line icon for area
    case 'pie':
      return ChartPieIcon;
    case 'kpi':
      return TrendingUpIcon;
    case 'table':
      return TableIcon;
    default:
      return ChartBarIcon;
  }
}

/**
 * Get chart type display label
 */
function getChartTypeLabel(chartType: string): string {
  const labels: Record<string, string> = {
    line: 'Line Chart',
    bar: 'Bar Chart',
    area: 'Area Chart',
    pie: 'Pie Chart',
    kpi: 'KPI Metric',
    table: 'Data Table',
  };
  return labels[chartType] || chartType;
}

export function LayoutWidgetPlaceholder({
  widget,
  onSettings,
  onMaximize,
  onDelete,
}: LayoutWidgetPlaceholderProps) {
  const [isHovered, setIsHovered] = useState(false);

  const size = getWidgetSize(widget.position_json);
  const sizeLabel = size.charAt(0).toUpperCase() + size.slice(1);
  const chartTypeLabel = getChartTypeLabel(widget.chart_type);
  const ChartIcon = getChartIcon(widget.chart_type);

  return (
    <div
      className="widget-placeholder"
      style={{
        gridColumn: `span ${widget.position_json.w}`,
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Header with drag handle, title, and size badge */}
      <div className="widget-placeholder-header">
        <InlineStack gap="200" blockAlign="center" wrap={false}>
          <span className="widget-drag-handle">::</span>
          <BlockStack gap="050">
            <Text as="h4" variant="headingSm" truncate>
              {widget.name}
            </Text>
            <Text as="span" variant="bodySm" tone="subdued" truncate>
              {chartTypeLabel}
            </Text>
          </BlockStack>
        </InlineStack>
        <span className="size-badge">{sizeLabel}</span>
      </div>

      {/* Icon placeholder */}
      <div className="widget-icon-placeholder">
        <Icon source={ChartIcon} tone="subdued" />
      </div>

      {/* Action buttons (visible on hover) */}
      {isHovered && (
        <div className="widget-actions">
          <InlineStack gap="200" align="end">
            <Button size="micro" onClick={onSettings}>
              Settings
            </Button>
            <Button size="micro" onClick={onMaximize}>
              Maximize
            </Button>
            <Button size="micro" tone="critical" onClick={onDelete}>
              Delete
            </Button>
          </InlineStack>
        </div>
      )}
    </div>
  );
}
