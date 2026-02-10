/**
 * useAuditEntries Hook
 *
 * Custom hook for fetching dashboard audit trail entries.
 * Follows the useShares/useVersions pattern.
 *
 * Phase 4C - Audit Trail UI
 */

import { useState, useCallback } from 'react';
import type { AuditEntry } from '../types/customDashboards';
import { listAuditEntries } from '../services/customDashboardsApi';
import { getErrorMessage } from '../services/apiUtils';

interface UseAuditEntriesResult {
  entries: AuditEntry[];
  total: number;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  fetchEntries: () => Promise<void>;
  loadMore: () => Promise<void>;
  clearError: () => void;
}

const PAGE_SIZE = 50;

/**
 * Hook for managing dashboard audit trail entries.
 *
 * Usage:
 * ```tsx
 * const { entries, loading, fetchEntries, loadMore } = useAuditEntries(dashboardId);
 * ```
 */
export function useAuditEntries(dashboardId: string | null): UseAuditEntriesResult {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  const fetchEntries = useCallback(async () => {
    if (!dashboardId) {
      setEntries([]);
      setTotal(0);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const data = await listAuditEntries(dashboardId, 0, PAGE_SIZE);
      setEntries(data.entries);
      setTotal(data.total);
    } catch (err) {
      console.error('Failed to fetch audit entries:', err);
      setError(getErrorMessage(err, 'Failed to load audit trail'));
    } finally {
      setLoading(false);
    }
  }, [dashboardId]);

  const loadMore = useCallback(async () => {
    if (!dashboardId || entries.length >= total) return;

    try {
      setLoadingMore(true);
      setError(null);
      const data = await listAuditEntries(dashboardId, entries.length, PAGE_SIZE);
      setEntries((prev) => [...prev, ...data.entries]);
      setTotal(data.total);
    } catch (err) {
      console.error('Failed to load more audit entries:', err);
      setError(getErrorMessage(err, 'Failed to load more entries'));
    } finally {
      setLoadingMore(false);
    }
  }, [dashboardId, entries.length, total]);

  return {
    entries,
    total,
    loading,
    loadingMore,
    error,
    fetchEntries,
    loadMore,
    clearError,
  };
}
