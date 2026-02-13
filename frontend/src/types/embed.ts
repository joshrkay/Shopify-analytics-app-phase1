/**
 * Types for Embedded Analytics
 *
 * TypeScript interfaces for Superset embedding in Shopify Admin.
 */

import type { ReactNode } from 'react';

/**
 * Access surface type for analytics embedding.
 * - 'shopify_embed': Embedded within Shopify Admin iframe
 * - 'external_app': Standalone external analytics surface
 */
export type AccessSurface = 'shopify_embed' | 'external_app';

/**
 * Embed token response from API.
 */
export interface EmbedTokenResponse {
  jwt_token: string;
  expires_at: string;
  refresh_before: string;
  dashboard_url: string;
  embed_config: EmbedDisplayConfig;
  access_surface?: AccessSurface;
}

/**
 * Display configuration for embedded dashboard.
 */
export interface EmbedDisplayConfig {
  standalone: boolean;
  show_filters: boolean;
  show_title: boolean;
  hide_chrome: boolean;
}

/**
 * Embed service configuration.
 */
export interface EmbedConfig {
  superset_url: string;
  allowed_dashboards: string[];
  session_refresh_interval_ms: number;
  csp_frame_ancestors: string[];
}

/**
 * Health check response.
 */
export interface EmbedHealthResponse {
  status: 'healthy' | 'unhealthy';
  embed_configured: boolean;
  superset_url_configured?: boolean;
  message?: string;
}

/**
 * Props for embedded Superset component.
 */
export interface ShopifyEmbeddedSupersetProps {
  /** Superset dashboard ID to embed */
  dashboardId: string;
  /** Tenant ID (optional, uses context if not provided) */
  tenantId?: string;
  /** Custom height for iframe */
  height?: string | number;
  /** Custom CSS class name */
  className?: string;
  /** Callback when dashboard loads successfully */
  onLoad?: () => void;
  /** Callback when error occurs */
  onError?: (error: Error) => void;
  /** Callback when token refreshes */
  onTokenRefresh?: () => void;
  /** Show loading skeleton while loading */
  showLoadingSkeleton?: boolean;
  /** Custom loading component */
  loadingComponent?: ReactNode;
  /** Custom error component */
  errorComponent?: ReactNode;
}

/**
 * State for embedded dashboard component.
 */
export interface EmbedState {
  status: 'idle' | 'loading' | 'ready' | 'error' | 'refreshing';
  token: string | null;
  dashboardUrl: string | null;
  error: Error | null;
  expiresAt: Date | null;
  refreshBefore: Date | null;
}

/**
 * Message types for iframe communication.
 */
export type IframeMessageType =
  | 'DASHBOARD_LOADED'
  | 'DASHBOARD_ERROR'
  | 'REFRESH_TOKEN'
  | 'FILTER_CHANGED'
  | 'CHART_CLICKED';

/**
 * Message from embedded iframe.
 */
export interface IframeMessage {
  type: IframeMessageType;
  payload?: unknown;
}

/**
 * Dashboard metadata from Superset.
 */
export interface DashboardMetadata {
  id: string;
  title: string;
  slug: string;
  position_json: Record<string, unknown>;
  css: string;
}

/**
 * Filter state from embedded dashboard.
 */
export interface DashboardFilterState {
  nativeFilters: Record<string, unknown>;
  crossFilters: Record<string, unknown>;
}
