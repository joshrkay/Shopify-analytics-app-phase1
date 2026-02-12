/**
 * TypeScript types for Custom Dashboards, Reports, Templates, Datasets, and Shares.
 *
 * Aligned with backend Pydantic schemas in:
 *   backend/src/api/schemas/custom_dashboards.py
 *
 * Phase 3 - Dashboard Builder UI
 */

// =============================================================================
// Dataset Discovery Types
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
// Chart Types & Configuration (matches backend ChartConfig schema)
// =============================================================================

/** Valid chart types — must match backend VALID_CHART_TYPES */
export type ChartType = 'line' | 'bar' | 'area' | 'pie' | 'kpi' | 'table';

export type Aggregation = 'SUM' | 'AVG' | 'COUNT' | 'MIN' | 'MAX';

export type FilterOperator =
  | '='
  | '!='
  | '>'
  | '<'
  | '>='
  | '<='
  | 'IN'
  | 'NOT IN'
  | 'LIKE';

export type TimeGrain = 'P1D' | 'P1W' | 'P1M' | 'P3M' | 'P1Y';

export interface MetricConfig {
  column: string;
  aggregation: Aggregation;
  label?: string;
  format?: string;
}

export interface ChartFilter {
  column: string;
  operator: FilterOperator;
  value: unknown;
}

export interface DisplayConfig {
  color_scheme?: string;
  show_legend: boolean;
  legend_position?: string;
  axis_label_x?: string;
  axis_label_y?: string;
}

export interface ChartConfig {
  metrics: MetricConfig[];
  dimensions: string[];
  time_range: string;
  time_grain: TimeGrain;
  filters: ChartFilter[];
  display: DisplayConfig;
}

// =============================================================================
// Grid Position (matches backend GridPosition schema — 12-column grid)
// =============================================================================

export interface GridPosition {
  x: number; // 0-11: column start
  y: number; // 0+: row start
  w: number; // 1-12: width in columns (x + w <= 12)
  h: number; // 1-20: height in rows
}

/** Minimum grid dimensions per chart type (from backend validation) */
export const MIN_GRID_DIMENSIONS: Record<ChartType, { w: number; h: number }> = {
  line: { w: 4, h: 3 },
  bar: { w: 4, h: 3 },
  area: { w: 4, h: 3 },
  pie: { w: 3, h: 3 },
  kpi: { w: 3, h: 2 },
  table: { w: 6, h: 4 },
};

export const GRID_COLS = 12;

// =============================================================================
// Dashboard Filter (dashboard-level filters)
// =============================================================================

export interface DashboardFilter {
  column: string;
  filter_type: 'date_range' | 'select' | 'multi_select';
  default_value?: unknown;
  dataset_names: string[];
}

// =============================================================================
// Chart Preview Types
// =============================================================================

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
  viz_type?: ChartType;
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
// Template Types
// =============================================================================

export type TemplateCategory =
  | 'sales'
  | 'marketing'
  | 'customer'
  | 'product'
  | 'operations';

export interface ReportTemplate {
  id: string;
  name: string;
  description: string;
  category: TemplateCategory;
  thumbnail_url: string | null;
  layout_json: Record<string, unknown>;
  reports_json: Record<string, unknown>[];
  required_datasets: string[];
  min_billing_tier: string;
  sort_order: number;
  is_active: boolean;
}

export interface TemplateListResponse {
  templates: ReportTemplate[];
  total: number;
}

export interface TemplateFilters {
  category?: TemplateCategory;
}

// =============================================================================
// Dashboard Types (matches backend DashboardResponse)
// =============================================================================

export type DashboardStatus = 'draft' | 'published' | 'archived';
export type AccessLevel = 'owner' | 'admin' | 'edit' | 'view';

