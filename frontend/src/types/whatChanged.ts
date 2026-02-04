/**
 * What Changed types for Story 9.8 - "What Changed?" Debug Panel
 *
 * Provides type definitions for the merchant-safe debug panel.
 */

// Import shared utilities
import {
  formatRelativeTime as _formatRelativeTime,
  formatDuration,
  formatRowCount,
} from '../utils/dateUtils';

// Re-export shared utilities for backwards compatibility
export { formatDuration, formatRowCount };

/**
 * Format relative time (e.g., "2 hours ago").
 * Uses verbose format for backwards compatibility with existing consumers.
 */
export function formatRelativeTime(dateString: string): string {
  return _formatRelativeTime(dateString, { verbose: true });
}

// =============================================================================
// Enum Types
// =============================================================================

/**
 * Types of data change events.
 */
export type DataChangeEventType =
  | 'sync_completed'
  | 'sync_failed'
  | 'backfill_completed'
  | 'metric_version_changed'
  | 'ai_action_executed'
  | 'ai_action_approved'
  | 'ai_action_rejected'
  | 'connector_status_changed'
  | 'connector_added'
  | 'connector_removed'
  | 'data_quality_incident'
  | 'data_quality_resolved';

/**
 * Freshness status levels.
 */
export type FreshnessStatus = 'fresh' | 'stale' | 'critical' | 'error' | 'unknown';

/**
 * Sync status.
 */
export type SyncStatus = 'success' | 'failed' | 'running';

/**
 * AI action status.
 */
export type AIActionStatus = 'approved' | 'rejected' | 'executed' | 'pending';

// =============================================================================
// Data Interfaces
// =============================================================================

/**
 * A data change event as returned by the API.
 */
export interface DataChangeEvent {
  id: string;
  event_type: DataChangeEventType;
  title: string;
  description: string;
  affected_metrics: string[];
  affected_connector_name?: string;
  impact_summary?: string;
  affected_date_start?: string;
  affected_date_end?: string;
  occurred_at: string;
}

/**
 * Freshness status for a single connector.
 */
export interface ConnectorFreshness {
  connector_id: string;
  connector_name: string;
  status: FreshnessStatus;
  last_sync_at?: string;
  minutes_since_sync?: number;
  source_type?: string;
}

/**
 * Overall data freshness status.
 */
export interface DataFreshness {
  overall_status: FreshnessStatus;
  last_sync_at?: string;
  hours_since_sync?: number;
  connectors: ConnectorFreshness[];
}

/**
 * Recent sync information.
 */
export interface RecentSync {
  sync_id: string;
  connector_id: string;
  connector_name: string;
  source_type?: string;
  status: SyncStatus;
  started_at: string;
  completed_at?: string;
  rows_synced?: number;
  duration_seconds?: number;
  error_message?: string;
}

/**
 * AI action summary.
 */
export interface AIActionSummary {
  action_id: string;
  action_type: string;
  status: AIActionStatus;
  target_name: string;
  target_platform?: string;
  performed_at: string;
  performed_by?: string;
}

/**
 * Connector status change.
 */
export interface ConnectorStatusChange {
  connector_id: string;
  connector_name: string;
  previous_status: string;
  new_status: string;
  changed_at: string;
  reason?: string;
}

// =============================================================================
// Response Interfaces
// =============================================================================

/**
 * Response for change events list queries.
 */
export interface ChangeEventsListResponse {
  events: DataChangeEvent[];
  total: number;
  has_more: boolean;
}

/**
 * Summary for the debug panel header.
 */
export interface WhatChangedSummary {
  data_freshness: DataFreshness;
  recent_syncs_count: number;
  recent_ai_actions_count: number;
  open_incidents_count: number;
  metric_changes_count: number;
  last_updated: string;
}

/**
 * Response for recent syncs query.
 */
export interface RecentSyncsResponse {
  syncs: RecentSync[];
  total: number;
}

/**
 * Response for AI actions query.
 */
export interface AIActionsResponse {
  actions: AIActionSummary[];
  total: number;
}

/**
 * Response for connector status changes query.
 */
export interface ConnectorStatusChangesResponse {
  changes: ConnectorStatusChange[];
  total: number;
}

// =============================================================================
// Request/Filter Interfaces
// =============================================================================

/**
 * Filters for change events queries.
 */
export interface ChangeEventsFilters {
  event_type?: DataChangeEventType;
  connector_id?: string;
  metric?: string;
  days?: number;
  limit?: number;
  offset?: number;
}

// =============================================================================
// Utility Functions
// =============================================================================

/**
 * Get human-readable label for an event type.
 */
export function getEventTypeLabel(type: DataChangeEventType): string {
  const labels: Record<DataChangeEventType, string> = {
    sync_completed: 'Sync Completed',
    sync_failed: 'Sync Failed',
    backfill_completed: 'Backfill Completed',
    metric_version_changed: 'Metric Updated',
    ai_action_executed: 'AI Action Executed',
    ai_action_approved: 'AI Action Approved',
    ai_action_rejected: 'AI Action Rejected',
    connector_status_changed: 'Connector Status Changed',
    connector_added: 'Connector Added',
    connector_removed: 'Connector Removed',
    data_quality_incident: 'Data Quality Issue',
    data_quality_resolved: 'Issue Resolved',
  };
  return labels[type] || type;
}

/**
 * Get badge tone for an event type (for Polaris Badge).
 */
export function getEventTypeTone(
  type: DataChangeEventType
): 'info' | 'success' | 'warning' | 'critical' | 'attention' | undefined {
  const tones: Record<DataChangeEventType, 'info' | 'success' | 'warning' | 'critical' | 'attention' | undefined> = {
    sync_completed: 'success',
    sync_failed: 'critical',
    backfill_completed: 'success',
    metric_version_changed: 'info',
    ai_action_executed: 'success',
    ai_action_approved: 'info',
    ai_action_rejected: 'attention',
    connector_status_changed: 'warning',
    connector_added: 'success',
    connector_removed: 'attention',
    data_quality_incident: 'critical',
    data_quality_resolved: 'success',
  };
  return tones[type];
}

/**
 * Get badge tone for freshness status.
 */
export function getFreshnessTone(
  status: FreshnessStatus
): 'info' | 'success' | 'warning' | 'critical' | undefined {
  const tones: Record<FreshnessStatus, 'info' | 'success' | 'warning' | 'critical' | undefined> = {
    fresh: 'success',
    stale: 'warning',
    critical: 'critical',
    error: 'critical',
    unknown: undefined,
  };
  return tones[status];
}

/**
 * Get human-readable label for freshness status.
 */
export function getFreshnessLabel(status: FreshnessStatus): string {
  const labels: Record<FreshnessStatus, string> = {
    fresh: 'Fresh',
    stale: 'Stale',
    critical: 'Critical',
    error: 'Error',
    unknown: 'Unknown',
  };
  return labels[status];
}

/**
 * Check if any events are critical.
 */
export function hasCriticalEvents(events: DataChangeEvent[]): boolean {
  return events.some(
    (e) =>
      e.event_type === 'sync_failed' ||
      e.event_type === 'data_quality_incident'
  );
}
