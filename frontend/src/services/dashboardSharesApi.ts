/**
 * Dashboard Shares API Service
 *
 * Handles API calls for sharing custom dashboards:
 * - Listing shares for a dashboard
 * - Creating a share (invite user)
 * - Updating a share's permission or expiry
 * - Revoking a share
 *
 * Uses async token refresh to handle long builder sessions.
 *
 * Phase 2D - Dashboard Sharing API Layer
 */

import type {
  ShareListResponse,
  CreateShareRequest,
  UpdateShareRequest,
  DashboardShare,
} from '../types/customDashboards';
import {
  API_BASE_URL,
  createHeadersAsync,
  handleResponse,
} from './apiUtils';

/**
 * List shares for a dashboard.
 */
export async function listShares(
  dashboardId: string,
): Promise<ShareListResponse> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards/${dashboardId}/shares`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<ShareListResponse>(response);
}

/**
 * Share a dashboard with another user.
 */
export async function createShare(
  dashboardId: string,
  body: CreateShareRequest,
): Promise<DashboardShare> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards/${dashboardId}/shares`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    },
  );
  return handleResponse<DashboardShare>(response);
}

/**
 * Update a dashboard share's permission or expiry.
 */
export async function updateShare(
  dashboardId: string,
  shareId: string,
  body: UpdateShareRequest,
): Promise<DashboardShare> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards/${dashboardId}/shares/${shareId}`,
    {
      method: 'PUT',
      headers,
      body: JSON.stringify(body),
    },
  );
  return handleResponse<DashboardShare>(response);
}

/**
 * Revoke a dashboard share.
 */
export async function revokeShare(
  dashboardId: string,
  shareId: string,
): Promise<void> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards/${dashboardId}/shares/${shareId}`,
    {
      method: 'DELETE',
      headers,
    },
  );
  if (!response.ok) {
    return handleResponse<void>(response);
  }
}
