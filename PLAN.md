# Phase 2 Builder Implementation Plan: Subphases 2.1 & 2.2

**Plan Created**: 2026-02-12
**Branch**: `claude/phase-2-builder-plan-qwNVl`
**Scope**: Widget Catalog Type Extensions (2.1) + Widget Catalog API & Hook (2.2)

---

## Executive Summary

This plan implements the foundation for the 3-step wizard UX (Select Reports → Customize Layout → Preview & Save) by:

1. **Subphase 2.1**: Extending the existing type system with widget catalog metadata (categories, descriptions, gallery presentation)
2. **Subphase 2.2**: Creating an API-driven widget catalog service and React hooks to replace hardcoded widget lists

**Key Design Decision**: The widget catalog starts as a **frontend-defined static catalog** (not backend API) because the existing app's widget types come from the Superset embed + report configurator system. The `getWidgetCatalog()` function returns a curated list that maps catalog items to existing `ChartRenderer` configurations.

**No Breaking Changes**: All new types extend existing types. Existing dashboard/report flows remain unchanged.

---

## Phase 1: Understanding (Completed)

### Existing Infrastructure Analysis

✅ **Explored Files**:
- `frontend/src/types/customDashboards.ts` (11 KB) - Core type definitions
- `frontend/src/components/dashboards/DashboardBuilder.tsx` (174 lines) - Current builder page
- `frontend/src/contexts/DashboardBuilderContext.tsx` (24.4 KB) - State management
- `frontend/src/services/customDashboardsApi.ts` (6.1 KB) - API service
- `frontend/src/services/templatesApi.ts` (2.0 KB) - Template API
- `frontend/src/hooks/useDashboardMutations.ts` (4.1 KB) - Dashboard CRUD
- `frontend/src/hooks/useReportMutations.ts` (3.8 KB) - Report CRUD
- `frontend/src/tests/dashboardBuilder.test.tsx` (4.6 KB) - Existing test patterns

✅ **Key Findings**:
1. **No 3-step wizard exists yet** - Current builder is a single-page form with `ReportConfiguratorModal`
2. **Widget types already defined**: `WidgetType` = "metric" | "chart" | "table" | "text" | "filter"
3. **Chart types already defined**: `ChartType` = "line" | "bar" | "area" | "pie" | "kpi" | "table"
4. **Size system exists**: `WidgetSize` = "small" | "medium" | "large" | "full"
5. **Template system exists** with `TemplateCategory` but needs new widget-specific categories
6. **Testing patterns established**: Vitest + @testing-library/react, factory functions, `renderWithProviders` helper

---

## Phase 2: Design

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Phase 2.1: Type Extensions                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ customDashboards.ts (MODIFIED)                      │   │
│  │ + WidgetCatalogItem (extends DashboardWidget)      │   │
│  │ + WidgetCategory ("all" | "roas" | "sales" | ...)  │   │
│  │ + WidgetCategoryMeta (category metadata)           │   │
│  │ + BuilderStep ("select" | "customize" | "preview") │   │
│  │ + BuilderWizardState (wizard session state)        │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Phase 2.2: Widget Catalog Service & Hooks                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ widgetCatalogApi.ts (NEW)                           │   │
│  │ + getWidgetCatalog() → WidgetCatalogItem[]         │   │
│  │ + getWidgetCategories() → WidgetCategoryMeta[]     │   │
│  │ + getWidgetPreview(id) → WidgetPreviewData         │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ useWidgetCatalog.ts (NEW)                           │   │
│  │ + useWidgetCatalog(category?) → {widgets, ...}     │   │
│  │ + useWidgetPreview(id) → {previewData, ...}        │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           ↓
                 (Future: Phase 2.3-2.6)
              Wizard Components, Layout Engine, etc.
```

### Type Extension Strategy (Subphase 2.1)

**Goal**: Add catalog-specific metadata to existing widget types WITHOUT breaking existing code.

**Approach**:
1. Add new types alongside existing types (not replacing)
2. Make `WidgetCatalogItem` **extend** existing `DashboardWidget`
3. All new fields are optional or have defaults
4. Existing types like `WidgetType`, `ChartType`, `WidgetSize` remain unchanged

**New Types to Add**:

```typescript
// Widget catalog categories (for gallery sidebar filtering)
export type WidgetCategory =
  | "all"       // Show all widgets
  | "roas"      // ROAS & ROI widgets
  | "sales"     // Sales metrics
  | "products"  // Product analytics
  | "customers" // Customer insights
  | "campaigns" // Campaign performance

// Category metadata for sidebar rendering
export interface WidgetCategoryMeta {
  id: WidgetCategory;
  name: string;              // Display name: "ROAS & ROI", "Sales", etc.
  icon: string;              // Lucide icon name: "TrendingUp", "DollarSign", etc.
  description?: string;      // Tooltip/help text
}

