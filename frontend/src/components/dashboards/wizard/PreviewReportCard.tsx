/**
 * Preview Report Card
 *
 * Displays a widget with sample data visualization in the preview step.
 * Uses ChartRenderer with generated sample data to show realistic previews.
 *
 * Phase 3 - Dashboard Builder Wizard Enhancements
 */

import { useMemo } from 'react';
import { Card, BlockStack, InlineStack, Text, Icon } from '@shopify/polaris';
import { ArrowUpIcon, ArrowDownIcon } from '@shopify/polaris-icons';
import { ChartRenderer } from '../../charts/ChartRenderer';
import { generateSampleData, generateTrendIndicator, formatCurrency } from '../../../utils/sampleDataGenerator';
import type { Report } from '../../../types/customDashboards';
import { getChartTypeLabel } from '../../../types/customDashboards';

interface PreviewReportCardProps {
  report: Report;
}

export function PreviewReportCard({ report }: PreviewReportCardProps) {
  // Generate sample data for preview
  const sampleData = useMemo(() => {
    const data = generateSampleData(
      report.chart_type,
      report.config_json.metrics || [],
      report.config_json.dimensions || [],
      10
    );

    // Convert to the format ChartRenderer expects
    return data as Record<string, unknown>[];
  }, [report.chart_type, report.config_json]);

  // Generate trend for KPI widgets
  const trend = useMemo(() => {
    return report.chart_type === 'kpi' ? generateTrendIndicator() : null;
  }, [report.chart_type]);

  // Get KPI value if applicable
  const kpiValue = useMemo(() => {
    if (report.chart_type === 'kpi' && sampleData.length > 0) {
      const firstMetric = report.config_json.metrics?.[0];
      const key = firstMetric?.label || firstMetric?.column || 'value';
      const value = sampleData[0][key];
      return typeof value === 'number' ? formatCurrency(value) : String(value);
    }
    return null;
  }, [report.chart_type, sampleData, report.config_json.metrics]);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Card padding="300">
        <BlockStack gap="300">
          {/* Header */}
          <InlineStack align="space-between" blockAlign="center">
            <BlockStack gap="050">
              <Text as="h3" variant="headingSm" fontWeight="semibold">
                {report.name}
              </Text>
              <Text as="span" variant="bodySm" tone="subdued">
                {getChartTypeLabel(report.chart_type)}
              </Text>
            </BlockStack>

            {/* Trend indicator for KPI */}
            {trend && trend.direction !== 'neutral' && (
              <InlineStack gap="100" blockAlign="center">
                <Icon
                  source={trend.direction === 'up' ? ArrowUpIcon : ArrowDownIcon}
                  tone={trend.direction === 'up' ? 'success' : 'critical'}
                />
                <Text
                  as="span"
                  variant="bodySm"
                  tone={trend.direction === 'up' ? 'success' : 'critical'}
                  fontWeight="medium"
                >
                  {trend.percentage}%
                </Text>
              </InlineStack>
            )}
          </InlineStack>

          {/* KPI Value Display */}
          {report.chart_type === 'kpi' && kpiValue && (
            <div style={{ padding: '16px 0' }}>
              <Text as="p" variant="heading2xl" fontWeight="bold">
                {kpiValue}
              </Text>
            </div>
          )}

          {/* Chart with sample data */}
          {report.chart_type !== 'kpi' && (
            <div style={{ minHeight: '200px' }}>
              <ChartRenderer
                data={sampleData}
                config={report.config_json}
                chartType={report.chart_type}
                height={200}
              />
            </div>
          )}
        </BlockStack>
      </Card>
    </div>
  );
}
