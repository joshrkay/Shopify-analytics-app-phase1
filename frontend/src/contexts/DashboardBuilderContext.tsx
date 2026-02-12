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
 * - Version tracking sync after report mutations (keeps expectedUpdatedAt fresh)
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
  useMemo,
  type ReactNode,
} from 'react';
import type {
  Dashboard,
  Report,
  CreateReportRequest,
  UpdateReportRequest,
  GridPosition,
  ChartType,
  BuilderWizardState,
  BuilderStep,
  WidgetCatalogItem,
} from '../types/customDashboards';
import { MIN_GRID_DIMENSIONS } from '../types/customDashboards';
import {
  getDashboard,
  updateDashboard,
  publishDashboard as publishDashboardApi,
  createDashboard,
} from '../services/customDashboardsApi';
import {
  createReport,
  updateReport as apiUpdateReport,
  deleteReport,
  reorderReports,
} from '../services/customReportsApi';
import { getErrorMessage, getErrorStatus } from '../services/apiUtils';
import DOMPurify from 'dompurify';

// =============================================================================
// Types
// =============================================================================

interface DashboardBuilderState {
  dashboard: Dashboard | null;
  loadError: string | null;
  isDirty: boolean;
  isSaving: boolean;
  saveError: string | null;
  saveErrorStatus: number | null;
  autoSaveStatus: 'idle' | 'saving' | 'error';
  autoSaveFailures: number;
  selectedReportId: string | null;
  isReportConfigOpen: boolean;
  wizardState: BuilderWizardState;
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

  // Refresh
  refreshDashboard: () => Promise<void>;

  // Auto-save
  autoSaveMessage: string | null;

  // Undo / Redo
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;

  // Wizard actions
  enterWizardMode: () => void;
  exitWizardMode: () => void;
  setBuilderStep: (step: BuilderStep) => void;
  setSelectedCategory: (category?: ChartType) => void;
  addCatalogWidget: (item: WidgetCatalogItem) => void;
  removeWizardWidget: (reportId: string) => void;
  moveWizardWidget: (reportId: string, newPosition: GridPosition) => void;
  setWizardDashboardName: (name: string) => void;
  setWizardDashboardDescription: (description: string) => void;
  setPreviewDateRange: (range: string) => void;
  setSaveAsTemplate: (value: boolean) => void;
  resetWizard: () => void;
  canProceedToCustomize: boolean;
  canProceedToPreview: boolean;
  canSaveDashboard: boolean;
}

type DashboardBuilderContextValue = DashboardBuilderState & DashboardBuilderActions;

// =============================================================================
// Context
// =============================================================================

const DashboardBuilderContext = createContext<DashboardBuilderContextValue | null>(null);

// =============================================================================
// Initial State
// =============================================================================

const AUTO_SAVE_INTERVAL_MS = 30_000;
const AUTO_SAVE_MAX_FAILURES = 3;
const AUTO_SAVE_RETRY_DELAYS = [5_000, 10_000, 20_000];

const initialState: DashboardBuilderState = {
  dashboard: null,
  loadError: null,
  isDirty: false,
  isSaving: false,
  saveError: null,
  saveErrorStatus: null,
  autoSaveStatus: 'idle',
  autoSaveFailures: 0,
  selectedReportId: null,
  isReportConfigOpen: false,
  wizardState: {
    isWizardMode: false,
    currentStep: 'select',
    selectedCategory: undefined,
    selectedWidgets: [],
    dashboardName: '',
    dashboardDescription: '',
    previewDateRange: '30',
    saveAsTemplate: false,
  },
};

// =============================================================================
// Provider
// =============================================================================

interface DashboardBuilderProviderProps {
  dashboardId?: string;
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

  // Undo/redo history stack (max 20 entries)
  const MAX_HISTORY = 20;
  const undoStackRef = useRef<Report[][]>([]);
  const redoStackRef = useRef<Report[][]>([]);

