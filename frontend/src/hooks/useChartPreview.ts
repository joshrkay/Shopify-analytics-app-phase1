/**
 * useChartPreview Hook
 *
 * Custom hook for on-demand chart preview queries.
 * Does NOT auto-fetch on mount -- the consumer calls fetchPreview explicitly
 * when the user clicks "Preview" or changes chart configuration.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useCallback } from 'react';
import type {
  ChartPreviewRequest,
  ChartPreviewResponse,
} from '../types/customDashboards';
import { chartPreview } from '../services/datasetsApi';
import { isApiError } from '../services/apiUtils';

interface UseChartPreviewResult {
  previewData: ChartPreviewResponse | null;
  loading: boolean;
  error: string | null;
  fetchPreview: (request: ChartPreviewRequest) => Promise<ChartPreviewResponse | null>;
  clearPreview: () => void;
}

/**
 * Hook for on-demand chart preview queries.
 *
 * Usage:
 * ```tsx
 * const { previewData, loading, error, fetchPreview, clearPreview } = useChartPreview();
 *
 * const handlePreview = async () => {
 *   await fetchPreview({
 *     dataset_name: 'orders',
 *     metrics: [{ label: 'Revenue', column: 'total', aggregate: 'SUM' }],
 *     dimensions: ['order_date'],
 *     time_range: 'last_30_days',
 *     viz_type: 'line',
 *   });
 * };
 *
 * return (
 *   <>
 *     <button onClick={handlePreview} disabled={loading}>Preview</button>
 *     {previewData && <ChartRenderer data={previewData} />}
 *   </>
 * );
 * ```
 */
export function useChartPreview(): UseChartPreviewResult {
  const [previewData, setPreviewData] = useState<ChartPreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPreview = useCallback(async (
    request: ChartPreviewRequest,
  ): Promise<ChartPreviewResponse | null> => {
    try {
      setLoading(true);
      setError(null);
      const data = await chartPreview(request);
      setPreviewData(data);
      return data;
    } catch (err) {
      console.error('Failed to fetch chart preview:', err);
      const message = isApiError(err)
        ? err.detail || err.message
        : err instanceof Error ? err.message : 'Failed to load chart preview';
      setError(message);
      setPreviewData(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const clearPreview = useCallback(() => {
    setPreviewData(null);
    setError(null);
  }, []);

  return {
    previewData,
    loading,
    error,
    fetchPreview,
    clearPreview,
  };
}
