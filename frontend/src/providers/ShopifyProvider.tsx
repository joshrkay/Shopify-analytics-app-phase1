/**
 * Shopify Provider
 *
 * Wraps the app with Shopify App Bridge when embedded in Shopify Admin.
 * Falls back to Polaris-only when not embedded (for admin routes).
 *
 * Features:
 * - Validates App Bridge configuration
 * - Handles missing API key errors gracefully
 * - Supports both embedded and standalone modes
 * - Error boundaries for App Bridge failures
 */

import { ReactNode, ErrorInfo, Component } from 'react';
import { AppProvider, Banner } from '@shopify/polaris';
import { AppBridgeProvider } from '@shopify/app-bridge-react';
import enTranslations from '@shopify/polaris/locales/en.json';
import '@shopify/polaris/build/esm/styles.css';
import { getShopifyHost, getAppBridgeConfig } from '../lib/shopifyAppBridge';

const SHOPIFY_API_KEY = import.meta.env.VITE_SHOPIFY_API_KEY || '';

interface ShopifyProviderProps {
  children: ReactNode;
}

interface ShopifyProviderState {
  hasError: boolean;
  error: Error | null;
}

/**
 * Error boundary component for App Bridge failures.
 */
class AppBridgeErrorBoundary extends Component<
  { children: ReactNode },
  ShopifyProviderState
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ShopifyProviderState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('App Bridge error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <AppProvider i18n={enTranslations}>
          <div style={{ padding: '20px' }}>
            <Banner tone="critical" title="App Bridge Error">
              <p>
                An error occurred initializing the Shopify App Bridge.
                {this.state.error && (
                  <span> Error: {this.state.error.message}</span>
                )}
              </p>
              <p>Please refresh the page or contact support if the issue persists.</p>
            </Banner>
          </div>
        </AppProvider>
      );
    }

    return this.props.children;
  }
}

/**
 * Validate App Bridge configuration.
 */
function validateAppBridgeConfig(host: string): { valid: boolean; error?: string } {
  if (!host) {
    return { valid: false, error: 'Host parameter is required for embedded apps' };
  }

  if (!SHOPIFY_API_KEY) {
    return {
      valid: false,
      error: 'VITE_SHOPIFY_API_KEY environment variable is not set. App Bridge will not work correctly.',
    };
  }

  // Validate API key format (basic check)
  if (SHOPIFY_API_KEY.length < 10) {
    return {
      valid: false,
      error: 'VITE_SHOPIFY_API_KEY appears to be invalid (too short).',
    };
  }

  return { valid: true };
}

export function ShopifyProvider({ children }: ShopifyProviderProps) {
  const host = getShopifyHost();

  // If host is present, we're embedded in Shopify Admin
  if (host) {
    // Validate configuration
    const validation = validateAppBridgeConfig(host);

    if (!validation.valid) {
      console.error('App Bridge configuration error:', validation.error);
      
      // Still render Polaris, but show error banner
      return (
        <AppProvider i18n={enTranslations}>
          <div style={{ padding: '20px' }}>
            <Banner tone="critical" title="Configuration Error">
              <p>{validation.error}</p>
              <p>Please check your environment variables and try again.</p>
            </Banner>
            {children}
          </div>
        </AppProvider>
      );
    }

    try {
      // Get validated App Bridge config
      const config = getAppBridgeConfig(host);

      return (
        <AppBridgeErrorBoundary>
          <AppBridgeProvider config={config}>
            <AppProvider i18n={enTranslations}>{children}</AppProvider>
          </AppBridgeProvider>
        </AppBridgeErrorBoundary>
      );
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      console.error('Failed to initialize App Bridge:', error);

      return (
        <AppProvider i18n={enTranslations}>
          <div style={{ padding: '20px' }}>
            <Banner tone="critical" title="App Bridge Initialization Error">
              <p>Failed to initialize Shopify App Bridge: {errorMessage}</p>
              <p>Please refresh the page or contact support.</p>
            </Banner>
            {children}
          </div>
        </AppProvider>
      );
    }
  }

  // Not embedded (e.g., admin routes), use Polaris only
  return <AppProvider i18n={enTranslations}>{children}</AppProvider>;
}
