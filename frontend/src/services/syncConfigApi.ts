import type {
  DataProcessingConfig,
  ErrorHandlingConfig,
  StorageConfig,
  SyncConfiguration,
  SyncScheduleConfig,
} from '../types/settingsTypes';

// All /api/sync/config/* endpoints have no backend implementation.
// Backend sync.py only provides /api/sync/trigger/{id}, /state/{id}, /failed.
// Return sensible defaults to prevent the Settings page from crashing.
const NOT_IMPLEMENTED_MSG = 'Sync configuration: backend endpoints not yet implemented';

export async function getSyncConfiguration(): Promise<SyncConfiguration> {
  console.warn(NOT_IMPLEMENTED_MSG);
  return {
    schedule: {} as SyncScheduleConfig,
    dataProcessing: {} as DataProcessingConfig,
    storage: {} as StorageConfig,
    errorHandling: {} as ErrorHandlingConfig,
  } as SyncConfiguration;
}

export async function updateSyncSchedule(_schedule: SyncScheduleConfig): Promise<SyncConfiguration> {
  console.warn(NOT_IMPLEMENTED_MSG);
  return getSyncConfiguration();
}

export async function updateDataProcessing(_config: DataProcessingConfig): Promise<SyncConfiguration> {
  console.warn(NOT_IMPLEMENTED_MSG);
  return getSyncConfiguration();
}

export async function updateStorageConfig(_config: Partial<StorageConfig>): Promise<SyncConfiguration> {
  console.warn(NOT_IMPLEMENTED_MSG);
  return getSyncConfiguration();
}

export async function updateErrorHandling(_config: ErrorHandlingConfig): Promise<SyncConfiguration> {
  console.warn(NOT_IMPLEMENTED_MSG);
  return getSyncConfiguration();
}

export async function downloadBackup(): Promise<Blob> {
  console.warn(NOT_IMPLEMENTED_MSG);
  throw new Error('Backup download is not yet available');
}

export async function restoreFromBackup(_file: File): Promise<{ success: boolean }> {
  console.warn(NOT_IMPLEMENTED_MSG);
  throw new Error('Backup restore is not yet available');
}
