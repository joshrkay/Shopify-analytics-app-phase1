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
} from '../types/customDashboards';
import {
  WIDGET_CATEGORY_META,
  mapChartTypeToWidgetCategory,
} from '../types/customDashboards';
import { fetchWidgetCatalog } from '../utils/widgetCatalog';

export interface WidgetPreviewData {
  widgetId: string;
  chartType: ChartType;
  isFallback: boolean;
  value?: number;
  trend?: number;
  series?: Array<{ label: string; value: number }>;
  rows?: Array<Record<string, unknown>>;
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
  datasetId?: string,
): Promise<WidgetPreviewData> {
  const items = await getWidgetCatalog();
  const widget = items.find((item) => item.id === widgetId);
  const chartType = widget?.chart_type ?? 'kpi';

  const base: WidgetPreviewData = {
    widgetId,
    chartType,
    isFallback: !datasetId,
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
      rows: [
        { dimension: 'A', value: 1200 },
        { dimension: 'B', value: 980 },
      ],
    };
  }

  return {
    ...base,
    series: [
      { label: 'Week 1', value: 120 },
      { label: 'Week 2', value: 180 },
      { label: 'Week 3', value: 140 },
    ],
  };
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
