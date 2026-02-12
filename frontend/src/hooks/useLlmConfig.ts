import { useCallback, useEffect, useState } from 'react';
import {
  getAIConfiguration,
  getAIUsageStats,
  setApiKey,
  testConnection,
  updateFeatureFlags,
} from '../services/llmConfigApi';
import type { AIFeatureFlags, AIProvider, AIUsageStats, AIConfiguration } from '../types/settingsTypes';

export function useLlmConfig() {
  const [config, setConfig] = useState<AIConfiguration | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      setConfig(await getAIConfiguration());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load AI configuration');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { config, isLoading, error, refetch };
}

export function useAIUsageStats() {
  const [stats, setStats] = useState<AIUsageStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refetch = useCallback(async () => {
    setIsLoading(true);
    try {
      setStats(await getAIUsageStats());
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { stats, isLoading, refetch };
}

export function useSetApiKey() {
  return useCallback((provider: AIProvider, key: string) => setApiKey(provider, key), []);
}

export function useTestConnection() {
  return useCallback(() => testConnection(), []);
}

export function useUpdateFeatureFlags() {
  return useCallback((flags: Partial<AIFeatureFlags>) => updateFeatureFlags(flags), []);
}
