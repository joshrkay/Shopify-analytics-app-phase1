/**
 * Tests for useShopifySession hook
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useShopifySession } from '../useShopifySession';
import { useAppBridge } from '@shopify/app-bridge-react';
import { getSessionToken } from '@shopify/app-bridge-utils';
import { isEmbedded } from '../../lib/shopifyAppBridge';

// Mock dependencies
vi.mock('@shopify/app-bridge-react', () => ({
  useAppBridge: vi.fn(),
}));

vi.mock('@shopify/app-bridge-utils', () => ({
  getSessionToken: vi.fn(),
}));

vi.mock('../../lib/shopifyAppBridge', () => ({
  isEmbedded: vi.fn(),
}));

describe('useShopifySession', () => {
  const mockApp = { id: 'test-app' };
  const mockToken = 'test-session-token-123';

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    (useAppBridge as any).mockReturnValue(mockApp);
    (isEmbedded as any).mockReturnValue(true);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns null token when app is not available', async () => {
    (useAppBridge as any).mockReturnValue(null);
    (isEmbedded as any).mockReturnValue(false);

    const { result } = renderHook(() => useShopifySession());

    const token = await result.current.getToken();
    expect(token).toBe(null);
    expect(result.current.isEmbedded).toBe(false);
  });

  it('fetches and caches session token', async () => {
    (getSessionToken as any).mockResolvedValue(mockToken);

    const { result } = renderHook(() => useShopifySession());

    const token = await result.current.getToken();
    expect(token).toBe(mockToken);
    expect(getSessionToken).toHaveBeenCalledWith(mockApp);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('returns cached token when still valid', async () => {
    (getSessionToken as any).mockResolvedValue(mockToken);

    const { result } = renderHook(() => useShopifySession());

    // First call
    const token1 = await result.current.getToken();
    expect(token1).toBe(mockToken);
    expect(getSessionToken).toHaveBeenCalledTimes(1);

    // Second call should use cache
    const token2 = await result.current.getToken();
    expect(token2).toBe(mockToken);
    expect(getSessionToken).toHaveBeenCalledTimes(1); // Still only called once
  });

  it('refreshes token when cache expires', async () => {
    const newToken = 'new-session-token-456';
    (getSessionToken as any)
      .mockResolvedValueOnce(mockToken)
      .mockResolvedValueOnce(newToken);

    const { result } = renderHook(() => useShopifySession());

    // First call
    await result.current.getToken();

    // Fast-forward time to just before expiry (59 minutes)
    vi.advanceTimersByTime(59 * 60 * 1000);

    // Token should still be cached
    const tokenBeforeExpiry = await result.current.getToken();
    expect(tokenBeforeExpiry).toBe(mockToken);

    // Fast-forward past expiry buffer (61 minutes)
    vi.advanceTimersByTime(2 * 60 * 1000);

    // Token should be refreshed
    const tokenAfterExpiry = await result.current.getToken();
    expect(tokenAfterExpiry).toBe(newToken);
    expect(getSessionToken).toHaveBeenCalledTimes(2);
  });

  it('handles token fetch errors gracefully', async () => {
    const error = new Error('Failed to get token');
    (getSessionToken as any).mockRejectedValue(error);

    const { result } = renderHook(() => useShopifySession());

    const token = await result.current.getToken();
    expect(token).toBe(null);
    expect(result.current.error).toBe(error);
    expect(result.current.isLoading).toBe(false);
  });

  it('returns null when getSessionToken returns null', async () => {
    (getSessionToken as any).mockResolvedValue(null);

    const { result } = renderHook(() => useShopifySession());

    const token = await result.current.getToken();
    expect(token).toBe(null);
    expect(result.current.error).toBe(null);
  });

  it('clears cache when app context changes', async () => {
    (getSessionToken as any).mockResolvedValue(mockToken);

    const { result, rerender } = renderHook(() => useShopifySession());

    // First call
    await result.current.getToken();

    // Change app context
    const newApp = { id: 'new-app' };
    (useAppBridge as any).mockReturnValue(newApp);
    rerender();

    // Cache should be cleared, new token should be fetched
    await waitFor(() => {
      expect(result.current.getToken()).resolves.toBe(mockToken);
    });
  });

  it('schedules automatic token refresh', async () => {
    (getSessionToken as any).mockResolvedValue(mockToken);

    renderHook(() => useShopifySession());

    // Fast-forward to just before refresh time (49 minutes)
    vi.advanceTimersByTime(49 * 60 * 1000);

    // Token should be automatically refreshed
    await waitFor(() => {
      expect(getSessionToken).toHaveBeenCalledTimes(2);
    });
  });
});
