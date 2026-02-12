import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/apiUtils', () => ({
  API_BASE_URL: '',
  createHeadersAsync: vi.fn().mockResolvedValue({ Authorization: 'Bearer token' }),
  handleResponse: vi.fn(async (res: Response) => res.json()),
}));

import {
  getAIConfiguration,
  getAIUsageStats,
  setApiKey,
  testConnection,
  updateFeatureFlags,
} from '../services/llmConfigApi';

beforeEach(() => {
  vi.clearAllMocks();
  global.fetch = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue({}) });
});

describe('llmConfigApi', () => {
  it('getAIConfiguration never returns raw key', async () => {
    const payload = { provider: 'openai', hasApiKey: true, connectionStatus: 'connected', enabledFeatures: {} };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue(payload) });
    const result = await getAIConfiguration();
    expect(result).not.toHaveProperty('apiKey');
  });

  it('setApiKey sends encrypted payload', async () => {
    await setApiKey('openai', 'secret');
    expect(global.fetch).toHaveBeenCalledWith('/api/llm-config/key', expect.objectContaining({ method: 'POST', body: JSON.stringify({ provider: 'openai', key: 'secret' }) }));
  });

  it('testConnection returns status', async () => {
    const payload = { status: 'success' };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue(payload) });
    await expect(testConnection()).resolves.toEqual(payload);
  });

  it('getAIUsageStats returns metric counts', async () => {
    const payload = { requestsThisMonth: 1, requestsLimit: 2, insightsGenerated: 3, recommendationsGenerated: 4, predictionsGenerated: 5 };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue(payload) });
    await expect(getAIUsageStats()).resolves.toEqual(payload);
  });

  it('updateFeatureFlags sends flag delta', async () => {
    await updateFeatureFlags({ predictions: true });
    expect(global.fetch).toHaveBeenCalledWith('/api/llm-config/features', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ predictions: true }) }));
  });
});
