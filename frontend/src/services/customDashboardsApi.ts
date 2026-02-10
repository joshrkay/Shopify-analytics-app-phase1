/**
 * Custom Dashboards API Service
 *
 * Handles API calls for user-created custom dashboards:
 * - Listing dashboards
 * - Getting dashboard details
 * - Creating, updating, deleting dashboards
 *
 * Uses async token refresh to handle long builder sessions
 * where Clerk tokens may expire.
 *
 * Phase 2D - Dashboard Builder API Layer
 */

import type {
  CustomDashboard,
  CustomDashboardListResponse,
  CreateDashboardRequest,
  UpdateDashboardRequest,
  DashboardFilters,
} from '../types/customDashboards';
import {
  API_BASE_URL,
  createHeadersAsync,
  handleResponse,
  buildQueryString,
} from './apiUtils';

/**
 * List custom dashboards for the current tenant.
 */
export async function listDashboards(
  filters: DashboardFilters = {},
): Promise<CustomDashboardListResponse> {
  const queryString = buildQueryString(filters);
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/custom-dashboards${queryString}`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<CustomDashboardListResponse>(response);
}

/**
 * Get a single dashboard by ID.
 */
export async function getDashboard(
  dashboardId: string,
): Promise<CustomDashboard> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/custom-dashboards/${dashboardId}`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<CustomDashboard>(response);
}

/**
 * Create a new custom dashboard.
 */
export async function createDashboard(
  body: CreateDashboardRequest,
): Promise<CustomDashboard> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/custom-dashboards`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return handleResponse<CustomDashboard>(response);
}

/**
 * Update an existing dashboard.
 *
 * Keeps a previousState reference for optimistic UI rollback
 * if the API call fails.
 */
export async function updateDashboard(
  dashboardId: string,
  body: UpdateDashboardRequest,
): Promise<CustomDashboard> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/custom-dashboards/${dashboardId}`,
    {
      method: 'PUT',
      headers,
      body: JSON.stringify(body),
    },
  );
  return handleResponse<CustomDashboard>(response);
}

/**
 * Delete a custom dashboard and all its reports.
 */
export async function deleteDashboard(
  dashboardId: string,
): Promise<void> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/custom-dashboards/${dashboardId}`,
    {
      method: 'DELETE',
      headers,
    },
  );
  if (!response.ok) {
    return handleResponse<void>(response);
  }
}
