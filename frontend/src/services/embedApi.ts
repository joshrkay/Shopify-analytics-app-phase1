/**
 * Embedded Analytics API Service
 *
 * Handles API calls for Superset embedding:
 * - Token generation for dashboard embedding
 * - Silent token refresh before expiry
 * - Embed configuration retrieval
 */

import { API_BASE_URL, createHeadersAsync, handleResponse } from './apiUtils';
import type { AccessSurface } from '../types/embed';

export type { AccessSurface } from '../types/embed';

export interface EmbedTokenResponse {
  jwt_token: string;
  expires_at: string;
  refresh_before: string;
  dashboard_url: string;
  embed_config: {
    standalone: boolean;
    show_filters: boolean;
    show_title: boolean;
    hide_chrome: boolean;
  };
  access_surface?: AccessSurface;
}

export interface EmbedConfig {
  superset_url: string;
  allowed_dashboards: string[];
  session_refresh_interval_ms: number;
  csp_frame_ancestors: string[];
}

export interface EmbedHealthResponse {
  status: 'healthy' | 'unhealthy';
  embed_configured: boolean;
  superset_url_configured?: boolean;
  message?: string;
}

export interface EmbedReadinessResponse {
  status: 'ready' | 'not_ready';
  embed_configured: boolean;
  superset_url_configured: boolean;
  allowed_dashboards_configured: boolean;
  message?: string;
}

/**
 * Generate an embed token for a specific dashboard.
 *
 * @param dashboardId - The Superset dashboard ID to embed
 * @param accessSurface - Optional access surface type ('shopify_embed' | 'external_app')
 * @returns Token response with JWT and dashboard URL
 */
export async function generateEmbedToken(
  dashboardId: string,
  accessSurface?: AccessSurface
): Promise<EmbedTokenResponse> {
  const body: Record<string, string> = {
    dashboard_id: dashboardId,
  };
  if (accessSurface) {
    body.access_surface = accessSurface;
  }
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/v1/embed/token`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return handleResponse<EmbedTokenResponse>(response);
}

/**
 * Refresh an existing embed token.
 *
 * Call this before the token expires to maintain seamless session.
 *
 * @param currentToken - The current JWT token to refresh
 * @param dashboardId - Optional dashboard ID (uses token's dashboard if not provided)
 * @param accessSurface - Optional access surface type ('shopify_embed' | 'external_app')
 * @returns New token response
 */
export async function refreshEmbedToken(
  currentToken: string,
  dashboardId?: string,
  accessSurface?: AccessSurface
): Promise<EmbedTokenResponse> {
  const body: Record<string, string | undefined> = {
    current_token: currentToken,
    dashboard_id: dashboardId,
  };
  if (accessSurface) {
    body.access_surface = accessSurface;
  }
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/v1/embed/token/refresh`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return handleResponse<EmbedTokenResponse>(response);
}

/**
 * Get embed configuration for frontend initialization.
 *
 * @returns Embed configuration including allowed dashboards and refresh interval
 */
export async function getEmbedConfig(): Promise<EmbedConfig> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/v1/embed/config`, {
    method: 'GET',
    headers,
  });
  return handleResponse<EmbedConfig>(response);
}

/**
 * Check embed service health.
 *
 * Does not require authentication.
 *
 * @returns Health status of embed service
 */
export async function checkEmbedHealth(): Promise<EmbedHealthResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/embed/health`, {
    method: 'GET',
  });
  return handleResponse<EmbedHealthResponse>(response);
}

/**
 * Check embed service readiness.
 *
 * Readiness is stricter than health and validates configuration required
 * for frontend dashboard bootstrap.
 */
export async function checkEmbedReadiness(): Promise<EmbedReadinessResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/embed/health/readiness`, {
    method: 'GET',
  });
  return handleResponse<EmbedReadinessResponse>(response);
}

/**
 * Token refresh manager for automatic token refresh.
 *
 * Handles scheduling refresh before token expiry.
 */
export class TokenRefreshManager {
  private refreshTimer: ReturnType<typeof setTimeout> | null = null;
  private currentToken: string | null = null;
  private dashboardId: string;
  private onTokenRefreshed: (token: EmbedTokenResponse) => void;
  private onRefreshError: (error: Error) => void;

  constructor(
    dashboardId: string,
    onTokenRefreshed: (token: EmbedTokenResponse) => void,
    onRefreshError: (error: Error) => void
  ) {
    this.dashboardId = dashboardId;
    this.onTokenRefreshed = onTokenRefreshed;
    this.onRefreshError = onRefreshError;
  }

  /**
   * Start managing token refresh for the given token.
   */
  start(tokenResponse: EmbedTokenResponse): void {
    this.currentToken = tokenResponse.jwt_token;
    this.scheduleRefresh(tokenResponse.refresh_before);
  }

  /**
   * Stop token refresh management.
   */
  stop(): void {
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
    }
    this.currentToken = null;
  }

  /**
   * Schedule token refresh before expiry.
   */
  private scheduleRefresh(refreshBefore: string): void {
    // Clear any existing timer
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
    }

    const refreshTime = new Date(refreshBefore).getTime();
    const now = Date.now();
    const delay = Math.max(0, refreshTime - now);

    console.log(`[TokenRefresh] Scheduling refresh in ${Math.round(delay / 1000 / 60)} minutes`);

    this.refreshTimer = setTimeout(() => this.performRefresh(), delay);
  }

  /**
   * Perform the token refresh.
   */
  private async performRefresh(): Promise<void> {
    if (!this.currentToken) {
      console.warn('[TokenRefresh] No current token to refresh');
      return;
    }

    try {
      console.log('[TokenRefresh] Refreshing token...');
      const newToken = await refreshEmbedToken(this.currentToken, this.dashboardId);

      this.currentToken = newToken.jwt_token;
      this.onTokenRefreshed(newToken);

      // Schedule next refresh
      this.scheduleRefresh(newToken.refresh_before);

      console.log('[TokenRefresh] Token refreshed successfully');
    } catch (error) {
      console.error('[TokenRefresh] Failed to refresh token:', error);
      this.onRefreshError(error as Error);
    }
  }
}

/**
 * Utility to check if we're running inside Shopify Admin iframe.
 */
export function isInShopifyAdmin(): boolean {
  try {
    // Check if we're in an iframe
    if (window.self === window.top) {
      return false;
    }

    // Check referrer for Shopify Admin
    const referrer = document.referrer;
    return (
      referrer.includes('admin.shopify.com') ||
      referrer.includes('.myshopify.com')
    );
  } catch {
    // Cross-origin iframe access may throw
    // If we can't access top, we're likely in an iframe
    return true;
  }
}

/**
 * Send message to parent frame (Shopify Admin).
 */
export function sendMessageToParent(type: string, data: Record<string, unknown> = {}): void {
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type, ...data }, '*');
  }
}

/**
 * Listen for messages from parent frame.
 */
export function addParentMessageListener(
  handler: (event: MessageEvent) => void
): () => void {
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}
