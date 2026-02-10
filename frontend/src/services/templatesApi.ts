/**
 * Templates API Service
 *
 * Handles API calls for report template gallery:
 * - Listing templates with billing tier filtering
 * - Getting template details
 * - Instantiating templates into dashboards
 * - Admin CRUD operations
 *
 * Phase 2C - Template System
 */

import type {
  TemplateListResponse,
  TemplateDetail,
  TemplateFilters,
  InstantiateRequest,
  InstantiateResponse,
  CreateTemplateRequest,
  UpdateTemplateRequest,
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
    `${API_BASE_URL}/api/templates${queryString}`,
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
): Promise<TemplateDetail> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/templates/${templateId}`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<TemplateDetail>(response);
}

/**
 * Instantiate a template into the user's dashboard.
 *
 * Creates a dashboard with all reports from the template.
 * Atomic - rolls back on partial failure.
 */
export async function instantiateTemplate(
  templateId: string,
  body: InstantiateRequest = {},
): Promise<InstantiateResponse> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/templates/${templateId}/instantiate`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    },
  );
  return handleResponse<InstantiateResponse>(response);
}

/**
 * Create a new template (admin-only).
 */
export async function createTemplate(
  body: CreateTemplateRequest,
): Promise<TemplateDetail> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/templates`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return handleResponse<TemplateDetail>(response);
}

/**
 * Update a template (admin-only). Bumps version.
 */
export async function updateTemplate(
  templateId: string,
  body: UpdateTemplateRequest,
): Promise<TemplateDetail> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/templates/${templateId}`,
    {
      method: 'PUT',
      headers,
      body: JSON.stringify(body),
    },
  );
  return handleResponse<TemplateDetail>(response);
}

/**
 * Deactivate a template (admin-only).
 *
 * Hides from gallery but does not affect existing dashboards.
 */
export async function deactivateTemplate(
  templateId: string,
): Promise<void> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}/api/templates/${templateId}`,
    {
      method: 'DELETE',
      headers,
    },
  );
  if (!response.ok) {
    return handleResponse<void>(response);
  }
}
