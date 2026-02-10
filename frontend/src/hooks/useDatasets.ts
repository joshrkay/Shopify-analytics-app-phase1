/**
 * useDatasets Hook
 *
 * Custom hook to fetch and manage the list of available datasets.
 * Fetches datasets on mount with column metadata for the report builder.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect, useCallback } from 'react';
import type { Dataset } from '../types/customDashboards';
import { listDatasets } from '../services/datasetsApi';
import { getErrorMessage } from '../services/apiUtils';

interface UseDatasetsResult {
  datasets: Dataset[];
  total: number;
  stale: boolean;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

/**
 * Hook to fetch the list of available datasets with column metadata.
 *
 * Usage:
 * ```tsx
 * const { datasets, stale, loading, error } = useDatasets();
 *
 * if (loading) return <Spinner />;
 * if (error) return <ErrorBanner message={error} />;
 * if (stale) return <StaleBanner />;
 *
 * return <DatasetPicker datasets={datasets} />;
 * ```
 */
export function useDatasets(): UseDatasetsResult {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [total, setTotal] = useState(0);
  const [stale, setStale] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDatasets = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listDatasets();
      setDatasets(data.datasets);
      setTotal(data.total);
      setStale(data.stale);
    } catch (err) {
      console.error('Failed to fetch datasets:', err);
      setError(getErrorMessage(err, 'Failed to load datasets'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDatasets();
  }, [loadDatasets]);

  return {
    datasets,
    total,
    stale,
    loading,
    error,
    refetch: loadDatasets,
  };
}
