/**
 * TypeScript types for Custom Dashboards, Reports, Templates, Datasets, and Shares.
 *
 * Phase 2D - Frontend Types
 */

// =============================================================================
// Dataset Discovery Types (Phase 2A)
// =============================================================================

export interface ColumnMetadata {
  column_name: string;
  data_type: string;
  description: string;
  is_metric: boolean;
  is_dimension: boolean;
  is_temporal: boolean;
}

export interface Dataset {
  dataset_name: string;
  dataset_id: number;
  schema: string;
  description: string;
  columns: ColumnMetadata[];
}

export interface DatasetListResponse {
  datasets: Dataset[];
  total: number;
  stale: boolean;
  cached_at: string | null;
}

export interface ConfigWarning {
  column_name: string;
  dataset_name: string;
  message: string;
}

export interface ValidateConfigRequest {
  dataset_name: string;
  referenced_columns: string[];
}

export interface ValidateConfigResponse {
  valid: boolean;
  warnings: ConfigWarning[];
}

// =============================================================================
// Chart Preview Types (Phase 2B)
// =============================================================================

export type AbstractChartType =
  | 'line'
  | 'bar'
  | 'pie'
  | 'big_number'
  | 'table'
  | 'area'
  | 'scatter';

export interface MetricDefinition {
  label: string;
  column?: string;
  aggregate?: string;
  expressionType?: 'SIMPLE' | 'SQL';
}

export interface FilterDefinition {
  column: string;
  operator: string;
  value: string | number | boolean | null;
}

export interface ChartPreviewRequest {
  dataset_name: string;
  metrics: MetricDefinition[];
  dimensions?: string[];
  filters?: FilterDefinition[];
  time_range?: string;
  time_column?: string | null;
  time_grain?: string;
  viz_type?: AbstractChartType;
}

export interface ChartPreviewResponse {
  data: Record<string, unknown>[];
  columns: string[];
  row_count: number;
  truncated: boolean;
  message: string | null;
  query_duration_ms: number | null;
  viz_type: string;
}

// =============================================================================
// Template Types (Phase 2C)
// =============================================================================

export type TemplateCategory =
  | 'revenue'
  | 'marketing'
  | 'product'
  | 'customer'
  | 'operations';

export interface ReportTemplate {
  id: string;
  name: string;
  description: string;
  category: TemplateCategory;
  thumbnail_url: string | null;
  min_billing_tier: string;
  report_count: number;
  version: number;
}

export interface TemplateListResponse {
  templates: ReportTemplate[];
  total: number;
}

export interface TemplateDetail {
  id: string;
  name: string;
  description: string;
  category: TemplateCategory;
  thumbnail_url: string | null;
  min_billing_tier: string;
  config_json: Record<string, unknown>;
  is_active: boolean;
  version: number;
}

export interface InstantiateRequest {
  dashboard_name?: string;
}

export interface InstantiateResponse {
  success: boolean;
  dashboard_id: string | null;
  report_ids: string[];
  error: string | null;
}

export interface CreateTemplateRequest {
  name: string;
  description?: string;
  category: TemplateCategory;
  config_json: Record<string, unknown>;
  min_billing_tier?: string;
  thumbnail_url?: string;
}

export interface UpdateTemplateRequest {
  name?: string;
  description?: string;
  category?: TemplateCategory;
  config_json?: Record<string, unknown>;
  min_billing_tier?: string;
  thumbnail_url?: string;
  is_active?: boolean;
}

// =============================================================================
// Custom Dashboard Types
// =============================================================================

export interface CustomDashboard {
  id: string;
  name: string;
  description: string;
  layout_json: Record<string, unknown>;
  is_default: boolean;
  template_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface CustomDashboardListResponse {
  dashboards: CustomDashboard[];
  total: number;
}

export interface CreateDashboardRequest {
  name: string;
  description?: string;
  layout_json?: Record<string, unknown>;
}

export interface UpdateDashboardRequest {
  name?: string;
  description?: string;
  layout_json?: Record<string, unknown>;
  is_default?: boolean;
}

// =============================================================================
// Custom Report Types
// =============================================================================

export interface CustomReport {
  id: string;
  dashboard_id: string;
  title: string;
  config_json: Record<string, unknown>;
  position: number;
  dataset_name: string;
  viz_type: string;
  warnings: ConfigWarning[];
  created_at: string;
  updated_at: string;
}

export interface CustomReportListResponse {
  reports: CustomReport[];
  total: number;
}

export interface CreateReportRequest {
  dashboard_id: string;
  title: string;
  config_json: Record<string, unknown>;
  dataset_name: string;
  viz_type?: AbstractChartType;
  position?: number;
}

export interface UpdateReportRequest {
  title?: string;
  config_json?: Record<string, unknown>;
  dataset_name?: string;
  viz_type?: AbstractChartType;
  position?: number;
}

// =============================================================================
// Dashboard Shares Types
// =============================================================================

export type SharePermission = 'view' | 'edit';

export interface DashboardShare {
  id: string;
  dashboard_id: string;
  shared_with_user_id: string;
  shared_with_email: string;
  permission: SharePermission;
  created_at: string;
}

export interface DashboardShareListResponse {
  shares: DashboardShare[];
  total: number;
}

export interface CreateShareRequest {
  shared_with_user_id: string;
  permission: SharePermission;
}

// =============================================================================
// Filter Types
// =============================================================================

export interface TemplateFilters {
  category?: TemplateCategory;
  billing_tier?: string;
}

export interface DashboardFilters {
  limit?: number;
  offset?: number;
}

export interface ReportFilters {
  dashboard_id?: string;
  limit?: number;
  offset?: number;
}

// =============================================================================
// Helpers
// =============================================================================

export function getTemplateCategoryLabel(category: TemplateCategory): string {
  const labels: Record<TemplateCategory, string> = {
    revenue: 'Revenue',
    marketing: 'Marketing',
    product: 'Product',
    customer: 'Customer',
    operations: 'Operations',
  };
  return labels[category] || category;
}

export function getChartTypeLabel(type: AbstractChartType): string {
  const labels: Record<AbstractChartType, string> = {
    line: 'Line Chart',
    bar: 'Bar Chart',
    pie: 'Pie Chart',
    big_number: 'Big Number',
    table: 'Table',
    area: 'Area Chart',
    scatter: 'Scatter Plot',
  };
  return labels[type] || type;
}
