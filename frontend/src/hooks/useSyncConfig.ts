import {
  getSyncConfiguration,
  updateDataProcessing,
  updateErrorHandling,
  updateStorageConfig,
  updateSyncSchedule,
} from '../services/syncConfigApi';
import type {
  DataProcessingConfig,
  ErrorHandlingConfig,
  StorageConfig,
  SyncScheduleConfig,
} from '../types/settingsTypes';
import { useMutationLite, useQueryClientLite, useQueryLite } from './queryClientLite';

const SYNC_QUERY_KEY = ['settings', 'sync', 'config'] as const;

export function useSyncConfig() {
  const query = useQueryLite({ queryKey: SYNC_QUERY_KEY, queryFn: getSyncConfiguration });

  return {
    config: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refetch: query.refetch,
  };
}

export function useUpdateSyncSchedule() {
  const queryClient = useQueryClientLite();

  return useMutationLite({
    mutationFn: (schedule: SyncScheduleConfig) => updateSyncSchedule(schedule),
    onSuccess: () => {
      queryClient.invalidateQueries(SYNC_QUERY_KEY);
    },
  });
}

export function useUpdateDataProcessing() {
  const queryClient = useQueryClientLite();

  return useMutationLite({
    mutationFn: (config: DataProcessingConfig) => updateDataProcessing(config),
    onSuccess: () => {
      queryClient.invalidateQueries(SYNC_QUERY_KEY);
    },
  });
}

export function useUpdateStorageConfig() {
  const queryClient = useQueryClientLite();

  return useMutationLite({
    mutationFn: (config: Partial<StorageConfig>) => updateStorageConfig(config),
    onSuccess: () => {
      queryClient.invalidateQueries(SYNC_QUERY_KEY);
    },
  });
}

export function useUpdateErrorHandling() {
  const queryClient = useQueryClientLite();

  return useMutationLite({
    mutationFn: (config: ErrorHandlingConfig) => updateErrorHandling(config),
    onSuccess: () => {
      queryClient.invalidateQueries(SYNC_QUERY_KEY);
    },
  });
}

export { SYNC_QUERY_KEY };