  // ---------------------------------------------------------------------------
  // Fetch dashboard on mount (or when dashboardId changes)
  // Skip fetch if dashboardId is not provided (wizard mode / create mode)
  // ---------------------------------------------------------------------------
  useEffect(() => {
    // Skip fetch if no dashboardId (wizard/create mode)
    if (!dashboardId) return;

    let cancelled = false;

    async function fetchDashboard() {
      try {
        const dashboard = await getDashboard(dashboardId!);
        if (cancelled) return;

        expectedUpdatedAtRef.current = dashboard.updated_at;
        pendingPositionsRef.current = new Map();

        setState({
          dashboard,
          loadError: null,
          isDirty: false,
          isSaving: false,
          saveError: null,
          saveErrorStatus: null,
          autoSaveStatus: 'idle',
          autoSaveFailures: 0,
          selectedReportId: null,
          isReportConfigOpen: false,
          wizardState: initialState.wizardState,
        });
      } catch (err) {
        if (cancelled) return;
        console.error('Failed to fetch dashboard:', err);
        setState((prev) => ({
          ...prev,
          loadError: getErrorMessage(err, 'Failed to load dashboard'),
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
      saveErrorStatus: null,
      autoSaveStatus: 'idle',
      autoSaveFailures: 0,
    }));
  }, []);

  // ---------------------------------------------------------------------------
  // Helper: sync expectedUpdatedAt after report mutations
  //
  // Report CRUD on the backend bumps the dashboard's updated_at and
  // version_number. Without this sync, the next saveDashboard call would
  // send a stale expected_updated_at and receive a 409 Conflict.
  // ---------------------------------------------------------------------------
  const syncExpectedUpdatedAt = useCallback(async () => {
    // Skip sync if no dashboardId (wizard/create mode)
    if (!dashboardId) return;

    try {
      const fresh = await getDashboard(dashboardId);
      expectedUpdatedAtRef.current = fresh.updated_at;
      setState((prev) => {
        if (!prev.dashboard) return prev;
        return {
          ...prev,
          dashboard: {
            ...prev.dashboard,
            version_number: fresh.version_number,
            updated_at: fresh.updated_at,
          },
        };
      });
    } catch {
      // Non-critical: stale version info won't block the user immediately
    }
  }, [dashboardId]);

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
      saveErrorStatus: null,
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
    setState((prev) => ({ ...prev, isSaving: true, saveError: null, saveErrorStatus: null }));

    try {
      const { dashboard, wizardState } = state;

      // WIZARD MODE: Create new dashboard with selected widgets
      if (wizardState.isWizardMode && !dashboard) {
        // 1. Create dashboard
        const newDashboard = await createDashboard({
          name: DOMPurify.sanitize(wizardState.dashboardName.trim()),
          description: DOMPurify.sanitize(wizardState.dashboardDescription.trim()) || undefined,
        });

        // 2. Create all reports in parallel
        const reportPromises = wizardState.selectedWidgets.map((widget) =>
          createReport(newDashboard.id, {
            name: widget.name,
            description: widget.description ?? undefined,
            chart_type: widget.chart_type,
            dataset_name: widget.dataset_name,
            config_json: widget.config_json,
            position_json: widget.position_json,
          }),
        );
        await Promise.all(reportPromises);

        // 3. Fetch complete dashboard with reports
        const completeDashboard = await getDashboard(newDashboard.id);

        // 4. Sync state and exit wizard
        expectedUpdatedAtRef.current = completeDashboard.updated_at;
        setState((prev) => ({
          ...prev,
          dashboard: completeDashboard,
          wizardState: { ...initialState.wizardState }, // Reset wizard state
          isDirty: false,
          isSaving: false,
        }));
        return;
      }

      // EDIT MODE: Existing save logic
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
      setState((prev) => ({
        ...prev,
        isSaving: false,
        saveError: getErrorMessage(err, 'Failed to save dashboard'),
        saveErrorStatus: getErrorStatus(err),
      }));
    }
  }, [state.dashboard, state.wizardState, syncDashboard]);

