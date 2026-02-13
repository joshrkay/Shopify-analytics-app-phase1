/**
 * Datasets API Service
 *
 * Handles API calls for dataset discovery and chart preview:
 * - Listing available datasets with column metadata
 * - Getting columns for a specific dataset
 * - Validating report config columns
 * - Executing chart preview queries
 *
 * Phase 2A/2B - Dataset Discovery + Chart Preview
 */

import type {
  DatasetListResponse,
  ColumnMetadata,
  ValidateConfigRequest,
  ValidateConfigResponse,
  ChartPreviewRequest,
  ChartPreviewResponse,
} from '../types/customDashboards';
import {
  API_BASE_URL,
  createHeadersAsync,
  handleResponse,
} from './apiUtils';
import { API_ROUTES } from './apiRoutes';

/**
 * List available datasets with column metadata.
 *
 * Returns cached data with stale flag if Superset is unavailable.
 */
export async function listDatasets(): Promise<DatasetListResponse> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}${API_ROUTES.datasets}`, {
    method: 'GET',
    headers,
  });
  return handleResponse<DatasetListResponse>(response);
}

/**
 * Get column metadata for a specific dataset.
 *
 * @param datasetId - Superset dataset ID
 */
export async function getDatasetColumns(
  datasetId: number,
): Promise<ColumnMetadata[]> {
  const headers = await createHeadersAsync();
  const response = await fetch(
    `${API_BASE_URL}${API_ROUTES.datasets}/${datasetId}/columns`,
    {
      method: 'GET',
      headers,
    },
  );
  return handleResponse<ColumnMetadata[]>(response);
}

/**
 * Validate that columns in a report config still exist in the dataset.
 *
 * Returns warnings for missing columns (non-blocking).
 */
export async function validateConfig(
  body: ValidateConfigRequest,
): Promise<ValidateConfigResponse> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}${API_ROUTES.datasets}/validate-config`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return handleResponse<ValidateConfigResponse>(response);
}

/**
 * Execute a chart preview query.
 *
 * Returns formatted data with 100-row limit and 10s timeout.
 * Results are cached server-side for 60s.
 */
export async function chartPreview(
  body: ChartPreviewRequest,
): Promise<ChartPreviewResponse> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}${API_ROUTES.datasetsPreview}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  return handleResponse<ChartPreviewResponse>(response);
}
