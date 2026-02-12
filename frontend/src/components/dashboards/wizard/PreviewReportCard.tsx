/**
 * Preview Report Card
 *
 * Displays a widget with sample or live data visualization in the preview step.
 * Supports two modes:
 * - Sample data mode (default): Uses generated sample data for quick previews
 * - Live data mode: Fetches real data from the backend with graceful fallback
 *
 * Phase 2.6 - Preview Step Live Data Integration
 */

import { useMemo, useState, useEffect } from 'react';
import { Card, BlockStack, InlineStack, Text, Icon, SkeletonDisplayText, SkeletonBodyText, Banner, Box } from '@shopify/polaris';
import { ArrowUpIcon, ArrowDownIcon } from '@shopify/polaris-icons';
import { ChartRenderer } from '../../charts/ChartRenderer';
import { generateSampleData, generateTrendIndicator, formatCurrency } from '../../../utils/sampleDataGenerator';
import { useReportData } from '../../../hooks/useReportData';
import type { Report } from '../../../types/customDashboards';
import { getChartTypeLabel } from '../../../types/customDashboards';

interface PreviewReportCardProps {
  report: Report;
  useLiveData?: boolean; // NEW: Enable live data fetching
  dateRange?: string; // NEW: Date range for queries (default "30")
  refetchKey?: number; // NEW: Key that triggers refetch when changed
}

export function PreviewReportCard({ report, useLiveData = false, dateRange = '30', refetchKey = 0 }: PreviewReportCardProps) {
  // Fetch live data if enabled
  const { data: liveDataResponse, isLoading, error, isFallback, queryStartTime } = useReportData(report, {
    enabled: useLiveData,
    dateRange,
    refetchKey,
  });

  // Track if query is slow (>5s)
  const [showSlowQueryWarning, setShowSlowQueryWarning] = useState(false);

  useEffect(() => {
    if (queryStartTime && isLoading) {
      // Set timer to show warning after 5 seconds
      const timer = setTimeout(() => {
        setShowSlowQueryWarning(true);
      }, 5000);

      return () => {
        clearTimeout(timer);
        setShowSlowQueryWarning(false);
      };
    } else {
      setShowSlowQueryWarning(false);
    }
  }, [queryStartTime, isLoading]);

  // Generate sample data as fallback
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

  // Determine which data to use
  const chartData = useLiveData && liveDataResponse ? liveDataResponse.data : sampleData;

  // Generate trend for KPI widgets
  const trend = useMemo(() => {
    return report.chart_type === 'kpi' ? generateTrendIndicator() : null;
  }, [report.chart_type]);

  // Get KPI value if applicable
  const kpiValue = useMemo(() => {
    if (report.chart_type === 'kpi' && chartData.length > 0) {
      const firstMetric = report.config_json.metrics?.[0];
      const key = firstMetric?.label || firstMetric?.column || 'value';
      const value = chartData[0][key];
      return typeof value === 'number' ? formatCurrency(value) : String(value);
    }
    return null;
  }, [report.chart_type, chartData, report.config_json.metrics]);

  // Loading state
  if (useLiveData && isLoading) {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <Card padding="300">
          <BlockStack gap="200">
            {showSlowQueryWarning && (
              <Banner tone="info">
                Query is taking longer than expected. Please wait...
              </Banner>
            )}
            <SkeletonDisplayText size="small" />
            <SkeletonBodyText lines={8} />
          </BlockStack>
        </Card>
      </div>
    );
  }

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

          {/* Fallback Banner (only show if no error message) */}
          {isFallback && !error && (
            <Banner tone="info">
              Showing sample data. Live data preview coming soon.
            </Banner>
          )}

          {/* Error Banner */}
          {error && (
            <Banner tone="critical">{error}</Banner>
          )}

          {/* KPI Value Display */}
          {report.chart_type === 'kpi' && kpiValue && (
            <div style={{ padding: '16px 0' }}>
              <Text as="p" variant="heading2xl" fontWeight="bold">
                {kpiValue}
              </Text>
            </div>
          )}

          {/* Chart Renderer */}
          {report.chart_type !== 'kpi' && (
            <Box minHeight="200px">
              <ChartRenderer
                data={chartData}
                config={report.config_json}
                chartType={report.chart_type}
                height={200}
              />
            </Box>
          )}

          {/* Query Info Footer (only for live data) */}
          {useLiveData && liveDataResponse && !isFallback && (
            <Text as="p" variant="bodySm" tone="subdued">
              {liveDataResponse.row_count} rows
              {liveDataResponse.query_duration_ms && ` • ${liveDataResponse.query_duration_ms}ms query time`}
              {liveDataResponse.truncated && ' • Results truncated to 1000 rows'}
            </Text>
          )}
        </BlockStack>
      </Card>
    </div>
  );
}
