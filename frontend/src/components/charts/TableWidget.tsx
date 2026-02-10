/**
 * TableWidget
 *
 * Renders data in a Shopify Polaris DataTable.
 * Column headings are derived from config dimensions followed by metrics.
 * Each data row is mapped to an array of cell values matching the column order.
 */

import React from 'react';
import { DataTable } from '@shopify/polaris';
import type { ChartConfig } from '../../types/customDashboards';

interface TableWidgetProps {
  data: Record<string, unknown>[];
  config: ChartConfig;
  width?: number;
  height?: number;
}

export function TableWidget({ data, config }: TableWidgetProps): React.ReactElement {
  // Build column keys: dimensions first, then metrics
  const dimensionColumns = config.dimensions;
  const metricColumns = config.metrics.map((m) => m.label ?? m.column);
  const allColumns = [...dimensionColumns, ...metricColumns];

  // Determine column content types for DataTable alignment
  const columnContentTypes: ('text' | 'numeric')[] = [
    ...dimensionColumns.map(() => 'text' as const),
    ...metricColumns.map(() => 'numeric' as const),
  ];

  // Map data records into ordered row arrays
  const rows = data.map((record) =>
    allColumns.map((col) => {
      const value = record[col];
      if (value === null || value === undefined) {
        return '--';
      }
      if (typeof value === 'number') {
        return value.toLocaleString();
      }
      return String(value);
    }),
  );

  return (
    <div style={{ maxHeight: '100%', overflow: 'auto' }}>
      <DataTable
        columnContentTypes={columnContentTypes}
        headings={allColumns}
        rows={rows}
        hoverable
      />
    </div>
  );
}
