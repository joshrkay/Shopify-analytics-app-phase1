/**
 * Dashboard Builder Context Provider
 *
 * Manages the entire dashboard builder session state:
 * - Fetches and caches dashboard on mount
 * - Tracks dirty state for unsaved changes
 * - Optimistic local updates for drag-drop (moveReport)
 * - Batched layout persistence (commitLayout)
 * - Optimistic locking via expectedUpdatedAt (409 conflict handling)
 * - Report CRUD with automatic dashboard refresh
 * - Report configurator panel open/close state
 *
 * Phase 3 - Dashboard Builder UI
 */

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  type ReactNode,
} from 'react';
import type {
  Dashboard,
  Report,
  CreateReportRequest,
  UpdateReportRequest,
  GridPosition,
  ChartType,
} from '../types/customDashboards';
import {
  getDashboard,
  updateDashboard,
  publishDashboard as publishDashboardApi,
} from '../services/customDashboardsApi';
import {
  createReport,
  updateReport as apiUpdateReport,
  deleteReport,
  reorderReports,
} from '../services/customReportsApi';
import { isApiError } from '../services/apiUtils';

// =============================================================================
// Types
// =============================================================================

interface DashboardBuilderState {
  dashboard: Dashboard | null;
  isDirty: boolean;
  isSaving: boolean;
  saveError: string | null;
  selectedReportId: string | null;
  isReportConfigOpen: boolean;
}

interface DashboardBuilderActions {
  // Dashboard actions
  setDashboard: (dashboard: Dashboard) => void;
  updateDashboardMeta: (updates: { name?: string; description?: string }) => void;
  saveDashboard: () => Promise<void>;
  publishDashboard: () => Promise<void>;

  // Report actions
  addReport: (body: CreateReportRequest) => Promise<void>;
  updateReport: (reportId: string, updates: UpdateReportRequest) => Promise<void>;
  removeReport: (reportId: string) => Promise<void>;
  moveReport: (reportId: string, newPosition: GridPosition) => void;
  commitLayout: () => Promise<void>;

  // Report configurator
  openReportConfig: (reportId: string | null) => void;
  closeReportConfig: () => void;

  // Error handling
  clearError: () => void;
}

type DashboardBuilderContextValue = DashboardBuilderState & DashboardBuilderActions;

// =============================================================================
// Context
// =============================================================================

const DashboardBuilderContext = createContext<DashboardBuilderContextValue | null>(null);

// =============================================================================
// Initial State
// =============================================================================

const initialState: DashboardBuilderState = {
  dashboard: null,
  isDirty: false,
  isSaving: false,
  saveError: null,
  selectedReportId: null,
  isReportConfigOpen: false,
};

// =============================================================================
// Provider
// =============================================================================

interface DashboardBuilderProviderProps {
  dashboardId: string;
  children: ReactNode;
}

