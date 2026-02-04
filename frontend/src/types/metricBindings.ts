/**
 * Types for Metric Version Bindings (Story 2.3)
 */

export interface MetricBannerData {
  /** Whether to show the banner */
  show: boolean;
  /** Banner tone: "info" | "warning" | "critical" */
  tone: 'info' | 'warning' | 'critical';
  /** Dashboard this banner applies to */
  dashboard_id: string;
  /** Metric name */
  metric_name: string;
  /** Currently bound version */
  current_version: string;
  /** Human-readable message */
  message: string;
  /** Date of upcoming change (ISO string) */
  change_date?: string | null;
  /** Newer version available */
  new_version_available?: string | null;
  /** Days until sunset (for deprecated versions) */
  days_until_sunset?: number | null;
}

export interface MetricBinding {
  dashboard_id: string;
  metric_name: string;
  metric_version: string;
  pinned_by?: string | null;
  pinned_at?: string | null;
  reason?: string | null;
  tenant_id?: string | null;
  is_tenant_override: boolean;
}

export interface BindingsListResponse {
  bindings: MetricBinding[];
  total: number;
}
