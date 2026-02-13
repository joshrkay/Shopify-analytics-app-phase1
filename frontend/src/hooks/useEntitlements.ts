/**
 * useEntitlements Hook
 *
 * Custom hook to fetch and manage entitlements state.
 * Fetches /api/billing/entitlements on load as per requirements.
 *
 * Accepts isTokenReady to avoid firing the API call before
 * the Clerk token is cached, which would result in a 401.
 */

import { useState, useEffect, useCallback } from 'react';
import { fetchEntitlements, type EntitlementsResponse } from '../services/entitlementsApi';

interface UseEntitlementsResult {
  entitlements: EntitlementsResponse | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

/**
 * Hook to fetch entitlements once the auth token is ready.
 *
 * @param isTokenReady - Pass `true` only after the Clerk token
 *   has been cached (from useClerkToken). Defaults to `true`
 *   for backwards compatibility.
 */
export function useEntitlements(isTokenReady = true): UseEntitlementsResult {
  const [entitlements, setEntitlements] = useState<EntitlementsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadEntitlements = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchEntitlements();
      setEntitlements(data);
    } catch (err) {
      console.error('Failed to fetch entitlements:', err);
      setError(err instanceof Error ? err.message : 'Failed to load entitlements');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isTokenReady) return;
    loadEntitlements();
  }, [isTokenReady, loadEntitlements]);

  return {
    entitlements,
    loading,
    error,
    refetch: loadEntitlements,
  };
}
