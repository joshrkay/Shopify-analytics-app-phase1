/**
 * Shopify API Provider
 *
 * Connects session token hook to API service.
 * This enables automatic session token authentication for embedded app API calls.
 */

import { ReactNode, useEffect } from 'react';
import { useShopifySession } from '../hooks/useShopifySession';
import { setSessionTokenGetter } from '../services/plansApi';

interface ShopifyApiProviderProps {
  children: ReactNode;
}

export function ShopifyApiProvider({ children }: ShopifyApiProviderProps) {
  const { getToken } = useShopifySession();

  useEffect(() => {
    // Register session token getter with API service
    setSessionTokenGetter(getToken);

    // Cleanup on unmount
    return () => {
      setSessionTokenGetter(() => Promise.resolve(null));
    };
  }, [getToken]);

  // This provider doesn't render anything, just sets up the connection
  return <>{children}</>;
}