  const publishDashboard = useCallback(async () => {
    setState((prev) => ({ ...prev, isSaving: true, saveError: null, saveErrorStatus: null }));

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
      setState((prev) => ({
        ...prev,
        isSaving: false,
        saveError: getErrorMessage(err, 'Failed to publish dashboard'),
        saveErrorStatus: getErrorStatus(err),
      }));
    }
  }, [state.dashboard, state.isDirty, syncDashboard]);

  // ---------------------------------------------------------------------------
  // Report Actions
  // ---------------------------------------------------------------------------

  const addReport = useCallback(
    async (body: CreateReportRequest) => {
      setState((prev) => ({ ...prev, isSaving: true, saveError: null, saveErrorStatus: null }));

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
            saveErrorStatus: null,
          };
        });

        // Sync version tracking so next saveDashboard won't get 409
        syncExpectedUpdatedAt();
      } catch (err) {
        setState((prev) => ({
          ...prev,
          isSaving: false,
          saveError: getErrorMessage(err, 'Failed to add report'),
          saveErrorStatus: getErrorStatus(err),
        }));
      }
    },
    [state.dashboard, syncExpectedUpdatedAt],
  );

  const updateReportAction = useCallback(
    async (reportId: string, updates: UpdateReportRequest) => {
      setState((prev) => ({ ...prev, isSaving: true, saveError: null, saveErrorStatus: null }));

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
            saveErrorStatus: null,
          };
        });

        // Clear any pending position for this report since it was just persisted
        pendingPositionsRef.current.delete(reportId);

        // Sync version tracking so next saveDashboard won't get 409
        syncExpectedUpdatedAt();
      } catch (err) {
        setState((prev) => ({
          ...prev,
          isSaving: false,
          saveError: getErrorMessage(err, 'Failed to update report'),
          saveErrorStatus: getErrorStatus(err),
        }));
      }
    },
    [state.dashboard, syncExpectedUpdatedAt],
  );

  const removeReport = useCallback(
    async (reportId: string) => {
      setState((prev) => ({ ...prev, isSaving: true, saveError: null, saveErrorStatus: null }));

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
            saveErrorStatus: null,
            // Close configurator if the removed report was selected
            selectedReportId:
              prev.selectedReportId === reportId ? null : prev.selectedReportId,
            isReportConfigOpen:
              prev.selectedReportId === reportId ? false : prev.isReportConfigOpen,
          };
        });

        // Sync version tracking so next saveDashboard won't get 409
        syncExpectedUpdatedAt();
      } catch (err) {
        setState((prev) => ({
          ...prev,
          isSaving: false,
          saveError: getErrorMessage(err, 'Failed to remove report'),
          saveErrorStatus: getErrorStatus(err),
        }));
      }
    },
    [state.dashboard, syncExpectedUpdatedAt],
  );

  // ---------------------------------------------------------------------------
  // Undo / Redo
  // ---------------------------------------------------------------------------

  const pushHistory = useCallback(() => {
    if (!state.dashboard) return;
    const snapshot = state.dashboard.reports.map((r) => ({ ...r, position_json: { ...r.position_json } }));
    undoStackRef.current = [
      ...undoStackRef.current.slice(-(MAX_HISTORY - 1)),
      snapshot,
    ];
    redoStackRef.current = [];
  }, [state.dashboard]);

  const undo = useCallback(() => {
    const stack = undoStackRef.current;
    if (stack.length === 0 || !state.dashboard) return;
    const previous = stack[stack.length - 1];
    undoStackRef.current = stack.slice(0, -1);
    redoStackRef.current = [
      ...redoStackRef.current,
      state.dashboard.reports.map((r) => ({ ...r, position_json: { ...r.position_json } })),
    ];
    setState((prev) => {
      if (!prev.dashboard) return prev;
      return {
        ...prev,
        dashboard: { ...prev.dashboard, reports: previous },
        isDirty: true,
      };
    });
  }, [state.dashboard]);

  const redo = useCallback(() => {
    const stack = redoStackRef.current;
    if (stack.length === 0 || !state.dashboard) return;
    const next = stack[stack.length - 1];
    redoStackRef.current = stack.slice(0, -1);
    undoStackRef.current = [
      ...undoStackRef.current,
      state.dashboard.reports.map((r) => ({ ...r, position_json: { ...r.position_json } })),
    ];
    setState((prev) => {
      if (!prev.dashboard) return prev;
      return {
        ...prev,
        dashboard: { ...prev.dashboard, reports: next },
        isDirty: true,
      };
    });
  }, [state.dashboard]);

  const canUndo = undoStackRef.current.length > 0;
  const canRedo = redoStackRef.current.length > 0;

  // Keyboard shortcuts: Ctrl+Z / Ctrl+Shift+Z
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        e.preventDefault();
        if (e.shiftKey) {
          redo();
        } else {
          undo();
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [undo, redo]);

  const moveReport = useCallback((reportId: string, newPosition: GridPosition) => {
    // Push current state to undo stack before changing
    pushHistory();

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
  }, [pushHistory]);

  const commitLayout = useCallback(async () => {
    const pending = pendingPositionsRef.current;
    if (pending.size === 0) return;

    setState((prev) => ({ ...prev, isSaving: true, saveError: null, saveErrorStatus: null }));

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
          saveErrorStatus: null,
        };
      });

      // Sync version tracking after layout commit
      syncExpectedUpdatedAt();
    } catch (err) {
      setState((prev) => ({
        ...prev,
        isSaving: false,
        saveError: getErrorMessage(err, 'Failed to save layout'),
        saveErrorStatus: getErrorStatus(err),
      }));
    }
  }, [state.dashboard, syncExpectedUpdatedAt]);

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
  // Wizard Actions
  // ---------------------------------------------------------------------------

  const enterWizardMode = useCallback(() => {
    setState((prev) => ({
      ...prev,
      dashboard: null,
      wizardState: {
        isWizardMode: true,
        currentStep: 'select',
        selectedCategory: undefined,
        selectedWidgets: [],
        dashboardName: '',
        dashboardDescription: '',
        previewDateRange: '30',
        saveAsTemplate: false,
      },
      isDirty: false,
    }));
    expectedUpdatedAtRef.current = null;
    pendingPositionsRef.current = new Map();
  }, []);

  const exitWizardMode = useCallback(() => {
    setState((prev) => ({
      ...prev,
      wizardState: {
        ...initialState.wizardState,
        isWizardMode: false,
      },
    }));
  }, []);

  const setBuilderStep = useCallback((step: BuilderStep) => {
    setState((prev) => ({
      ...prev,
      wizardState: {
        ...prev.wizardState,
        currentStep: step,
      },
    }));
  }, []);

  const setSelectedCategory = useCallback((category?: ChartType) => {
    setState((prev) => ({
      ...prev,
      wizardState: {
        ...prev.wizardState,
        selectedCategory: category,
      },
    }));
  }, []);

  const addCatalogWidget = useCallback((item: WidgetCatalogItem) => {
    setState((prev) => {
      // Calculate auto-position: place at bottom of grid
      const maxY = prev.wizardState.selectedWidgets.reduce(
        (max, w) => Math.max(max, w.position_json.y + w.position_json.h),
        0,
      );

      // Use 2x minimum dimensions for default sizing
      const minDims = MIN_GRID_DIMENSIONS[item.chart_type];
      const width = minDims.w * 2;
      const height = minDims.h * 2;

      // Create Report object from catalog item
      const newReport: Report = {
        id: `${item.id}::${Date.now()}`,
        dashboard_id: '', // Will be set when dashboard is created
        name: item.name,
        description: item.description,
        chart_type: item.chart_type,
        dataset_name: item.required_dataset || '',
        config_json: item.default_config,
        position_json: {
          x: 0,
          y: maxY,
          w: width,
          h: height,
        },
        sort_order: prev.wizardState.selectedWidgets.length,
        created_by: '',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        warnings: [],
      };

      return {
        ...prev,
        wizardState: {
          ...prev.wizardState,
          selectedWidgets: [...prev.wizardState.selectedWidgets, newReport],
        },
        isDirty: true,
      };
    });
  }, []);

  const removeWizardWidget = useCallback((reportId: string) => {
    setState((prev) => ({
      ...prev,
      wizardState: {
        ...prev.wizardState,
        selectedWidgets: prev.wizardState.selectedWidgets.filter(
          (w) => w.id !== reportId,
        ),
      },
      isDirty: true,
    }));
  }, []);

  const moveWizardWidget = useCallback((reportId: string, newPosition: GridPosition) => {
    setState((prev) => ({
      ...prev,
      wizardState: {
        ...prev.wizardState,
        selectedWidgets: prev.wizardState.selectedWidgets.map((w) =>
          w.id === reportId ? { ...w, position_json: newPosition } : w
        ),
      },
      isDirty: true,
    }));
  }, []);

  const setWizardDashboardName = useCallback((name: string) => {
    setState((prev) => ({
      ...prev,
      wizardState: {
        ...prev.wizardState,
        dashboardName: name,
      },
      isDirty: true,
    }));
  }, []);

  const setWizardDashboardDescription = useCallback((description: string) => {
    setState((prev) => ({
      ...prev,
      wizardState: {
        ...prev.wizardState,
        dashboardDescription: description,
      },
      isDirty: true,
    }));
  }, []);

  const setPreviewDateRange = useCallback((range: string) => {
    setState((prev) => ({
      ...prev,
      wizardState: {
        ...prev.wizardState,
        previewDateRange: range,
      },
    }));
  }, []);

  const setSaveAsTemplate = useCallback((value: boolean) => {
    setState((prev) => ({
      ...prev,
      wizardState: {
        ...prev.wizardState,
        saveAsTemplate: value,
      },
    }));
  }, []);

  const resetWizard = useCallback(() => {
    setState((prev) => ({
      ...prev,
      wizardState: {
        ...initialState.wizardState,
      },
      isDirty: false,
    }));
  }, []);

  // ---------------------------------------------------------------------------
  // Error Handling
  // ---------------------------------------------------------------------------

  const clearError = useCallback(() => {
    setState((prev) => ({ ...prev, saveError: null, saveErrorStatus: null }));
  }, []);

  const refreshDashboard = useCallback(async () => {
    // Skip refresh if no dashboardId (wizard/create mode)
    if (!dashboardId) return;

    try {
      const dashboard = await getDashboard(dashboardId);
      expectedUpdatedAtRef.current = dashboard.updated_at;
      pendingPositionsRef.current = new Map();
      setState({
        dashboard,
        loadError: null,
        isDirty: false,
        isSaving: false,
        saveError: null,
        saveErrorStatus: null,
        autoSaveStatus: 'idle',
        autoSaveFailures: 0,
        selectedReportId: null,
        isReportConfigOpen: false,
        wizardState: initialState.wizardState,
      });
    } catch (err) {
      console.error('Failed to refresh dashboard:', err);
      setState((prev) => ({
        ...prev,
        saveError: getErrorMessage(err, 'Failed to refresh dashboard'),
        saveErrorStatus: getErrorStatus(err),
      }));
    }
  }, [dashboardId]);

  // ---------------------------------------------------------------------------
  // Auto-save every 30 seconds (draft only)
  // ---------------------------------------------------------------------------
  useEffect(() => {
    // Disable auto-save in wizard mode (no dashboard exists yet)
    if (state.wizardState.isWizardMode) {
      return;
    }
    if (!state.dashboard || state.dashboard.status !== 'draft' || !state.isDirty) {
      return;
    }
    // Don't auto-save if already saving or if auto-save has exceeded max failures
    if (state.isSaving || state.autoSaveFailures >= AUTO_SAVE_MAX_FAILURES) {
      return;
    }

    const delay = state.autoSaveFailures > 0
      ? AUTO_SAVE_RETRY_DELAYS[Math.min(state.autoSaveFailures - 1, AUTO_SAVE_RETRY_DELAYS.length - 1)]
      : AUTO_SAVE_INTERVAL_MS;

    const timer = setTimeout(async () => {
      setState((prev) => ({ ...prev, autoSaveStatus: 'saving' }));
      try {
        const current = state.dashboard;
        if (!current) return;
        const updated = await updateDashboard(current.id, {
          name: current.name,
          description: current.description ?? undefined,
          layout_json: current.layout_json,
          expected_updated_at: expectedUpdatedAtRef.current ?? undefined,
        });
        pendingPositionsRef.current = new Map();
        expectedUpdatedAtRef.current = updated.updated_at;
        setState((prev) => ({
          ...prev,
          dashboard: updated,
          isDirty: false,
          autoSaveStatus: 'idle',
          autoSaveFailures: 0,
          saveError: null,
          saveErrorStatus: null,
        }));
      } catch {
        setState((prev) => ({
          ...prev,
          autoSaveStatus: 'error',
          autoSaveFailures: prev.autoSaveFailures + 1,
        }));
      }
    }, delay);

    return () => clearTimeout(timer);
  }, [state.dashboard, state.isDirty, state.isSaving, state.autoSaveFailures, state.wizardState.isWizardMode]);

  const autoSaveMessage = useMemo(() => {
    if (state.autoSaveStatus === 'saving') return 'Saving...';
    if (state.autoSaveStatus === 'error' && state.autoSaveFailures < AUTO_SAVE_MAX_FAILURES) {
      return 'Changes not saved. Retrying...';
    }
    if (state.autoSaveFailures >= AUTO_SAVE_MAX_FAILURES) {
      return 'Unable to save. Please check your connection.';
    }
    return null;
  }, [state.autoSaveStatus, state.autoSaveFailures]);

  // ---------------------------------------------------------------------------
  // Wizard Derived Values
  // ---------------------------------------------------------------------------

  const canProceedToCustomize = useMemo(() => {
    return state.wizardState.selectedWidgets.length > 0;
  }, [state.wizardState.selectedWidgets.length]);

  const canProceedToPreview = useMemo(() => {
    return state.wizardState.dashboardName.trim().length > 0 &&
           state.wizardState.selectedWidgets.length > 0;
  }, [state.wizardState.dashboardName, state.wizardState.selectedWidgets.length]);

  const canSaveDashboard = useMemo(() => {
    if (!state.wizardState.isWizardMode) return true; // Edit mode always allows save
    return state.wizardState.dashboardName.trim().length > 0 &&
           state.wizardState.selectedWidgets.length > 0;
  }, [state.wizardState.isWizardMode, state.wizardState.dashboardName, state.wizardState.selectedWidgets.length]);

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
    refreshDashboard,
    autoSaveMessage,
    undo,
    redo,
    canUndo,
    canRedo,
    // Wizard actions
    enterWizardMode,
    exitWizardMode,
    setBuilderStep,
    setSelectedCategory,
    addCatalogWidget,
    removeWizardWidget,
    moveWizardWidget,
    setWizardDashboardName,
    setWizardDashboardDescription,
    setPreviewDateRange,
    setSaveAsTemplate,
    resetWizard,
    canProceedToCustomize,
    canProceedToPreview,
    canSaveDashboard,
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
