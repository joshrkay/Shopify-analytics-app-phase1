/**
 * Data Health Context Provider
 *
 * Provides app-wide data health state with smart polling:
 * - Adaptive poll frequency based on health status
 * - Pauses when browser tab is hidden
 * - Exposes health and incident state for badges/banners
 *
 * Story 9.5 - Data Freshness Indicators
 * Story 9.6 - Incident Communication
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
import {
  getCompactHealth,
  getActiveIncidents,
  getMerchantDataHealth,
  acknowledgeIncident as acknowledgeIncidentApi,
  formatTimeSinceSync,
  type CompactHealth,
  type ActiveIncidentBanner,
  type MerchantDataHealthResponse,
} from '../services/syncHealthApi';
import { isBackendDown, resetCircuitBreaker } from '../services/apiUtils';
import type { MerchantHealthState } from '../utils/data_health_copy';

// =============================================================================
// Types
// =============================================================================

interface DataHealthState {
  health: CompactHealth | null;
  activeIncidents: ActiveIncidentBanner[];
  hasCritical: boolean;
  hasBlocking: boolean;
  loading: boolean;
  error: string | null;
  lastUpdated: Date | null;
  /** Merchant-facing health state (Story 4.3) */
  merchantHealth: MerchantDataHealthResponse | null;
}

interface DataHealthContextValue extends DataHealthState {
  /** Force refresh health and incidents data */
  refresh: () => Promise<void>;
  /** Acknowledge an incident to hide from banner */
  acknowledgeIncident: (incidentId: string) => Promise<void>;
  // Computed helpers
  /** True if any connector has stale data */
  hasStaleData: boolean;
  /** True if any critical issues exist */
  hasCriticalIssues: boolean;
  /** True if there are blocking issues */
  hasBlockingIssues: boolean;
  /** True if banner should be shown (has active incidents) */
  shouldShowBanner: boolean;
  /** Most severe incident for banner display */
  mostSevereIncident: ActiveIncidentBanner | null;
  /** Human-readable freshness label */
  freshnessLabel: string;
  /** Merchant-facing health state (Story 4.3) */
  merchantHealthState: MerchantHealthState | null;
  /** Merchant-facing health message (Story 4.3) */
  merchantHealthMessage: string | null;
}

// Poll intervals based on health status
const POLL_INTERVALS = {
  healthy: 60000,   // 1 minute
  degraded: 30000,  // 30 seconds
  critical: 15000,  // 15 seconds
};

// Error backoff: stop polling after consecutive failures to avoid flooding a down backend
const MAX_CONSECUTIVE_ERRORS = 5;
const ERROR_BACKOFF_BASE_MS = 30000; // 30s base, doubles each error

const initialState: DataHealthState = {
  health: null,
  activeIncidents: [],
  hasCritical: false,
  hasBlocking: false,
  loading: true,
  error: null,
  lastUpdated: null,
  merchantHealth: null,
};

const DataHealthContext = createContext<DataHealthContextValue | null>(null);

// =============================================================================
// Provider
// =============================================================================

interface DataHealthProviderProps {
  children: ReactNode;
  /** Disable polling (for testing) */
  disablePolling?: boolean;
}

