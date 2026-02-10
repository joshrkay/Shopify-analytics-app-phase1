/**
 * ChartRenderer
 *
 * Dispatcher component that selects and renders the correct chart widget
 * based on the provided chartType. Handles empty data states and wraps
 * rendering in an ErrorBoundary for fault isolation.
 */

import React from 'react';
import type { ChartType, ChartConfig } from '../../types/customDashboards';
import { ErrorBoundary } from '../ErrorBoundary';
import { LineChartWidget } from './LineChartWidget';
import { BarChartWidget } from './BarChartWidget';
import { AreaChartWidget } from './AreaChartWidget';
import { PieChartWidget } from './PieChartWidget';
import { KpiWidget } from './KpiWidget';
import { TableWidget } from './TableWidget';

export interface ChartProps {
  data: Record<string, unknown>[];
  config: ChartConfig;
  chartType: ChartType;
  width?: number;
  height?: number;
}

function ChartErrorFallback(): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        padding: '16px',
        color: '#6d7175',
      }}
    >
      <p>Failed to render chart. Please check the configuration.</p>
    </div>
  );
}

function EmptyDataMessage(): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        padding: '16px',
        color: '#6d7175',
      }}
    >
      <p>No data available</p>
    </div>
  );
}

function renderChart(
  chartType: ChartType,
  data: Record<string, unknown>[],
  config: ChartConfig,
  width?: number,
  height?: number,
): React.ReactElement {
  switch (chartType) {
    case 'line':
      return <LineChartWidget data={data} config={config} width={width} height={height} />;
    case 'bar':
      return <BarChartWidget data={data} config={config} width={width} height={height} />;
    case 'area':
      return <AreaChartWidget data={data} config={config} width={width} height={height} />;
    case 'pie':
      return <PieChartWidget data={data} config={config} width={width} height={height} />;
    case 'kpi':
      return <KpiWidget data={data} config={config} width={width} height={height} />;
    case 'table':
      return <TableWidget data={data} config={config} width={width} height={height} />;
    default: {
      const _exhaustive: never = chartType;
      void _exhaustive;
      return <p>Unsupported chart type</p>;
    }
  }
}

export function ChartRenderer({ data, config, chartType, width, height }: ChartProps): React.ReactElement {
  if (!data || data.length === 0) {
    return <EmptyDataMessage />;
  }

  return (
    <ErrorBoundary fallback={<ChartErrorFallback />}>
      {renderChart(chartType, data, config, width, height)}
    </ErrorBoundary>
  );
}
