/**
 * Chart components barrel export.
 *
 * Re-exports all chart rendering widgets and the ChartRenderer dispatcher
 * for use by the dashboard builder and report preview panels.
 */

export { ChartRenderer } from './ChartRenderer';
export type { ChartProps } from './ChartRenderer';
export { LineChartWidget } from './LineChartWidget';
export { BarChartWidget } from './BarChartWidget';
export { AreaChartWidget } from './AreaChartWidget';
export { PieChartWidget } from './PieChartWidget';
export { KpiWidget } from './KpiWidget';
export { TableWidget } from './TableWidget';
