/**
 * ViewReportCard Component
 *
 * Read-only version of ReportCard for the DashboardView page.
 * Displays report name, chart type, and chart preview.
 * No edit/delete actions are available.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect } from 'react';
import {
  Card,
  BlockStack,
  InlineStack,
  Text,
  Spinner,
  Box,
  Banner,
} from '@shopify/polaris';
import { ChartRenderer } from '../charts/ChartRenderer';
import { chartPreview } from '../../services/datasetsApi';
import type {
  Report,
  ChartPreviewResponse,
  MetricDefinition,
  FilterDefinition,
} from '../../types/customDashboards';
import { getChartTypeLabel } from '../../types/customDashboards';

interface ViewReportCardProps {
  report: Report;
}

export function ViewReportCard({ report }: ViewReportCardProps) {
  const [previewData, setPreviewData] = useState<Record<string, unknown>[] | null>(null);
  const [previewLoading, setPreviewLoading] = useState(true);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // Fetch chart preview on mount
  useEffect(() => {
    let cancelled = false;

    async function fetchPreview() {
      setPreviewLoading(true);
      setPreviewError(null);

      try {
        const validMetrics = report.config_json.metrics.filter((m) => m.column !== '');
        if (validMetrics.length === 0) {
          setPreviewData([]);
          setPreviewLoading(false);
          return;
        }

        const metricDefs: MetricDefinition[] = validMetrics.map((m) => ({
          label: m.label ?? `${m.aggregation}(${m.column})`,
          column: m.column,
          aggregate: m.aggregation,
          expressionType: 'SIMPLE' as const,
        }));

        const filterDefs: FilterDefinition[] = report.config_json.filters
          .filter((f) => f.column !== '')
          .map((f) => ({
            column: f.column,
            operator: f.operator,
            value: f.value as string | number | boolean | null,
          }));

        const response: ChartPreviewResponse = await chartPreview({
          dataset_name: report.dataset_name,
          metrics: metricDefs,
          dimensions: report.config_json.dimensions.length > 0
            ? report.config_json.dimensions
            : undefined,
          filters: filterDefs.length > 0 ? filterDefs : undefined,
          time_range: report.config_json.time_range,
          time_grain: report.config_json.time_grain,
          viz_type: report.chart_type,
        });

        if (!cancelled) {
          setPreviewData(response.data);
        }
      } catch (err) {
        if (!cancelled) {
          console.error('Chart preview failed for report:', report.id, err);
          setPreviewError(
            err instanceof Error ? err.message : 'Failed to load preview',
          );
        }
      } finally {
        if (!cancelled) {
          setPreviewLoading(false);
        }
      }
    }

    fetchPreview();

    return () => {
      cancelled = true;
    };
  }, [report]);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Card padding="300">
        <BlockStack gap="200">
          {/* Header */}
          <InlineStack align="space-between" blockAlign="center">
            <BlockStack gap="050">
              <Text as="h3" variant="headingSm">
                {report.name}
              </Text>
              <Text as="span" variant="bodySm" tone="subdued">
                {getChartTypeLabel(report.chart_type)}
              </Text>
            </BlockStack>
          </InlineStack>

          {/* Warnings */}
          {report.warnings.length > 0 && (
            <Banner tone="warning">
              <BlockStack gap="100">
                {report.warnings.map((warning, idx) => (
                  <Text key={idx} as="p" variant="bodySm">
                    {warning}
                  </Text>
                ))}
              </BlockStack>
            </Banner>
          )}

          {/* Chart preview */}
          <Box minHeight="120px">
            {previewLoading && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  height: '120px',
                }}
              >
                <Spinner size="small" />
              </div>
            )}
            {previewError && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  height: '120px',
                  color: '#6d7175',
                }}
              >
                <Text as="p" variant="bodySm" tone="subdued">
                  {previewError}
                </Text>
              </div>
            )}
            {!previewLoading && !previewError && previewData && (
              <ChartRenderer
                data={previewData}
                config={report.config_json}
                chartType={report.chart_type}
              />
            )}
          </Box>
        </BlockStack>
      </Card>
    </div>
  );
}
