/**
 * Sample Data Generator
 *
 * Generates realistic sample data for widget previews in the dashboard wizard.
 * Each chart type gets appropriate sample data with trends and realistic values.
 *
 * Phase 3 - Dashboard Builder Wizard Enhancements
 */

import type { ChartType, MetricConfig } from '../types/customDashboards';

export interface SampleDataPoint {
  [key: string]: string | number;
}

export interface TrendIndicator {
  direction: 'up' | 'down' | 'neutral';
  percentage: number;
}

/**
 * Generate sample data for chart preview based on chart type and configuration
 *
 * @param chartType - Type of chart (line, bar, pie, kpi, table)
 * @param metrics - Metric configurations from widget config
 * @param dimensions - Dimension fields from widget config
 * @param rowCount - Number of data points to generate (default 10)
 * @returns Array of sample data points
 */
export function generateSampleData(
  chartType: ChartType,
  metrics: MetricConfig[],
  dimensions: string[],
  rowCount: number = 10
): SampleDataPoint[] {
  const dimension = dimensions[0] || 'date';

  switch (chartType) {
    case 'kpi':
      // Single data point for KPI metric
      return [{
        [metrics[0]?.label || 'value']: Math.floor(Math.random() * 50000) + 10000,
      }];

    case 'line':
    case 'bar':
    case 'area':
      // Time-series data with upward trend
      return Array.from({ length: rowCount }, (_, i) => {
        const date = new Date();
        date.setDate(date.getDate() - (rowCount - i - 1));

        const dataPoint: SampleDataPoint = {
          [dimension]: date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
        };

        metrics.forEach((metric, idx) => {
          const key = metric.label || metric.column || `metric_${idx}`;
          const baseValue = Math.random() * 5000 + 1000;
          const trend = i * (50 + Math.random() * 100); // Add upward trend with variance
          const noise = Math.random() * 500 - 250; // Add some noise
          dataPoint[key] = Math.floor(baseValue + trend + noise);
        });

        return dataPoint;
      });

    case 'pie':
      // Category distribution with 5 segments
      const categories = ['Category A', 'Category B', 'Category C', 'Category D', 'Category E'];
      return categories.map((cat, i) => {
        const value = Math.floor(Math.random() * 5000) + 1000 + (i * 500); // Vary sizes
        return {
          [dimension]: cat,
          [metrics[0]?.label || 'value']: value,
        };
      });

    case 'table':
      // Tabular data with multiple columns and rows
      return Array.from({ length: rowCount }, (_, i) => {
        const dataPoint: SampleDataPoint = {
          id: i + 1,
          [dimension]: `Item ${i + 1}`,
        };

        metrics.forEach((metric, idx) => {
          const key = metric.label || metric.column || `column_${idx}`;
          const baseValue = Math.random() * 10000 + 500;
          dataPoint[key] = Math.floor(baseValue);
        });

        return dataPoint;
      });

    default:
      return [];
  }
}

/**
 * Generate a random trend indicator for KPI widgets
 *
 * @returns Trend direction and percentage change
 */
export function generateTrendIndicator(): TrendIndicator {
  const percentage = Math.floor(Math.random() * 30) + 1; // 1-30%
  const random = Math.random();

  let direction: 'up' | 'down' | 'neutral';
  if (random > 0.7) {
    direction = 'up';
  } else if (random > 0.3) {
    direction = 'down';
  } else {
    direction = 'neutral';
  }

  return { direction, percentage };
}

/**
 * Format a number as currency (USD)
 *
 * @param value - Numeric value to format
 * @returns Formatted currency string
 */
export function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

/**
 * Format a number with thousand separators
 *
 * @param value - Numeric value to format
 * @returns Formatted number string
 */
export function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-US').format(value);
}
