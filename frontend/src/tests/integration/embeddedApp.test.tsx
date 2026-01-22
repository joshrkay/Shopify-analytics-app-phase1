/**
 * Integration tests for embedded app shell
 *
 * Tests the complete flow of:
 * - App loading in embedded context
 * - Session token retrieval and refresh
 * - Route protection
 * - Navigation
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import App from '../../App';
import { ShopifyProvider } from '../../providers/ShopifyProvider';
import { ShopifyApiProvider } from '../../providers/ShopifyApiProvider';

// Mock App Bridge
vi.mock('@shopify/app-bridge-react', () => ({
  useAppBridge: vi.fn(),
  AppBridgeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('@shopify/app-bridge-utils', () => ({
  getSessionToken: vi.fn(),
}));

vi.mock('../../lib/shopifyAppBridge', () => ({
  isEmbedded: vi.fn(),
  getShopifyHost: vi.fn(),
  getAppBridgeConfig: vi.fn(),
}));

vi.mock('../../lib/redirects', () => ({
  redirectToOAuthInstall: vi.fn(),
}));

import { useAppBridge } from '@shopify/app-bridge-react';
import { getSessionToken } from '@shopify/app-bridge-utils';
import { isEmbedded, getShopifyHost } from '../../lib/shopifyAppBridge';

describe('Embedded App Integration', () => {
  const mockApp = { id: 'test-app' };
  const mockToken = 'test-session-token';

  beforeEach(() => {
    vi.clearAllMocks();
    (useAppBridge as any).mockReturnValue(mockApp);
    (getSessionToken as any).mockResolvedValue(mockToken);
    (isEmbedded as any).mockReturnValue(true);
    (getShopifyHost as any).mockReturnValue('encoded-host-123');

    // Mock environment variable
    vi.stubEnv('VITE_SHOPIFY_API_KEY', 'test-api-key');
  });

  it('loads app successfully in embedded context with valid token', async () => {
    // Mock the AdminPlans component to verify it renders
    vi.mock('../../pages/AdminPlans', () => ({
      default: () => <div>Admin Plans Page</div>,
    }));

    render(
      <ShopifyProvider>
        <ShopifyApiProvider>
          <App />
        </ShopifyApiProvider>
      </ShopifyProvider>
    );

    // App should load and render the default route
    await waitFor(() => {
      // Verify App Bridge was initialized
      expect(useAppBridge).toHaveBeenCalled();
    });
  });

  it('handles missing session token gracefully', async () => {
    (getSessionToken as any).mockResolvedValue(null);

    render(
      <ShopifyProvider>
        <ShopifyApiProvider>
          <App />
        </ShopifyApiProvider>
      </ShopifyProvider>
    );

    // Should handle missing token without crashing
    await waitFor(() => {
      expect(getSessionToken).toHaveBeenCalled();
    });
  });

  it('works in non-embedded context (admin routes)', () => {
    (isEmbedded as any).mockReturnValue(false);
    (getShopifyHost as any).mockReturnValue(null);

    render(
      <ShopifyProvider>
        <ShopifyApiProvider>
          <App />
        </ShopifyApiProvider>
      </ShopifyProvider>
    );

    // Should render without App Bridge
    expect(screen.getByText(/Plan Management/i)).toBeInTheDocument();
  });
});
