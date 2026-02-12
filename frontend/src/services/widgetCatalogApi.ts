/**
 * Widget Catalog API Service
 *
 * Provides an API-like service surface for builder widget catalog data.
 * v1 uses frontend-derived data from templates with lightweight caching,
 * while preserving a stable interface for future backend endpoints.
 */

import type {
  WidgetCatalogItem,
  WidgetCategory,
  WidgetCategoryMeta,
  ChartType,
  ChartConfig,
  ChartPreviewRequest,
} from '../types/customDashboards';
import {
  WIDGET_CATEGORY_META,
  mapChartTypeToWidgetCategory,
} from '../types/customDashboards';
import { fetchWidgetCatalog } from '../utils/widgetCatalog';
import { chartPreview } from './datasetsApi';
import { isApiError } from './apiUtils';

export interface WidgetPreviewData {
  widgetId: string;
  chartType: ChartType;
  isFallback: boolean;
  fallbackReason?: 'missing_widget' | 'missing_dataset' | 'missing_metrics' | 'api_error';
  value?: number;
  trend?: number;
  series?: Array<{ label: string; value: number }>;
  rows?: Array<Record<string, unknown>>;
}

function toPreviewRequest(widget: WidgetCatalogItem, datasetName: string): ChartPreviewRequest {
  const config = widget.default_config as ChartConfig;

  const metrics = (config.metrics ?? [])
    .map((metric) => {
      if (typeof metric === 'string') {
        return {
          label: metric,
          column: metric,
          aggregate: 'SUM',
        };
      }

      const column = metric.column || metric.label;
      if (!column) return null;

      return {
        label: metric.label || column,
        column,
        aggregate: metric.aggregation,
      };
    })
    .filter((metric): metric is NonNullable<typeof metric> => Boolean(metric));

  return {
    dataset_name: datasetName,
    metrics,
    dimensions: config.dimensions ?? [],
    filters: config.filters ?? [],
    time_range: config.time_range ?? '30',
    time_grain: config.time_grain,
    viz_type: widget.chart_type,
  };
}

function toFallbackPreviewData(
  widgetId: string,
  chartType: ChartType,
  hasDataset: boolean,
  fallbackReason: WidgetPreviewData['fallbackReason'],
): WidgetPreviewData {
  const base: WidgetPreviewData = {
    widgetId,
    chartType,
    isFallback: true,
    fallbackReason,
  };

  if (chartType === 'kpi') {
    return {
      ...base,
      value: 12458,
      trend: 12.5,
    };
  }

  if (chartType === 'table') {
    return {
      ...base,
      rows: hasDataset
        ? [{ message: 'No preview rows returned by API' }]
        : [
            { dimension: 'A', value: 1200 },
            { dimension: 'B', value: 980 },
          ],
    };
  }

  return {
    ...base,
    series: hasDataset
      ? []
      : [
          { label: 'Week 1', value: 120 },
          { label: 'Week 2', value: 180 },
          { label: 'Week 3', value: 140 },
        ],
  };
}

const CATALOG_STALE_MS = 30 * 60 * 1000;

let catalogCache: WidgetCatalogItem[] | null = null;
let catalogCacheAt = 0;

function normalizeCategory(item: WidgetCatalogItem): WidgetCatalogItem {
  return {
    ...item,
    businessCategory:
      item.businessCategory ?? mapChartTypeToWidgetCategory(item.chart_type),
  };
}

export async function getWidgetCatalog(): Promise<WidgetCatalogItem[]> {
  const now = Date.now();
  if (catalogCache && now - catalogCacheAt < CATALOG_STALE_MS) {
    return catalogCache;
  }

  const items = await fetchWidgetCatalog();
  catalogCache = items.map(normalizeCategory);
  catalogCacheAt = now;
  return catalogCache;
}

export async function getWidgetCategories(): Promise<WidgetCategoryMeta[]> {
  return WIDGET_CATEGORY_META.filter((category) => category.id !== 'uncategorized');
}

export async function getWidgetPreview(
  widgetId: string,
  datasetName?: string,
): Promise<WidgetPreviewData> {
  const items = await getWidgetCatalog();
  const widget = items.find((item) => item.id === widgetId);
  const chartType = widget?.chart_type ?? 'kpi';
  const resolvedDatasetName = datasetName ?? widget?.required_dataset;

  if (!widget) {
    return toFallbackPreviewData(widgetId, chartType, false, 'missing_widget');
  }

  if (!resolvedDatasetName) {
    return toFallbackPreviewData(widgetId, chartType, false, 'missing_dataset');
  }

  try {
    const request = toPreviewRequest(widget, resolvedDatasetName);
    if (request.metrics.length === 0) {
      return toFallbackPreviewData(widgetId, chartType, true, 'missing_metrics');
    }

    const response = await chartPreview(request);

    if (chartType === 'kpi') {
      const firstRow = response.data[0] ?? {};
      const firstNumeric = Object.values(firstRow).find(
        (value) => typeof value === 'number',
      );

      return {
        widgetId,
        chartType,
        isFallback: false,
        value: typeof firstNumeric === 'number' ? firstNumeric : 0,
        trend: 0,
      };
    }

    if (chartType === 'table') {
      return {
        widgetId,
        chartType,
        isFallback: false,
        rows: response.data,
      };
    }

    const rows = response.data ?? [];
    const dimensionKey = response.columns[0] ?? 'label';
    const valueKey = response.columns.find((column) => column !== dimensionKey) ?? response.columns[0];

    return {
      widgetId,
      chartType,
      isFallback: false,
      series: rows.map((row, index) => ({
        label: String((row[dimensionKey] ?? `Row ${index + 1}`)),
        value: Number(row[valueKey] ?? 0),
      })),
    };
  } catch (err) {
    if (isApiError(err) && (err.status === 401 || err.status === 403)) {
      throw err;
    }
    console.error('Failed to fetch widget preview from backend API', {
      widgetId,
      datasetName: resolvedDatasetName,
      chartType,
      error: err,
    });
    return toFallbackPreviewData(widgetId, chartType, true, 'api_error');
  }
}

export function filterWidgetsByCategory(
  widgets: WidgetCatalogItem[],
  category: WidgetCategory,
): WidgetCatalogItem[] {
  if (category === 'all') return widgets;
  return widgets.filter((item) => (item.businessCategory ?? 'uncategorized') === category);
}

/** Test-only cache reset helper */
export function __resetWidgetCatalogCacheForTests(): void {
  catalogCache = null;
  catalogCacheAt = 0;
}
