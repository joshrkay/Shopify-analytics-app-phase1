/**
 * useDashboards Hook
 *
 * Custom hook to fetch and manage the list of dashboards.
 * Fetches dashboards on mount with optional filters, supports refetch.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect, useCallback } from 'react';
import type {
  Dashboard,
  DashboardFilters,
  DashboardListResponse,
} from '../types/customDashboards';
import { listDashboards } from '../services/customDashboardsApi';
import { getErrorMessage } from '../services/apiUtils';

interface UseDashboardsResult {
  dashboards: Dashboard[];
  total: number;
  hasMore: boolean;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

/**
 * Hook to fetch a list of dashboards with optional filters.
 *
 * Usage:
 * ```tsx
 * const { dashboards, loading, error, refetch } = useDashboards({ status: 'published' });
 *
 * if (loading) return <Spinner />;
 * if (error) return <ErrorBanner message={error} />;
 *
 * return <DashboardList dashboards={dashboards} />;
 * ```
 */
export function useDashboards(filters: DashboardFilters = {}): UseDashboardsResult {
  const [dashboards, setDashboards] = useState<Dashboard[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDashboards = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data: DashboardListResponse = await listDashboards(filters);
      setDashboards(data.dashboards);
      setTotal(data.total);
      setHasMore(data.has_more);
    } catch (err) {
      console.error('Failed to fetch dashboards:', err);
      setError(getErrorMessage(err, 'Failed to load dashboards'));
    } finally {
      setLoading(false);
    }
  }, [filters.status, filters.limit, filters.offset]);

  useEffect(() => {
    loadDashboards();
  }, [loadDashboards]);

  return {
    dashboards,
    total,
    hasMore,
    loading,
    error,
    refetch: loadDashboards,
  };
}
