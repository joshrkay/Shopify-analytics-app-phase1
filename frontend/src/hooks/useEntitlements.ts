/**
 * useEntitlements Hook
 *
 * Custom hook to fetch and manage entitlements state.
 * Fetches /api/billing/entitlements on load as per requirements.
 *
 * Accepts isTokenReady to avoid firing the API call before
 * the Clerk token is cached, which would result in a 401.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchEntitlements, type EntitlementsResponse } from '../services/entitlementsApi';
import { isBackendDown, isApiError } from '../services/apiUtils';

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
  const retryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadEntitlements = useCallback(async (retryCount = 0) => {
    // Skip if circuit breaker is open
    if (retryCount === 0 && isBackendDown()) {
      setLoading(false);
      setError('Backend unavailable — waiting for recovery');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const data = await fetchEntitlements();
      setEntitlements(data);
    } catch (err) {
      const is5xx = isApiError(err) && err.status >= 500;
      // Retry up to 2 times on server errors with exponential backoff
      if (is5xx && retryCount < 2) {
        const delay = Math.min(5000 * Math.pow(2, retryCount), 30000);
        retryTimeoutRef.current = setTimeout(() => loadEntitlements(retryCount + 1), delay);
        return;
      }
      if (retryCount === 0) {
        console.error('Failed to fetch entitlements:', err);
      }
      setError(err instanceof Error ? err.message : 'Failed to load entitlements');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isTokenReady) return;
    loadEntitlements();
    return () => {
      if (retryTimeoutRef.current) clearTimeout(retryTimeoutRef.current);
    };
  }, [isTokenReady, loadEntitlements]);

  return {
    entitlements,
    loading,
    error,
    refetch: loadEntitlements,
  };
}
