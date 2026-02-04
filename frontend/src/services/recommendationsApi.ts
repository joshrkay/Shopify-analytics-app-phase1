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
import { API_BASE_URL, createHeaders, handleResponse, buildQueryString } from './apiUtils';

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
