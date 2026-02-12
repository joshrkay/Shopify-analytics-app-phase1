/**
 * Report Data API Service
 *
 * Handles API calls for executing report queries and fetching live data:
 * - Executing saved report queries with parameters
 * - Previewing data for unsaved reports (wizard mode)
 * - Query timeout handling (10s max)
 * - Error handling with graceful fallback
 *
 * Phase 2.6 - Preview Step Live Data Integration
 */

import type {
  ChartConfig,
  ChartFilter,
  ChartPreviewResponse,
} from '../types/customDashboards';
import {
  API_BASE_URL,
  createHeadersAsync,
  handleResponse,
} from './apiUtils';
import { API_ROUTES } from './apiRoutes';

// =============================================================================
// Request/Response Types
// =============================================================================

export interface ReportExecuteParams {
  date_range?: string; // e.g., "7", "30", "90", "custom"
  filters?: ChartFilter[]; // Additional filters from preview controls
  limit?: number; // Row limit (default 1000 for preview)
}

/**
 * Report data response (subset of ChartPreviewResponse with required fields)
 */
export interface ReportDataResponse {
  data: Record<string, unknown>[]; // Query result rows
  columns: string[]; // Column names
  row_count: number; // Total rows returned
  truncated: boolean; // Whether results were truncated
  query_duration_ms: number | null; // Query execution time
}

// =============================================================================
// Helper Functions
// =============================================================================

/**
 * Creates a fetch request with timeout handling and external abort signal support.
 *
 * @param url - The URL to fetch
 * @param options - Fetch options (headers, body, etc.)
 * @param timeoutMs - Timeout in milliseconds (default 10000)
 * @param externalSignal - Optional external abort signal
 * @returns Promise<Response>
 */
async function fetchWithTimeout(
  url: string,
  options: RequestInit,
  timeoutMs: number = 10000,
  externalSignal?: AbortSignal,
): Promise<Response> {
  // Create AbortController for timeout
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  // Listen to external signal for cancellation
  if (externalSignal) {
    externalSignal.addEventListener('abort', () => controller.abort());
  }

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });

    clearTimeout(timeoutId);
    return response;
  } catch (err) {
    clearTimeout(timeoutId);

    // Handle timeout errors
    if (err instanceof Error && err.name === 'AbortError') {
      const timeoutError = new Error('Query timed out after 10 seconds') as any;
      timeoutError.status = 408; // Request Timeout
      timeoutError.detail = 'Query timed out after 10 seconds';
      throw timeoutError;
    }

    throw err;
  }
}

// =============================================================================
// API Functions
// =============================================================================

/**
 * Execute a saved report's query with optional parameters.
 *
 * This endpoint is for reports that have been saved to a dashboard.
 * For unsaved reports in wizard mode, use previewReportData instead.
 *
 * @param reportId - UUID of the saved report
 * @param params - Query parameters (date range, filters, limit)
 * @returns Report data with query results
 * @throws ApiError on HTTP errors
 */
export async function executeReport(
  reportId: string,
  params: ReportExecuteParams = {},
  externalSignal?: AbortSignal,
): Promise<ReportDataResponse> {
  const headers = await createHeadersAsync();

  // Convert params to API request format
  const requestBody = {
    date_range: params.date_range || '30',
    filters: params.filters || [],
    limit: params.limit || 1000,
  };

  const response = await fetchWithTimeout(
    `${API_BASE_URL}/api/v1/reports/${reportId}/execute`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify(requestBody),
    },
    10000,
    externalSignal,
  );

  return handleResponse<ReportDataResponse>(response);
}

/**
 * Preview data for an unsaved report (wizard mode).
 *
 * This endpoint is used in the dashboard wizard to preview widgets
 * before they are saved. It builds a query from the chart configuration
 * and returns sample data.
 *
 * @param datasetName - Name of the dataset to query
 * @param config - Chart configuration (metrics, dimensions, filters)
 * @param dateRange - Date range string (default "30")
 * @returns Preview data with query results
 * @throws ApiError on HTTP errors
 */
export async function previewReportData(
  datasetName: string,
  config: ChartConfig,
  dateRange: string = '30',
  externalSignal?: AbortSignal,
): Promise<ReportDataResponse> {
  const headers = await createHeadersAsync();

  // Convert ChartConfig to preview request format
  const requestBody = {
    dataset_name: datasetName,
    metrics: config.metrics.map((m) => ({
      label: m.label || m.column,
      column: m.column,
      aggregate: m.aggregation,
    })),
    dimensions: config.dimensions,
    filters: config.filters,
    time_range: dateRange,
    time_grain: config.time_grain,
    viz_type: 'line', // Default viz type for preview
  };

  const response = await fetchWithTimeout(
    `${API_BASE_URL}${API_ROUTES.datasetsPreview}`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify(requestBody),
    },
    10000,
    externalSignal,
  );

  // Parse full ChartPreviewResponse and extract needed fields
  const fullResponse = await handleResponse<ChartPreviewResponse>(response);

  return {
    data: fullResponse.data,
    columns: fullResponse.columns,
    row_count: fullResponse.row_count,
    truncated: fullResponse.truncated,
    query_duration_ms: fullResponse.query_duration_ms,
  };
}
