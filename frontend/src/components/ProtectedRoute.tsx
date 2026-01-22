/**
 * Protected Route Component
 *
 * Protects routes behind embedded authentication.
 * - If not embedded: allows access (for admin routes)
 * - If embedded but no token: redirects to OAuth install
 * - If embedded with token: allows access
 */

import { ReactNode, useEffect, useState } from 'react';
import { useAppBridge } from '@shopify/app-bridge-react';
import { Spinner, Page } from '@shopify/polaris';
import { useShopifySession } from '../hooks/useShopifySession';
import { isEmbedded, getShopifyHost } from '../lib/shopifyAppBridge';
import { redirectToOAuthInstall } from '../lib/redirects';

interface ProtectedRouteProps {
  children: ReactNode;
  /** Whether this route requires embedded context */
  requireEmbedded?: boolean;
  /** Shop domain for OAuth redirect (if not provided, extracted from host) */
  shopDomain?: string;
}

/**
 * ProtectedRoute component that ensures proper authentication for embedded apps.
 *
 * @param children - The route content to render when authenticated
 * @param requireEmbedded - If true, only allow access when embedded (default: false)
 * @param shopDomain - Shop domain for OAuth redirect (optional)
 */
export function ProtectedRoute({
  children,
  requireEmbedded = false,
  shopDomain,
}: ProtectedRouteProps) {
  const app = useAppBridge();
  const { getToken, isLoading: tokenLoading, error: tokenError, isEmbedded: embedded } = useShopifySession();
  const [isVerifying, setIsVerifying] = useState(true);
  const [hasToken, setHasToken] = useState(false);

  const embeddedContext = isEmbedded();

  useEffect(() => {
    const verifyAuth = async () => {
      // If not embedded and not required, allow access
      if (!embeddedContext && !requireEmbedded) {
        setIsVerifying(false);
        setHasToken(true);
        return;
      }

      // If embedded is required but not present, show error
      if (requireEmbedded && !embeddedContext) {
        setIsVerifying(false);
        setHasToken(false);
        return;
      }

      // If embedded, verify we can get a token
      if (embeddedContext) {
        try {
          const token = await getToken();
          if (token) {
            setHasToken(true);
          } else {
            setHasToken(false);
            // Redirect to OAuth install if no token
            const shop = shopDomain || extractShopFromHost();
            if (shop) {
              redirectToOAuthInstall(shop);
            }
          }
        } catch (err) {
          console.error('Token verification failed:', err);
          setHasToken(false);
          const shop = shopDomain || extractShopFromHost();
          if (shop) {
            redirectToOAuthInstall(shop);
          }
        } finally {
          setIsVerifying(false);
        }
      } else {
        setIsVerifying(false);
        setHasToken(true);
      }
    };

    verifyAuth();
  }, [embeddedContext, requireEmbedded, getToken, shopDomain]);

  /**
   * Extract shop domain from host parameter.
   * This is a fallback if shopDomain prop is not provided.
   */
  function extractShopFromHost(): string | null {
    const host = getShopifyHost();
    if (!host) {
      return null;
    }

    // Try to extract shop from host parameter
    // In practice, the shop domain might be available from the session token
    // For now, return null and let the OAuth flow handle it
    return null;
  }

  // Show loading state while verifying
  if (isVerifying || tokenLoading) {
    return (
      <Page>
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '400px' }}>
          <Spinner size="large" />
        </div>
      </Page>
    );
  }

  // Show error state if token verification failed
  if (tokenError) {
    return (
      <Page>
        <div style={{ padding: '20px' }}>
          <p>Authentication error: {tokenError.message}</p>
          <p>Redirecting to installation...</p>
        </div>
      </Page>
    );
  }

  // If embedded is required but not present, show error
  if (requireEmbedded && !embeddedContext) {
    return (
      <Page>
        <div style={{ padding: '20px' }}>
          <p>This route requires the app to be embedded in Shopify Admin.</p>
        </div>
      </Page>
    );
  }

  // If no token in embedded context, redirect (handled in useEffect)
  if (embeddedContext && !hasToken) {
    return (
      <Page>
        <div style={{ padding: '20px' }}>
          <p>Redirecting to installation...</p>
          <Spinner size="small" />
        </div>
      </Page>
    );
  }

  // Render protected content
  return <>{children}</>;
}
