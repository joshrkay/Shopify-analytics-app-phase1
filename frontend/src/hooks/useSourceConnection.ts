/**
 * useSourceConnection Hooks
 *
 * Custom hooks for data source connection management:
 * - useSourceCatalog: Fetch available platforms
 * - useConnectionWizard: Multi-step connection wizard state machine
 * - useSourceMutations: Mutation operations (disconnect, test, configure)
 *
 * Follows useDashboardMutations pattern with useState + useCallback.
 *
 * Phase 3 — Subphase 3.3: Connection Management Hooks
 */

import { useState, useCallback, useEffect } from 'react';
import type { SourcePlatform } from '../types/sources';
import type {
  DataSourceDefinition,
  ConnectionWizardState,
  ConnectionTestResult,
  UpdateSyncConfigRequest,
  ConnectionStep,
} from '../types/sourceConnection';
import {
  getAvailableSources,
  initiateOAuth,
  disconnectSource as apiDisconnectSource,
  testConnection as apiTestConnection,
  updateSyncConfig as apiUpdateSyncConfig,
} from '../services/sourcesApi';
import { getErrorMessage } from '../services/apiUtils';

// =============================================================================
// useSourceCatalog — Fetch available platforms
// =============================================================================

interface UseSourceCatalogResult {
  catalog: DataSourceDefinition[];
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

/**
 * Hook for fetching available data source platforms.
 *
 * Loads catalog on mount and provides refetch function.
 *
 * Usage:
 * ```tsx
 * const { catalog, loading, error } = useSourceCatalog();
 * ```
 */
export function useSourceCatalog(): UseSourceCatalogResult {
  const [catalog, setCatalog] = useState<DataSourceDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const sources = await getAvailableSources();
      setCatalog(sources);
    } catch (err) {
      console.error('Failed to load source catalog:', err);
      setError(getErrorMessage(err, 'Failed to load available sources'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const sources = await getAvailableSources();
        if (!cancelled) {
          setCatalog(sources);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to load source catalog:', err);
          setError(getErrorMessage(err, 'Failed to load available sources'));
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, []);

  return {
    catalog,
    loading,
    error,
    refetch,
  };
}

// =============================================================================
// useConnectionWizard — Multi-step wizard state machine
// =============================================================================

interface UseConnectionWizardResult {
  state: ConnectionWizardState;
  selectPlatform: (platform: DataSourceDefinition) => void;
  setStep: (step: ConnectionStep) => void;
  configure: (config: Record<string, any>) => void;
  startOAuth: () => Promise<void>;
  testConnection: () => Promise<void>;
  setTestResult: (result: ConnectionTestResult) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

/**
 * Hook for managing connection wizard state.
 *
 * Provides state machine for 5-step wizard flow:
 * 1. select — Choose platform
 * 2. configure — Platform-specific config (shop domain, API key, etc.)
 * 3. authenticate — OAuth redirect or credential validation
 * 4. test — Test connection
 * 5. complete — Success confirmation
 *
 * Usage:
 * ```tsx
 * const { state, selectPlatform, startOAuth, testConnection, reset } = useConnectionWizard();
 * ```
 */
export function useConnectionWizard(): UseConnectionWizardResult {
  const [state, setState] = useState<ConnectionWizardState>({
    step: 'select',
    selectedPlatform: null,
    configuration: {},
    testResult: null,
    error: null,
  });

  const selectPlatform = useCallback((platform: DataSourceDefinition) => {
    setState((prev) => ({
      ...prev,
      selectedPlatform: platform,
      step: 'configure',
      error: null,
    }));
  }, []);

  const setStep = useCallback((step: ConnectionStep) => {
    setState((prev) => ({
      ...prev,
      step,
    }));
  }, []);

  const configure = useCallback((config: Record<string, any>) => {
    setState((prev) => ({
      ...prev,
      configuration: config,
      step: 'authenticate',
      error: null,
    }));
  }, []);

  const startOAuth = useCallback(async () => {
    setState((prev) => ({ ...prev, error: null }));

    if (!state.selectedPlatform) {
      setState((prev) => ({ ...prev, error: 'No platform selected' }));
      return;
    }

    try {
      const response = await initiateOAuth(state.selectedPlatform.platform);
      // Redirect to OAuth provider
      window.location.href = response.authorization_url;
    } catch (err) {
      console.error('Failed to initiate OAuth:', err);
      setState((prev) => ({
        ...prev,
        error: getErrorMessage(err, 'Failed to start OAuth flow'),
      }));
    }
  }, [state.selectedPlatform]);

  const testConnection = useCallback(async () => {
    setState((prev) => ({ ...prev, error: null, step: 'test' }));

    // For API key auth, we would test here
    // For OAuth, test happens in OAuthCallback page after redirect
    // This is a placeholder for the API key flow
    try {
      // TODO: Implement API key connection test
      setState((prev) => ({
        ...prev,
        testResult: { success: true, message: 'Connection successful' },
        step: 'complete',
      }));
    } catch (err) {
      console.error('Failed to test connection:', err);
      setState((prev) => ({
        ...prev,
        error: getErrorMessage(err, 'Connection test failed'),
      }));
    }
  }, []);

  const setTestResult = useCallback((result: ConnectionTestResult) => {
    setState((prev) => ({
      ...prev,
      testResult: result,
      step: result.success ? 'complete' : 'test',
    }));
  }, []);

  const setError = useCallback((error: string | null) => {
    setState((prev) => ({ ...prev, error }));
  }, []);

  const reset = useCallback(() => {
    setState({
      step: 'select',
      selectedPlatform: null,
      configuration: {},
      testResult: null,
      error: null,
    });
  }, []);

  return {
    state,
    selectPlatform,
    setStep,
    configure,
    startOAuth,
    testConnection,
    setTestResult,
    setError,
    reset,
  };
}

// =============================================================================
// useSourceMutations — Mutation operations
// =============================================================================

interface UseSourceMutationsResult {
  disconnecting: boolean;
  testing: boolean;
  configuring: boolean;
  error: string | null;
  disconnect: (sourceId: string) => Promise<void>;
  testConnection: (sourceId: string) => Promise<ConnectionTestResult>;
  updateSyncConfig: (sourceId: string, config: UpdateSyncConfigRequest) => Promise<void>;
  clearError: () => void;
}

/**
 * Hook for source mutation operations.
 *
 * Provides methods to disconnect, test, and configure data sources.
 * Follows useDashboardMutations pattern with loading states and error handling.
 *
 * Usage:
 * ```tsx
 * const { disconnecting, disconnect, testConnection } = useSourceMutations();
 *
 * const handleDisconnect = async (sourceId: string) => {
 *   await disconnect(sourceId);
 *   // Refresh source list
 * };
 * ```
 */
export function useSourceMutations(): UseSourceMutationsResult {
  const [disconnecting, setDisconnecting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [configuring, setConfiguring] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  const disconnect = useCallback(async (sourceId: string): Promise<void> => {
    try {
      setDisconnecting(true);
      setError(null);
      await apiDisconnectSource(sourceId);
    } catch (err) {
      console.error('Failed to disconnect source:', err);
      setError(getErrorMessage(err, 'Failed to disconnect source'));
      throw err;
    } finally {
      setDisconnecting(false);
    }
  }, []);

  const testConnection = useCallback(async (sourceId: string): Promise<ConnectionTestResult> => {
    try {
      setTesting(true);
      setError(null);
      const result = await apiTestConnection(sourceId);
      return result;
    } catch (err) {
      console.error('Failed to test connection:', err);
      setError(getErrorMessage(err, 'Connection test failed'));
      throw err;
    } finally {
      setTesting(false);
    }
  }, []);

  const updateSyncConfig = useCallback(
    async (sourceId: string, config: UpdateSyncConfigRequest): Promise<void> => {
      try {
        setConfiguring(true);
        setError(null);
        await apiUpdateSyncConfig(sourceId, config);
      } catch (err) {
        console.error('Failed to update sync config:', err);
        setError(getErrorMessage(err, 'Failed to update sync configuration'));
        throw err;
      } finally {
        setConfiguring(false);
      }
    },
    []
  );

  return {
    disconnecting,
    testing,
    configuring,
    error,
    disconnect,
    testConnection,
    updateSyncConfig,
    clearError,
  };
}
