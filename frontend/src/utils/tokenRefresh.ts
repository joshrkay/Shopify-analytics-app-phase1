/**
 * Unified Token Refresh Manager
 *
 * Extracted and improved token refresh logic for use across both
 * Shopify embed and external app surfaces.
 *
 * Features:
 * - Configurable refresh threshold (defaults to 5 minutes before expiry)
 * - Retry logic with configurable max retries and delay
 * - Access surface awareness for multi-surface token management
 * - Manual force refresh capability
 * - Clean lifecycle management (start/stop)
 */

import { refreshEmbedToken } from '../services/embedApi';
import type { EmbedTokenResponse } from '../services/embedApi';

export type AccessSurface = 'shopify_embed' | 'external_app';

/**
 * Configuration for the UnifiedTokenRefreshManager.
 */
export interface TokenRefreshConfig {
  /** Dashboard ID for token refresh calls */
  dashboardId: string;
  /** Access surface type for the token */
  accessSurface: AccessSurface;
  /** Time before expiry to trigger refresh (default: 5 minutes) */
  refreshThresholdMs?: number;
  /** Maximum number of retry attempts on failure (default: 3) */
  maxRetries?: number;
  /** Delay between retries in milliseconds (default: 3000) */
  retryDelayMs?: number;
  /** Callback when token is successfully refreshed */
  onRefreshed?: (token: EmbedTokenResponse) => void;
  /** Callback when all retries are exhausted */
  onError?: (error: Error) => void;
}

const DEFAULT_MAX_RETRIES = 3;
const DEFAULT_RETRY_DELAY_MS = 3000;

/**
 * UnifiedTokenRefreshManager
 *
 * Manages automatic and manual token refresh for embedded analytics.
 * Works across both Shopify embed and external app surfaces.
 */
export class UnifiedTokenRefreshManager {
  private refreshTimer: ReturnType<typeof setTimeout> | null = null;
  private currentToken: string | null = null;
  private dashboardId: string;
  private accessSurface: AccessSurface;
  private maxRetries: number;
  private retryDelayMs: number;
  private onRefreshed?: (token: EmbedTokenResponse) => void;
  private onError?: (error: Error) => void;
  private retryCount = 0;
  private isRefreshing = false;

  constructor(config: TokenRefreshConfig) {
    this.dashboardId = config.dashboardId;
    this.accessSurface = config.accessSurface;
    this.maxRetries = config.maxRetries ?? DEFAULT_MAX_RETRIES;
    this.retryDelayMs = config.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS;
    this.onRefreshed = config.onRefreshed;
    this.onError = config.onError;
  }

  /**
   * Start managing token refresh for the given token response.
   * Schedules the next refresh based on the refresh_before timestamp.
   */
  start(initialToken: EmbedTokenResponse): void {
    this.currentToken = initialToken.jwt_token;
    this.retryCount = 0;
    this.scheduleRefresh(initialToken.refresh_before);
  }

  /**
   * Stop token refresh management and clear all timers.
   */
  stop(): void {
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
    }
    this.currentToken = null;
    this.retryCount = 0;
    this.isRefreshing = false;
  }

  /**
   * Manually trigger a token refresh.
   * Returns the new token response or throws on failure.
   */
  async forceRefresh(): Promise<EmbedTokenResponse> {
    if (!this.currentToken) {
      throw new Error('No current token to refresh. Call start() first.');
    }

    // Cancel any scheduled refresh
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
    }

    this.retryCount = 0;
    return this.performRefresh();
  }

  /**
   * Schedule the next token refresh based on the refresh_before timestamp.
   * If the refresh time has already passed, refresh immediately.
   */
  private scheduleRefresh(refreshBefore: string): void {
    // Clear any existing timer
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
    }

    const refreshTime = new Date(refreshBefore).getTime();
    const now = Date.now();
    const delay = Math.max(0, refreshTime - now);

    console.log(
      `[UnifiedTokenRefresh] Scheduling refresh in ${Math.round(delay / 1000 / 60)} minutes ` +
      `(surface: ${this.accessSurface})`
    );

    this.refreshTimer = setTimeout(() => this.performRefresh(), delay);
  }

  /**
   * Perform the token refresh with retry logic.
   * On success: schedules next refresh and calls onRefreshed.
   * On failure: retries up to maxRetries, then calls onError.
   */
  private async performRefresh(): Promise<EmbedTokenResponse> {
    if (!this.currentToken) {
      const error = new Error('No current token to refresh');
      console.warn('[UnifiedTokenRefresh]', error.message);
      throw error;
    }

    if (this.isRefreshing) {
      throw new Error('Refresh already in progress');
    }

    this.isRefreshing = true;

    try {
      console.log(
        `[UnifiedTokenRefresh] Refreshing token (surface: ${this.accessSurface})...`
      );

      const newToken = await refreshEmbedToken(
        this.currentToken,
        this.dashboardId,
        this.accessSurface
      );

      this.currentToken = newToken.jwt_token;
      this.retryCount = 0;
      this.isRefreshing = false;

      // Schedule next refresh
      this.scheduleRefresh(newToken.refresh_before);

      // Notify callback
      this.onRefreshed?.(newToken);

      console.log('[UnifiedTokenRefresh] Token refreshed successfully');
      return newToken;
    } catch (error) {
      this.isRefreshing = false;

      console.error(
        `[UnifiedTokenRefresh] Refresh failed (attempt ${this.retryCount + 1}/${this.maxRetries}):`,
        error
      );

      if (this.retryCount < this.maxRetries) {
        this.retryCount++;
        console.log(
          `[UnifiedTokenRefresh] Retrying in ${this.retryDelayMs}ms ` +
          `(attempt ${this.retryCount}/${this.maxRetries})`
        );

        return new Promise<EmbedTokenResponse>((resolve, reject) => {
          this.refreshTimer = setTimeout(async () => {
            try {
              const result = await this.performRefresh();
              resolve(result);
            } catch (retryError) {
              reject(retryError);
            }
          }, this.retryDelayMs);
        });
      }

      // Max retries exhausted
      const exhaustedError = new Error(
        `Token refresh failed after ${this.maxRetries} retries`
      );
      this.onError?.(exhaustedError);
      throw exhaustedError;
    }
  }
}