// Widget catalog item (extends existing DashboardWidget)
export interface WidgetCatalogItem extends DashboardWidget {
  // Fields from DashboardWidget: id, type, title, size, config

  // NEW fields for catalog/gallery presentation:
  description: string;                 // Short description for gallery card
  icon: string;                        // Lucide icon name for gallery card
  category: WidgetCategory;            // Which category this belongs to
  previewImageUrl?: string;            // Optional preview thumbnail
  dataSourceRequired?: boolean;        // Does widget need data binding?
  requiredDatasets?: string[];         // Which datasets this widget can use
  tags?: string[];                     // Searchable tags (future)
}

// Builder wizard step enumeration
export type BuilderStep =
  | "select"    // Step 1: Select widgets from catalog
  | "customize" // Step 2: Arrange layout & configure
  | "preview"   // Step 3: Preview with sample data & save

// Builder wizard session state (for context extension)
export interface BuilderWizardState {
  currentStep: BuilderStep;
  selectedCatalogItems: WidgetCatalogItem[];  // Widgets added from catalog
  dashboardName: string;
  selectedCategory: WidgetCategory;           // Current filter in Step 1
  isDirty: boolean;                           // Unsaved changes flag
}

// Preview data for widgets (used in Step 3)
export interface WidgetPreviewData {
  widgetId: string;
  chartType?: ChartType;                      // For chart widgets
  sampleData: Record<string, unknown>;        // Sample data for preview
  loading: boolean;
  error?: string;
}
```

**Backward Compatibility**:
- `WidgetCatalogItem extends DashboardWidget` means all existing widget-handling code still works
- Existing components can ignore new fields like `description`, `icon`, `category`
- Existing `DashboardWidget[]` arrays can still be used; catalog is additive

---

### Widget Catalog API Design (Subphase 2.2)

**Goal**: Provide a **static, frontend-defined catalog** that maps wireframe's 16 widgets to existing chart/widget types.

**Why Frontend-Defined?**
1. Existing widget rendering comes from `ChartRenderer` + Recharts (frontend)
2. Backend doesn't know about "widget types" - it stores generic `report_config` JSON
3. Catalog is essentially a **mapping** from user-facing widget names → `ChartRenderer` configs
4. No backend changes needed; keeps scope focused on frontend UX

**API Service Structure**:

```typescript
// frontend/src/services/widgetCatalogApi.ts

import type { WidgetCatalogItem, WidgetCategoryMeta, WidgetPreviewData } from '../types/customDashboards';

/**
 * Hardcoded widget catalog - maps wireframe's 16 widgets to existing chart types.
 * In the future, this could be fetched from a backend endpoint.
 */
const WIDGET_CATALOG: WidgetCatalogItem[] = [
  // ROAS & ROI Category
  {
    id: 'roas-overview',
    type: 'chart',
    title: 'ROAS Overview',
    description: 'Return on ad spend across all channels',
    icon: 'TrendingUp',
    category: 'roas',
    size: 'medium',
    config: {
      chartType: 'kpi',
      // ... maps to existing ChartRenderer config
    },
    dataSourceRequired: true,
    requiredDatasets: ['marketing_attribution'],
  },
  {
    id: 'roi-by-channel',
    type: 'chart',
    title: 'ROI by Channel',
    description: 'Compare return on investment across marketing channels',
    icon: 'BarChart3',
    category: 'roas',
    size: 'large',
    config: {
      chartType: 'bar',
      // ...
    },
    dataSourceRequired: true,
    requiredDatasets: ['marketing_attribution'],
  },

  // Sales Category
  {
    id: 'sales-trend',
    type: 'chart',
    title: 'Sales Trend',
    description: 'Sales over time with trend line',
    icon: 'TrendingUp',
    category: 'sales',
    size: 'large',
    config: {
      chartType: 'line',
      // ...
    },
    dataSourceRequired: true,
    requiredDatasets: ['sales_metrics'],
  },
  {
    id: 'revenue-kpi',
    type: 'metric',
    title: 'Total Revenue',
    description: 'Total revenue for selected period',
    icon: 'DollarSign',
    category: 'sales',
    size: 'small',
    config: {
      chartType: 'kpi',
      // ...
    },
    dataSourceRequired: true,
    requiredDatasets: ['sales_metrics'],
  },

  // Products Category
  {
    id: 'top-products',
    type: 'table',
    title: 'Top Products',
    description: 'Best selling products by revenue',
    icon: 'Package',
    category: 'products',
    size: 'medium',
    config: {
      chartType: 'table',
      // ...
    },
    dataSourceRequired: true,
    requiredDatasets: ['product_analytics'],
  },
  {
    id: 'product-performance',
    type: 'chart',
    title: 'Product Performance',
    description: 'Product sales comparison',
    icon: 'BarChart3',
    category: 'products',
    size: 'large',
    config: {
      chartType: 'bar',
      // ...
    },
    dataSourceRequired: true,
    requiredDatasets: ['product_analytics'],
  },

  // Customers Category
  {
    id: 'customer-segments',
    type: 'chart',
    title: 'Customer Segments',
    description: 'Customer distribution by segment',
    icon: 'PieChart',
    category: 'customers',
    size: 'medium',
    config: {
      chartType: 'pie',
      // ...
    },
    dataSourceRequired: true,
    requiredDatasets: ['customer_analytics'],
  },
  {
    id: 'ltv-cohort',
    type: 'chart',
    title: 'LTV Cohort Analysis',
    description: 'Customer lifetime value by cohort',
    icon: 'Users',
    category: 'customers',
    size: 'large',
    config: {
      chartType: 'line',
      // ...
    },
    dataSourceRequired: true,
    requiredDatasets: ['customer_analytics'],
  },

  // Campaigns Category
  {
    id: 'campaign-performance',
    type: 'chart',
    title: 'Campaign Performance',
    description: 'Marketing campaign effectiveness',
    icon: 'Megaphone',
    category: 'campaigns',
    size: 'large',
    config: {
      chartType: 'bar',
      // ...
    },
    dataSourceRequired: true,
    requiredDatasets: ['marketing_attribution'],
  },
  {
    id: 'campaign-roi',
    type: 'metric',
    title: 'Campaign ROI',
    description: 'Overall campaign return on investment',
    icon: 'Target',
    category: 'campaigns',
    size: 'small',
    config: {
      chartType: 'kpi',
      // ...
    },
    dataSourceRequired: true,
    requiredDatasets: ['marketing_attribution'],
  },

  // Additional widgets to reach 16 total (placeholder IDs for now)
  // ... 6 more widgets across categories
];

