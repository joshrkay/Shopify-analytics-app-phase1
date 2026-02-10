/**
 * LineChartWidget
 *
 * Renders a Recharts LineChart based on ChartConfig metrics and dimensions.
 * Each metric is rendered as a separate Line with colors from the shared palette.
 */

import React from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';
import type { ChartConfig } from '../../types/customDashboards';
import { getColor } from '../../utils/chartColors';

interface LineChartWidgetProps {
  data: Record<string, unknown>[];
  config: ChartConfig;
  width?: number;
  height?: number;
}

export function LineChartWidget({ data, config, width, height = 300 }: LineChartWidgetProps): React.ReactElement {
  const xAxisKey = config.dimensions.length > 0 ? config.dimensions[0] : undefined;
  const { display } = config;

  return (
    <ResponsiveContainer width={width ?? '100%'} height={height}>
      <LineChart data={data} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
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
          return (
            <Line
              key={dataKey}
              type="monotone"
              dataKey={dataKey}
              stroke={getColor(index, display.color_scheme)}
              activeDot={{ r: 6 }}
              dot={{ r: 3 }}
            />
          );
        })}
      </LineChart>
    </ResponsiveContainer>
  );
}
