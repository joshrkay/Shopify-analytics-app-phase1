/**
 * useEntitlements Hook
 *
 * Custom hook to fetch and manage entitlements state.
 * Fetches /api/billing/entitlements on load as per requirements.
 */

import { useState, useEffect } from 'react';
import { fetchEntitlements, type EntitlementsResponse } from '../services/entitlementsApi';

interface UseEntitlementsResult {
  entitlements: EntitlementsResponse | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

/**
 * Hook to fetch entitlements on load.
 * 
 * Usage:
 * ```tsx
 * const { entitlements, loading, error } = useEntitlements();
 * 
 * if (loading) return <Spinner />;
 * if (error) return <ErrorBanner />;
 * 
 * return <FeatureGate feature="premium" entitlements={entitlements}>...</FeatureGate>;
 * ```
 */
export function useEntitlements(): UseEntitlementsResult {
  const [entitlements, setEntitlements] = useState<EntitlementsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadEntitlements = async () => {
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
  };

  useEffect(() => {
    loadEntitlements();
  }, []);

  return {
    entitlements,
    loading,
    error,
    refetch: loadEntitlements,
  };
}
