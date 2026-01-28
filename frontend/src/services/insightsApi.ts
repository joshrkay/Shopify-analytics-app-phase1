/**
 * AI Insights API Service
 *
 * Handles API calls for AI-generated insights:
 * - Listing insights with filtering
 * - Marking insights as read
 * - Dismissing insights
 * - Recovering dismissed insights
 *
 * Story 9.3 - Insight & Recommendation UX
 */

import type {
  Insight,
  InsightsListResponse,
  InsightActionResponse,
  InsightsFilters,
} from '../types/insights';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/**
 * Get the current JWT token from localStorage.
 */
function getAuthToken(): string | null {
  return localStorage.getItem('jwt_token') || localStorage.getItem('auth_token');
}

/**
 * Create headers with authentication.
 */
function createHeaders(): HeadersInit {
  const token = getAuthToken();
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

/**
 * Handle API response and throw on error.
 */
async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    const error = new Error(errorData.detail || `API error: ${response.status}`);
    (error as Error & { status: number; detail: string }).status = response.status;
    (error as Error & { status: number; detail: string }).detail = errorData.detail;
    throw error;
  }
  return response.json();
}

/**
 * Build query string from filters.
 */
function buildQueryString(filters: InsightsFilters): string {
  const params = new URLSearchParams();

  if (filters.insight_type) {
    params.append('insight_type', filters.insight_type);
  }
  if (filters.severity) {
    params.append('severity', filters.severity);
  }
  if (filters.include_dismissed !== undefined) {
    params.append('include_dismissed', String(filters.include_dismissed));
  }
  if (filters.include_read !== undefined) {
    params.append('include_read', String(filters.include_read));
  }
  if (filters.limit !== undefined) {
    params.append('limit', String(filters.limit));
  }
  if (filters.offset !== undefined) {
    params.append('offset', String(filters.offset));
  }

  const queryString = params.toString();
  return queryString ? `?${queryString}` : '';
}

/**
 * List AI insights with optional filtering.
 *
 * @param filters - Optional filters for insights
 * @returns List of insights with pagination info
 */
export async function listInsights(
  filters: InsightsFilters = {}
): Promise<InsightsListResponse> {
  const queryString = buildQueryString(filters);
  const response = await fetch(`${API_BASE_URL}/api/insights${queryString}`, {
    method: 'GET',
    headers: createHeaders(),
  });
  return handleResponse<InsightsListResponse>(response);
}

/**
 * Get a single insight by ID.
 *
 * @param insightId - The insight ID
 * @returns The insight details
 */
export async function getInsight(insightId: string): Promise<Insight> {
  const response = await fetch(`${API_BASE_URL}/api/insights/${insightId}`, {
    method: 'GET',
    headers: createHeaders(),
  });
  return handleResponse<Insight>(response);
}

/**
 * Mark an insight as read.
 *
 * @param insightId - The insight ID to mark as read
 * @returns Action response
 */
export async function markInsightRead(
  insightId: string
): Promise<InsightActionResponse> {
  const response = await fetch(`${API_BASE_URL}/api/insights/${insightId}/read`, {
    method: 'PATCH',
    headers: createHeaders(),
  });
  return handleResponse<InsightActionResponse>(response);
}

/**
 * Dismiss an insight (hide from default list).
 *
 * Dismissed insights can be recovered by listing with include_dismissed=true.
 *
 * @param insightId - The insight ID to dismiss
 * @returns Action response
 */
export async function dismissInsight(
  insightId: string
): Promise<InsightActionResponse> {
  const response = await fetch(`${API_BASE_URL}/api/insights/${insightId}/dismiss`, {
    method: 'PATCH',
    headers: createHeaders(),
  });
  return handleResponse<InsightActionResponse>(response);
}

/**
 * Mark multiple insights as read in batch.
 *
 * @param insightIds - Array of insight IDs to mark as read
 * @returns Batch action response with count of updated items
 */
export async function markInsightsReadBatch(
  insightIds: string[]
): Promise<{ status: string; updated: number }> {
  const response = await fetch(`${API_BASE_URL}/api/insights/batch/read`, {
    method: 'POST',
    headers: createHeaders(),
    body: JSON.stringify(insightIds),
  });
  return handleResponse<{ status: string; updated: number }>(response);
}

/**
 * Get count of unread insights.
 *
 * Useful for badge displays.
 *
 * @returns Count of unread insights
 */
export async function getUnreadInsightsCount(): Promise<number> {
  const response = await listInsights({
    include_read: false,
    include_dismissed: false,
    limit: 1,
  });
  return response.total;
}