export interface Dashboard {
  id: string;
  name: string;
  description: string | null;
  status: DashboardStatus;
  layout_json: Record<string, unknown>;
  filters_json: DashboardFilter[] | null;
  template_id: string | null;
  is_template_derived: boolean;
  version_number: number;
  reports: Report[];
  access_level: AccessLevel;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface DashboardListResponse {
  dashboards: Dashboard[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface DashboardCountResponse {
  current_count: number;
  max_count: number | null;
  can_create: boolean;
}

export interface DashboardFilters {
  status?: DashboardStatus;
  limit?: number;
  offset?: number;
}

export interface CreateDashboardRequest {
  name: string;
  description?: string;
  template_id?: string;
}

export interface UpdateDashboardRequest {
  name?: string;
  description?: string;
  layout_json?: Record<string, unknown>;
  filters_json?: DashboardFilter[];
  expected_updated_at?: string; // ISO datetime for optimistic locking
}

// =============================================================================
// Report Types (matches backend ReportResponse)
// =============================================================================

export interface Report {
  id: string;
  dashboard_id: string;
  name: string;
  description: string | null;
  chart_type: ChartType;
  dataset_name: string;
  config_json: ChartConfig;
  position_json: GridPosition;
  sort_order: number;
  created_by: string;
  created_at: string;
  updated_at: string;
  warnings: string[];
}

export interface CreateReportRequest {
  name: string;
  description?: string;
  chart_type: ChartType;
  dataset_name: string;
  config_json: ChartConfig;
  position_json: GridPosition;
}

export interface UpdateReportRequest {
  name?: string;
  description?: string;
  chart_type?: ChartType;
  config_json?: ChartConfig;
  position_json?: GridPosition;
}

export interface ReorderReportsRequest {
  report_ids: string[];
}

// =============================================================================
// Dashboard Shares Types (matches backend ShareResponse)
// =============================================================================

export type SharePermission = 'view' | 'edit' | 'admin';

export interface DashboardShare {
  id: string;
  dashboard_id: string;
  shared_with_user_id: string | null;
  shared_with_role: string | null;
  permission: SharePermission;
  granted_by: string;
  expires_at: string | null;
  is_expired: boolean;
  created_at: string;
  updated_at: string;
}

export interface ShareListResponse {
  shares: DashboardShare[];
  total: number;
}

export interface CreateShareRequest {
  shared_with_user_id?: string;
  shared_with_role?: string;
  permission: SharePermission;
  expires_at?: string;
}

export interface UpdateShareRequest {
  permission?: SharePermission;
  expires_at?: string;
}

// =============================================================================
// Version History Types (matches backend DashboardVersionResponse)
// =============================================================================

export interface DashboardVersion {
  id: string;
  dashboard_id: string;
  version_number: number;
  change_summary: string;
  created_by: string;
  created_at: string;
}

export interface VersionListResponse {
  versions: DashboardVersion[];
  total: number;
}

// =============================================================================
// Audit Trail Types (matches backend AuditEntryResponse)
// =============================================================================

export interface AuditEntry {
  id: string;
  dashboard_id: string;
  action: string;
  actor_id: string;
  details_json: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditListResponse {
  entries: AuditEntry[];
  total: number;
}

// =============================================================================
// Version Snapshot Types (for version preview)
// =============================================================================

export interface VersionSnapshot {
  dashboard: {
    name: string;
    description: string | null;
    layout_json: Record<string, unknown>;
    filters_json: DashboardFilter[] | null;
  };
  reports: Array<{
    id: string;
    name: string;
    description: string | null;
    chart_type: ChartType;
    dataset_name: string;
    config_json: Record<string, unknown>;
    position_json: GridPosition;
    sort_order: number;
  }>;
}

export interface DashboardVersionDetail extends DashboardVersion {
  snapshot_json: VersionSnapshot;
}

// =============================================================================
// Helpers
// =============================================================================

export function getTemplateCategoryLabel(category: TemplateCategory): string {
  const labels: Record<TemplateCategory, string> = {
    sales: 'Sales',
    marketing: 'Marketing',
    customer: 'Customer',
    product: 'Product',
    operations: 'Operations',
  };
  return labels[category] || category;
}

export function getChartTypeLabel(type: ChartType): string {
  const labels: Record<ChartType, string> = {
    line: 'Line Chart',
    bar: 'Bar Chart',
    area: 'Area Chart',
    pie: 'Pie Chart',
    kpi: 'KPI',
    table: 'Table',
  };
  return labels[type] || type;
}

// =============================================================================
// Widget Catalog Types (Phase 2 Builder - 3-Step Wizard)
// =============================================================================

/**
 * Widget categories for gallery filtering.
 * Corresponds to the 6 categories in the wireframe builder.
 */
export type WidgetCategory =
  | 'all'       // Show all widgets
  | 'roas'      // ROAS & ROI widgets
  | 'sales'     // Sales metrics
  | 'products'  // Product analytics
  | 'customers' // Customer insights
  | 'campaigns'; // Campaign performance

/**
 * Category metadata for sidebar rendering in the widget gallery.
 */
export interface WidgetCategoryMeta {
  id: WidgetCategory;
  name: string;              // Display name: "ROAS & ROI", "Sales", etc.
  icon: string;              // Lucide icon name: "TrendingUp", "DollarSign", etc.
  description?: string;      // Tooltip/help text
}

/**
 * Widget size presets for gallery items.
 * Maps to grid column spans: small=3, medium=6, large=9, full=12
 */
export type WidgetSize = 'small' | 'medium' | 'large' | 'full';

/**
 * Widget catalog item for the gallery/selection step.
 * Represents a widget type that users can add to their dashboard.
 */
export interface WidgetCatalogItem {
  id: string;                          // Unique widget catalog ID (e.g., "roas-overview")
  type: 'metric' | 'chart' | 'table';  // Widget type
  title: string;                       // Display name in gallery
  description: string;                 // Short description for gallery card
  icon: string;                        // Lucide icon name for gallery card
  category: WidgetCategory;            // Which category this belongs to
  defaultSize: WidgetSize;             // Default size when added to dashboard
  chartType?: ChartType;               // For chart widgets: line, bar, area, pie, kpi, table
  previewImageUrl?: string;            // Optional preview thumbnail URL
  dataSourceRequired?: boolean;        // Does widget need data binding?
  requiredDatasets?: string[];         // Which datasets this widget can use
  tags?: string[];                     // Searchable tags (future)
  defaultConfig?: Partial<ChartConfig>; // Default chart configuration
}

/**
 * Builder wizard step enumeration for the 3-step flow.
 */
export type BuilderStep =
  | 'select'    // Step 1: Select widgets from catalog
  | 'customize' // Step 2: Arrange layout & configure
  | 'preview';  // Step 3: Preview with sample data & save

/**
 * Builder wizard session state.
 * Tracks the current state of the wizard flow.
 */
export interface BuilderWizardState {
  currentStep: BuilderStep;
  selectedCatalogItems: WidgetCatalogItem[];  // Widgets added from catalog
  dashboardName: string;
  selectedCategory: WidgetCategory;           // Current filter in Step 1
  isDirty: boolean;                           // Unsaved changes flag
}

/**
 * Preview data for widgets in the Preview step.
 */
export interface WidgetPreviewData {
  widgetId: string;
  chartType?: ChartType;                      // For chart widgets
  sampleData: Record<string, unknown>;        // Sample data for preview
  loading: boolean;
  error?: string;
}

/**
 * Helper to get display label for widget category.
 */
export function getWidgetCategoryLabel(category: WidgetCategory): string {
  const labels: Record<WidgetCategory, string> = {
    all: 'All Widgets',
    roas: 'ROAS & ROI',
    sales: 'Sales',
    products: 'Products',
    customers: 'Customers',
    campaigns: 'Campaigns',
  };
  return labels[category] || category;
}

/**
 * Helper to map widget size to grid column span.
 */
export function getWidgetSizeColumns(size: WidgetSize): number {
  const columns: Record<WidgetSize, number> = {
    small: 3,
    medium: 6,
    large: 9,
    full: 12,
  };
  return columns[size];
}