export function DashboardBuilderProvider({
  dashboardId,
  children,
}: DashboardBuilderProviderProps) {
  const [state, setState] = useState<DashboardBuilderState>(initialState);

  // Track expected updated_at for optimistic locking
  const expectedUpdatedAtRef = useRef<string | null>(null);

  // Track pending position changes from moveReport (not yet persisted)
  const pendingPositionsRef = useRef<Map<string, GridPosition>>(new Map());

  // ---------------------------------------------------------------------------
  // Fetch dashboard on mount (or when dashboardId changes)
  // ---------------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;

    async function fetchDashboard() {
      try {
        const dashboard = await getDashboard(dashboardId);
        if (cancelled) return;

        expectedUpdatedAtRef.current = dashboard.updated_at;
        pendingPositionsRef.current = new Map();

        setState({
          dashboard,
          isDirty: false,
          isSaving: false,
          saveError: null,
          selectedReportId: null,
          isReportConfigOpen: false,
        });
      } catch (err) {
        if (cancelled) return;
        console.error('Failed to fetch dashboard:', err);
        setState((prev) => ({
          ...prev,
          saveError: err instanceof Error ? err.message : 'Failed to load dashboard',
        }));
      }
    }

    fetchDashboard();

    return () => {
      cancelled = true;
    };
  }, [dashboardId]);

  // ---------------------------------------------------------------------------
  // Helper: update dashboard in state and sync expectedUpdatedAt
  // ---------------------------------------------------------------------------
  const syncDashboard = useCallback((updated: Dashboard) => {
    expectedUpdatedAtRef.current = updated.updated_at;
    setState((prev) => ({
      ...prev,
      dashboard: updated,
      isDirty: false,
      isSaving: false,
      saveError: null,
    }));
  }, []);

  // ---------------------------------------------------------------------------
  // Helper: handle 409 conflict errors
  // ---------------------------------------------------------------------------
  const handleApiError = useCallback((err: unknown): string => {
    if (isApiError(err) && err.status === 409) {
      return 'Dashboard was modified by another user. Please reload.';
    }
    return err instanceof Error ? err.message : 'An unexpected error occurred';
  }, []);

  // ---------------------------------------------------------------------------
  // Dashboard Actions
  // ---------------------------------------------------------------------------

  const setDashboard = useCallback((dashboard: Dashboard) => {
    expectedUpdatedAtRef.current = dashboard.updated_at;
    pendingPositionsRef.current = new Map();
    setState((prev) => ({
      ...prev,
      dashboard,
      isDirty: false,
      saveError: null,
    }));
  }, []);

  const updateDashboardMeta = useCallback(
    (updates: { name?: string; description?: string }) => {
      setState((prev) => {
        if (!prev.dashboard) return prev;
        return {
          ...prev,
          dashboard: {
            ...prev.dashboard,
            ...(updates.name !== undefined && { name: updates.name }),
            ...(updates.description !== undefined && { description: updates.description }),
          },
          isDirty: true,
        };
      });
    },
    [],
  );

  const saveDashboard = useCallback(async () => {
    setState((prev) => ({ ...prev, isSaving: true, saveError: null }));

    try {
      const current = state.dashboard;
      if (!current) {
        throw new Error('No dashboard loaded');
      }

      const updated = await updateDashboard(current.id, {
        name: current.name,
        description: current.description ?? undefined,
        layout_json: current.layout_json,
        expected_updated_at: expectedUpdatedAtRef.current ?? undefined,
      });

      pendingPositionsRef.current = new Map();
      syncDashboard(updated);
    } catch (err) {
      const errorMessage = handleApiError(err);
      setState((prev) => ({
        ...prev,
        isSaving: false,
        saveError: errorMessage,
      }));
    }
  }, [state.dashboard, syncDashboard, handleApiError]);

  const publishDashboard = useCallback(async () => {
    setState((prev) => ({ ...prev, isSaving: true, saveError: null }));

    try {
      const current = state.dashboard;
      if (!current) {
        throw new Error('No dashboard loaded');
      }

      // Save any pending changes first
      if (state.isDirty) {
        const saved = await updateDashboard(current.id, {
          name: current.name,
          description: current.description ?? undefined,
          layout_json: current.layout_json,
          expected_updated_at: expectedUpdatedAtRef.current ?? undefined,
        });
        expectedUpdatedAtRef.current = saved.updated_at;
      }

      const published = await publishDashboardApi(current.id);

      pendingPositionsRef.current = new Map();
      syncDashboard(published);
    } catch (err) {
      const errorMessage = handleApiError(err);
      setState((prev) => ({
        ...prev,
        isSaving: false,
        saveError: errorMessage,
      }));
    }
  }, [state.dashboard, state.isDirty, syncDashboard, handleApiError]);

  // ---------------------------------------------------------------------------
  // Report Actions
  // ---------------------------------------------------------------------------

  const addReport = useCallback(
    async (body: CreateReportRequest) => {
      setState((prev) => ({ ...prev, isSaving: true, saveError: null }));

      try {
        const current = state.dashboard;
        if (!current) {
          throw new Error('No dashboard loaded');
        }

        const newReport = await createReport(current.id, body);

        setState((prev) => {
          if (!prev.dashboard) return prev;
          return {
            ...prev,
            dashboard: {
              ...prev.dashboard,
              reports: [...prev.dashboard.reports, newReport],
            },
            isSaving: false,
            saveError: null,
          };
        });
      } catch (err) {
        const errorMessage = handleApiError(err);
        setState((prev) => ({
          ...prev,
          isSaving: false,
          saveError: errorMessage,
        }));
      }
    },
    [state.dashboard, handleApiError],
  );

  const updateReportAction = useCallback(
    async (reportId: string, updates: UpdateReportRequest) => {
      setState((prev) => ({ ...prev, isSaving: true, saveError: null }));

      try {
        const current = state.dashboard;
        if (!current) {
          throw new Error('No dashboard loaded');
        }

        const updatedReport = await apiUpdateReport(current.id, reportId, updates);

        setState((prev) => {
          if (!prev.dashboard) return prev;
          return {
            ...prev,
            dashboard: {
              ...prev.dashboard,
              reports: prev.dashboard.reports.map((r) =>
                r.id === reportId ? updatedReport : r,
              ),
            },
            isSaving: false,
            saveError: null,
          };
        });

        // Clear any pending position for this report since it was just persisted
        pendingPositionsRef.current.delete(reportId);
      } catch (err) {
        const errorMessage = handleApiError(err);
        setState((prev) => ({
          ...prev,
          isSaving: false,
          saveError: errorMessage,
        }));
      }
    },
    [state.dashboard, handleApiError],
  );

  const removeReport = useCallback(
    async (reportId: string) => {
      setState((prev) => ({ ...prev, isSaving: true, saveError: null }));

      try {
        const current = state.dashboard;
        if (!current) {
          throw new Error('No dashboard loaded');
        }

        await deleteReport(current.id, reportId);

        // Remove from pending positions if present
        pendingPositionsRef.current.delete(reportId);

        setState((prev) => {
          if (!prev.dashboard) return prev;
          return {
            ...prev,
            dashboard: {
              ...prev.dashboard,
              reports: prev.dashboard.reports.filter((r) => r.id !== reportId),
            },
            isSaving: false,
            saveError: null,
            // Close configurator if the removed report was selected
            selectedReportId:
              prev.selectedReportId === reportId ? null : prev.selectedReportId,
            isReportConfigOpen:
              prev.selectedReportId === reportId ? false : prev.isReportConfigOpen,
          };
        });
      } catch (err) {
        const errorMessage = handleApiError(err);
        setState((prev) => ({
          ...prev,
          isSaving: false,
          saveError: errorMessage,
        }));
      }
    },
    [state.dashboard, handleApiError],
  );

  const moveReport = useCallback((reportId: string, newPosition: GridPosition) => {
    // Track the pending position change
    pendingPositionsRef.current.set(reportId, newPosition);

    // Update local state immediately for smooth drag-drop UX
    setState((prev) => {
      if (!prev.dashboard) return prev;
      return {
        ...prev,
        dashboard: {
          ...prev.dashboard,
          reports: prev.dashboard.reports.map((r) =>
            r.id === reportId ? { ...r, position_json: newPosition } : r,
          ),
        },
        isDirty: true,
      };
    });
  }, []);

  const commitLayout = useCallback(async () => {
    const pending = pendingPositionsRef.current;
    if (pending.size === 0) return;

    setState((prev) => ({ ...prev, isSaving: true, saveError: null }));

    try {
      const current = state.dashboard;
      if (!current) {
        throw new Error('No dashboard loaded');
      }

      // Batch all pending position changes into individual API calls
      const updatePromises = Array.from(pending.entries()).map(
        ([reportId, position]) =>
          apiUpdateReport(current.id, reportId, { position_json: position }),
      );

      const updatedReports = await Promise.all(updatePromises);

      // Build a map of updated reports for efficient lookup
      const updatedMap = new Map(updatedReports.map((r) => [r.id, r]));

      // Clear pending positions
      pendingPositionsRef.current = new Map();

      setState((prev) => {
        if (!prev.dashboard) return prev;
        return {
          ...prev,
          dashboard: {
            ...prev.dashboard,
            reports: prev.dashboard.reports.map((r) => updatedMap.get(r.id) ?? r),
          },
          isDirty: false,
          isSaving: false,
          saveError: null,
        };
      });
    } catch (err) {
      const errorMessage = handleApiError(err);
      setState((prev) => ({
        ...prev,
        isSaving: false,
        saveError: errorMessage,
      }));
    }
  }, [state.dashboard, handleApiError]);

  // ---------------------------------------------------------------------------
  // Report Configurator
  // ---------------------------------------------------------------------------

  const openReportConfig = useCallback((reportId: string | null) => {
    setState((prev) => ({
      ...prev,
      selectedReportId: reportId,
      isReportConfigOpen: true,
    }));
  }, []);

  const closeReportConfig = useCallback(() => {
    setState((prev) => ({
      ...prev,
      selectedReportId: null,
      isReportConfigOpen: false,
    }));
  }, []);

  // ---------------------------------------------------------------------------
  // Error Handling
  // ---------------------------------------------------------------------------

  const clearError = useCallback(() => {
    setState((prev) => ({ ...prev, saveError: null }));
  }, []);

  // ---------------------------------------------------------------------------
  // Context Value
  // ---------------------------------------------------------------------------

  const value: DashboardBuilderContextValue = {
    ...state,
    setDashboard,
    updateDashboardMeta,
    saveDashboard,
    publishDashboard,
    addReport,
    updateReport: updateReportAction,
    removeReport,
    moveReport,
    commitLayout,
    openReportConfig,
    closeReportConfig,
    clearError,
  };

  return (
    <DashboardBuilderContext.Provider value={value}>
      {children}
    </DashboardBuilderContext.Provider>
  );
}

// =============================================================================
// Hooks
// =============================================================================

/**
 * Hook to access the dashboard builder context.
 *
 * Must be used within a DashboardBuilderProvider.
 */
export function useDashboardBuilder(): DashboardBuilderContextValue {
  const context = useContext(DashboardBuilderContext);
  if (!context) {
    throw new Error(
      'useDashboardBuilder must be used within a DashboardBuilderProvider',
    );
  }
  return context;
}

export default DashboardBuilderContext;
