/**
 * useDashboard Hook
 *
 * Custom hook to fetch and manage a single dashboard by ID.
 * Fetches dashboard details on mount and when the ID changes.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect, useCallback } from 'react';
import type { Dashboard } from '../types/customDashboards';
import { getDashboard } from '../services/customDashboardsApi';
import { isApiError } from '../services/apiUtils';

interface UseDashboardResult {
  dashboard: Dashboard | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

/**
 * Hook to fetch a single dashboard by its ID.
 *
 * Usage:
 * ```tsx
 * const { dashboard, loading, error, refetch } = useDashboard(dashboardId);
 *
 * if (loading) return <Spinner />;
 * if (error) return <ErrorBanner message={error} />;
 * if (!dashboard) return <NotFound />;
 *
 * return <DashboardEditor dashboard={dashboard} />;
 * ```
 */
export function useDashboard(dashboardId: string | null): UseDashboardResult {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    if (!dashboardId) {
      setDashboard(null);
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const data = await getDashboard(dashboardId);
      setDashboard(data);
    } catch (err) {
      console.error('Failed to fetch dashboard:', err);
      if (isApiError(err)) {
        setError(err.detail || err.message);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load dashboard');
      }
    } finally {
      setLoading(false);
    }
  }, [dashboardId]);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  return {
    dashboard,
    loading,
    error,
    refetch: loadDashboard,
  };
}
