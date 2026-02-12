/**
 * Source Connection Types
 *
 * Extended type definitions for connection wizard, OAuth flow, and sync configuration.
 * Complements the base Source types in sources.ts.
 *
 * Phase 3 — Subphase 3.1: Extended Type Definitions
 */

import type { SourcePlatform, SourceAuthType } from './sources';

// =============================================================================
// Catalog Types (Available Platforms)
// =============================================================================

/**
 * Definition of an available data source platform that can be connected.
 * Used in the connection wizard to display platform options.
 */
export interface DataSourceDefinition {
  id: string;
  platform: SourcePlatform;
  displayName: string;
  description: string;
  authType: SourceAuthType;
  logoUrl?: string;
  category: 'ecommerce' | 'ads' | 'email' | 'sms';
  isEnabled: boolean;
}

// =============================================================================
// Connection Wizard Flow State
// =============================================================================

/**
 * Step in the connection wizard flow
 */
export type ConnectionStep = 'select' | 'configure' | 'authenticate' | 'test' | 'complete';

/**
 * State of the connection wizard
 */
export interface ConnectionWizardState {
  step: ConnectionStep;
  selectedPlatform: DataSourceDefinition | null;
  configuration: Record<string, any>;
  testResult: ConnectionTestResult | null;
  error: string | null;
}

/**
 * Result of connection test
 */
export interface ConnectionTestResult {
  success: boolean;
  message: string;
  details?: Record<string, any>;
}

// =============================================================================
// OAuth Flow Types
// =============================================================================

/**
 * Response from initiating OAuth flow
 */
export interface OAuthInitiateResponse {
  authorization_url: string;
  state: string; // CSRF token
  connection_id?: string; // Optional: for tracking the connection being created
}

/**
 * Parameters from OAuth callback redirect
 */
export interface OAuthCallbackParams {
  code: string;
  state: string;
}

/**
 * Response from completing OAuth flow
 */
export interface OAuthCompleteResponse {
  success: boolean;
  connection_id: string;
  message: string;
  error?: string;
}

// =============================================================================
// Sync Configuration Types
// =============================================================================

/**
 * Sync frequency options
 */
export type SyncFrequency = 'hourly' | 'daily' | 'weekly';

/**
 * Sync configuration for a data source connection
 */
export interface SyncConfig {
  start_date: string; // ISO date format (YYYY-MM-DD)
  sync_frequency: SyncFrequency;
  enabled_streams?: string[]; // Optional: specific data streams to sync
}

/**
 * Request to update sync configuration
 */
export interface UpdateSyncConfigRequest {
  sync_frequency?: SyncFrequency;
  enabled_streams?: string[];
}

// =============================================================================
// API Response Types
// =============================================================================

/**
 * Response from catalog endpoint
 */
export interface CatalogResponse {
  sources: DataSourceDefinition[];
  total: number;
}
