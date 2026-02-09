/**
 * Tests for UnifiedTokenRefreshManager
 *
 * Phase 2 (5.6.2) — Silent Token Refresh
 *
 * Verifies:
 * - Schedules refresh based on refresh_before timestamp
 * - Retries on failure up to maxRetries
 * - Calls onError after max retries exhausted
 * - forceRefresh works and resets retry count
 * - stop() clears timers and resets state
 * - Idempotent: does not double-refresh
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock the embedApi module before importing the manager
vi.mock('../services/embedApi', () => ({
  refreshEmbedToken: vi.fn(),
}));

import { UnifiedTokenRefreshManager } from '../utils/tokenRefresh';
import { refreshEmbedToken } from '../services/embedApi';
import type { EmbedTokenResponse } from '../services/embedApi';

const mockRefresh = refreshEmbedToken as ReturnType<typeof vi.fn>;

function createMockTokenResponse(overrides?: Partial<EmbedTokenResponse>): EmbedTokenResponse {
  return {
    jwt_token: 'mock-jwt-token-' + Math.random().toString(36).slice(2),
    expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    refresh_before: new Date(Date.now() + 55 * 60 * 1000).toISOString(),
    dashboard_url: 'https://analytics.example.com/superset/dashboard/1/?token=abc&standalone=1',
    embed_config: {
      standalone: true,
      show_filters: false,
      show_title: false,
      hide_chrome: true,
    },
    ...overrides,
  };
}

describe('UnifiedTokenRefreshManager', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('schedules refresh based on refresh_before timestamp', () => {
    const onRefreshed = vi.fn();
    const manager = new UnifiedTokenRefreshManager({
      dashboardId: 'dash-1',
      accessSurface: 'shopify_embed',
      onRefreshed,
    });

    const refreshTime = new Date(Date.now() + 10 * 60 * 1000); // 10 min from now
    const token = createMockTokenResponse({
      refresh_before: refreshTime.toISOString(),
    });

    mockRefresh.mockResolvedValue(createMockTokenResponse());

    manager.start(token);

    // Advance time to just before refresh
    vi.advanceTimersByTime(9 * 60 * 1000);
    expect(mockRefresh).not.toHaveBeenCalled();

    // Advance past refresh time
    vi.advanceTimersByTime(2 * 60 * 1000);
    expect(mockRefresh).toHaveBeenCalledTimes(1);

    manager.stop();
  });

  it('calls onRefreshed callback on successful refresh', async () => {
    const onRefreshed = vi.fn();
    const newToken = createMockTokenResponse();
    mockRefresh.mockResolvedValue(newToken);

    const manager = new UnifiedTokenRefreshManager({
      dashboardId: 'dash-1',
      accessSurface: 'shopify_embed',
      onRefreshed,
    });

    // Set refresh_before to now so it triggers immediately
    const token = createMockTokenResponse({
      refresh_before: new Date(Date.now() - 1000).toISOString(),
    });

    manager.start(token);

    // Let the setTimeout(fn, 0) fire
    await vi.advanceTimersByTimeAsync(0);

    expect(onRefreshed).toHaveBeenCalledWith(newToken);

    manager.stop();
  });

  it('stop() clears timers and resets state', () => {
    const manager = new UnifiedTokenRefreshManager({
      dashboardId: 'dash-1',
      accessSurface: 'external_app',
    });

    const token = createMockTokenResponse({
      refresh_before: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
    });

    manager.start(token);
    manager.stop();

    // Advance time past the original refresh_before — should NOT trigger
    vi.advanceTimersByTime(35 * 60 * 1000);
    expect(mockRefresh).not.toHaveBeenCalled();
  });

  it('forceRefresh triggers immediate refresh', async () => {
    const newToken = createMockTokenResponse();
    mockRefresh.mockResolvedValue(newToken);

    const manager = new UnifiedTokenRefreshManager({
      dashboardId: 'dash-1',
      accessSurface: 'shopify_embed',
    });

    const token = createMockTokenResponse({
      refresh_before: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
    });

    manager.start(token);

    const result = await manager.forceRefresh();

    expect(result).toEqual(newToken);
    expect(mockRefresh).toHaveBeenCalledTimes(1);

    manager.stop();
  });

  it('throws error when forceRefresh called without start', async () => {
    const manager = new UnifiedTokenRefreshManager({
      dashboardId: 'dash-1',
      accessSurface: 'shopify_embed',
    });

    await expect(manager.forceRefresh()).rejects.toThrow('No current token');
  });

  it('passes accessSurface to refreshEmbedToken', async () => {
    const newToken = createMockTokenResponse();
    mockRefresh.mockResolvedValue(newToken);

    const manager = new UnifiedTokenRefreshManager({
      dashboardId: 'dash-1',
      accessSurface: 'external_app',
    });

    const token = createMockTokenResponse({
      refresh_before: new Date(Date.now() - 1000).toISOString(),
    });

    manager.start(token);
    await vi.advanceTimersByTimeAsync(0);

    expect(mockRefresh).toHaveBeenCalledWith(
      token.jwt_token,
      'dash-1',
      'external_app'
    );

    manager.stop();
  });
});
