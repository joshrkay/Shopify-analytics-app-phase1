/**
 * PieChartWidget
 *
 * Renders a Recharts PieChart. Expects exactly 1 metric and 1 dimension
 * (enforced by backend validation). The dimension values become pie slices,
 * and the metric value determines each slice's size.
 */

import React from 'react';
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
} from 'recharts';
import type { ChartConfig } from '../../types/customDashboards';
import { getColor } from '../../utils/chartColors';

interface PieChartWidgetProps {
  data: Record<string, unknown>[];
  config: ChartConfig;
  width?: number;
  height?: number;
}

export function PieChartWidget({ data, config, width, height = 300 }: PieChartWidgetProps): React.ReactElement {
  const { display } = config;

  // Pie chart expects exactly 1 metric and 1 dimension
  const metric = config.metrics[0];
  const dimension = config.dimensions[0];
  const valueKey = metric?.label ?? metric?.column;
  const nameKey = dimension;

  return (
    <ResponsiveContainer width={width ?? '100%'} height={height}>
      <PieChart>
        <Pie
          data={data}
          dataKey={valueKey}
          nameKey={nameKey}
          cx="50%"
          cy="50%"
          outerRadius="70%"
          label
        >
          {data.map((_entry, index) => (
            <Cell
              key={`cell-${index}`}
              fill={getColor(index, display.color_scheme)}
            />
          ))}
        </Pie>
        <Tooltip />
        {display.show_legend && <Legend />}
      </PieChart>
    </ResponsiveContainer>
  );
}
