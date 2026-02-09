/**
 * Shopify Admin Embedded Superset Dashboard
 *
 * Renders Superset dashboard inside Shopify Admin iframe.
 * Handles JWT auth and session refresh.
 *
 * Features:
 * - JWT-based authentication
 * - Silent token refresh before expiry
 * - Hides Superset navigation chrome
 * - Shopify Polaris-compatible styling
 * - Error handling with retry
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Card,
  SkeletonBodyText,
  Spinner,
  BlockStack,
  Text,
} from '@shopify/polaris';
import type { ShopifyEmbeddedSupersetProps, EmbedState } from '../types/embed';
import {
  generateEmbedToken,
  sendMessageToParent,
  addParentMessageListener,
} from '../services/embedApi';
import type { EmbedTokenResponse } from '../services/embedApi';
import { UnifiedTokenRefreshManager } from '../utils/tokenRefresh';
import { AnalyticsHealthBanner } from './AnalyticsHealthBanner';

import './ShopifyEmbeddedSuperset.css';

const DEFAULT_HEIGHT = '600px';
const RETRY_DELAY_MS = 3000;
const MAX_RETRIES = 3;

/**
 * ShopifyEmbeddedSuperset Component
 *
 * Embeds a Superset dashboard within Shopify Admin with proper
 * authentication and session management.
 */
