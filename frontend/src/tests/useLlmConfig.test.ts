import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/llmConfigApi', () => ({
  getAIConfiguration: vi.fn(),
  getAIUsageStats: vi.fn(),
  setApiKey: vi.fn(),
  testConnection: vi.fn(),
  updateFeatureFlags: vi.fn(),
}));

import { useAIUsageStats } from '../hooks/useLlmConfig';
import { getAIUsageStats } from '../services/llmConfigApi';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useAIUsageStats edge cases', () => {
  it('returns error state when usage stats request fails', async () => {
    vi.mocked(getAIUsageStats).mockRejectedValue(new Error('usage failed'));

    const { result } = renderHook(() => useAIUsageStats());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toContain('usage failed');
  });
});
