/**
 * What Changed API Service
 *
 * Handles API calls for the "What Changed?" debug panel:
 * - Getting summary data for panel header
 * - Getting data freshness status
 * - Listing recent syncs
 * - Listing AI action activity
 * - Listing connector status changes
 *
 * Story 9.8 - "What Changed?" Debug Panel
 */

import type {
  ChangeEventsListResponse,
  WhatChangedSummary,
  DataFreshness,
  RecentSyncsResponse,
  AIActionsResponse,
  ConnectorStatusChangesResponse,
  ChangeEventsFilters,
} from '../types/whatChanged';
import { API_BASE_URL, createHeadersAsync, handleResponse, buildQueryString } from './apiUtils';

/**
 * List data change events with optional filtering.
 *
 * @param filters - Optional filters for events
 * @returns List of events with pagination info
 */
export async function listChangeEvents(
  filters: ChangeEventsFilters = {}
): Promise<ChangeEventsListResponse> {
  const queryString = buildQueryString(filters);
  const response = await fetch(`${API_BASE_URL}/api/what-changed${queryString}`, {
    method: 'GET',
    headers: await createHeadersAsync(),
  });
  return handleResponse<ChangeEventsListResponse>(response);
}

/**
 * Get summary for the debug panel header.
 *
 * @param days - Number of days to look back (default 7)
 * @returns Summary with freshness, counts, and last updated
 */
export async function getSummary(days: number = 7): Promise<WhatChangedSummary> {
  const params = new URLSearchParams();
  params.append('days', String(days));

  const response = await fetch(
    `${API_BASE_URL}/api/what-changed/summary?${params.toString()}`,
    {
      method: 'GET',
      headers: await createHeadersAsync(),
    }
  );
  return handleResponse<WhatChangedSummary>(response);
}

/**
 * Get data freshness status.
 *
 * @returns Overall freshness and per-connector breakdown
 */
export async function getFreshnessStatus(): Promise<DataFreshness> {
  const response = await fetch(`${API_BASE_URL}/api/what-changed/freshness`, {
    method: 'GET',
    headers: await createHeadersAsync(),
  });
  return handleResponse<DataFreshness>(response);
}

/**
 * Get recent sync activity.
 *
 * @param days - Number of days to look back (default 7)
 * @param limit - Maximum syncs to return (default 20)
 * @returns List of recent syncs
 */
export async function getRecentSyncs(
  days: number = 7,
  limit: number = 20
): Promise<RecentSyncsResponse> {
  const params = new URLSearchParams();
  params.append('days', String(days));
  params.append('limit', String(limit));

  const response = await fetch(
    `${API_BASE_URL}/api/what-changed/recent-syncs?${params.toString()}`,
    {
      method: 'GET',
      headers: await createHeadersAsync(),
    }
  );
  return handleResponse<RecentSyncsResponse>(response);
}

/**
 * Get recent AI action activity.
 *
 * @param days - Number of days to look back (default 7)
 * @param limit - Maximum actions to return (default 20)
 * @returns List of AI action summaries
 */
export async function getAIActions(
  days: number = 7,
  limit: number = 20
): Promise<AIActionsResponse> {
  const params = new URLSearchParams();
  params.append('days', String(days));
  params.append('limit', String(limit));

  const response = await fetch(
    `${API_BASE_URL}/api/what-changed/ai-actions?${params.toString()}`,
    {
      method: 'GET',
      headers: await createHeadersAsync(),
    }
  );
  return handleResponse<AIActionsResponse>(response);
}

/**
 * Get recent connector status changes.
 *
 * @param days - Number of days to look back (default 7)
 * @returns List of connector status changes
 */
export async function getConnectorStatusChanges(
  days: number = 7
): Promise<ConnectorStatusChangesResponse> {
  const params = new URLSearchParams();
  params.append('days', String(days));

  const response = await fetch(
    `${API_BASE_URL}/api/what-changed/connector-status?${params.toString()}`,
    {
      method: 'GET',
      headers: await createHeadersAsync(),
    }
  );
  return handleResponse<ConnectorStatusChangesResponse>(response);
}

/**
 * Check if there are any critical issues.
 *
 * Convenience function for showing alerts.
 *
 * @returns True if there are critical events in the last 24 hours
 */
export async function hasCriticalIssues(): Promise<boolean> {
  const summary = await getSummary(1);
  return (
    summary.data_freshness.overall_status === 'critical' ||
    summary.open_incidents_count > 0
  );
}

/**
 * Get count of recent changes.
 *
 * Convenience function for badge displays.
 *
 * @param days - Number of days to look back (default 7)
 * @returns Number of change events
 */
export async function getRecentChangesCount(days: number = 7): Promise<number> {
  const events = await listChangeEvents({ days, limit: 1 });
  return events.total;
}