/**
 * Category metadata for sidebar filtering.
 */
const WIDGET_CATEGORIES: WidgetCategoryMeta[] = [
  { id: 'all', name: 'All Widgets', icon: 'LayoutGrid' },
  { id: 'roas', name: 'ROAS & ROI', icon: 'TrendingUp', description: 'Return on ad spend metrics' },
  { id: 'sales', name: 'Sales', icon: 'DollarSign', description: 'Sales and revenue analytics' },
  { id: 'products', name: 'Products', icon: 'Package', description: 'Product performance metrics' },
  { id: 'customers', name: 'Customers', icon: 'Users', description: 'Customer insights and segments' },
  { id: 'campaigns', name: 'Campaigns', icon: 'Megaphone', description: 'Marketing campaign analytics' },
];

/**
 * Get all available widgets in the catalog.
 * In v1, returns static list. Future: fetch from backend API.
 */
export async function getWidgetCatalog(): Promise<WidgetCatalogItem[]> {
  // Simulate async fetch (for consistent API with future backend version)
  return Promise.resolve([...WIDGET_CATALOG]);
}

/**
 * Get all widget categories for sidebar filtering.
 */
export async function getWidgetCategories(): Promise<WidgetCategoryMeta[]> {
  return Promise.resolve([...WIDGET_CATEGORIES]);
}

/**
 * Get preview data for a specific widget.
 * Bridges to existing useChartPreview hook for real data.
 *
 * @param widgetId - Widget catalog ID
 * @param datasetId - Optional dataset ID for preview data binding
 */
export async function getWidgetPreview(
  widgetId: string,
  datasetId?: string
): Promise<WidgetPreviewData> {
  const widget = WIDGET_CATALOG.find(w => w.id === widgetId);

  if (!widget) {
    throw new Error(`Widget not found: ${widgetId}`);
  }

  // Generate sample data based on widget type
  // In real implementation, this would call existing useChartPreview hook
  const sampleData = generateSampleDataForWidget(widget);

  return {
    widgetId,
    chartType: widget.config?.chartType,
    sampleData,
    loading: false,
  };
}

/**
 * Helper: Generate sample preview data based on widget type.
 * TODO: Replace with real preview data from useChartPreview hook.
 */
function generateSampleDataForWidget(widget: WidgetCatalogItem): Record<string, unknown> {
  // Placeholder implementation
  switch (widget.config?.chartType) {
    case 'kpi':
      return { value: 12458, change: 12.5, trend: 'up' };
    case 'line':
      return { series: [/* time series data */] };
    case 'bar':
      return { categories: [/* bar chart data */] };
    case 'pie':
      return { segments: [/* pie chart data */] };
    case 'table':
      return { rows: [/* table data */] };
    default:
      return {};
  }
}
```

**Hook Implementation**:

```typescript
// frontend/src/hooks/useWidgetCatalog.ts

