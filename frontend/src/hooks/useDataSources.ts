/**
 * useDataSources Hooks
 *
 * QueryClientLite-based hooks for data source management:
 * - useDataSources: Connection list with 30s polling
 * - useDataSourceCatalog: Platform catalog (static)
 * - useConnection: Single connection detail
 * - useSyncProgress: Sync progress with 3s polling
 * - useOAuthFlow: OAuth initiation mutation
 * - useDisconnectSource: Disconnect mutation with cache invalidation
 * - useSyncConfigMutation: Sync config mutation
 * - useGlobalSyncSettings: Global settings query + mutation
 *
 * Follows useSyncConfig.ts pattern (QueryClientLite + invalidation).
 *
 * Phase 3 — Subphase 3.2: Data Sources Hooks
 */

import { useCallback, useEffect, useRef } from 'react';
import { useQueryLite, useMutationLite, useQueryClientLite } from './queryClientLite';
import {
  getConnections,
  getAvailableSources,
  getConnection as apiGetConnection,
  getSyncProgress as apiGetSyncProgress,
  initiateOAuth,
  disconnectSource as apiDisconnectSource,
  updateSyncConfig as apiUpdateSyncConfig,
  getGlobalSyncSettings as apiGetGlobalSyncSettings,
  updateGlobalSyncSettings as apiUpdateGlobalSyncSettings,
} from '../services/dataSourcesApi';
import type { Source, SourcePlatform } from '../types/sources';
import type {
  DataSourceDefinition,
  DataSourceConnection,
  SyncProgress,
  GlobalSyncSettings,
  UpdateSyncConfigRequest,
} from '../types/sourceConnection';

// =============================================================================
// Query Keys
// =============================================================================

const SOURCES_KEY = ['data-sources'] as const;
const CATALOG_KEY = ['data-source-catalog'] as const;
const CONNECTION_KEY = (id: string) => ['data-source-connection', id] as const;
const SYNC_PROGRESS_KEY = (id: string) => ['sync-progress', id] as const;
const GLOBAL_SETTINGS_KEY = ['global-sync-settings'] as const;

export { SOURCES_KEY, CATALOG_KEY, GLOBAL_SETTINGS_KEY };

// =============================================================================
// useDataSources — Connection list with 30s polling
// =============================================================================

interface UseDataSourcesResult {
  /** @deprecated Use `sources` instead */
  connections: Source[];
  sources: Source[];
  isLoading: boolean;
  error: unknown;
  hasConnectedSources: boolean;
  refetch: () => Promise<Source[]>;
}

export function useDataSources(): UseDataSourcesResult {
  const query = useQueryLite<Source[]>({
    queryKey: SOURCES_KEY,
    queryFn: getConnections,
  });

  const refetchRef = useRef(query.refetch);
  refetchRef.current = query.refetch;

  // 30s polling interval
  useEffect(() => {
    const interval = setInterval(() => {
      refetchRef.current().catch(() => {});
    }, 30_000);
    return () => clearInterval(interval);
  }, []);

  const sources = query.data ?? [];

  return {
    connections: sources,
    sources,
    isLoading: query.isLoading,
    error: query.error,
    hasConnectedSources: sources.length > 0,
    refetch: query.refetch,
  };
}

// =============================================================================
// useDataSourceCatalog — Platform catalog (static)
// =============================================================================

interface UseDataSourceCatalogResult {
  catalog: DataSourceDefinition[];
  isLoading: boolean;
  error: unknown;
  refetch: () => Promise<DataSourceDefinition[]>;
}

