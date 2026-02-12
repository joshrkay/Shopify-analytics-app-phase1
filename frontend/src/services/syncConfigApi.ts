import { API_BASE_URL, createHeadersAsync, handleResponse } from './apiUtils';
import type {
  DataProcessingConfig,
  ErrorHandlingConfig,
  StorageConfig,
  SyncConfiguration,
  SyncScheduleConfig,
} from '../types/settingsTypes';

export async function getSyncConfiguration(): Promise<SyncConfiguration> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/sync/config`, { method: 'GET', headers });
  return handleResponse<SyncConfiguration>(response);
}

export async function updateSyncSchedule(schedule: SyncScheduleConfig): Promise<SyncConfiguration> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/sync/config/schedule`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(schedule),
  });
  return handleResponse<SyncConfiguration>(response);
}

export async function updateDataProcessing(config: DataProcessingConfig): Promise<SyncConfiguration> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/sync/config/processing`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(config),
  });
  return handleResponse<SyncConfiguration>(response);
}

export async function updateStorageConfig(config: Partial<StorageConfig>): Promise<SyncConfiguration> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/sync/config/storage`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(config),
  });
  return handleResponse<SyncConfiguration>(response);
}

export async function updateErrorHandling(config: ErrorHandlingConfig): Promise<SyncConfiguration> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/sync/config/error-handling`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(config),
  });
  return handleResponse<SyncConfiguration>(response);
}

export async function downloadBackup(): Promise<Blob> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/sync/backup/download`, {
    method: 'GET',
    headers,
  });

  if (!response.ok) {
    await handleResponse<{ detail?: string }>(response);
  }

  return response.blob();
}

export async function restoreFromBackup(file: File): Promise<{ success: boolean }> {
  const authHeaders = await createHeadersAsync();
  const formData = new FormData();
  formData.append('file', file);

  const authorization = authHeaders instanceof Headers
    ? authHeaders.get('Authorization')
    : Array.isArray(authHeaders)
      ? authHeaders.find(([key]) => key.toLowerCase() === 'authorization')?.[1]
      : authHeaders.Authorization ?? authHeaders.authorization;

  const headers: HeadersInit = authorization ? { Authorization: authorization } : {};
  const response = await fetch(`${API_BASE_URL}/api/sync/backup/restore`, {
    method: 'POST',
    headers,
    body: formData,
  });
  return handleResponse<{ success: boolean }>(response);
}
