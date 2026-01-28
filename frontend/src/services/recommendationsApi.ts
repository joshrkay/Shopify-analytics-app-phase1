/**
 * AI Recommendations API Service
 *
 * Handles API calls for AI-generated recommendations:
 * - Listing recommendations with filtering
 * - Accepting recommendations (advisory tracking)
 * - Dismissing recommendations
 *
 * Story 9.3 - Insight & Recommendation UX
 */

import type {
  Recommendation,
  RecommendationsListResponse,
  RecommendationActionResponse,
  RecommendationsFilters,
} from '../types/recommendations';

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
function buildQueryString(filters: RecommendationsFilters): string {
  const params = new URLSearchParams();

  if (filters.recommendation_type) {
    params.append('recommendation_type', filters.recommendation_type);
  }
  if (filters.priority) {
    params.append('priority', filters.priority);
  }
  if (filters.risk_level) {
    params.append('risk_level', filters.risk_level);
  }
  if (filters.related_insight_id) {
    params.append('related_insight_id', filters.related_insight_id);
  }
  if (filters.include_dismissed !== undefined) {
    params.append('include_dismissed', String(filters.include_dismissed));
  }
  if (filters.include_accepted !== undefined) {
    params.append('include_accepted', String(filters.include_accepted));
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
 * List AI recommendations with optional filtering.
 *
 * @param filters - Optional filters for recommendations
 * @returns List of recommendations with pagination info
 */
export async function listRecommendations(
  filters: RecommendationsFilters = {}
): Promise<RecommendationsListResponse> {
  const queryString = buildQueryString(filters);
  const response = await fetch(`${API_BASE_URL}/api/recommendations${queryString}`, {
    method: 'GET',
    headers: createHeaders(),
  });
  return handleResponse<RecommendationsListResponse>(response);
}

/**
 * Get a single recommendation by ID.
 *
 * @param recommendationId - The recommendation ID
 * @returns The recommendation details
 */
export async function getRecommendation(
  recommendationId: string
): Promise<Recommendation> {
  const response = await fetch(
    `${API_BASE_URL}/api/recommendations/${recommendationId}`,
    {
      method: 'GET',
      headers: createHeaders(),
    }
  );
  return handleResponse<Recommendation>(response);
}

/**
 * Get recommendations related to a specific insight.
 *
 * @param insightId - The insight ID
 * @returns List of related recommendations
 */
export async function getRecommendationsForInsight(
  insightId: string
): Promise<RecommendationsListResponse> {
  return listRecommendations({
    related_insight_id: insightId,
    include_dismissed: false,
  });
}

/**
 * Accept a recommendation (advisory tracking only).
 *
 * This does NOT execute any action - recommendations are advisory only.
 *
 * @param recommendationId - The recommendation ID to accept
 * @returns Action response
 */
export async function acceptRecommendation(
  recommendationId: string
): Promise<RecommendationActionResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/recommendations/${recommendationId}/accept`,
    {
      method: 'PATCH',
      headers: createHeaders(),
    }
  );
  return handleResponse<RecommendationActionResponse>(response);
}

/**
 * Dismiss a recommendation (hide from default list).
 *
 * Dismissed recommendations can be recovered by listing with include_dismissed=true.
 *
 * @param recommendationId - The recommendation ID to dismiss
 * @returns Action response
 */
export async function dismissRecommendation(
  recommendationId: string
): Promise<RecommendationActionResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/recommendations/${recommendationId}/dismiss`,
    {
      method: 'PATCH',
      headers: createHeaders(),
    }
  );
  return handleResponse<RecommendationActionResponse>(response);
}

/**
 * Dismiss multiple recommendations in batch.
 *
 * @param recommendationIds - Array of recommendation IDs to dismiss
 * @returns Batch action response with count of updated items
 */
export async function dismissRecommendationsBatch(
  recommendationIds: string[]
): Promise<{ status: string; updated: number }> {
  const response = await fetch(`${API_BASE_URL}/api/recommendations/batch/dismiss`, {
    method: 'POST',
    headers: createHeaders(),
    body: JSON.stringify(recommendationIds),
  });
  return handleResponse<{ status: string; updated: number }>(response);
}

/**
 * Get count of active (not dismissed) recommendations.
 *
 * @returns Count of active recommendations
 */
export async function getActiveRecommendationsCount(): Promise<number> {
  const response = await listRecommendations({
    include_dismissed: false,
    limit: 1,
  });
  return response.total;
}
