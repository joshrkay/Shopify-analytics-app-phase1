/**
 * ReportCard Component
 *
 * Renders a single report within the dashboard grid.
 * Features:
 * - Report name header with drag handle
 * - Chart preview fetched on mount via datasetsApi.chartPreview
 * - Action menu with Edit and Delete options
 * - Warning banner if report has validation warnings
 * - Loading and error states for chart preview
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect } from 'react';
import {
  Card,
  BlockStack,
  InlineStack,
  Text,
  Button,
  Popover,
  ActionList,
  Spinner,
  Banner,
  Box,
} from '@shopify/polaris';
import { useDashboardBuilder } from '../../contexts/DashboardBuilderContext';
import { ChartRenderer } from '../charts/ChartRenderer';
import { chartPreview, validateConfig } from '../../services/datasetsApi';
import type {
  Report,
  ChartPreviewResponse,
  MetricDefinition,
  FilterDefinition,
} from '../../types/customDashboards';
import { getChartTypeLabel } from '../../types/customDashboards';

interface ReportCardProps {
  report: Report;
}

export function ReportCard({ report }: ReportCardProps) {
  const { openReportConfig, removeReport } = useDashboardBuilder();

  const [previewData, setPreviewData] = useState<Record<string, unknown>[] | null>(null);
  const [previewLoading, setPreviewLoading] = useState(true);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [configWarnings, setConfigWarnings] = useState<string[]>([]);
  const [menuActive, setMenuActive] = useState(false);

  // Fetch chart preview on mount
  useEffect(() => {
    let cancelled = false;

    async function fetchPreview() {
      setPreviewLoading(true);
      setPreviewError(null);

      // Validate config columns against current dataset schema
      try {
        const referencedColumns = [
          ...report.config_json.metrics.map((m) => m.column),
          ...report.config_json.dimensions,
          ...report.config_json.filters.map((f) => f.column),
        ].filter(Boolean);
        if (referencedColumns.length > 0) {
          const validation = await validateConfig({
            dataset_name: report.dataset_name,
            referenced_columns: referencedColumns,
          });
          if (!cancelled && validation.warnings.length > 0) {
            setConfigWarnings(validation.warnings.map((w) => w.message));
          }
        }
      } catch {
        // Non-critical: validation failure shouldn't block preview
      }

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

  const menuActivator = (
    <Button
      variant="plain"
      onClick={() => setMenuActive((prev) => !prev)}
      accessibilityLabel="Report actions"
    >
      ...
    </Button>
  );

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Card padding="300">
        <BlockStack gap="200">
          {/* Header */}
          <InlineStack align="space-between" blockAlign="center">
            <InlineStack gap="200" blockAlign="center">
              <div
                className="report-card-drag-handle"
                style={{ cursor: 'grab', padding: '0 4px', color: '#8c9196' }}
              >
                ::
              </div>
              <BlockStack gap="050">
                <Text as="h3" variant="headingSm">
                  {report.name}
                </Text>
                <Text as="span" variant="bodySm" tone="subdued">
                  {getChartTypeLabel(report.chart_type)}
                </Text>
              </BlockStack>
            </InlineStack>

            <Popover
              active={menuActive}
              activator={menuActivator}
              onClose={() => setMenuActive(false)}
              preferredAlignment="right"
            >
              <ActionList
                items={[
                  {
                    content: 'Edit',
                    onAction: () => {
                      setMenuActive(false);
                      openReportConfig(report.id);
                    },
                  },
                  {
                    content: 'Delete',
                    destructive: true,
                    onAction: () => {
                      setMenuActive(false);
                      removeReport(report.id);
                    },
                  },
                ]}
              />
            </Popover>
          </InlineStack>

          {/* Warnings */}
          {(report.warnings.length > 0 || configWarnings.length > 0) && (
            <Banner tone="warning">
              <BlockStack gap="100">
                {[...report.warnings, ...configWarnings].map((warning, idx) => (
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
