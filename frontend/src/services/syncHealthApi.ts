/**
 * Sync Health API Service
 *
 * Handles API calls for sync health monitoring:
 * - Overall sync health summary
 * - Per-connector health status
 * - Incident management
 * - Backfill triggering
 */

// =============================================================================
// Types
// =============================================================================

export interface ConnectorHealth {
  connector_id: string;
  connector_name: string;
  source_type: string | null;
  status: 'healthy' | 'delayed' | 'error';
  freshness_status: 'fresh' | 'stale' | 'critical' | 'never_synced';
  severity: 'warning' | 'high' | 'critical' | null;
  last_sync_at: string | null;
  last_rows_synced: number | null;
  minutes_since_sync: number | null;
  message: string;
  merchant_message: string;
  recommended_actions: string[];
  is_blocking: boolean;
  has_open_incidents: boolean;
  open_incident_count: number;
}

export interface SyncHealthSummary {
  total_connectors: number;
  healthy_count: number;
  delayed_count: number;
  error_count: number;
  blocking_issues: number;
  overall_status: 'healthy' | 'degraded' | 'critical';
  health_score: number;
  connectors: ConnectorHealth[];
  has_blocking_issues: boolean;
}

export interface DQIncident {
  id: string;
  connector_id: string;
  severity: 'warning' | 'high' | 'critical';
  status: 'open' | 'acknowledged' | 'resolved' | 'auto_resolved';
  is_blocking: boolean;
  title: string;
  description: string | null;
  merchant_message: string | null;
  recommended_actions: string[];
  opened_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
}

export interface DashboardBlockStatus {
  is_blocked: boolean;
  blocking_messages: string[];
}

export interface BackfillEstimate {
  connector_id: string;
  start_date: string;
  end_date: string;
  days_count: number;
  is_allowed: boolean;
  max_allowed_days: number;
  message: string;
  warning: string | null;
}

export interface BackfillResponse {
  id: string;
  connector_id: string;
  start_date: string;
  end_date: string;
  status: string;
  requested_by: string;
  estimated_days: number;
  message: string;
}

export interface BackfillRequest {
  start_date: string;
  end_date: string;
}

// =============================================================================
// API Configuration
// =============================================================================

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/**
 * Get the current JWT token from localStorage.
 */
function getAuthToken(): string | null {
  return localStorage.getItem('jwt_token') || localStorage.getItem('auth_token');
}

/**
 * Create headers with authentication.
 */
function createHeaders(): HeadersInit {
  const token = getAuthToken();
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

/**
 * Handle API response and throw on error.
 */
async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    const error = new Error(errorData.detail || `API error: ${response.status}`);
    (error as any).status = response.status;
    (error as any).detail = errorData.detail;
    throw error;
  }
  return response.json();
}

// =============================================================================
// Sync Health API Functions
// =============================================================================

/**
 * Get overall sync health summary.
 *
 * @returns Sync health summary with per-connector health
 */
export async function getSyncHealthSummary(): Promise<SyncHealthSummary> {
  const response = await fetch(`${API_BASE_URL}/api/sync-health/summary`, {
    method: 'GET',
    headers: createHeaders(),
  });
  return handleResponse<SyncHealthSummary>(response);
}

/**
 * Get health information for a specific connector.
 *
 * @param connectorId - The connector ID
 * @returns Connector health information
 */
export async function getConnectorHealth(
  connectorId: string
): Promise<ConnectorHealth> {
  const response = await fetch(
    `${API_BASE_URL}/api/sync-health/connector/${connectorId}`,
    {
      method: 'GET',
      headers: createHeaders(),
    }
  );
  return handleResponse<ConnectorHealth>(response);
}

/**
 * Get DQ incidents.
 *
 * @param connectorId - Optional filter by connector ID
 * @param includeResolved - Whether to include resolved incidents
 * @returns List of incidents
 */
export async function getIncidents(
  connectorId?: string,
  includeResolved: boolean = false
): Promise<DQIncident[]> {
  const params = new URLSearchParams();
  if (connectorId) {
    params.set('connector_id', connectorId);
  }
  if (includeResolved) {
    params.set('include_resolved', 'true');
  }

  const url = `${API_BASE_URL}/api/sync-health/incidents${
    params.toString() ? `?${params.toString()}` : ''
  }`;

  const response = await fetch(url, {
    method: 'GET',
    headers: createHeaders(),
  });
  return handleResponse<DQIncident[]>(response);
}

/**
 * Acknowledge an incident.
 *
 * @param incidentId - The incident ID to acknowledge
 * @returns Updated incident
 */