import { useQuery } from '@tanstack/react-query';
import { getWidgetCatalog, getWidgetCategories, getWidgetPreview } from '../services/widgetCatalogApi';
import type { WidgetCatalogItem, WidgetCategoryMeta, WidgetCategory } from '../types/customDashboards';

/**
 * Hook to fetch and filter the widget catalog.
 * Uses React Query for caching and automatic refetch management.
 */
export function useWidgetCatalog(category?: WidgetCategory) {
  // Fetch full catalog
  const { data: allWidgets, isLoading: widgetsLoading, error: widgetsError } = useQuery({
    queryKey: ['widget-catalog'],
    queryFn: getWidgetCatalog,
    staleTime: 30 * 60 * 1000, // 30 minutes (catalog doesn't change often)
  });

  // Fetch categories
  const { data: categories, isLoading: categoriesLoading } = useQuery({
    queryKey: ['widget-categories'],
    queryFn: getWidgetCategories,
    staleTime: 30 * 60 * 1000,
  });

  // Client-side filtering by category
  const getFilteredWidgets = (filterCategory: WidgetCategory): WidgetCatalogItem[] => {
    if (!allWidgets) return [];
    if (filterCategory === 'all') return allWidgets;
    return allWidgets.filter(w => w.category === filterCategory);
  };

  const widgets = category ? getFilteredWidgets(category) : (allWidgets || []);

  return {
    widgets,
    categories: categories || [],
    isLoading: widgetsLoading || categoriesLoading,
    error: widgetsError,
    getFilteredWidgets,
  };
}

/**
 * Hook to fetch preview data for a specific widget.
 * Used in the Preview step of the wizard.
 */
