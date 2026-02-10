/**
 * Dashboards API Service
 *
 * Handles API calls for user-created dashboards:
 * - Listing dashboards (with filters)
 * - Getting dashboard details
 * - Creating, updating, deleting dashboards
 * - Publishing and duplicating dashboards
 * - Dashboard count (billing limits)
 * - Version history and restore
 * - Audit trail
 *
 * Uses async token refresh to handle long builder sessions
 * where Clerk tokens may expire.
 *
 * Phase 2D - Dashboard Builder API Layer
 */

import type {
  Dashboard,
  DashboardListResponse,
  CreateDashboardRequest,
  UpdateDashboardRequest,
  DashboardFilters,
  DashboardCountResponse,
  VersionListResponse,
  DashboardVersionDetail,
  AuditListResponse,
} from '../types/customDashboards';
import {
  API_BASE_URL,
  createHeadersAsync,
  handleResponse,
  buildQueryString,
} from './apiUtils';

/**
 * List dashboards for the current tenant.
 */
export async function listDashboards(
  filters: DashboardFilters = {},
): Promise<DashboardListResponse> {
  const queryString = buildQueryString(filters);
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards${queryString}`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<DashboardListResponse>(response);
}

/**
 * Get a single dashboard by ID.
 */
export async function getDashboard(
  dashboardId: string,
): Promise<Dashboard> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards/${dashboardId}`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<Dashboard>(response);
}

/**
 * Create a new dashboard.
 */
export async function createDashboard(
  body: CreateDashboardRequest,
): Promise<Dashboard> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/v1/dashboards`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return handleResponse<Dashboard>(response);
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
): Promise<Dashboard> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards/${dashboardId}`,
    {
      method: 'PUT',
      headers,
      body: JSON.stringify(body),
    },
  );
  return handleResponse<Dashboard>(response);
}

/**
 * Delete a dashboard and all its reports.
 */
export async function deleteDashboard(
  dashboardId: string,
): Promise<void> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards/${dashboardId}`,
    {
      method: 'DELETE',
      headers,
    },
  );
  if (!response.ok) {
    return handleResponse<void>(response);
  }
}

/**
 * Publish a draft dashboard, changing its status to "published".
 */
export async function publishDashboard(
  dashboardId: string,
): Promise<Dashboard> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards/${dashboardId}/publish`,
    {
      method: 'POST',
      headers,
    },
  );
  return handleResponse<Dashboard>(response);
}

/**
 * Duplicate an existing dashboard under a new name.
 */
export async function duplicateDashboard(
  dashboardId: string,
  newName: string,
): Promise<Dashboard> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards/${dashboardId}/duplicate`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify({ new_name: newName }),
    },
  );
  return handleResponse<Dashboard>(response);
}

/**
 * Get the dashboard count and billing-tier limit for the current tenant.
 */
export async function getDashboardCount(): Promise<DashboardCountResponse> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards/count`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<DashboardCountResponse>(response);
}

/**
 * List version history entries for a dashboard.
 */
export async function listVersions(
  dashboardId: string,
  offset?: number,
  limit?: number,
): Promise<VersionListResponse> {
  const queryString = buildQueryString({ offset, limit });
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards/${dashboardId}/versions${queryString}`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<VersionListResponse>(response);
}

/**
 * Get a single version with its full snapshot for preview.
 */
export async function getVersion(
  dashboardId: string,
  versionNumber: number,
): Promise<DashboardVersionDetail> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards/${dashboardId}/versions/${versionNumber}`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<DashboardVersionDetail>(response);
}

/**
 * Restore a dashboard to a previous version.
 */
export async function restoreVersion(
  dashboardId: string,
  versionNumber: number,
): Promise<Dashboard> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards/${dashboardId}/restore/${versionNumber}`,
    {
      method: 'POST',
      headers,
    },
  );
  return handleResponse<Dashboard>(response);
}

/**
 * List audit trail entries for a dashboard.
 */
export async function listAuditEntries(
  dashboardId: string,
  offset?: number,
  limit?: number,
): Promise<AuditListResponse> {
  const queryString = buildQueryString({ offset, limit });
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/dashboards/${dashboardId}/audit${queryString}`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<AuditListResponse>(response);
}
