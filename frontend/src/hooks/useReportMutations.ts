/**
 * useReportMutations Hook
 *
 * Custom hook providing mutation operations for reports within a dashboard:
 * create, update, delete, and reorder.
 *
 * Each mutation wraps its API call with saving state and error handling.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useCallback } from 'react';
import type {
  Report,
  CreateReportRequest,
  UpdateReportRequest,
  ReorderReportsRequest,
} from '../types/customDashboards';
import {
  createReport,
  updateReport,
  deleteReport,
  reorderReports,
} from '../services/customReportsApi';
import { isApiError } from '../services/apiUtils';

interface UseReportMutationsResult {
  saving: boolean;
  error: string | null;
  create: (dashboardId: string, body: CreateReportRequest) => Promise<Report>;
  update: (dashboardId: string, reportId: string, body: UpdateReportRequest) => Promise<Report>;
  remove: (dashboardId: string, reportId: string) => Promise<void>;
  reorder: (dashboardId: string, body: ReorderReportsRequest) => Promise<Report[]>;
  clearError: () => void;
}

/**
 * Hook for report mutation operations (create, update, delete, reorder).
 *
 * Usage:
 * ```tsx
 * const { saving, error, create, update, remove, reorder } = useReportMutations();
 *
 * const handleAddReport = async () => {
 *   const report = await create(dashboardId, {
 *     name: 'Revenue Chart',
 *     chart_type: 'line',
 *     dataset_name: 'orders',
 *     config_json: chartConfig,
 *     position_json: { x: 0, y: 0, w: 6, h: 4 },
 *   });
 * };
 * ```
 */
export function useReportMutations(): UseReportMutationsResult {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  const create = useCallback(async (
    dashboardId: string,
    body: CreateReportRequest,
  ): Promise<Report> => {
    try {
      setSaving(true);
      setError(null);
      const result = await createReport(dashboardId, body);
      return result;
    } catch (err) {
      console.error('Failed to create report:', err);
      const message = isApiError(err)
        ? err.detail || err.message
        : err instanceof Error ? err.message : 'Failed to create report';
      setError(message);
      throw err;
    } finally {
      setSaving(false);
    }
  }, []);

  const update = useCallback(async (
    dashboardId: string,
    reportId: string,
    body: UpdateReportRequest,
  ): Promise<Report> => {
    try {
      setSaving(true);
      setError(null);
      const result = await updateReport(dashboardId, reportId, body);
      return result;
    } catch (err) {
      console.error('Failed to update report:', err);
      const message = isApiError(err)
        ? err.detail || err.message
        : err instanceof Error ? err.message : 'Failed to update report';
      setError(message);
      throw err;
    } finally {
      setSaving(false);
    }
  }, []);

  const remove = useCallback(async (
    dashboardId: string,
    reportId: string,
  ): Promise<void> => {
    try {
      setSaving(true);
      setError(null);
      await deleteReport(dashboardId, reportId);
    } catch (err) {
      console.error('Failed to delete report:', err);
      const message = isApiError(err)
        ? err.detail || err.message
        : err instanceof Error ? err.message : 'Failed to delete report';
      setError(message);
      throw err;
    } finally {
      setSaving(false);
    }
  }, []);

  const reorder = useCallback(async (
    dashboardId: string,
    body: ReorderReportsRequest,
  ): Promise<Report[]> => {
    try {
      setSaving(true);
      setError(null);
      const result = await reorderReports(dashboardId, body);
      return result;
    } catch (err) {
      console.error('Failed to reorder reports:', err);
      const message = isApiError(err)
        ? err.detail || err.message
        : err instanceof Error ? err.message : 'Failed to reorder reports';
      setError(message);
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
    reorder,
    clearError,
  };
}