export async function acknowledgeIncident(
  incidentId: string
): Promise<DQIncident> {
  const response = await fetch(
    `${API_BASE_URL}/api/sync-health/incidents/${incidentId}/acknowledge`,
    {
      method: 'POST',
      headers: createHeaders(),
    }
  );
  return handleResponse<DQIncident>(response);
}

/**
 * Check if dashboards should be blocked.
 *
 * @returns Dashboard block status
 */
export async function getDashboardBlockStatus(): Promise<DashboardBlockStatus> {
  const response = await fetch(`${API_BASE_URL}/api/sync-health/dashboard-block`, {
    method: 'GET',
    headers: createHeaders(),
  });
  return handleResponse<DashboardBlockStatus>(response);
}

// =============================================================================
// Backfill API Functions
// =============================================================================

/**
 * Estimate a potential backfill operation.
 *
 * @param connectorId - Connector ID
 * @param startDate - Start date (YYYY-MM-DD)
 * @param endDate - End date (YYYY-MM-DD)
 * @returns Backfill estimate with validation
 */
export async function estimateBackfill(
  connectorId: string,
  startDate: string,
  endDate: string
): Promise<BackfillEstimate> {
  const params = new URLSearchParams({
    start_date: startDate,
    end_date: endDate,
  });

  const response = await fetch(
    `${API_BASE_URL}/api/sync-health/connectors/${connectorId}/backfill/estimate?${params.toString()}`,
    {
      method: 'GET',
      headers: createHeaders(),
    }
  );
  return handleResponse<BackfillEstimate>(response);
}

/**
 * Trigger a backfill for a connector.
 *
 * @param connectorId - Connector ID
 * @param request - Backfill request with date range
 * @returns Backfill response with job info
 */
export async function triggerBackfill(
  connectorId: string,
  request: BackfillRequest
): Promise<BackfillResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/sync-health/connectors/${connectorId}/backfill`,
    {
      method: 'POST',
      headers: createHeaders(),
      body: JSON.stringify(request),
    }
  );
  return handleResponse<BackfillResponse>(response);
}

/**
 * Get backfill status for a connector.
 *
 * @param connectorId - Connector ID
 * @returns Current or most recent backfill status
 */
export async function getBackfillStatus(
  connectorId: string
): Promise<BackfillResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/sync-health/connectors/${connectorId}/backfill/status`,
    {
      method: 'GET',
      headers: createHeaders(),
    }
  );
  return handleResponse<BackfillResponse>(response);
}

// =============================================================================
// Utility Functions
// =============================================================================

/**
 * Format minutes since sync to human-readable string.
 */
export function formatTimeSinceSync(minutes: number | null): string {
  if (minutes === null) {
    return 'Never synced';
  }

  if (minutes < 60) {
    return `${minutes} minutes ago`;
  }

  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return hours === 1 ? '1 hour ago' : `${hours} hours ago`;
  }

  const days = Math.floor(hours / 24);
  return days === 1 ? '1 day ago' : `${days} days ago`;
}

/**
 * Get badge tone based on status.
 */
export function getStatusBadgeTone(
  status: 'healthy' | 'delayed' | 'error'
): 'success' | 'attention' | 'critical' {
  switch (status) {
    case 'healthy':
      return 'success';
    case 'delayed':
      return 'attention';
    case 'error':
      return 'critical';
    default:
      return 'attention';
  }
}

/**
 * Get severity badge tone.
 */
export function getSeverityBadgeTone(
  severity: 'warning' | 'high' | 'critical' | null
): 'attention' | 'warning' | 'critical' {
  switch (severity) {
    case 'critical':
      return 'critical';
    case 'high':
      return 'warning';
    case 'warning':
    default:
      return 'attention';
  }
}

/**
 * Calculate date range for backfill (max 90 days).
 */
export function calculateBackfillDateRange(
  startDate: Date,
  endDate: Date
): { isValid: boolean; days: number; message: string } {
  const diffTime = endDate.getTime() - startDate.getTime();
  const days = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) + 1;
  const maxDays = 90;

  if (days <= 0) {
    return {
      isValid: false,
      days: 0,
      message: 'End date must be after start date',
    };
  }

  if (days > maxDays) {
    return {
      isValid: false,
      days,
      message: `Maximum backfill range is ${maxDays} days. Contact support for larger backfills.`,
    };
  }

  return {
    isValid: true,
    days,
    message: `${days} day${days > 1 ? 's' : ''} selected`,
  };
}
