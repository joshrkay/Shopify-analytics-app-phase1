/**
 * ReportConfiguratorModal Component
 *
 * Large modal for adding or editing reports within a dashboard.
 * Provides a full-featured form including:
 * - Report name and description
 * - Dataset selection
 * - Chart type selection
 * - Metric configuration (column + aggregation)
 * - Dimension selection
 * - Time range and grain controls
 * - Chart-level filter builder
 * - Display settings (legend, axes, colors)
 * - Live chart preview
 *
 * Uses the DashboardBuilderContext for state management and
 * report CRUD operations.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Modal,
  FormLayout,
  TextField,
  BlockStack,
  InlineStack,
  Button,
  Banner,
  Select,
  Text,
  Divider,
  Spinner,
} from '@shopify/polaris';
import { useDashboardBuilder } from '../../contexts/DashboardBuilderContext';
import type {
  ChartType,
  ChartConfig,
  MetricConfig,
  ChartFilter,
  DisplayConfig,
  GridPosition,
  CreateReportRequest,
  UpdateReportRequest,
  Dataset,
  ColumnMetadata,
  ChartPreviewRequest,
  MetricDefinition,
  FilterDefinition,
  TimeGrain,
} from '../../types/customDashboards';
import { MIN_GRID_DIMENSIONS } from '../../types/customDashboards';
import { DatasetPicker } from './configurator/DatasetPicker';
import { ChartTypePicker } from './configurator/ChartTypePicker';
import { MetricBuilder } from './configurator/MetricBuilder';
import { DimensionPicker } from './configurator/DimensionPicker';
import { ChartFilterBuilder } from './configurator/ChartFilterBuilder';
import { DisplaySettingsForm } from './configurator/DisplaySettingsForm';
import { ChartRenderer } from '../charts/ChartRenderer';
import { chartPreview, listDatasets } from '../../services/datasetsApi';

// =============================================================================
// Constants
// =============================================================================

const TIME_RANGE_OPTIONS = [
  { label: 'Last 7 days', value: 'Last 7 days' },
  { label: 'Last 30 days', value: 'Last 30 days' },
  { label: 'Last 90 days', value: 'Last 90 days' },
  { label: 'Last 12 months', value: 'Last 12 months' },
];

const TIME_GRAIN_OPTIONS: { label: string; value: TimeGrain }[] = [
  { label: 'Daily', value: 'P1D' },
  { label: 'Weekly', value: 'P1W' },
  { label: 'Monthly', value: 'P1M' },
  { label: 'Quarterly', value: 'P3M' },
  { label: 'Yearly', value: 'P1Y' },
];

const DEFAULT_DISPLAY: DisplayConfig = {
  show_legend: true,
  legend_position: 'top',
  color_scheme: 'default',
};

// =============================================================================
// Validation
// =============================================================================

interface ValidationResult {
  valid: boolean;
  errors: string[];
}

function validateForm(
  name: string,
  chartType: ChartType,
  metrics: MetricConfig[],
  dimensions: string[],
): ValidationResult {
  const errors: string[] = [];

  if (!name.trim()) {
    errors.push('Report name is required.');
  }

  const validMetrics = metrics.filter((m) => m.column !== '');
  if (validMetrics.length === 0) {
    errors.push('At least one metric is required.');
  }

  if (chartType === 'kpi' && validMetrics.length !== 1) {
    errors.push('KPI charts require exactly one metric.');
  }

  if (chartType === 'pie') {
    if (validMetrics.length !== 1) {
      errors.push('Pie charts require exactly one metric.');
    }
    if (dimensions.length !== 1) {
      errors.push('Pie charts require exactly one dimension.');
    }
  }

  return {
    valid: errors.length === 0,
    errors,
  };
}

// =============================================================================
// Component
// =============================================================================

export function ReportConfiguratorModal() {
  const {
    isReportConfigOpen,
    selectedReportId,
    dashboard,
    closeReportConfig,
    addReport,
    updateReport,
  } = useDashboardBuilder();

  // ---------------------------------------------------------------------------
  // Datasets state (fetched on mount)
  // ---------------------------------------------------------------------------
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState(false);

  // ---------------------------------------------------------------------------
  // Form state
  // ---------------------------------------------------------------------------
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [datasetName, setDatasetName] = useState('');
  const [chartType, setChartType] = useState<ChartType>('bar');
  const [metrics, setMetrics] = useState<MetricConfig[]>([
    { column: '', aggregation: 'SUM' },
  ]);
  const [dimensions, setDimensions] = useState<string[]>([]);
  const [timeRange, setTimeRange] = useState('Last 30 days');
  const [timeGrain, setTimeGrain] = useState<TimeGrain>('P1D');
  const [filters, setFilters] = useState<ChartFilter[]>([]);
  const [display, setDisplay] = useState<DisplayConfig>(DEFAULT_DISPLAY);

  // ---------------------------------------------------------------------------
  // Preview state
  // ---------------------------------------------------------------------------
  const [previewData, setPreviewData] = useState<Record<string, unknown>[] | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Validation and save state
  // ---------------------------------------------------------------------------
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // ---------------------------------------------------------------------------
  // Determine if editing an existing report
  // ---------------------------------------------------------------------------
  const isEditing = selectedReportId !== null;
  const existingReport = useMemo(() => {
    if (!isEditing || !dashboard) return null;
    return dashboard.reports.find((r) => r.id === selectedReportId) ?? null;
  }, [isEditing, selectedReportId, dashboard]);

  // ---------------------------------------------------------------------------
  // Fetch datasets on modal open
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (!isReportConfigOpen) return;

    let cancelled = false;

    async function fetchDatasets() {
      setDatasetsLoading(true);
      try {
        const response = await listDatasets();
        if (!cancelled) {
          setDatasets(response.datasets);
        }
      } catch (err) {
        console.error('Failed to fetch datasets:', err);
      } finally {
        if (!cancelled) {
          setDatasetsLoading(false);
        }
      }
    }

    fetchDatasets();

    return () => {
      cancelled = true;
    };
  }, [isReportConfigOpen]);

  // ---------------------------------------------------------------------------
  // Pre-populate form when editing
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (!isReportConfigOpen) return;

    if (existingReport) {
      setName(existingReport.name);
      setDescription(existingReport.description ?? '');
      setDatasetName(existingReport.dataset_name);
      setChartType(existingReport.chart_type);
      setMetrics(
        existingReport.config_json.metrics.length > 0
          ? existingReport.config_json.metrics
          : [{ column: '', aggregation: 'SUM' }],
      );
      setDimensions(existingReport.config_json.dimensions);
      setTimeRange(existingReport.config_json.time_range || 'Last 30 days');
      setTimeGrain(existingReport.config_json.time_grain || 'P1D');
      setFilters(existingReport.config_json.filters);
      setDisplay(existingReport.config_json.display || DEFAULT_DISPLAY);
    } else {
      // Reset to defaults for new report
      setName('');
      setDescription('');
      setDatasetName('');
      setChartType('bar');
      setMetrics([{ column: '', aggregation: 'SUM' }]);
      setDimensions([]);
      setTimeRange('Last 30 days');
      setTimeGrain('P1D');
      setFilters([]);
      setDisplay(DEFAULT_DISPLAY);
    }

    // Clear transient state
    setPreviewData(null);
    setPreviewError(null);
    setValidationErrors([]);
    setSaveError(null);
  }, [isReportConfigOpen, existingReport]);

  // ---------------------------------------------------------------------------
  // Derived: columns for the selected dataset
  // ---------------------------------------------------------------------------
  const selectedDataset = useMemo(
    () => datasets.find((ds) => ds.dataset_name === datasetName) ?? null,
    [datasets, datasetName],
  );

  const metricColumns = useMemo(
    () => (selectedDataset?.columns ?? []).filter((col) => col.is_metric),
    [selectedDataset],
  );

  const dimensionColumns = useMemo(
    () => (selectedDataset?.columns ?? []).filter((col) => col.is_dimension),
    [selectedDataset],
  );

  const allColumns = useMemo(
    () => selectedDataset?.columns ?? [],
    [selectedDataset],
  );

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleDatasetChange = useCallback((newDatasetName: string) => {
    setDatasetName(newDatasetName);
    // Reset metric/dimension selections when dataset changes
    setMetrics([{ column: '', aggregation: 'SUM' }]);
    setDimensions([]);
    setFilters([]);
    setPreviewData(null);
    setPreviewError(null);
  }, []);

  const handlePreview = useCallback(async () => {
    if (!datasetName) {
      setPreviewError('Please select a dataset first.');
      return;
    }

    const validMetrics = metrics.filter((m) => m.column !== '');
    if (validMetrics.length === 0) {
      setPreviewError('Please add at least one metric.');
      return;
    }

    setPreviewLoading(true);
    setPreviewError(null);
    setPreviewData(null);

    try {
      const metricDefinitions: MetricDefinition[] = validMetrics.map((m) => ({
        label: m.label ?? `${m.aggregation}(${m.column})`,
        column: m.column,
        aggregate: m.aggregation,
        expressionType: 'SIMPLE' as const,
      }));

      const filterDefinitions: FilterDefinition[] = filters
        .filter((f) => f.column !== '')
        .map((f) => ({
          column: f.column,
          operator: f.operator,
          value: f.value as string | number | boolean | null,
        }));

      const request: ChartPreviewRequest = {
        dataset_name: datasetName,
        metrics: metricDefinitions,
        dimensions: dimensions.length > 0 ? dimensions : undefined,
        filters: filterDefinitions.length > 0 ? filterDefinitions : undefined,
        time_range: timeRange,
        time_grain: timeGrain,
        viz_type: chartType,
      };

      const response = await chartPreview(request);
      setPreviewData(response.data);
    } catch (err) {
      console.error('Chart preview failed:', err);
      setPreviewError(
        err instanceof Error ? err.message : 'Failed to load chart preview.',
      );
    } finally {
      setPreviewLoading(false);
    }
  }, [datasetName, metrics, dimensions, filters, timeRange, timeGrain, chartType]);

  const handleSave = useCallback(async () => {
    // Validate
    const validation = validateForm(name, chartType, metrics, dimensions);
    if (!validation.valid) {
      setValidationErrors(validation.errors);
      return;
    }
    setValidationErrors([]);

    // Build config
    const validMetrics = metrics.filter((m) => m.column !== '');
    const validFilters = filters.filter((f) => f.column !== '');

    const configJson: ChartConfig = {
      metrics: validMetrics,
      dimensions,
      time_range: timeRange,
      time_grain: timeGrain,
      filters: validFilters,
      display,
    };

    setIsSaving(true);
    setSaveError(null);

    try {
      if (isEditing && selectedReportId) {
        const updateBody: UpdateReportRequest = {
          name: name.trim(),
          description: description.trim() || undefined,
          chart_type: chartType,
          config_json: configJson,
        };
        await updateReport(selectedReportId, updateBody);
      } else {
        const position: GridPosition = {
          x: 0,
          y: Infinity,
          w: MIN_GRID_DIMENSIONS[chartType].w * 2,
          h: MIN_GRID_DIMENSIONS[chartType].h * 2,
        };

        const createBody: CreateReportRequest = {
          name: name.trim(),
          description: description.trim() || undefined,
          chart_type: chartType,
          dataset_name: datasetName,
          config_json: configJson,
          position_json: position,
        };
        await addReport(createBody);
      }

      closeReportConfig();
    } catch (err) {
      console.error('Failed to save report:', err);
      setSaveError(
        err instanceof Error ? err.message : 'Failed to save report.',
      );
    } finally {
      setIsSaving(false);
    }
  }, [
    name,
    description,
    chartType,
    datasetName,
    metrics,
    dimensions,
    timeRange,
    timeGrain,
    filters,
    display,
    isEditing,
    selectedReportId,
    addReport,
    updateReport,
    closeReportConfig,
  ]);

  const handleClose = useCallback(() => {
    closeReportConfig();
  }, [closeReportConfig]);

  // ---------------------------------------------------------------------------
  // Build the preview ChartConfig for ChartRenderer
  // ---------------------------------------------------------------------------
  const previewConfig: ChartConfig = useMemo(
    () => ({
      metrics: metrics.filter((m) => m.column !== ''),
      dimensions,
      time_range: timeRange,
      time_grain: timeGrain,
      filters: filters.filter((f) => f.column !== ''),
      display,
    }),
    [metrics, dimensions, timeRange, timeGrain, filters, display],
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const modalTitle = isEditing ? 'Edit report' : 'Add report';

  return (
    <Modal
      open={isReportConfigOpen}
      onClose={handleClose}
      title={modalTitle}
      size="large"
    >
      <Modal.Section>
        <BlockStack gap="400">
          {/* Validation errors */}
          {validationErrors.length > 0 && (
            <Banner
              tone="critical"
              onDismiss={() => setValidationErrors([])}
            >
              <BlockStack gap="100">
                {validationErrors.map((error, idx) => (
                  <Text key={idx} as="p" variant="bodySm">
                    {error}
                  </Text>
                ))}
              </BlockStack>
            </Banner>
          )}

          {/* Save error */}
          {saveError && (
            <Banner tone="critical" onDismiss={() => setSaveError(null)}>
              {saveError}
            </Banner>
          )}

          {/* 1. Report name */}
          <FormLayout>
            <TextField
              label="Report name"
              value={name}
              onChange={setName}
              placeholder="e.g., Monthly Revenue Trend"
              autoComplete="off"
              requiredIndicator
            />
          </FormLayout>

          <Divider />

          {/* 2. Dataset picker */}
          {datasetsLoading ? (
            <InlineStack gap="200" blockAlign="center">
              <Spinner size="small" />
              <Text as="p" variant="bodySm" tone="subdued">
                Loading datasets...
              </Text>
            </InlineStack>
          ) : (
            <DatasetPicker
              datasets={datasets}
              value={datasetName}
              onChange={handleDatasetChange}
            />
          )}

          <Divider />

          {/* 3. Chart type picker */}
          <ChartTypePicker value={chartType} onChange={setChartType} />

          <Divider />

          {/* 4. Metric builder */}
          <MetricBuilder
            metrics={metrics}
            columns={metricColumns}
            onChange={setMetrics}
          />

          <Divider />

          {/* 5. Dimension picker */}
          {dimensionColumns.length > 0 && (
            <>
              <DimensionPicker
                dimensions={dimensions}
                columns={dimensionColumns}
                onChange={setDimensions}
              />
              <Divider />
            </>
          )}

          {/* 6. Time range and grain */}
          <FormLayout>
            <FormLayout.Group>
              <Select
                label="Time range"
                options={TIME_RANGE_OPTIONS}
                value={timeRange}
                onChange={setTimeRange}
              />
              <Select
                label="Time grain"
                options={TIME_GRAIN_OPTIONS}
                value={timeGrain}
                onChange={(val) => setTimeGrain(val as TimeGrain)}
              />
            </FormLayout.Group>
          </FormLayout>

          <Divider />

          {/* 7. Chart filter builder */}
          <ChartFilterBuilder
            filters={filters}
            columns={allColumns}
            onChange={setFilters}
          />

          <Divider />

          {/* 8. Display settings */}
          <DisplaySettingsForm display={display} onChange={setDisplay} />

          <Divider />

          {/* 9. Preview section */}
          <BlockStack gap="300">
            <InlineStack align="space-between" blockAlign="center">
              <Text as="p" variant="bodyMd" fontWeight="semibold">
                Preview
              </Text>
              <Button onClick={handlePreview} loading={previewLoading}>
                Preview
              </Button>
            </InlineStack>

            {previewError && (
              <Banner tone="warning" onDismiss={() => setPreviewError(null)}>
                {previewError}
              </Banner>
            )}

            {previewData && (
              <div
                style={{
                  border: '1px solid var(--p-color-border-subdued, #E1E3E5)',
                  borderRadius: '8px',
                  padding: '16px',
                  minHeight: '300px',
                }}
              >
                <ChartRenderer
                  data={previewData}
                  config={previewConfig}
                  chartType={chartType}
                  height={300}
                />
              </div>
            )}

            {!previewData && !previewLoading && !previewError && (
              <div
                style={{
                  border: '1px dashed var(--p-color-border-subdued, #E1E3E5)',
                  borderRadius: '8px',
                  padding: '32px',
                  textAlign: 'center',
                  color: '#6d7175',
                }}
              >
                <Text as="p" variant="bodySm" tone="subdued">
                  Click "Preview" to see a sample visualization
                </Text>
              </div>
            )}
          </BlockStack>
        </BlockStack>
      </Modal.Section>

      {/* Modal footer */}
      <Modal.Section>
        <InlineStack align="end" gap="200">
          <Button onClick={handleClose} disabled={isSaving}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleSave}
            loading={isSaving}
            disabled={isSaving}
          >
            {isEditing ? 'Save changes' : 'Add report'}
          </Button>
        </InlineStack>
      </Modal.Section>
    </Modal>
  );
}