export function useDataSourceCatalog(): UseDataSourceCatalogResult {
  const query = useQueryLite<DataSourceDefinition[]>({
    queryKey: CATALOG_KEY,
    queryFn: getAvailableSources,
  });

  return {
    catalog: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}

// =============================================================================
// useConnection — Single connection detail
// =============================================================================

interface UseConnectionResult {
  connection: DataSourceConnection | null;
  isLoading: boolean;
  error: unknown;
  refetch: () => Promise<DataSourceConnection>;
}

export function useConnection(connectionId: string): UseConnectionResult {
  const queryFn = useCallback(() => apiGetConnection(connectionId), [connectionId]);
  const query = useQueryLite<DataSourceConnection>({
    queryKey: CONNECTION_KEY(connectionId),
    queryFn,
  });

  return {
    connection: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}

// =============================================================================
// useSyncProgress — 3s polling when enabled, stops when not running
// =============================================================================

interface UseSyncProgressResult {
  progress: SyncProgress | null;
  isLoading: boolean;
  error: unknown;
}

export function useSyncProgress(connectionId: string, enabled: boolean): UseSyncProgressResult {
  const queryFn = useCallback(() => apiGetSyncProgress(connectionId), [connectionId]);
  const query = useQueryLite<SyncProgress>({
    queryKey: SYNC_PROGRESS_KEY(connectionId),
    queryFn,
  });

  const refetchRef = useRef(query.refetch);
  refetchRef.current = query.refetch;

  const statusRef = useRef(query.data?.status);
  statusRef.current = query.data?.status;

  // 3s polling when enabled and status is still running
  useEffect(() => {
    if (!enabled) return;

    const interval = setInterval(() => {
      // Stop polling if sync is no longer running
      if (statusRef.current && statusRef.current !== 'running') {
        clearInterval(interval);
        return;
      }
      refetchRef.current().catch(() => {});
    }, 3_000);

    return () => clearInterval(interval);
  }, [enabled]);

  return {
    progress: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error,
  };
}

// =============================================================================
// useOAuthFlow — OAuth initiation mutation
// =============================================================================

export function useOAuthFlow() {
  return useMutationLite({
    mutationFn: (platform: SourcePlatform) => initiateOAuth(platform),
  });
}

// =============================================================================
// useDisconnectSource — Disconnect with cache invalidation
// =============================================================================

export function useDisconnectSource() {
  const queryClient = useQueryClientLite();

  return useMutationLite({
    mutationFn: (sourceId: string) => apiDisconnectSource(sourceId),
    onSuccess: () => {
      queryClient.invalidateQueries(SOURCES_KEY);
    },
  });
}

// =============================================================================
// useSyncConfigMutation — Update sync config with cache invalidation
// =============================================================================

interface SyncConfigMutationParams {
  sourceId: string;
  config: UpdateSyncConfigRequest;
}

export function useSyncConfigMutation() {
  const queryClient = useQueryClientLite();

  return useMutationLite({
    mutationFn: ({ sourceId, config }: SyncConfigMutationParams) =>
      apiUpdateSyncConfig(sourceId, config),
    onSuccess: () => {
      queryClient.invalidateQueries(SOURCES_KEY);
    },
  });
}

// =============================================================================
// useGlobalSyncSettings — Query + mutation
// =============================================================================

interface UseGlobalSyncSettingsResult {
  settings: GlobalSyncSettings | null;
  isLoading: boolean;
  error: unknown;
  updateSettings: (settings: Partial<GlobalSyncSettings>) => Promise<GlobalSyncSettings>;
  isSaving: boolean;
}

export function useGlobalSyncSettings(): UseGlobalSyncSettingsResult {
  const queryClient = useQueryClientLite();

  const query = useQueryLite<GlobalSyncSettings>({
    queryKey: GLOBAL_SETTINGS_KEY,
    queryFn: apiGetGlobalSyncSettings,
  });

  const mutation = useMutationLite({
    mutationFn: (settings: Partial<GlobalSyncSettings>) =>
      apiUpdateGlobalSyncSettings(settings),
    onSuccess: () => {
      queryClient.invalidateQueries(GLOBAL_SETTINGS_KEY);
    },
  });

  return {
    settings: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error,
    updateSettings: mutation.mutateAsync,
    isSaving: mutation.isPending,
  };
}
