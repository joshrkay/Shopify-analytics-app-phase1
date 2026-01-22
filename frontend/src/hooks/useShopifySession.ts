/**
 * Shopify Session Hook
 *
 * Manages Shopify session token retrieval, caching, and automatic refresh.
 * Session tokens are used for authentication in embedded apps.
 *
 * Features:
 * - Automatic token refresh before expiry (60-second buffer)
 * - Background refresh to prevent expired tokens
 * - Error handling for token failures
 * - Integration with App Bridge lifecycle
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import { useAppBridge } from '@shopify/app-bridge-react';
import { getSessionToken } from '@shopify/app-bridge-utils';
import { isEmbedded } from '../lib/shopifyAppBridge';

interface SessionTokenCache {
  token: string;
  expiresAt: number;
}

// Cache with 60-second buffer before expiry to ensure we refresh in time
const CACHE_BUFFER_MS = 60 * 1000;

// Default token expiry (50 minutes, conservative estimate)
// Shopify tokens are typically valid for 1 hour
const DEFAULT_TOKEN_EXPIRY_MS = 50 * 60 * 1000;

export interface UseShopifySessionReturn {
  /** Get the current session token (cached or fresh) */
  getToken: () => Promise<string | null>;
  /** Whether a token request is currently in progress */
  isLoading: boolean;
  /** Any error that occurred during token retrieval */
  error: Error | null;
  /** Whether the app is embedded (has App Bridge context) */
  isEmbedded: boolean;
}

/**
 * Hook for managing Shopify session tokens in embedded apps.
 *
 * Automatically refreshes tokens before expiry to prevent authentication failures.
 * Only works when the app is embedded in Shopify Admin (has App Bridge context).
 *
 * @returns Object with getToken function, loading state, error, and embedded status
 */
export function useShopifySession(): UseShopifySessionReturn {
  const app = useAppBridge();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [cache, setCache] = useState<SessionTokenCache | null>(null);
  const refreshTimerRef = useRef<NodeJS.Timeout | null>(null);
  const embedded = isEmbedded();

  /**
   * Get session token, using cache if valid, otherwise fetching fresh token.
   */
  const getToken = useCallback(async (): Promise<string | null> => {
    // If app is not available (not embedded), return null
    if (!app || !embedded) {
      return null;
    }

    // Check if we have a valid cached token
    if (cache && cache.expiresAt > Date.now() + CACHE_BUFFER_MS) {
      return cache.token;
    }

    setIsLoading(true);
    setError(null);

    try {
      // Get session token from App Bridge
      const token = await getSessionToken(app);

      if (!token) {
        return null;
      }

      // Calculate expiry time (tokens are typically valid for 1 hour)
      // We use a conservative 50 minutes to ensure we refresh in time
      const expiresAt = Date.now() + DEFAULT_TOKEN_EXPIRY_MS;

      // Cache the token
      setCache({ token, expiresAt });

      // Schedule automatic refresh before expiry
      scheduleTokenRefresh(expiresAt, app);

      return token;
    } catch (err) {
      const error = err instanceof Error ? err : new Error('Failed to get session token');
      setError(error);
      console.error('Session token error:', error);
      return null;
    } finally {
      setIsLoading(false);
    }
  }, [app, cache, embedded]);

  /**
   * Schedule automatic token refresh before expiry.
   */
  const scheduleTokenRefresh = useCallback((expiresAt: number, appInstance: typeof app) => {
    // Clear any existing timer
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
    }

    // Calculate time until refresh (refresh 60 seconds before expiry)
    const timeUntilRefresh = expiresAt - Date.now() - CACHE_BUFFER_MS;

    if (timeUntilRefresh > 0 && appInstance) {
      refreshTimerRef.current = setTimeout(async () => {
        // Trigger refresh by clearing cache
        setCache(null);
        // Get fresh token
        try {
          const token = await getSessionToken(appInstance);
          if (token) {
            const newExpiresAt = Date.now() + DEFAULT_TOKEN_EXPIRY_MS;
            setCache({ token, expiresAt: newExpiresAt });
            scheduleTokenRefresh(newExpiresAt, appInstance);
          }
        } catch (err) {
          console.error('Automatic token refresh failed:', err);
        }
      }, timeUntilRefresh);
    }
  }, []);

  /**
   * Effect to automatically refresh token when it's about to expire.
   */
  useEffect(() => {
    if (!app || !embedded || !cache) {
      return;
    }

    // Check if token needs refresh
    const timeUntilExpiry = cache.expiresAt - Date.now();
    const needsRefresh = timeUntilExpiry <= CACHE_BUFFER_MS;

    if (needsRefresh) {
      // Token is about to expire, refresh it
      getToken();
    } else {
      // Schedule refresh before expiry
      scheduleTokenRefresh(cache.expiresAt, app);
    }

    // Cleanup timer on unmount or when dependencies change
    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
    };
  }, [app, embedded, cache, getToken, scheduleTokenRefresh]);

  /**
   * Clear cache when app context changes (e.g., navigation, shop change).
   */
  useEffect(() => {
    setCache(null);
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
  }, [app]);

  /**
   * Cleanup on unmount.
   */
  useEffect(() => {
    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
    };
  }, []);

  return { getToken, isLoading, error, isEmbedded: embedded };
}