export function DataHealthProvider({
  children,
  disablePolling = false,
}: DataHealthProviderProps) {
  const [state, setState] = useState<DataHealthState>(initialState);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isPendingRef = useRef(false);
  const consecutiveErrorsRef = useRef(0);
  // Ref breaks circular dependency: schedulePoll ↔ refresh ↔ schedulePoll
  const schedulePollRef = useRef<() => void>(() => {});

  // Fetch health and incidents data
  const fetchData = useCallback(async () => {
    // Prevent concurrent fetches
    if (isPendingRef.current) return;
    // Skip if global circuit breaker says backend is down
    if (isBackendDown()) return;
    isPendingRef.current = true;

    try {
      const [healthData, incidentsData, merchantHealthData] = await Promise.all([
        getCompactHealth(),
        getActiveIncidents(),
        getMerchantDataHealth().catch(() => null),
      ]);

      consecutiveErrorsRef.current = 0;
      setState({
        health: healthData,
        activeIncidents: incidentsData.incidents,
        hasCritical: incidentsData.has_critical,
        hasBlocking: incidentsData.has_blocking,
        loading: false,
        error: null,
        lastUpdated: new Date(),
        merchantHealth: merchantHealthData,
      });
    } catch (err) {
      consecutiveErrorsRef.current += 1;
      const errorCount = consecutiveErrorsRef.current;
      if (errorCount <= 3) {
        console.error('Failed to fetch data health:', err);
      } else if (errorCount === MAX_CONSECUTIVE_ERRORS) {
        console.error(
          `Data health polling paused after ${errorCount} consecutive failures. Use refresh() to retry.`
        );
      }
      setState((prev) => ({
        ...prev,
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to fetch health data',
      }));
    } finally {
      isPendingRef.current = false;
    }
  }, []);

  // Get poll interval based on current health status
  const getPollInterval = useCallback((): number => {
    const status = state.health?.overall_status;
    return POLL_INTERVALS[status || 'healthy'];
  }, [state.health?.overall_status]);

  // Schedule next poll (with error backoff)
  const schedulePoll = useCallback(() => {
    if (disablePolling) return;

    // Clear existing timeout
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current);
    }

    // Stop polling after too many consecutive errors to avoid flooding a down backend
    const errorCount = consecutiveErrorsRef.current;
    if (errorCount >= MAX_CONSECUTIVE_ERRORS) {
      return;
    }

    // Use exponential backoff when errors are occurring
    const baseInterval = getPollInterval();
    const interval = errorCount > 0
      ? Math.min(ERROR_BACKOFF_BASE_MS * Math.pow(2, errorCount - 1), 300000)
      : baseInterval;

    pollTimeoutRef.current = setTimeout(() => {
      fetchData().then(() => schedulePollRef.current());
    }, interval);
  }, [disablePolling, getPollInterval, fetchData]);

  // Keep ref in sync so callbacks always use the latest schedulePoll
  schedulePollRef.current = schedulePoll;

  // Public refresh function (resets error backoff and circuit breaker)
  const refresh = useCallback(async () => {
    consecutiveErrorsRef.current = 0;
    resetCircuitBreaker();
    setState((prev) => ({ ...prev, loading: true, error: null }));
    await fetchData();
    schedulePollRef.current();
  }, [fetchData]);

  // Acknowledge incident
  const acknowledgeIncident = useCallback(async (incidentId: string) => {
    try {
      await acknowledgeIncidentApi(incidentId);
      // Remove from local state immediately
      setState((prev) => ({
        ...prev,
        activeIncidents: prev.activeIncidents.filter((i) => i.id !== incidentId),
      }));
    } catch (err) {
      console.error('Failed to acknowledge incident:', err);
      throw err;
    }
  }, []);

  // Initial fetch and polling setup
  useEffect(() => {
    fetchData().then(() => schedulePollRef.current());

    return () => {
      if (pollTimeoutRef.current) {
        clearTimeout(pollTimeoutRef.current);
      }
    };
  }, [fetchData]);

  // Pause polling when tab is hidden
  useEffect(() => {
    if (disablePolling) return;

    const handleVisibilityChange = () => {
      if (document.hidden) {
        // Pause polling
        if (pollTimeoutRef.current) {
          clearTimeout(pollTimeoutRef.current);
          pollTimeoutRef.current = null;
        }
      } else {
        // Resume polling and fetch immediately
        fetchData().then(() => schedulePollRef.current());
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [disablePolling, fetchData]);

  // Computed values
  const hasStaleData = (state.health?.stale_count ?? 0) > 0;
  const hasCriticalIssues = (state.health?.critical_count ?? 0) > 0 || state.hasCritical;
  const hasBlockingIssues = state.health?.has_blocking_issues ?? false;
  const shouldShowBanner = state.activeIncidents.length > 0;

  const mostSevereIncident = state.activeIncidents.reduce<ActiveIncidentBanner | null>(
    (most, current) => {
      if (!most) return current;
      const severityOrder = { critical: 3, high: 2, warning: 1 };
      return severityOrder[current.severity] > severityOrder[most.severity]
        ? current
        : most;
    },
    null
  );

  const freshnessLabel = state.health?.oldest_sync_minutes !== null
    ? formatTimeSinceSync(state.health?.oldest_sync_minutes ?? null)
    : 'All data fresh';

  // Merchant health state (Story 4.3)
  const merchantHealthState: MerchantHealthState | null =
    (state.merchantHealth?.health_state as MerchantHealthState) ?? null;
  const merchantHealthMessage: string | null =
    state.merchantHealth?.user_safe_message ?? null;

  const value: DataHealthContextValue = {
    ...state,
    refresh,
    acknowledgeIncident,
    hasStaleData,
    hasCriticalIssues,
    hasBlockingIssues,
    shouldShowBanner,
    mostSevereIncident,
    freshnessLabel,
    merchantHealthState,
    merchantHealthMessage,
  };

  return (
    <DataHealthContext.Provider value={value}>
      {children}
    </DataHealthContext.Provider>
  );
}

// =============================================================================
// Hooks
// =============================================================================

/**
 * Hook to access full data health context.
 *
 * Must be used within a DataHealthProvider.
 */
export function useDataHealth(): DataHealthContextValue {
  const context = useContext(DataHealthContext);
  if (!context) {
    throw new Error('useDataHealth must be used within a DataHealthProvider');
  }
  return context;
}

/**
 * Hook to get freshness status for badges.
 */
export function useFreshnessStatus(): {
  status: 'healthy' | 'degraded' | 'critical' | null;
  hasStaleData: boolean;
  hasCriticalIssues: boolean;
  freshnessLabel: string;
  loading: boolean;
} {
  const { health, hasStaleData, hasCriticalIssues, freshnessLabel, loading } =
    useDataHealth();
  return {
    status: health?.overall_status ?? null,
    hasStaleData,
    hasCriticalIssues,
    freshnessLabel,
    loading,
  };
}

/**
 * Hook to get active incidents for banners.
 */
export function useActiveIncidents(): {
  incidents: ActiveIncidentBanner[];
  shouldShowBanner: boolean;
  mostSevereIncident: ActiveIncidentBanner | null;
  acknowledgeIncident: (id: string) => Promise<void>;
} {
  const { activeIncidents, shouldShowBanner, mostSevereIncident, acknowledgeIncident } =
    useDataHealth();
  return {
    incidents: activeIncidents,
    shouldShowBanner,
    mostSevereIncident,
    acknowledgeIncident,
  };
}

/**
 * Hook to get merchant-facing health state (Story 4.3).
 *
 * Returns the simplified trust indicator for merchant UI.
 */
export function useMerchantHealth(): {
  healthState: MerchantHealthState | null;
  message: string | null;
  aiInsightsEnabled: boolean;
  dashboardsEnabled: boolean;
  exportsEnabled: boolean;
  loading: boolean;
} {
  const { merchantHealth, loading } = useDataHealth();
  return {
    healthState: (merchantHealth?.health_state as MerchantHealthState) ?? null,
    message: merchantHealth?.user_safe_message ?? null,
    aiInsightsEnabled: merchantHealth?.ai_insights_enabled ?? true,
    dashboardsEnabled: merchantHealth?.dashboards_enabled ?? true,
    exportsEnabled: merchantHealth?.exports_enabled ?? true,
    loading,
  };
}

export default DataHealthContext;
