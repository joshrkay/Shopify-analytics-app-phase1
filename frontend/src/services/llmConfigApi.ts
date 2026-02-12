import { API_BASE_URL, createHeadersAsync, handleResponse } from './apiUtils';
import type { AIConfiguration, AIFeatureFlags, AIProvider, AIUsageStats } from '../types/settingsTypes';

export async function getAIConfiguration(): Promise<AIConfiguration> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/llm-config`, { method: 'GET', headers });
  return handleResponse<AIConfiguration>(response);
}

export async function updateAIProvider(provider: AIProvider): Promise<AIConfiguration> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/llm-config/provider`, {
    method: 'PUT',
    headers,
    body: JSON.stringify({ provider }),
  });
  return handleResponse<AIConfiguration>(response);
}

export async function setApiKey(provider: AIProvider, key: string): Promise<{ success: boolean }> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/llm-config/key`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ provider, key }),
  });
  return handleResponse<{ success: boolean }>(response);
}

export async function testConnection(): Promise<{ status: 'success' | 'error'; message?: string }> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/llm-config/test`, {
    method: 'POST',
    headers,
  });
  return handleResponse<{ status: 'success' | 'error'; message?: string }>(response);
}

export async function getAIUsageStats(): Promise<AIUsageStats> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/llm-config/usage`, { method: 'GET', headers });
  return handleResponse<AIUsageStats>(response);
}

export async function updateFeatureFlags(flags: Partial<AIFeatureFlags>): Promise<AIConfiguration> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/llm-config/features`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(flags),
  });
  return handleResponse<AIConfiguration>(response);
}
