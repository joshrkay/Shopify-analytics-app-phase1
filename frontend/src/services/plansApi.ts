/**
 * Plans API Service
 *
 * Handles all API calls for admin plan management.
 */

import type {
  Plan,
  PlansListResponse,
  CreatePlanRequest,
  UpdatePlanRequest,
  PlanFeature,
  ToggleFeatureRequest,
  ShopifyValidationRequest,
  ShopifyValidationResponse,
} from '../types/plans';
import { API_BASE_URL, createHeaders } from './apiUtils';
import type { ApiError } from './apiUtils';

async function fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
  const response = await fetch(`${API_BASE_URL}${url}`, {
    ...options,
    headers: {
      ...createHeaders(),
      ...options.headers,
    },
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    const error = new Error(errorData.detail || `HTTP ${response.status}`) as ApiError;
    error.status = response.status;
    error.detail = errorData.detail;
    throw error;
  }

  return response;
}

export const plansApi = {
  /**
   * List all plans with optional pagination and filters
   */
  async listPlans(params?: {
    include_inactive?: boolean;
    limit?: number;
    offset?: number;
  }): Promise<PlansListResponse> {
    const searchParams = new URLSearchParams();
    if (params?.include_inactive) {
      searchParams.set('include_inactive', 'true');
    }
    if (params?.limit) {
      searchParams.set('limit', params.limit.toString());
    }
    if (params?.offset) {
      searchParams.set('offset', params.offset.toString());
    }

    const queryString = searchParams.toString();
    const url = `/admin/plans${queryString ? `?${queryString}` : ''}`;

    const response = await fetchWithAuth(url);
    return response.json();
  },

  /**
   * Get a specific plan by ID
   */
  async getPlan(planId: string): Promise<Plan> {
    const response = await fetchWithAuth(`/admin/plans/${planId}`);
    return response.json();
  },

  /**
   * Create a new plan
   */
  async createPlan(data: CreatePlanRequest): Promise<Plan> {
    const response = await fetchWithAuth('/admin/plans', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    return response.json();
  },

  /**
   * Update an existing plan
   */
  async updatePlan(planId: string, data: UpdatePlanRequest): Promise<Plan> {
    const response = await fetchWithAuth(`/admin/plans/${planId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
    return response.json();
  },

  /**
   * Toggle a feature on/off for a plan
   */
  async toggleFeature(
    planId: string,
    data: ToggleFeatureRequest
  ): Promise<PlanFeature> {
    const response = await fetchWithAuth(`/admin/plans/${planId}/features/toggle`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
    return response.json();
  },

  /**
   * Delete a plan (use with caution - prefer deactivating)
   */
  async deletePlan(planId: string): Promise<void> {
    await fetchWithAuth(`/admin/plans/${planId}`, {
      method: 'DELETE',
    });
  },

  /**
   * Validate Shopify plan sync
   */
  async validateShopifySync(
    planId: string,
    data: ShopifyValidationRequest
  ): Promise<ShopifyValidationResponse> {
    const response = await fetchWithAuth(`/admin/plans/${planId}/validate-shopify`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
    return response.json();
  },
};

export { isApiError } from './apiUtils';
export type { ApiError } from './apiUtils';
export default plansApi;