export const ShopifyEmbeddedSuperset: React.FC<ShopifyEmbeddedSupersetProps> = ({
  dashboardId,
  tenantId,
  height = DEFAULT_HEIGHT,
  className = '',
  onLoad,
  onError,
  onTokenRefresh,
  showLoadingSkeleton = true,
  loadingComponent,
  errorComponent,
}) => {
  const [state, setState] = useState<EmbedState>({
    status: 'idle',
    token: null,
    dashboardUrl: null,
    error: null,
    expiresAt: null,
    refreshBefore: null,
  });

  const [isRetrying, setIsRetrying] = useState(false);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const refreshManagerRef = useRef<UnifiedTokenRefreshManager | null>(null);
  const retryCountRef = useRef(0);

  /**
   * Handle successful token generation/refresh.
   */
  const handleTokenSuccess = useCallback(
    (tokenResponse: EmbedTokenResponse) => {
      setState((prev) => ({
        ...prev,
        status: 'ready',
        token: tokenResponse.jwt_token,
        dashboardUrl: tokenResponse.dashboard_url,
        error: null,
        expiresAt: new Date(tokenResponse.expires_at),
        refreshBefore: new Date(tokenResponse.refresh_before),
      }));

      // Reset retry counter on success
      retryCountRef.current = 0;

      onTokenRefresh?.();
    },
    [onTokenRefresh]
  );

  /**
   * Handle token refresh error.
   */
  const handleRefreshError = useCallback(
    (error: Error) => {
      console.error('[EmbeddedSuperset] Token refresh failed:', error);

      // If refresh fails, try to re-fetch token
      if (retryCountRef.current < MAX_RETRIES) {
        retryCountRef.current++;
        console.log(
          `[EmbeddedSuperset] Retrying token fetch (attempt ${retryCountRef.current}/${MAX_RETRIES})`
        );
        setTimeout(() => fetchToken(), RETRY_DELAY_MS);
      } else {
        setState((prev) => ({
          ...prev,
          status: 'error',
          error: new Error('Session expired. Please refresh the page.'),
        }));
        onError?.(error);
      }
    },
    [onError]
  );

  /**
   * Fetch embed token from backend.
   */
  const fetchToken = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'loading', error: null }));

    try {
      const tokenResponse = await generateEmbedToken(dashboardId, 'shopify_embed');

      // Initialize refresh manager
      if (refreshManagerRef.current) {
        refreshManagerRef.current.stop();
      }
      refreshManagerRef.current = new UnifiedTokenRefreshManager({
        dashboardId,
        accessSurface: 'shopify_embed',
        onRefreshed: handleTokenSuccess,
        onError: handleRefreshError,
      });
      refreshManagerRef.current.start(tokenResponse);

      handleTokenSuccess(tokenResponse);
    } catch (error) {
      console.error('[EmbeddedSuperset] Failed to fetch token:', error);

      setState((prev) => ({
        ...prev,
        status: 'error',
        error: error as Error,
      }));

      onError?.(error as Error);
    }
  }, [dashboardId, handleTokenSuccess, handleRefreshError, onError]);

  /**
   * Handle iframe load event.
   */
  const handleIframeLoad = useCallback(() => {
    console.log('[EmbeddedSuperset] Dashboard iframe loaded');
    onLoad?.();

    // Notify parent frame (Shopify Admin) that dashboard is ready
    sendMessageToParent('DASHBOARD_LOADED', { dashboardId });
  }, [dashboardId, onLoad]);

  /**
   * Handle iframe error.
   */
  const handleIframeError = useCallback(() => {
    const error = new Error('Failed to load dashboard');
    console.error('[EmbeddedSuperset] Iframe error');

    setState((prev) => ({
      ...prev,
      status: 'error',
      error,
    }));

    onError?.(error);
  }, [onError]);

  /**
   * Handle messages from parent frame (Shopify Admin).
   */
  const handleParentMessage = useCallback(
    (event: MessageEvent) => {
      // Validate origin for security
      const allowedOrigins = [
        'https://admin.shopify.com',
        window.location.origin,
      ];

      if (!allowedOrigins.some((origin) => event.origin.includes(origin.replace('https://', '')))) {
        return;
      }

      const { type } = event.data || {};

      switch (type) {
        case 'REFRESH_TOKEN':
          console.log('[EmbeddedSuperset] Token refresh requested from parent');
          fetchToken();
          break;

        case 'RELOAD_DASHBOARD':
          console.log('[EmbeddedSuperset] Dashboard reload requested');
          fetchToken();
          break;

        default:
          // Unknown message type, ignore
          break;
      }
    },
    [fetchToken]
  );

  /**
   * Initialize component.
   */
  useEffect(() => {
    fetchToken();

    // Listen for parent frame messages
    const removeListener = addParentMessageListener(handleParentMessage);

    return () => {
      // Cleanup
      removeListener();
      if (refreshManagerRef.current) {
        refreshManagerRef.current.stop();
      }
    };
  }, [dashboardId, tenantId]); // Re-fetch when dashboard or tenant changes

  /**
   * Handle retry button click.
   */
  const handleRetry = useCallback(() => {
    retryCountRef.current = 0;
    setIsRetrying(true);
    fetchToken().finally(() => setIsRetrying(false));
  }, [fetchToken]);

  /**
   * Render loading state.
   */
  const renderLoading = () => {
    if (loadingComponent) {
      return loadingComponent;
    }

    if (showLoadingSkeleton) {
      return (
        <Card>
          <BlockStack gap="400">
            <div style={{ display: 'flex', justifyContent: 'center', padding: '20px' }}>
              <Spinner size="large" />
            </div>
            <Text as="p" alignment="center" tone="subdued">
              Loading analytics dashboard...
            </Text>
            <SkeletonBodyText lines={10} />
          </BlockStack>
        </Card>
      );
    }

    return (
      <div className="superset-embed-loading">
        <Spinner size="large" />
        <Text as="p" tone="subdued">
          Loading analytics...
        </Text>
      </div>
    );
  };

  /**
   * Render error state.
   */
  const renderError = () => {
    if (errorComponent) {
      return errorComponent;
    }

    return (
      <Card>
        <AnalyticsHealthBanner
          onRetry={handleRetry}
          isRetrying={isRetrying}
          errorType={state.error?.message || 'unknown'}
          accessSurface="shopify_embed"
        />
      </Card>
    );
  };

  /**
   * Render iframe.
   */
  const renderIframe = () => {
    if (!state.dashboardUrl) {
      return null;
    }

    const iframeHeight = typeof height === 'number' ? `${height}px` : height;

    return (
      <iframe
        ref={iframeRef}
        src={state.dashboardUrl}
        title={`Analytics Dashboard: ${dashboardId}`}
        className="superset-iframe"
        style={{ height: iframeHeight }}
        onLoad={handleIframeLoad}
        onError={handleIframeError}
        allow="fullscreen"
        sandbox="allow-same-origin allow-scripts allow-popups allow-forms allow-presentation"
      />
    );
  };

  return (
    <div className={`superset-embed-container ${className}`}>
      {state.status === 'loading' && renderLoading()}
      {state.status === 'error' && renderError()}
      {(state.status === 'ready' || state.status === 'refreshing') && renderIframe()}

      {/* Hidden status indicator for debugging */}
      {import.meta.env.DEV && (
        <div className="superset-embed-debug">
          Status: {state.status} | Token expires:{' '}
          {state.expiresAt?.toLocaleTimeString() || 'N/A'}
        </div>
      )}
    </div>
  );
};

export default ShopifyEmbeddedSuperset;
