/**
 * Custom Reports API Service
 *
 * Handles API calls for reports nested under dashboards:
 * - Listing reports for a dashboard
 * - Creating, updating, deleting reports
 * - Reordering reports within a dashboard
 *
 * All endpoints are nested under /api/v1/dashboards/{dashboardId}/reports.
 *
 * Uses async token refresh to handle long builder sessions.
 */

import type {
  Report,
  CreateReportRequest,
  UpdateReportRequest,
  ReorderReportsRequest,
} from '../types/customDashboards';
import {
  API_BASE_URL,
  createHeadersAsync,
  handleResponse,
} from './apiUtils';

/**
 * Build the base URL for reports under a dashboard.
 */
function reportsBaseUrl(dashboardId: string): string {
  return `${API_BASE_URL}/api/v1/dashboards/${dashboardId}/reports`;
}

/**
 * List all reports for a dashboard.
 */
export async function listReports(
  dashboardId: string,
): Promise<Report[]> {
  const headers = await createHeadersAsync();
  const response = await fetch(reportsBaseUrl(dashboardId), {
    method: 'GET',
    headers,
  });
  return handleResponse<Report[]>(response);
}

/**
 * Create a new report in a dashboard.
 */
export async function createReport(
  dashboardId: string,
  body: CreateReportRequest,
): Promise<Report> {
  const headers = await createHeadersAsync();
  const response = await fetch(reportsBaseUrl(dashboardId), {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return handleResponse<Report>(response);
}

/**
 * Update an existing report within a dashboard.
 */
export async function updateReport(
  dashboardId: string,
  reportId: string,
  body: UpdateReportRequest,
): Promise<Report> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${reportsBaseUrl(dashboardId)}/${reportId}`,
    {
      method: 'PUT',
      headers,
      body: JSON.stringify(body),
    },
  );
  return handleResponse<Report>(response);
}

/**
 * Delete a report from a dashboard.
 */
export async function deleteReport(
  dashboardId: string,
  reportId: string,
): Promise<void> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${reportsBaseUrl(dashboardId)}/${reportId}`,
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
 * Reorder reports within a dashboard.
 */
export async function reorderReports(
  dashboardId: string,
  body: ReorderReportsRequest,
): Promise<Report[]> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${reportsBaseUrl(dashboardId)}/reorder`,
    {
      method: 'PUT',
      headers,
      body: JSON.stringify(body),
    },
  );
  return handleResponse<Report[]>(response);
}
