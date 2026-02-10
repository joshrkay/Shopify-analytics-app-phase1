/**
 * useShares Hook
 *
 * Custom hook combining data fetching and mutations for dashboard shares.
 * Fetches shares on mount and auto-refetches after mutations.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect, useCallback } from 'react';
import type {
  DashboardShare,
  CreateShareRequest,
  UpdateShareRequest,
} from '../types/customDashboards';
import {
  listShares,
  createShare,
  updateShare,
  revokeShare,
} from '../services/dashboardSharesApi';
import { isApiError } from '../services/apiUtils';

interface UseSharesResult {
  shares: DashboardShare[];
  total: number;
  loading: boolean;
  saving: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  create: (body: CreateShareRequest) => Promise<DashboardShare>;
  update: (shareId: string, body: UpdateShareRequest) => Promise<DashboardShare>;
  revoke: (shareId: string) => Promise<void>;
  clearError: () => void;
}

/**
 * Hook for managing dashboard shares (fetch + mutations with auto-refetch).
 *
 * Usage:
 * ```tsx
 * const { shares, loading, saving, error, create, update, revoke } = useShares(dashboardId);
 *
 * const handleShare = async () => {
 *   await create({ shared_with_user_id: userId, permission: 'view' });
 *   // shares list is automatically refetched after mutation
 * };
 * ```
 */
export function useShares(dashboardId: string | null): UseSharesResult {
  const [shares, setShares] = useState<DashboardShare[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  const loadShares = useCallback(async () => {
    if (!dashboardId) {
      setShares([]);
      setTotal(0);
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const data = await listShares(dashboardId);
      setShares(data.shares);
      setTotal(data.total);
    } catch (err) {
      console.error('Failed to fetch shares:', err);
      if (isApiError(err)) {
        setError(err.detail || err.message);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load shares');
      }
    } finally {
      setLoading(false);
    }
  }, [dashboardId]);

  useEffect(() => {
    loadShares();
  }, [loadShares]);

  const createFn = useCallback(async (body: CreateShareRequest): Promise<DashboardShare> => {
    if (!dashboardId) {
      throw new Error('Dashboard ID is required to create a share');
    }

    try {
      setSaving(true);
      setError(null);
      const result = await createShare(dashboardId, body);
      // Auto-refetch shares list after successful mutation
      await loadShares();
      return result;
    } catch (err) {
      console.error('Failed to create share:', err);
      const message = isApiError(err)
        ? err.detail || err.message
        : err instanceof Error ? err.message : 'Failed to create share';
      setError(message);
      throw err;
    } finally {
      setSaving(false);
    }
  }, [dashboardId, loadShares]);

  const updateFn = useCallback(async (
    shareId: string,
    body: UpdateShareRequest,
  ): Promise<DashboardShare> => {
    if (!dashboardId) {
      throw new Error('Dashboard ID is required to update a share');
    }

    try {
      setSaving(true);
      setError(null);
      const result = await updateShare(dashboardId, shareId, body);
      // Auto-refetch shares list after successful mutation
      await loadShares();
      return result;
    } catch (err) {
      console.error('Failed to update share:', err);
      const message = isApiError(err)
        ? err.detail || err.message
        : err instanceof Error ? err.message : 'Failed to update share';
      setError(message);
      throw err;
    } finally {
      setSaving(false);
    }
  }, [dashboardId, loadShares]);

  const revokeFn = useCallback(async (shareId: string): Promise<void> => {
    if (!dashboardId) {
      throw new Error('Dashboard ID is required to revoke a share');
    }

    try {
      setSaving(true);
      setError(null);
      await revokeShare(dashboardId, shareId);
      // Auto-refetch shares list after successful mutation
      await loadShares();
    } catch (err) {
      console.error('Failed to revoke share:', err);
      const message = isApiError(err)
        ? err.detail || err.message
        : err instanceof Error ? err.message : 'Failed to revoke share';
      setError(message);
      throw err;
    } finally {
      setSaving(false);
    }
  }, [dashboardId, loadShares]);

  return {
    shares,
    total,
    loading,
    saving,
    error,
    refetch: loadShares,
    create: createFn,
    update: updateFn,
    revoke: revokeFn,
    clearError,
  };
}
