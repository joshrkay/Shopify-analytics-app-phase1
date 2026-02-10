/**
 * Custom Reports API Service
 *
 * Handles API calls for reports within custom dashboards:
 * - Listing reports for a dashboard
 * - Getting report details (with column validation warnings)
 * - Creating, updating, deleting reports
 *
 * Uses async token refresh to handle long builder sessions.
 *
 * Phase 2D - Report Builder API Layer
 */

import type {
  CustomReport,
  CustomReportListResponse,
  CreateReportRequest,
  UpdateReportRequest,
  ReportFilters,
} from '../types/customDashboards';
import {
  API_BASE_URL,
  createHeadersAsync,
  handleResponse,
  buildQueryString,
} from './apiUtils';

/**
 * List reports for a dashboard.
 */
export async function listReports(
  filters: ReportFilters = {},
): Promise<CustomReportListResponse> {
  const queryString = buildQueryString(filters);
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/custom-reports${queryString}`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<CustomReportListResponse>(response);
}

/**
 * Get a single report by ID.
 *
 * Includes warnings[] array if any referenced columns no longer exist
 * in the dataset (e.g., after a schema change).
 */
export async function getReport(
  reportId: string,
): Promise<CustomReport> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/custom-reports/${reportId}`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<CustomReport>(response);
}

/**
 * Create a new report in a dashboard.
 */
export async function createReport(
  body: CreateReportRequest,
): Promise<CustomReport> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/custom-reports`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return handleResponse<CustomReport>(response);
}

/**
 * Update an existing report.
 *
 * For position updates (drag & drop), the caller should keep a
 * previousState reference for optimistic UI rollback on failure.
 */
export async function updateReport(
  reportId: string,
  body: UpdateReportRequest,
): Promise<CustomReport> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/custom-reports/${reportId}`,
    {
      method: 'PUT',
      headers,
      body: JSON.stringify(body),
    },
  );
  return handleResponse<CustomReport>(response);
}

/**
 * Delete a report from a dashboard.
 */
export async function deleteReport(
  reportId: string,
): Promise<void> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/custom-reports/${reportId}`,
    {
      method: 'DELETE',
      headers,
    },
  );
  if (!response.ok) {
    return handleResponse<void>(response);
  }
}
