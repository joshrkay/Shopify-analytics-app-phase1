/**
 * Tests for ProtectedRoute component
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ProtectedRoute } from '../ProtectedRoute';
import { useAppBridge } from '@shopify/app-bridge-react';
import { useShopifySession } from '../../hooks/useShopifySession';
import { isEmbedded, getShopifyHost } from '../../lib/shopifyAppBridge';
import { redirectToOAuthInstall } from '../../lib/redirects';

// Mock dependencies
vi.mock('@shopify/app-bridge-react', () => ({
  useAppBridge: vi.fn(),
  AppBridgeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('../../hooks/useShopifySession', () => ({
  useShopifySession: vi.fn(),
}));

vi.mock('../../lib/shopifyAppBridge', () => ({
  isEmbedded: vi.fn(),
  getShopifyHost: vi.fn(),
}));

vi.mock('../../lib/redirects', () => ({
  redirectToOAuthInstall: vi.fn(),
}));

describe('ProtectedRoute', () => {
  const mockChildren = <div>Protected Content</div>;
  const mockApp = { id: 'test-app' };

  beforeEach(() => {
    vi.clearAllMocks();
    (useAppBridge as any).mockReturnValue(mockApp);
    (isEmbedded as any).mockReturnValue(false);
    (getShopifyHost as any).mockReturnValue(null);
  });

  it('renders children when not embedded and not required', async () => {
    (isEmbedded as any).mockReturnValue(false);
    (useShopifySession as any).mockReturnValue({
      getToken: vi.fn().mockResolvedValue(null),
      isLoading: false,
      error: null,
      isEmbedded: false,
    });

    render(<ProtectedRoute>{mockChildren}</ProtectedRoute>);

    await waitFor(() => {
      expect(screen.getByText('Protected Content')).toBeInTheDocument();
    });
  });

  it('shows loading spinner while verifying token', () => {
    (isEmbedded as any).mockReturnValue(true);
    (useShopifySession as any).mockReturnValue({
      getToken: vi.fn().mockResolvedValue('token'),
      isLoading: true,
      error: null,
      isEmbedded: true,
    });

    render(<ProtectedRoute>{mockChildren}</ProtectedRoute>);

    // Should show spinner, not content
    expect(screen.queryByText('Protected Content')).not.toBeInTheDocument();
  });

  it('renders children when embedded and token is available', async () => {
    (isEmbedded as any).mockReturnValue(true);
    (useShopifySession as any).mockReturnValue({
      getToken: vi.fn().mockResolvedValue('valid-token'),
      isLoading: false,
      error: null,
      isEmbedded: true,
    });

    render(<ProtectedRoute>{mockChildren}</ProtectedRoute>);

    await waitFor(() => {
      expect(screen.getByText('Protected Content')).toBeInTheDocument();
    });
  });

  it('redirects to OAuth install when embedded but no token', async () => {
    (isEmbedded as any).mockReturnValue(true);
    (getShopifyHost as any).mockReturnValue('encoded-host');
    (useShopifySession as any).mockReturnValue({
      getToken: vi.fn().mockResolvedValue(null),
      isLoading: false,
      error: null,
      isEmbedded: true,
    });

    render(<ProtectedRoute shopDomain="mystore.myshopify.com">{mockChildren}</ProtectedRoute>);

    await waitFor(() => {
      expect(redirectToOAuthInstall).toHaveBeenCalledWith('mystore.myshopify.com');
    });
  });

  it('shows error message when token verification fails', async () => {
    const error = new Error('Token verification failed');
    (isEmbedded as any).mockReturnValue(true);
    (useShopifySession as any).mockReturnValue({
      getToken: vi.fn().mockRejectedValue(error),
      isLoading: false,
      error: error,
      isEmbedded: true,
    });

    render(<ProtectedRoute shopDomain="mystore.myshopify.com">{mockChildren}</ProtectedRoute>);

    await waitFor(() => {
      expect(screen.getByText(/Authentication error/)).toBeInTheDocument();
    });
  });

  it('shows error when embedded is required but not present', async () => {
    (isEmbedded as any).mockReturnValue(false);
    (useShopifySession as any).mockReturnValue({
      getToken: vi.fn().mockResolvedValue(null),
      isLoading: false,
      error: null,
      isEmbedded: false,
    });

    render(<ProtectedRoute requireEmbedded={true}>{mockChildren}</ProtectedRoute>);

    await waitFor(() => {
      expect(
        screen.getByText(/This route requires the app to be embedded/)
      ).toBeInTheDocument();
    });
  });
});
