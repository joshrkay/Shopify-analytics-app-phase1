/**
 * Clerk Token Hook
 *
 * Sets up the Clerk token provider for API utilities.
 * This hook should be called once at the app root level.
 *
 * Features:
 * - Syncs Clerk token to API utilities
 * - Caches token in localStorage for offline/fallback use
 * - Clears token on sign out
 */

import { useEffect, useCallback } from 'react';
import { useAuth } from '@clerk/clerk-react';
import { setTokenProvider, setAuthToken, clearAuthToken } from '../services/apiUtils';

/**
 * Hook to set up Clerk token integration with API utilities.
 *
 * Call this once in a component that's inside ClerkProvider and SignedIn.
 *
 * @example
 * function AuthenticatedApp() {
 *   useClerkToken();
 *   return <YourApp />;
 * }
 */
export function useClerkToken(): void {
  const { getToken, isSignedIn } = useAuth();

  // Create a stable token provider function
  const tokenProvider = useCallback(async () => {
    if (!isSignedIn) return null;
    try {
      const token = await getToken();
      if (token) {
        // Cache in localStorage for backwards compatibility
        setAuthToken(token);
      }
      return token;
    } catch (error) {
      console.error('Failed to get Clerk token:', error);
      return null;
    }
  }, [getToken, isSignedIn]);

  // Set up the token provider on mount and when auth state changes
  useEffect(() => {
    if (isSignedIn) {
      setTokenProvider(tokenProvider);
      // Fetch initial token
      tokenProvider();
    } else {
      // Clear token on sign out
      setTokenProvider(null);
      clearAuthToken();
    }
  }, [isSignedIn, tokenProvider]);
}

/**
 * Hook to get the current Clerk session token.
 *
 * @returns The current JWT token or null if not signed in
 */
export function useSessionToken(): {
  getToken: () => Promise<string | null>;
  isLoading: boolean;
} {
  const { getToken, isLoaded } = useAuth();

  const wrappedGetToken = useCallback(async () => {
    try {
      return await getToken();
    } catch (error) {
      console.error('Failed to get session token:', error);
      return null;
    }
  }, [getToken]);

  return {
    getToken: wrappedGetToken,
    isLoading: !isLoaded,
  };
}

export default useClerkToken;
