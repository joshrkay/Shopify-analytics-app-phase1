/**
 * Changelog API Service
 *
 * Handles API calls for changelog entries:
 * - Listing changelog entries with filtering
 * - Getting unread count for badges
 * - Marking entries as read
 * - Getting entries for specific feature areas (contextual badges)
 *
 * Story 9.7 - In-App Changelog & Release Notes
 */

import type {
  ChangelogEntry,
  ChangelogListResponse,
  ChangelogUnreadCountResponse,
  ChangelogMarkReadResponse,
  ChangelogFilters,
  FeatureArea,
} from '../types/changelog';
import { API_BASE_URL, createHeadersAsync, handleResponse, buildQueryString } from './apiUtils';

/**
 * List published changelog entries with optional filtering.
 *
 * @param filters - Optional filters for entries
 * @returns List of entries with pagination info and unread count
 */
export async function listChangelog(
  filters: ChangelogFilters = {}
): Promise<ChangelogListResponse> {
  const queryString = buildQueryString(filters);
  const response = await fetch(`${API_BASE_URL}/api/changelog${queryString}`, {
    method: 'GET',
    headers: await createHeadersAsync(),
  });
  return handleResponse<ChangelogListResponse>(response);
}

/**
 * Get a single changelog entry by ID.
 *
 * @param entryId - The changelog entry ID
 * @returns The changelog entry details
 */
export async function getChangelogEntry(entryId: string): Promise<ChangelogEntry> {
  const response = await fetch(`${API_BASE_URL}/api/changelog/${entryId}`, {
    method: 'GET',
    headers: await createHeadersAsync(),
  });
  return handleResponse<ChangelogEntry>(response);
}

/**
 * Get unread changelog count.
 *
 * Useful for badge displays.
 *
 * @param featureArea - Optional filter by feature area
 * @returns Unread count and breakdown by feature area
 */
export async function getUnreadCount(
  featureArea?: FeatureArea
): Promise<ChangelogUnreadCountResponse> {
  const params = new URLSearchParams();
  if (featureArea) {
    params.append('feature_area', featureArea);
  }
  const queryString = params.toString();
  const url = `${API_BASE_URL}/api/changelog/unread/count${queryString ? `?${queryString}` : ''}`;

  const response = await fetch(url, {
    method: 'GET',
    headers: await createHeadersAsync(),
  });
  return handleResponse<ChangelogUnreadCountResponse>(response);
}

/**
 * Get changelog entries for a specific feature area.
 *
 * Used for contextual banners near changed features.
 *
 * @param featureArea - The feature area to filter by
 * @param limit - Maximum entries to return (default 5)
 * @returns List of unread entries for the feature area
 */
export async function getEntriesForFeature(
  featureArea: FeatureArea,
  limit: number = 5
): Promise<ChangelogListResponse> {
  const params = new URLSearchParams();
  params.append('limit', String(limit));

  const response = await fetch(
    `${API_BASE_URL}/api/changelog/feature/${featureArea}?${params.toString()}`,
    {
      method: 'GET',
      headers: await createHeadersAsync(),
    }
  );
  return handleResponse<ChangelogListResponse>(response);
}

/**
 * Mark a changelog entry as read.
 *
 * @param entryId - The entry ID to mark as read
 * @returns Response with updated counts
 */
export async function markAsRead(entryId: string): Promise<ChangelogMarkReadResponse> {
  const response = await fetch(`${API_BASE_URL}/api/changelog/${entryId}/read`, {
    method: 'POST',
    headers: await createHeadersAsync(),
  });
  return handleResponse<ChangelogMarkReadResponse>(response);
}

/**
 * Mark all changelog entries as read.
 *
 * @returns Response with count of entries marked
 */
export async function markAllAsRead(): Promise<ChangelogMarkReadResponse> {
  const response = await fetch(`${API_BASE_URL}/api/changelog/read-all`, {
    method: 'POST',
    headers: await createHeadersAsync(),
  });
  return handleResponse<ChangelogMarkReadResponse>(response);
}

/**
 * Get simple unread count number.
 *
 * Convenience function for badge components.
 *
 * @param featureArea - Optional filter by feature area
 * @returns Number of unread entries
 */
export async function getUnreadCountNumber(featureArea?: FeatureArea): Promise<number> {
  const result = await getUnreadCount(featureArea);
  return result.count;
}
