/**
 * useVersions Hook
 *
 * Custom hook for fetching dashboard version history and restoring versions.
 * Follows the useShares pattern: useState for state, useCallback for mutations,
 * isApiError() for error extraction.
 *
 * Phase 4A - Version History UI
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import type {
  Dashboard,
  DashboardVersion,
} from '../types/customDashboards';
import {
  listVersions,
  restoreVersion,
} from '../services/customDashboardsApi';
import { getErrorMessage } from '../services/apiUtils';

interface UseVersionsResult {
  versions: DashboardVersion[];
  total: number;
  loading: boolean;
  loadingMore: boolean;
  restoring: boolean;
  error: string | null;
  staleWarning: boolean;
  fetchVersions: () => Promise<void>;
  loadMore: () => Promise<void>;
  restore: (versionNumber: number) => Promise<Dashboard>;
  clearError: () => void;
  dismissStaleWarning: () => void;
}

const PAGE_SIZE = 20;

/**
 * Hook for managing dashboard version history.
 *
 * Usage:
 * ```tsx
 * const { versions, loading, restore } = useVersions(dashboardId);
 * ```
 */
export function useVersions(dashboardId: string | null): UseVersionsResult {
  const [versions, setVersions] = useState<DashboardVersion[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [staleWarning, setStaleWarning] = useState(false);

  // Track the initial total to detect new versions created by other users
  const initialTotalRef = useRef<number | null>(null);

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  const dismissStaleWarning = useCallback(() => {
    setStaleWarning(false);
  }, []);

  const fetchVersions = useCallback(async () => {
    if (!dashboardId) {
      setVersions([]);
      setTotal(0);
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setStaleWarning(false);
      const data = await listVersions(dashboardId, 0, PAGE_SIZE);
      setVersions(data.versions);
      setTotal(data.total);
      initialTotalRef.current = data.total;
    } catch (err) {
      console.error('Failed to fetch versions:', err);
      setError(getErrorMessage(err, 'Failed to load version history'));
    } finally {
      setLoading(false);
    }
  }, [dashboardId]);

  const loadMore = useCallback(async () => {
    if (!dashboardId || versions.length >= total) return;

    try {
      setLoadingMore(true);
      setError(null);
      const data = await listVersions(dashboardId, versions.length, PAGE_SIZE);
      setVersions((prev) => [...prev, ...data.versions]);
      setTotal(data.total);

      // Detect stale data: total increased since initial load
      if (initialTotalRef.current !== null && data.total > initialTotalRef.current) {
        setStaleWarning(true);
      }
    } catch (err) {
      console.error('Failed to load more versions:', err);
      setError(getErrorMessage(err, 'Failed to load more versions'));
    } finally {
      setLoadingMore(false);
    }
  }, [dashboardId, versions.length, total]);

  const restoreFn = useCallback(async (versionNumber: number): Promise<Dashboard> => {
    if (!dashboardId) {
      throw new Error('Dashboard ID is required to restore a version');
    }

    try {
      setRestoring(true);
      setError(null);
      const result = await restoreVersion(dashboardId, versionNumber);
      // Re-fetch versions after restore since a new version is created
      await fetchVersions();
      return result;
    } catch (err) {
      console.error('Failed to restore version:', err);
      setError(getErrorMessage(err, 'Failed to restore version'));
      throw err;
    } finally {
      setRestoring(false);
    }
  }, [dashboardId, fetchVersions]);

  // No auto-fetch on mount — caller opens the panel and triggers fetchVersions

  return {
    versions,
    total,
    loading,
    loadingMore,
    restoring,
    error,
    staleWarning,
    fetchVersions,
    loadMore,
    restore: restoreFn,
    clearError,
    dismissStaleWarning,
  };
}