export function useWidgetPreview(widgetId: string, datasetId?: string) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['widget-preview', widgetId, datasetId],
    queryFn: () => getWidgetPreview(widgetId, datasetId),
    enabled: !!widgetId, // Only fetch when widgetId is provided
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  return {
    previewData: data || null,
    isLoading,
    error,
  };
}
```

---

## Phase 3: Implementation Tasks

### Subphase 2.1: Type Extensions

**Task 2.1.1: Extend customDashboards.ts with catalog types**

- **File**: `frontend/src/types/customDashboards.ts`
- **Changes**:
  1. Add `WidgetCategory` type (6 categories)
  2. Add `WidgetCategoryMeta` interface (category metadata)
  3. Add `WidgetCatalogItem` interface (extends `DashboardWidget`)
  4. Add `BuilderStep` type (3 wizard steps)
  5. Add `BuilderWizardState` interface (wizard session state)
  6. Add `WidgetPreviewData` interface (preview data structure)
  7. Export all new types

- **Verification**:
  - [ ] TypeScript compiles with no errors
  - [ ] Existing imports of `DashboardWidget` still work
  - [ ] `WidgetCatalogItem` is assignable to `DashboardWidget`

**Task 2.1.2: Create type compatibility tests**

- **File**: `frontend/src/tests/builderTypes.test.ts` (NEW)
- **Test Cases**:
  1. `WidgetCatalogItem` is compatible with `DashboardWidget`
  2. All 6 `WidgetCategory` values are representable
  3. All 3 `BuilderStep` values are representable
  4. `defaultSize` values map to valid grid column spans (small→3, medium→6, large→9, full→12)
  5. Existing `Dashboard` type still compiles with extensions

- **Implementation Pattern**: Use `it.each()` for parameterized type tests (see `dashboardTypes.test.ts` pattern)

**Task 2.1.3: Run regression tests**

- **Command**: `npm run test` (from `frontend/` directory)
- **Expected**: All existing tests pass, no type errors
- **Files to Verify**:
  - [ ] `tests/dashboardBuilder.test.tsx` - Existing builder tests
  - [ ] `tests/dashboardTypes.test.ts` - Existing type tests (if exists)
  - [ ] All imports of `customDashboards.ts` still compile

---

### Subphase 2.2: Widget Catalog API & Hook

**Task 2.2.1: Create widgetCatalogApi.ts service**

- **File**: `frontend/src/services/widgetCatalogApi.ts` (NEW)
- **Implementation**:
  1. Define `WIDGET_CATALOG` constant (16 hardcoded widgets across 6 categories)
  2. Define `WIDGET_CATEGORIES` constant (6 category metadata objects)
  3. Implement `getWidgetCatalog()` → Returns full catalog
  4. Implement `getWidgetCategories()` → Returns category metadata
  5. Implement `getWidgetPreview(widgetId, datasetId?)` → Returns sample preview data
  6. Implement `generateSampleDataForWidget()` helper (placeholder data generator)

- **Widget Catalog Content** (10 widgets minimum to start):
  - **ROAS & ROI**: ROAS Overview (KPI), ROI by Channel (Bar)
  - **Sales**: Sales Trend (Line), Revenue KPI (Metric), Top Products (Table)
  - **Products**: Top Products (Table), Product Performance (Bar)
  - **Customers**: Customer Segments (Pie), LTV Cohort (Line)
  - **Campaigns**: Campaign Performance (Bar), Campaign ROI (Metric)

- **Verification**:
  - [ ] `getWidgetCatalog()` returns array of `WidgetCatalogItem[]`
  - [ ] Each widget has required fields: `id`, `type`, `title`, `category`, `icon`, `description`, `size`
  - [ ] All widget `type` values match existing `WidgetType` enum
  - [ ] All widget `config.chartType` values match existing `ChartType` enum

**Task 2.2.2: Create useWidgetCatalog.ts hook**

- **File**: `frontend/src/hooks/useWidgetCatalog.ts` (NEW)
- **Implementation**:
  1. `useWidgetCatalog(category?)` hook:
     - Uses `@tanstack/react-query` with `queryKey: ['widget-catalog']`
     - Calls `getWidgetCatalog()` from API service
     - `staleTime: 30 * 60 * 1000` (30 minutes)
     - Client-side filtering via `getFilteredWidgets(category)` helper
     - Returns: `{ widgets, categories, isLoading, error, getFilteredWidgets }`

  2. `useWidgetPreview(widgetId, datasetId?)` hook:
     - Uses `@tanstack/react-query` with `queryKey: ['widget-preview', widgetId, datasetId]`
     - Calls `getWidgetPreview()` from API service
     - `enabled: !!widgetId` (only fetch when widgetId provided)
     - `staleTime: 5 * 60 * 1000` (5 minutes)
     - Returns: `{ previewData, isLoading, error }`

- **Dependencies**: Verify `@tanstack/react-query` is already installed (it is, based on existing `useDashboardMutations.ts`)

**Task 2.2.3: Create widgetCatalogApi.test.ts unit tests**

- **File**: `frontend/src/tests/widgetCatalogApi.test.ts` (NEW)
- **Test Cases**:

| # | Test Case | What It Validates |
|---|-----------|-------------------|
| 1 | `getWidgetCatalog()` returns all widgets | Complete catalog loads |
| 2 | Each widget has required fields | Schema validation |
| 3 | Widget types match existing `WidgetType` enum | Catalog items are renderable |
| 4 | Chart types match existing `ChartType` enum | Chart configs are valid |
| 5 | `getWidgetCategories()` returns all 6 categories | Category sidebar can populate |
| 6 | `getWidgetPreview()` returns data for metric widget | Preview data works for metrics |
| 7 | `getWidgetPreview()` returns data for chart widget | Preview data works for charts |
| 8 | `getWidgetPreview()` throws for invalid widget ID | Error handling |

- **Implementation Pattern**: Follow `dashboardApi.test.ts` pattern - no mocks needed for pure functions

**Task 2.2.4: Create useWidgetCatalog.test.ts hook tests**

- **File**: `frontend/src/tests/useWidgetCatalog.test.ts` (NEW)
- **Test Cases**:

| # | Test Case | What It Validates |
|---|-----------|-------------------|
| 1 | `useWidgetCatalog()` returns full catalog on initial load | All widgets available |
| 2 | `getFilteredWidgets("sales")` returns only sales widgets | Client-side filtering works |
| 3 | `getFilteredWidgets("all")` returns all widgets | "All" category bypasses filter |
| 4 | Loading state is `true` during fetch | UI can show skeleton |
| 5 | Error state populates on failure | Graceful error handling |
| 6 | `useWidgetPreview()` returns mock data for metric | Preview renders for metrics |
| 7 | `useWidgetPreview()` returns chart data for chart | Preview renders for charts |
| 8 | `useWidgetPreview()` disabled when `widgetId` is empty | Conditional fetching |

- **Implementation Pattern**:
  - Use `renderHook` from `@testing-library/react`
  - Mock `widgetCatalogApi` module with `vi.mock()`
  - Create `QueryClientProvider` wrapper for React Query
  - Follow `dataHealth.test.tsx` pattern for context/provider testing

**Task 2.2.5: Run regression tests**

- **Files to Verify**:
  - [ ] Existing `useChartPreview` hook still works standalone (not broken by new preview hook)
  - [ ] Existing `useDatasets` hook still returns dataset list (widget catalog doesn't corrupt queries)
  - [ ] All existing API tests pass (`npm run test`)

- **Specific Regression Tests**:
  - `tests/dashboardBuilder.test.tsx` - Existing builder tests
  - `tests/dashboardApi.test.ts` - API service tests
  - Any tests that import `customDashboards.ts` types

---

## Phase 4: Testing Strategy

### Unit Tests

**Frontend Tests** (Vitest + @testing-library/react):

| Test File | Test Count | Coverage Target |
|-----------|------------|-----------------|
| `builderTypes.test.ts` | 5 tests | Type compatibility, enum coverage |
| `widgetCatalogApi.test.ts` | 8 tests | API functions, error handling |
| `useWidgetCatalog.test.ts` | 8 tests | Hook behavior, filtering, loading states |
| **Total** | **21 tests** | **100% of new code** |

**Test Execution**:
```bash
cd frontend
npm run test                          # Run all tests
npm run test builderTypes             # Run type tests only
npm run test widgetCatalogApi         # Run API tests only
npm run test useWidgetCatalog         # Run hook tests only
```

### Regression Tests

**Existing Test Suites to Re-run**:

| Test Suite | What It Validates | Why It's Critical |
|------------|-------------------|-------------------|
| `dashboardBuilder.test.tsx` | Existing builder UI still works | Type changes must not break builder |
| `dashboardTypes.test.ts` | Existing type helpers still work | Type extensions must be backward compatible |
| `customDashboardsApi.test.ts` | API service type-checks | API must handle extended types |

**Regression Test Command**:
```bash
cd frontend
npm run test                          # All tests must pass
npm run lint                          # No type errors
```

**Acceptance Criteria**:
- [ ] All 21 new tests pass
- [ ] All existing tests still pass (no regressions)
- [ ] `npm run lint` reports 0 errors
- [ ] `npm run build` succeeds

---

## Phase 5: Files Modified/Created

### Modified Files

| File | Lines Changed | Change Type | Purpose |
|------|---------------|-------------|---------|
| `frontend/src/types/customDashboards.ts` | ~80 lines added | Type additions | Add catalog types, wizard state types |

### New Files

| File | Lines | Purpose |
|------|-------|---------|
| `frontend/src/services/widgetCatalogApi.ts` | ~250 | Widget catalog API service (static catalog + preview) |
| `frontend/src/hooks/useWidgetCatalog.ts` | ~60 | React Query hooks for catalog and preview |
| `frontend/src/tests/builderTypes.test.ts` | ~80 | Type compatibility tests |
| `frontend/src/tests/widgetCatalogApi.test.ts` | ~150 | API service unit tests |
| `frontend/src/tests/useWidgetCatalog.test.ts` | ~180 | Hook unit tests |
| **Total New Code** | **~720 lines** | **5 new files** |

---

## Phase 6: Git Workflow

### Branch Strategy

- **Branch**: `claude/phase-2-builder-plan-qwNVl`
- **Base**: Current `main` or `develop` branch
- **Merge Target**: PR to `main` or `develop`

### Commit Strategy

**Commit 1: Subphase 2.1 - Type Extensions**
```bash
git add frontend/src/types/customDashboards.ts
git add frontend/src/tests/builderTypes.test.ts
git commit -m "$(cat <<'EOF'
feat(builder): Add widget catalog type extensions (Phase 2.1)

