/**
 * Templates API Service
 *
 * Handles API calls for report template gallery:
 * - Listing templates with billing tier filtering
 * - Getting template details
 * - Instantiating templates into dashboards
 *
 * Phase 3 - Dashboard Builder UI
 */

import type {
  ReportTemplate,
  TemplateListResponse,
  TemplateFilters,
  Dashboard,
} from '../types/customDashboards';
import {
  API_BASE_URL,
  createHeadersAsync,
  handleResponse,
  buildQueryString,
} from './apiUtils';

/**
 * List active templates filtered by billing tier and category.
 */
export async function listTemplates(
  filters: TemplateFilters = {},
): Promise<TemplateListResponse> {
  const queryString = buildQueryString(filters);
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/templates${queryString}`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<TemplateListResponse>(response);
}

/**
 * Get full template details including config.
 */
export async function getTemplate(
  templateId: string,
): Promise<ReportTemplate> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/templates/${templateId}`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<ReportTemplate>(response);
}

/**
 * Instantiate a template into the user's dashboard.
 *
 * Creates a dashboard with all reports from the template.
 * The backend expects the dashboard name as a query parameter.
 */
export async function instantiateTemplate(
  templateId: string,
  dashboardName: string,
): Promise<Dashboard> {
  const queryString = buildQueryString({ name: dashboardName });
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/v1/templates/${templateId}/instantiate${queryString}`,
    {
      method: 'POST',
      headers,
    },
  );
  return handleResponse<Dashboard>(response);
}
