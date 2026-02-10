/**
 * AreaChartWidget
 *
 * Renders a Recharts AreaChart based on ChartConfig metrics and dimensions.
 * Each metric is rendered as a separate Area with a gradient fill defined
 * via SVG <defs> + <linearGradient>.
 */

import React from 'react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';
import type { ChartConfig } from '../../types/customDashboards';
import { getColor } from '../../utils/chartColors';

interface AreaChartWidgetProps {
  data: Record<string, unknown>[];
  config: ChartConfig;
  width?: number;
  height?: number;
}

export function AreaChartWidget({ data, config, width, height = 300 }: AreaChartWidgetProps): React.ReactElement {
  const xAxisKey = config.dimensions.length > 0 ? config.dimensions[0] : undefined;
  const { display } = config;

  return (
    <ResponsiveContainer width={width ?? '100%'} height={height}>
      <AreaChart data={data} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
        <defs>
          {config.metrics.map((metric, index) => {
            const color = getColor(index, display.color_scheme);
            const gradientId = `gradient-${metric.label ?? metric.column}`;
            return (
              <linearGradient key={gradientId} id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={color} stopOpacity={0.3} />
                <stop offset="95%" stopColor={color} stopOpacity={0.05} />
              </linearGradient>
            );
          })}
        </defs>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis
          dataKey={xAxisKey}
          label={
            display.axis_label_x
              ? { value: display.axis_label_x, position: 'insideBottom', offset: -5 }
              : undefined
          }
        />
        <YAxis
          label={
            display.axis_label_y
              ? { value: display.axis_label_y, angle: -90, position: 'insideLeft' }
              : undefined
          }
        />
        <Tooltip />
        {display.show_legend && <Legend />}
        {config.metrics.map((metric, index) => {
          const dataKey = metric.label ?? metric.column;
          const color = getColor(index, display.color_scheme);
          const gradientId = `gradient-${dataKey}`;
          return (
            <Area
              key={dataKey}
              type="monotone"
              dataKey={dataKey}
              stroke={color}
              fill={`url(#${gradientId})`}
              strokeWidth={2}
            />
          );
        })}
      </AreaChart>
    </ResponsiveContainer>
  );
}