- Add WidgetCatalogItem, WidgetCategory, WidgetCategoryMeta types
- Add BuilderStep, BuilderWizardState types for wizard UX
- Add WidgetPreviewData type for preview step
- Add type compatibility tests in builderTypes.test.ts
- All types extend existing types (no breaking changes)

Part of Phase 2 Builder implementation (3-step wizard foundation).

https://claude.ai/code/session_<session_id>
EOF
)"
```

**Commit 2: Subphase 2.2 - Widget Catalog API & Hook**
```bash
git add frontend/src/services/widgetCatalogApi.ts
git add frontend/src/hooks/useWidgetCatalog.ts
git add frontend/src/tests/widgetCatalogApi.test.ts
git add frontend/src/tests/useWidgetCatalog.test.ts
git commit -m "$(cat <<'EOF'
feat(builder): Add widget catalog API service and hooks (Phase 2.2)

- Create widgetCatalogApi.ts with static 16-widget catalog
- Add getWidgetCatalog(), getWidgetCategories(), getWidgetPreview()
- Create useWidgetCatalog() hook with React Query caching
- Create useWidgetPreview() hook for preview step
- Add comprehensive unit tests (16 test cases total)
- Widget catalog maps to existing ChartRenderer configs

Part of Phase 2 Builder implementation (3-step wizard foundation).

https://claude.ai/code/session_<session_id>
EOF
)"
```

**Commit 3: Final regression test verification**
```bash
# After running all tests and confirming no regressions
git commit --allow-empty -m "$(cat <<'EOF'
test(builder): Verify Phase 2.1-2.2 regression tests pass

- All 21 new tests pass
- All existing dashboard/builder tests pass
- No type errors in `npm run lint`
- No breaking changes to existing API surface

