/**
 * useWidgetCatalog Hook
 *
 * Query hook for widget catalog and category metadata.
 * Maintains backward-compatible aliases used by current wizard components.
 */

import { useCallback, useMemo } from 'react';
import { useQueryLite } from './queryClientLite';
import type { WidgetCatalogItem, WidgetCategory, WidgetCategoryMeta } from '../types/customDashboards';
import {
  filterWidgetsByCategory,
  getWidgetCatalog,
  getWidgetCategories,
  getWidgetPreview,
  type WidgetPreviewData,
} from '../services/widgetCatalogApi';
import { getErrorMessage } from '../services/apiUtils';

interface UseWidgetCatalogResult {
  widgets: WidgetCatalogItem[];
  categories: WidgetCategoryMeta[];
  isLoading: boolean;
  error: Error | null;
  getFilteredWidgets: (category: WidgetCategory) => WidgetCatalogItem[];
  refresh: () => Promise<void>;

  // Backward compatibility aliases
  items: WidgetCatalogItem[];
  loading: boolean;
}

export function useWidgetCatalog(category: WidgetCategory = 'all'): UseWidgetCatalogResult {
  const widgetsQuery = useQueryLite({
    queryKey: ['widget-catalog'],
    queryFn: getWidgetCatalog,
  });

  const categoriesQuery = useQueryLite({
    queryKey: ['widget-categories'],
    queryFn: getWidgetCategories,
  });

  const widgets = widgetsQuery.data ?? [];
  const categories = categoriesQuery.data ?? [];

  const isLoading = widgetsQuery.isLoading || categoriesQuery.isLoading;

  const error = useMemo(() => {
    const err = widgetsQuery.error ?? categoriesQuery.error;
    if (!err) return null;
    if (err instanceof Error) return err;
    return new Error(getErrorMessage(err, 'Failed to load widget catalog'));
  }, [widgetsQuery.error, categoriesQuery.error]);

  const filteredWidgets = useMemo(
    () => filterWidgetsByCategory(widgets, category),
    [widgets, category],
  );

  return {
    widgets: filteredWidgets,
    categories,
    isLoading,
    error,
    getFilteredWidgets: (targetCategory: WidgetCategory) =>
      filterWidgetsByCategory(widgets, targetCategory),
    refresh: async () => {
      await Promise.all([widgetsQuery.refetch(), categoriesQuery.refetch()]);
    },

    // aliases
    items: filteredWidgets,
    loading: isLoading,
  };
}

interface UseWidgetPreviewResult {
  previewData: WidgetPreviewData | null;
  isLoading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
}

export function useWidgetPreview(
  widgetId: string,
  datasetName?: string,
): UseWidgetPreviewResult {
  const queryFn = useCallback(
    () => getWidgetPreview(widgetId, datasetName),
    [widgetId, datasetName],
  );

  const query = useQueryLite({
    queryKey: ['widget-preview', widgetId, datasetName],
    queryFn,
  });

  const error = useMemo(() => {
    if (!query.error) return null;
    if (query.error instanceof Error) return query.error;
    return new Error(getErrorMessage(query.error, 'Failed to load widget preview'));
  }, [query.error]);

  return {
    previewData: query.data ?? null,
    isLoading: query.isLoading,
    error,
    refresh: async () => {
      await query.refetch();
    },
  };
}
