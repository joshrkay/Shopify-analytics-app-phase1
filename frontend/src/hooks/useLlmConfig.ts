import {
  getAIConfiguration,
  getAIUsageStats,
  setApiKey,
  testConnection,
  updateFeatureFlags,
} from '../services/llmConfigApi';
import type { AIFeatureFlags, AIProvider } from '../types/settingsTypes';
import { useMutationLite, useQueryClientLite, useQueryLite } from './queryClientLite';

const LLM_QUERY_KEYS = {
  config: ['settings', 'ai', 'config'] as const,
  usage: ['settings', 'ai', 'usage'] as const,
};

export function useLlmConfig() {
  const query = useQueryLite({
    queryKey: LLM_QUERY_KEYS.config,
    queryFn: getAIConfiguration,
  });

  return {
    config: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refetch: query.refetch,
  };
}

export function useAIUsageStats() {
  const query = useQueryLite({
    queryKey: LLM_QUERY_KEYS.usage,
    queryFn: getAIUsageStats,
  });

  return {
    stats: query.data ?? null,
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refetch: query.refetch,
  };
}

export function useSetApiKey() {
  const queryClient = useQueryClientLite();

  return useMutationLite({
    mutationFn: ({ provider, key }: { provider: AIProvider; key: string }) => setApiKey(provider, key),
    onSuccess: () => {
      queryClient.invalidateQueries(LLM_QUERY_KEYS.config);
    },
  });
}

export function useTestConnection() {
  return useMutationLite({
    mutationFn: () => testConnection(),
  });
}

export function useUpdateFeatureFlags() {
  const queryClient = useQueryClientLite();

  return useMutationLite({
    mutationFn: (flags: Partial<AIFeatureFlags>) => updateFeatureFlags(flags),
    onSuccess: () => {
      queryClient.invalidateQueries(LLM_QUERY_KEYS.config);
    },
  });
}

export { LLM_QUERY_KEYS };