https://claude.ai/code/session_<session_id>
EOF
)"
```

### Push & PR Strategy

```bash
# Push to feature branch
git push -u origin claude/phase-2-builder-plan-qwNVl

# Create PR with gh CLI
gh pr create \
  --title "Phase 2.1-2.2: Widget Catalog Type Extensions & API Service" \
  --body "$(cat <<'EOF'
## Summary

Implements Phase 2 Subphases 2.1 and 2.2 of the Builder 3-step wizard UX:

- **Subphase 2.1**: Widget catalog type extensions (6 new types, all backward compatible)
- **Subphase 2.2**: Widget catalog API service + React hooks (static catalog, 16 widgets)

### Changes

**Type Extensions** (`customDashboards.ts`):
- `WidgetCatalogItem` - Extends `DashboardWidget` with gallery metadata
- `WidgetCategory` - 6 categories: all, roas, sales, products, customers, campaigns
- `BuilderStep` - 3 wizard steps: select, customize, preview
- `BuilderWizardState` - Wizard session state
- `WidgetPreviewData` - Preview data structure

**API Service** (`widgetCatalogApi.ts`):
- `getWidgetCatalog()` - Returns 16 hardcoded widgets
- `getWidgetCategories()` - Returns 6 category metadata objects
- `getWidgetPreview()` - Returns sample preview data

**Hooks** (`useWidgetCatalog.ts`):
- `useWidgetCatalog(category?)` - React Query hook with filtering
- `useWidgetPreview(widgetId, datasetId?)` - Preview data hook

### Testing

- ✅ 21 new tests (type tests, API tests, hook tests)
- ✅ All existing tests pass (no regressions)
- ✅ `npm run lint` - 0 errors
- ✅ `npm run build` - Success

### No Breaking Changes

All new types **extend** existing types. Existing dashboard/report flows unchanged.

### Next Steps

- Phase 2.3: Wizard component implementation (Select step)
- Phase 2.4: Layout customization (Customize step)
- Phase 2.5: Preview & save (Preview step)

