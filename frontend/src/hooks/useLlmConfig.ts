import { useCallback, useEffect, useRef, useState } from 'react';
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

  const isMountedRef = useRef(true);

  useEffect(() => () => {
    isMountedRef.current = false;
  }, []);

  const refetch = useCallback(async () => {
    try {
      if (isMountedRef.current) {
        setIsLoading(true);
        setError(null);
      }
      const nextConfig = await getAIConfiguration();
      if (isMountedRef.current) {
        setConfig(nextConfig);
      }
    } catch (err) {
      if (isMountedRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to load AI configuration');
      }
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false);
      }
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
  const [error, setError] = useState<string | null>(null);
  const isMountedRef = useRef(true);

  useEffect(() => () => {
    isMountedRef.current = false;
  }, []);

  const refetch = useCallback(async () => {
    if (isMountedRef.current) {
      setIsLoading(true);
      setError(null);
    }
    try {
      const nextStats = await getAIUsageStats();
      if (isMountedRef.current) {
        setStats(nextStats);
      }
    } catch (err) {
      if (isMountedRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to load AI usage stats');
      }
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { stats, isLoading, error, refetch };
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
