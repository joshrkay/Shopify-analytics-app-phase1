/**
 * useDashboardMutations Hook
 *
 * Custom hook providing mutation operations for dashboards:
 * create, update, delete, publish, and duplicate.
 *
 * Each mutation wraps its API call with saving state and error handling.
 * Returns the mutated dashboard (or void for delete) on success.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useCallback } from 'react';
import type {
  Dashboard,
  CreateDashboardRequest,
  UpdateDashboardRequest,
} from '../types/customDashboards';
import {
  createDashboard,
  updateDashboard,
  deleteDashboard,
  publishDashboard,
  duplicateDashboard,
} from '../services/customDashboardsApi';
import { getErrorMessage } from '../services/apiUtils';

interface UseDashboardMutationsResult {
  saving: boolean;
  error: string | null;
  create: (body: CreateDashboardRequest) => Promise<Dashboard>;
  update: (dashboardId: string, body: UpdateDashboardRequest) => Promise<Dashboard>;
  remove: (dashboardId: string) => Promise<void>;
  publish: (dashboardId: string) => Promise<Dashboard>;
  duplicate: (dashboardId: string, newName: string) => Promise<Dashboard>;
  clearError: () => void;
}

/**
 * Hook for dashboard mutation operations (create, update, delete, publish, duplicate).
 *
 * Usage:
 * ```tsx
 * const { saving, error, create, update, remove, publish, duplicate } = useDashboardMutations();
 *
 * const handleCreate = async () => {
 *   const dashboard = await create({ name: 'My Dashboard' });
 *   navigate(`/dashboards/${dashboard.id}`);
 * };
 * ```
 */
export function useDashboardMutations(): UseDashboardMutationsResult {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  const create = useCallback(async (body: CreateDashboardRequest): Promise<Dashboard> => {
    try {
      setSaving(true);
      setError(null);
      const result = await createDashboard(body);
      return result;
    } catch (err) {
      console.error('Failed to create dashboard:', err);
      setError(getErrorMessage(err, 'Failed to create dashboard'));
      throw err;
    } finally {
      setSaving(false);
    }
  }, []);

  const update = useCallback(async (
    dashboardId: string,
    body: UpdateDashboardRequest,
  ): Promise<Dashboard> => {
    try {
      setSaving(true);
      setError(null);
      const result = await updateDashboard(dashboardId, body);
      return result;
    } catch (err) {
      console.error('Failed to update dashboard:', err);
      setError(getErrorMessage(err, 'Failed to update dashboard'));
      throw err;
    } finally {
      setSaving(false);
    }
  }, []);

  const remove = useCallback(async (dashboardId: string): Promise<void> => {
    try {
      setSaving(true);
      setError(null);
      await deleteDashboard(dashboardId);
    } catch (err) {
      console.error('Failed to delete dashboard:', err);
      setError(getErrorMessage(err, 'Failed to delete dashboard'));
      throw err;
    } finally {
      setSaving(false);
    }
  }, []);

  const publish = useCallback(async (dashboardId: string): Promise<Dashboard> => {
    try {
      setSaving(true);
      setError(null);
      const result = await publishDashboard(dashboardId);
      return result;
    } catch (err) {
      console.error('Failed to publish dashboard:', err);
      setError(getErrorMessage(err, 'Failed to publish dashboard'));
      throw err;
    } finally {
      setSaving(false);
    }
  }, []);

  const duplicateFn = useCallback(async (
    dashboardId: string,
    newName: string,
  ): Promise<Dashboard> => {
    try {
      setSaving(true);
      setError(null);
      const result = await duplicateDashboard(dashboardId, newName);
      return result;
    } catch (err) {
      console.error('Failed to duplicate dashboard:', err);
      setError(getErrorMessage(err, 'Failed to duplicate dashboard'));
      throw err;
    } finally {
      setSaving(false);
    }
  }, []);

  return {
    saving,
    error,
    create,
    update,
    remove,
    publish,
    duplicate: duplicateFn,
    clearError,
  };
}
