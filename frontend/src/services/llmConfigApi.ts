import { API_BASE_URL, createHeadersAsync, handleResponse } from './apiUtils';
import type { AIConfiguration, AIFeatureFlags, AIProvider, AIUsageStats } from '../types/settingsTypes';

export async function getAIConfiguration(): Promise<AIConfiguration> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/llm/config`, { method: 'GET', headers });
  return handleResponse<AIConfiguration>(response);
}

export async function updateAIProvider(provider: AIProvider): Promise<AIConfiguration> {
  // Backend route not yet implemented — update org config instead
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/llm/config`, {
    method: 'PUT',
    headers,
    body: JSON.stringify({ default_provider: provider }),
  });
  return handleResponse<AIConfiguration>(response);
}

export async function setApiKey(_provider: AIProvider, _key: string): Promise<{ success: boolean }> {
  // Backend route not yet implemented
  console.warn('setApiKey: backend endpoint not yet implemented');
  return { success: false };
}

export async function testConnection(): Promise<{ status: 'success' | 'error'; message?: string }> {
  // Backend route not yet implemented
  console.warn('testConnection: backend endpoint not yet implemented');
  return { status: 'error', message: 'Feature not yet available' };
}

export async function getAIUsageStats(): Promise<AIUsageStats> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/llm/usage/stats`, { method: 'GET', headers });
  return handleResponse<AIUsageStats>(response);
}

export async function updateFeatureFlags(_flags: Partial<AIFeatureFlags>): Promise<AIConfiguration> {
  // Backend route not yet implemented — return current config
  console.warn('updateFeatureFlags: backend endpoint not yet implemented');
  return getAIConfiguration();
}
