import { useCallback, useEffect, useState } from 'react';
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
  SyncConfiguration,
  SyncScheduleConfig,
} from '../types/settingsTypes';

export function useSyncConfig() {
  const [config, setConfig] = useState<SyncConfiguration | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      setConfig(await getSyncConfiguration());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load sync configuration');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { config, isLoading, error, refetch };
}

export function useUpdateSyncSchedule() {
  return useCallback((schedule: SyncScheduleConfig) => updateSyncSchedule(schedule), []);
}

export function useUpdateDataProcessing() {
  return useCallback((config: DataProcessingConfig) => updateDataProcessing(config), []);
}

export function useUpdateStorageConfig() {
  return useCallback((config: Partial<StorageConfig>) => updateStorageConfig(config), []);
}

export function useUpdateErrorHandling() {
  return useCallback((config: ErrorHandlingConfig) => updateErrorHandling(config), []);
}
