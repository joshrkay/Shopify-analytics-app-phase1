/**
 * Diagnostics API Service
 *
 * Handles API calls for root cause diagnostics:
 * - Fetch root cause signals for a dataset
 * - Fetch a specific signal
 * - Trigger on-demand analysis
 *
 * Story 4.2 - Data Quality Root Cause Signals (Prompt 4.2.7)
 */

import { API_BASE_URL, createHeadersAsync, handleResponse } from './apiUtils';

// =============================================================================
// Types
// =============================================================================

export interface EvidenceLink {
  label: string;
  link_type: 'sync_run' | 'dbt_run' | 'dq_result' | 'log';
  resource_id: string | null;
}

export interface RankedCause {
  rank: number;
  cause_type: string;
  confidence_score: number;
  evidence: Record<string, unknown>;
  first_seen_at: string | null;
  suggested_next_step: string;
  evidence_links: EvidenceLink[];
}

export interface AnomalySummary {
  dataset: string;
  anomaly_type: string;
  detected_at: string;
  connector_id: string | null;
  correlation_id: string | null;
}

export interface DiagnosticsSignal {
  signal_id: string;
  anomaly_summary: AnomalySummary;
  ranked_causes: RankedCause[];
  total_hypotheses: number;
  confidence_sum: number;
  analysis_duration_ms: number;
  investigation_steps: string[];
  is_active: boolean;
}

export interface DiagnosticsListResponse {
  signals: DiagnosticsSignal[];
  total: number;
  has_more: boolean;
}

// =============================================================================
// API Functions
// =============================================================================

/**
 * Get root cause diagnostics for a dataset.
 *
 * @param dataset - Dataset name (e.g. "shopify_orders")
 * @param options - Optional query params
 * @returns List of diagnostics signals
 */
export async function getDiagnostics(
  dataset: string,
  options: {
    activeOnly?: boolean;
    limit?: number;
    offset?: number;
  } = {}
): Promise<DiagnosticsListResponse> {
  const params = new URLSearchParams();
  if (options.activeOnly !== undefined) {
    params.set('active_only', String(options.activeOnly));
  }
  if (options.limit !== undefined) {
    params.set('limit', String(options.limit));
  }
  if (options.offset !== undefined) {
    params.set('offset', String(options.offset));
  }

  const qs = params.toString() ? `?${params.toString()}` : '';
  const response = await fetch(
    `${API_BASE_URL}/api/admin/diagnostics/${encodeURIComponent(dataset)}${qs}`,
    {
      method: 'GET',
      headers: await createHeadersAsync(),
    }
  );
  return handleResponse<DiagnosticsListResponse>(response);
}

/**
 * Get a specific diagnostic signal by ID.
 *
 * @param dataset - Dataset name
 * @param signalId - Signal ID
 * @returns Diagnostics signal details
 */
export async function getDiagnosticSignal(
  dataset: string,
  signalId: string
): Promise<DiagnosticsSignal> {
  const response = await fetch(
    `${API_BASE_URL}/api/admin/diagnostics/${encodeURIComponent(dataset)}/${encodeURIComponent(signalId)}`,
    {
      method: 'GET',
      headers: await createHeadersAsync(),
    }
  );
  return handleResponse<DiagnosticsSignal>(response);
}

/**
 * Run on-demand root cause analysis.
 *
 * @param dataset - Dataset to analyze
 * @param anomalyType - DQ check type that triggered analysis
 * @param options - Optional connector and correlation IDs
 * @returns Analysis result
 */
export async function runDiagnostics(
  dataset: string,
  anomalyType: string,
  options: {
    connectorId?: string;
    correlationId?: string;
  } = {}
): Promise<DiagnosticsSignal> {
  const params = new URLSearchParams({
    anomaly_type: anomalyType,
  });
  if (options.connectorId) {
    params.set('connector_id', options.connectorId);
  }
  if (options.correlationId) {
    params.set('correlation_id', options.correlationId);
  }

  const response = await fetch(
    `${API_BASE_URL}/api/admin/diagnostics/${encodeURIComponent(dataset)}/analyze?${params.toString()}`,
    {
      method: 'POST',
      headers: await createHeadersAsync(),
    }
  );
  return handleResponse<DiagnosticsSignal>(response);
}

// =============================================================================
// Utility Functions
// =============================================================================

/**
 * Get a human-readable label for a cause type.
 */
export function getCauseTypeLabel(causeType: string): string {
  const labels: Record<string, string> = {
    ingestion_failure: 'Ingestion Failure',
    schema_drift: 'Schema Drift',
    transformation_regression: 'Transformation Regression',
    upstream_data_shift: 'Upstream Data Shift',
    downstream_logic_change: 'Downstream Logic Change',
  };
  return labels[causeType] || causeType;
}

/**
 * Get badge tone based on confidence score.
 */
export function getConfidenceTone(
  score: number
): 'success' | 'attention' | 'warning' | 'critical' {
  if (score >= 0.8) return 'critical';
  if (score >= 0.6) return 'warning';
  if (score >= 0.4) return 'attention';
  return 'success';
}

/**
 * Format confidence score as percentage.
 */
export function formatConfidence(score: number): string {
  return `${Math.round(score * 100)}%`;
}