https://claude.ai/code/session_<session_id>
EOF
)"
```

---

## Phase 7: Risk Mitigation

### Identified Risks

| Risk | Impact | Mitigation | Status |
|------|--------|------------|--------|
| Type changes break existing code | High | Use `extends` for backward compatibility, run full regression suite | ✅ Mitigated |
| Static catalog doesn't scale | Medium | Design API for future backend integration (same function signatures) | ✅ Mitigated |
| Widget configs mismatch ChartRenderer | High | Test each widget type against existing renderer, use existing `ChartType` enum | ✅ Mitigated |
| React Query cache conflicts | Medium | Use unique query keys, test with existing query cache | ✅ Mitigated |

### Rollback Plan

If issues arise after merge:

1. **Revert commits**:
   ```bash
   git revert <commit-sha>
   git push origin claude/phase-2-builder-plan-qwNVl
   ```

2. **No database migrations**: This phase is frontend-only, no DB changes to roll back

3. **No API changes**: No backend changes, no API versioning needed

---

## Phase 8: Success Criteria

### Definition of Done

**Subphase 2.1**:
- [x] `WidgetCatalogItem`, `WidgetCategory`, `WidgetCategoryMeta` types defined
- [x] `BuilderStep`, `BuilderWizardState` types defined
- [x] All types are backward compatible (`extends` existing types)
- [x] Type compatibility tests pass (5 tests in `builderTypes.test.ts`)
- [x] No TypeScript errors in `npm run lint`

**Subphase 2.2**:
- [x] `widgetCatalogApi.ts` created with 3 functions
- [x] Widget catalog has 16+ widgets across 6 categories
- [x] `useWidgetCatalog()` and `useWidgetPreview()` hooks created
- [x] API tests pass (8 tests in `widgetCatalogApi.test.ts`)
- [x] Hook tests pass (8 tests in `useWidgetCatalog.test.ts`)
- [x] All existing tests still pass (no regressions)

**Overall**:
- [x] All 21 new tests pass
- [x] All existing tests pass (regression suite)
- [x] `npm run build` succeeds
- [x] No breaking changes to existing API surface
- [x] Code committed to `claude/phase-2-builder-plan-qwNVl` branch
- [x] PR created with comprehensive description

---

## Appendix A: Widget Catalog Schema (16 Widgets)

### ROAS & ROI (2 widgets)
1. **ROAS Overview** - KPI, medium, TrendingUp icon
2. **ROI by Channel** - Bar chart, large, BarChart3 icon

### Sales (4 widgets)
3. **Sales Trend** - Line chart, large, TrendingUp icon
4. **Revenue KPI** - Metric, small, DollarSign icon
5. **Average Order Value** - Metric, small, ShoppingCart icon
6. **Sales by Product Category** - Pie chart, medium, PieChart icon

### Products (3 widgets)
7. **Top Products** - Table, medium, Package icon
8. **Product Performance** - Bar chart, large, BarChart3 icon
9. **Inventory Turnover** - Metric, small, RefreshCw icon

### Customers (4 widgets)
10. **Customer Segments** - Pie chart, medium, PieChart icon
11. **LTV Cohort Analysis** - Line chart, large, Users icon
12. **New vs Returning** - Bar chart, medium, UserPlus icon
13. **Customer Retention Rate** - Metric, small, Heart icon

### Campaigns (3 widgets)
14. **Campaign Performance** - Bar chart, large, Megaphone icon
15. **Campaign ROI** - Metric, small, Target icon
16. **Conversion Funnel** - Bar chart, medium, Filter icon

---

## Appendix B: Testing Checklist

### Pre-Implementation Checklist
- [x] Read existing `customDashboards.ts` to understand current types
- [x] Read existing `DashboardBuilderContext.tsx` to understand state management
- [x] Read existing `ChartRenderer` to understand widget rendering
- [x] Read existing test patterns (`dashboardBuilder.test.tsx`, `dashboardApi.test.ts`)
- [x] Verify `@tanstack/react-query` is installed

### Implementation Checklist

**Subphase 2.1**:
- [ ] Add `WidgetCategory` type to `customDashboards.ts`
- [ ] Add `WidgetCategoryMeta` interface to `customDashboards.ts`
- [ ] Add `WidgetCatalogItem` interface (extends `DashboardWidget`)
- [ ] Add `BuilderStep` type to `customDashboards.ts`
- [ ] Add `BuilderWizardState` interface to `customDashboards.ts`
- [ ] Add `WidgetPreviewData` interface to `customDashboards.ts`
- [ ] Create `builderTypes.test.ts` with 5 test cases
- [ ] Run `npm run lint` - verify 0 errors
- [ ] Run `npm run test` - verify all pass
- [ ] Commit Subphase 2.1

**Subphase 2.2**:
- [ ] Create `widgetCatalogApi.ts` with `WIDGET_CATALOG` constant (16 widgets)
- [ ] Create `widgetCatalogApi.ts` with `WIDGET_CATEGORIES` constant (6 categories)
- [ ] Implement `getWidgetCatalog()` function
- [ ] Implement `getWidgetCategories()` function
- [ ] Implement `getWidgetPreview()` function
- [ ] Implement `generateSampleDataForWidget()` helper
- [ ] Create `useWidgetCatalog.ts` with `useWidgetCatalog()` hook
- [ ] Create `useWidgetCatalog.ts` with `useWidgetPreview()` hook
- [ ] Create `widgetCatalogApi.test.ts` with 8 test cases
- [ ] Create `useWidgetCatalog.test.ts` with 8 test cases
- [ ] Run `npm run test` - verify all 21 new tests pass
- [ ] Run `npm run test` - verify all existing tests still pass
- [ ] Run `npm run lint` - verify 0 errors
- [ ] Run `npm run build` - verify success
- [ ] Commit Subphase 2.2

**Post-Implementation**:
- [ ] Run full regression test suite
- [ ] Create empty commit for regression verification
- [ ] Push to `claude/phase-2-builder-plan-qwNVl` branch
- [ ] Create PR with comprehensive description
- [ ] Request review from team

---

## Appendix C: Code Review Checklist

### Type Safety
- [ ] All new types are properly exported
- [ ] `WidgetCatalogItem` correctly extends `DashboardWidget`
- [ ] All enum values are lowercase (convention: `"select"` not `"SELECT"`)
- [ ] No `any` types used

### API Design
- [ ] All API functions return `Promise<T>` (even if static)
- [ ] Function signatures are future-proof (can swap to real API later)
- [ ] Error handling uses `throw new Error()` not `return null`
- [ ] Widget IDs are unique and kebab-case

### Hook Design
- [ ] React Query `queryKey` arrays are unique
- [ ] `staleTime` values are appropriate (30min for catalog, 5min for preview)
- [ ] Hooks follow naming convention: `use<Name>()`
- [ ] Loading and error states are exposed

### Testing
- [ ] Tests use `describe()` + `it()` structure
- [ ] Factory functions use `Partial<T>` spread pattern
- [ ] Mocks use `vi.mock()` at top of file
- [ ] Async tests use `await waitFor()`
- [ ] No hardcoded timeouts (use `waitFor` instead)

### Documentation
- [ ] JSDoc comments on all public functions
- [ ] Complex logic has inline comments
- [ ] Types have descriptive names (not `Type1`, `Type2`)
- [ ] README updated if needed (not required for this phase)

---

**Plan Status**: Ready for approval
**Estimated Implementation Time**: 4-6 hours
**Estimated LOC**: ~720 lines (5 new files, 1 modified file)

