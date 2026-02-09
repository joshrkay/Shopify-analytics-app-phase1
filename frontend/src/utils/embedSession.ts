/**
 * Embed Session Manager
 *
 * Provides a high-level session management interface for embedded Superset.
 * Wraps TokenRefreshManager with lifecycle management, state tracking,
 * and configurable event hooks.
 *
 * Usage:
 *   const session = createEmbedSession({
 *     dashboardId: 'abc-123',
 *     onSessionStart: (token) => console.log('Started'),
 *     onSessionExpired: (error) => console.log('Expired'),
 *   });
 *   await session.start();
 *   // ... later
 *   session.destroy();
 *
 * Story 5.1.5 - Embedded Dashboard Rendering
 */

import {
  generateEmbedToken,
  TokenRefreshManager,
  isInShopifyAdmin,
} from '../services/embedApi';
import type { EmbedTokenResponse } from '../services/embedApi';

export interface SessionConfig {
  /** Superset dashboard ID to embed */
  dashboardId: string;
  /** Called when session starts successfully */
  onSessionStart?: (token: EmbedTokenResponse) => void;
  /** Called when token is silently refreshed */
  onSessionRefresh?: (token: EmbedTokenResponse) => void;
  /** Called when session expires and cannot be refreshed */
  onSessionExpired?: (error: Error) => void;
  /** Called on any session error */
  onSessionError?: (error: Error) => void;
  /** Maximum retry attempts on refresh failure */
  maxRetries?: number;
  /** Delay between retries in milliseconds */
  retryDelayMs?: number;
}

const DEFAULT_MAX_RETRIES = 3;
const DEFAULT_RETRY_DELAY_MS = 3000;

export class EmbedSessionManager {
  private refreshManager: TokenRefreshManager | null = null;
  private config: SessionConfig;
  private retryCount = 0;
  private _isActive = false;
  private _currentToken: EmbedTokenResponse | null = null;

  constructor(config: SessionConfig) {
    this.config = {
      maxRetries: DEFAULT_MAX_RETRIES,
      retryDelayMs: DEFAULT_RETRY_DELAY_MS,
      ...config,
    };
  }

  /** Whether the session is currently active and authenticated. */
  get isActive(): boolean {
    return this._isActive;
  }

  /** Whether we're running inside a Shopify Admin iframe. */
  get isEmbedded(): boolean {
    return isInShopifyAdmin();
  }

  /** The current token response, or null if not started. */
  get currentToken(): EmbedTokenResponse | null {
    return this._currentToken;
  }

  /**
   * Start a new session by generating an embed token.
   * Sets up automatic refresh management.
   */
  async start(): Promise<EmbedTokenResponse> {
    this.stop();
    this.retryCount = 0;

    try {
      const tokenResponse = await generateEmbedToken(this.config.dashboardId);

      this._isActive = true;
      this._currentToken = tokenResponse;

      // Set up refresh manager
      this.refreshManager = new TokenRefreshManager(
        this.config.dashboardId,
        this.handleRefreshSuccess,
        this.handleRefreshError
      );
      this.refreshManager.start(tokenResponse);

      this.config.onSessionStart?.(tokenResponse);
      return tokenResponse;
    } catch (error) {
      this._isActive = false;
      this.config.onSessionError?.(error as Error);
      throw error;
    }
  }

  /**
   * Restart the session (stop + start).
   * Useful for recovering from errors or tenant switches.
   */
  async restart(): Promise<EmbedTokenResponse> {
    this.stop();
    return this.start();
  }

  /**
   * Stop the session. Cancels pending refresh timers.
   */
  stop(): void {
    if (this.refreshManager) {
      this.refreshManager.stop();
      this.refreshManager = null;
    }
    this._isActive = false;
    this._currentToken = null;
  }

  /**
   * Destroy the session. Call on component unmount.
   */
  destroy(): void {
    this.stop();
    this.config.onSessionStart = undefined;
    this.config.onSessionRefresh = undefined;
    this.config.onSessionExpired = undefined;
    this.config.onSessionError = undefined;
  }

  private handleRefreshSuccess = (token: EmbedTokenResponse): void => {
    this._currentToken = token;
    this.retryCount = 0;
    this.config.onSessionRefresh?.(token);
  };

  private handleRefreshError = (_error: Error): void => {
    const maxRetries = this.config.maxRetries ?? DEFAULT_MAX_RETRIES;
    const retryDelay = this.config.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS;

    if (this.retryCount < maxRetries) {
      this.retryCount++;
      console.log(
        `[EmbedSession] Retry ${this.retryCount}/${maxRetries} in ${retryDelay}ms`
      );
      setTimeout(() => {
        this.start().catch((retryError) => {
          this.config.onSessionError?.(retryError);
        });
      }, retryDelay);
    } else {
      this._isActive = false;
      this.config.onSessionExpired?.(
        new Error('Session expired after maximum retries')
      );
    }
  };
}

/**
 * Factory function to create an EmbedSessionManager.
 */
export function createEmbedSession(config: SessionConfig): EmbedSessionManager {
  return new EmbedSessionManager(config);
}
