# Phase 2 Builder Plan — Implementation Review

## Executive summary

Status by subphase (against the plan in the request):

- **2.1 Widget Catalog Type Extensions**: **Partially implemented**
- **2.2 Widget Catalog API & Hook**: **Mostly implemented**
- **2.3 Builder Context Extension — Wizard State**: **Mostly implemented (with architecture deviation)**
- **2.4 Widget Gallery UI (Step 1)**: **Partially implemented**
- **2.5 Layout Customizer UI (Step 2)**: **Partially implemented**
- **2.6 Preview/Save/Assembly (Step 3)**: **Partially implemented**

## Detailed review

### Subphase 2.1 — Widget Catalog Type Extensions

**Implemented**
- `WidgetCategory`, `WidgetCategoryMeta`, `BuilderStep`, `WidgetCatalogItem`, and `BuilderWizardState` are present in `customDashboards.ts`.
- Grid size mapping (`SIZE_TO_COLUMNS`) exists and matches the 12-column mapping in the plan.
- Supporting category metadata and mapping helpers are present.

**Gaps / deviations**
- `WidgetCategory` includes an extra `"uncategorized"` value not in the requested 6 categories.
- `WidgetCatalogItem` shape differs from requested spec:
  - Uses `name`, `category: ChartType`, `chart_type`, `default_config`, and `templateId` as core fields.
  - Requested `type: WidgetType`, `category: WidgetCategory`, and pure gallery model fields are only partially represented (some optional aliases were added).
- Wizard state uses additional fields (`isWizardMode`, `selectedWidgets`, description/date/template flags), which is okay, but is not a direct schema match.

### Subphase 2.2 — Widget Catalog API & Hook

**Implemented**
- `services/widgetCatalogApi.ts` exists with:
  - `getWidgetCatalog()`
  - `getWidgetCategories()`
  - `getWidgetPreview()`
  - category filter helper and cache reset helper.
- `hooks/useWidgetCatalog.ts` exists with:
  - `useWidgetCatalog(...)`
  - `useWidgetPreview(...)`
- Unit tests exist for API and hook.

**Gaps / deviations**
- Catalog is sourced from templates (`fetchWidgetCatalog()`), not from a fixed wireframe-style 16-item static list.
- `getWidgetPreview()` currently returns synthetic fallback-style payloads (KPI/table/series) and does not appear to bridge directly into the existing chart preview pipeline.
- Hook uses `useQueryLite` with two keys (`widget-catalog`, `widget-categories`), rather than a single React Query setup exactly as described.

### Subphase 2.3 — Builder Context Extension (Wizard State)

**Implemented**
- Context exposes wizard state and many wizard actions:
  - `setBuilderStep`, `setSelectedCategory`, `addCatalogWidget`, `resetWizard`, dirty handling, derived guards (`canProceedToCustomize`, `canProceedToPreview`), etc.
- Wizard-related tests exist and pass.

**Gaps / deviations**
- The plan’s critical constraint requested extending an existing reducer/action pattern; implementation uses `useState` state transitions (no centralized reducer with the named action constants).
- Action naming differs from plan (functional API rather than explicit reducer action types).
- Coverage is lighter than requested matrix (the existing test file has 5 wizard tests, not the full requested suite + integrations/regressions).

### Subphase 2.4 — Widget Gallery UI (Step 1)

**Implemented**
- Wizard Step 1 components exist (under `components/dashboards/wizard/`):
  - `WidgetGallery`, `WidgetCatalogCard`, `CategorySidebar`, `BuilderStepNav`, and toolbar components.
- `WizardFlow` renders category sidebar + widget gallery and supports selection/continue flow.

**Gaps / deviations**
- File locations differ from requested `components/builder/*` structure.
- No dedicated `SelectedWidgetsList.tsx` file in requested location.
- Requested component-level unit test files for Step 1 are not present.

### Subphase 2.5 — Layout Customizer UI (Step 2)

**Implemented**
- Step 2 components in `components/builder/`:
  - `LayoutCustomizer.tsx`
  - `LayoutWidgetPlaceholder.tsx`
  - `LayoutControls.tsx`
- Includes empty state, info banner, size cycling, settings/delete actions, and step navigation controls.

**Gaps / deviations**
- The requested dedicated unit/integration test files for layout customizer are not present.
- The drag handle appears visual only (which is acceptable per plan), but there is no explicit evidence of full DnD.

### Subphase 2.6 — Preview Step, Save Flow & Full Assembly

**Implemented**
- Preview-related wizard components exist in `components/dashboards/wizard/` (`PreviewGrid`, `PreviewControls`, `PreviewReportCard`) and are wired in `WizardFlow`.
- Route `/dashboards/wizard` renders `WizardFlow` within `DashboardBuilderProvider`.

**Gaps / deviations**
- Requested files (`DashboardPreview.tsx`, `PreviewWidget.tsx`, `PreviewToolbar.tsx`) in `components/builder/` are not present.
- `pages/DashboardBuilder.tsx` remains the legacy edit builder page and does not assemble all 3 wizard steps.
- Save-as-template is explicitly TODO/placeholder (`alert(...)`).
- Requested save-flow tests, integration tests, e2e smoke tests, and full Phase 2 regression suite are not present.

## Test/regression coverage snapshot

**Present and passing (sampled)**
- `builderTypes.test.ts`
- `widgetCatalogApi.test.ts`
- `useWidgetCatalog.test.ts`
- `builderContext.wizard.test.tsx`

**Not found (from requested plan)**
- Step-1 UI component tests (`WidgetCatalogCard.test.tsx`, `CategorySidebar.test.tsx`, etc.)
- Step-2/Step-3 dedicated component tests and integration suites
- `DashboardBuilder.integration.test.tsx`, `Phase2.e2e.test.tsx`, `Phase2.regression.test.tsx`

## Bottom line

The repository has **meaningful Phase 2 groundwork implemented**, especially in types/catalog/context and a routed wizard flow. However, it does **not fully match** the requested subphase plan in file structure, strict type contract, reducer architecture constraint, and breadth of automated test coverage.

## Subphase 2.1 gap-closure plan (actionable)

This section breaks **only Subphase 2.1** into a concrete implementation plan to close the type-system gaps while minimizing churn to existing wizard code.

### Objective

Align `customDashboards.ts` with the requested wireframe catalog model while preserving compatibility with current template-driven catalog extraction and wizard state usage.

---

### Gap summary to close

1. **Category union mismatch**
   - Requested taxonomy: `all | roas | sales | products | customers | campaigns`
   - Current model includes extra `uncategorized`.

2. **Catalog item contract mismatch**
   - Requested core model uses:
     - `type: WidgetType`
     - `title`
     - `category: WidgetCategory`
     - `defaultSize: WidgetSize`
   - Current model centers on template-derived report fields (`name`, `chart_type`, `default_config`, `templateId`, etc.).

3. **Wizard state shape mismatch**
   - Requested minimal shape:
     - `currentStep`, `selectedCatalogItems`, `dashboardName`, `selectedCategory`, `isDirty`
   - Current shape is expanded and uses `selectedCategory?: ChartType`.

4. **Explicit compatibility contract is missing**
   - No formal adapter types/functions define conversion between new canonical catalog model and existing report/template/wizard internals.

---

### Proposed design approach

Use a **canonical + compatibility adapter** model to avoid breaking existing flows:

- Introduce canonical Phase 2.1 types as requested.
- Keep existing template/report-oriented fields, but isolate them behind a compatibility wrapper.
- Add explicit mapper helpers for deterministic conversions.

This avoids large rewrites while making the requested contract first-class.

---

### Implementation plan (sequenced)

#### Step 1 — Add canonical catalog types (no behavior change)

Update `frontend/src/types/customDashboards.ts`:

- Add/confirm:
  - `WidgetType` (if absent) as union aligned to renderable widget kinds.
  - `WidgetCategory` **canonical** union with only the 6 requested categories (+ `all`).
  - `WidgetCatalogItem` canonical interface exactly per plan fields.
  - `BuilderStep` and `BuilderWizardState` canonical interfaces.

- Keep existing extended fields by introducing:
  - `LegacyWidgetCatalogItem` (or `TemplateBackedWidgetCatalogItem`) for current template extraction extras.
  - `LegacyBuilderWizardState` for current expanded context state.

Acceptance criteria:
- TypeScript compiles.
- Existing imports continue to resolve (no immediate runtime changes).

#### Step 2 — Introduce explicit adapters

In `customDashboards.ts` (or a new `frontend/src/types/widgetCatalogAdapters.ts`):

- Add pure conversion helpers:
  - `toCanonicalWidgetCatalogItem(legacyItem): WidgetCatalogItem`
  - `toLegacyWidgetCatalogItem(canonicalItem, defaults): LegacyWidgetCatalogItem`
  - `chartTypeToWidgetType(chartType): WidgetType`
  - `widgetTypeToChartType(widgetType): ChartType | null`

- Add safe category normalization:
  - `normalizeWidgetCategory(input): WidgetCategory`
  - map unknowns to a defined fallback policy (e.g., `'all'`) instead of widening the union.

Acceptance criteria:
- Adapters are unit-testable and deterministic.

#### Step 3 — Repoint catalog API contract to canonical model

Update `frontend/src/services/widgetCatalogApi.ts`:

- `getWidgetCatalog()` returns canonical `WidgetCatalogItem[]`.
- Internal template-derived fields should remain internal (or exposed via dedicated metadata object, not primary type contract).
- `getWidgetCategories()` returns strictly requested categories for UI sidebar.

Acceptance criteria:
- Hook and existing gallery still render.
- No `any` casting needed in catalog API tests.

#### Step 4 — Reconcile wizard state typing without full refactor

Update context typing in `frontend/src/contexts/DashboardBuilderContext.tsx`:

- Keep existing runtime state but expose a typed `wizardStateView` (or align existing `wizardState`) that satisfies canonical `BuilderWizardState` where consumed by wizard UI.
- Change category filter typing from `ChartType` to `WidgetCategory` at the gallery boundary.

Acceptance criteria:
- No behavior regression in add/remove widgets and step guards.
- Existing edit-mode hydration remains functional.

#### Step 5 — Test coverage for 2.1-specific contract

Expand/add tests:

- `frontend/src/tests/builderTypes.test.ts`
  - assert category union contains exactly requested set.
  - assert default size→columns mapping.
  - assert canonical `WidgetCatalogItem` minimal required fields.
- New tests for adapters:
  - `frontend/src/tests/widgetCatalogAdapters.test.ts`
  - round-trip conversion invariants.
- Keep `dashboardTypes.test.ts` green for regression.

Acceptance criteria:
- New tests pass.
- Existing type tests and API compile tests pass.

---

### Suggested task breakdown (PR slices)

1. **PR A (Types only)**
   - canonical type additions + deprecation comments on legacy fields.
2. **PR B (Adapters + tests)**
   - mapper utilities + focused unit tests.
3. **PR C (API/hook alignment)**
   - catalog API returns canonical contract + hook typing updates.
4. **PR D (Context boundary alignment)**
   - category typing alignment at wizard boundary + regression checks.

This sequence reduces risk and keeps each reviewable.

---

### Risks and mitigations

- **Risk:** broad type ripple into wizard/context/report config.
  - **Mitigation:** add canonical interfaces first, then migrate call sites incrementally via adapters.

- **Risk:** category fallback handling breaks legacy edit-mode hydration.
  - **Mitigation:** centralize normalization in adapter helpers and test with legacy report fixtures.

- **Risk:** accidental API contract ambiguity between canonical and legacy fields.
  - **Mitigation:** document canonical contract as default export type and mark legacy extensions as internal/deprecated.

---

### Definition of done for Subphase 2.1

Subphase 2.1 is considered complete when:

1. Canonical requested types are present and used as the public catalog contract.
2. Legacy/template-backed needs are represented through explicit compatibility types/adapters (not mixed implicit fields).
3. Category and wizard-step typing at UI boundaries match the wireframe plan.
4. 2.1-specific tests pass, and existing dashboard type/API regression tests remain green.


## Subphase 2.2 gap-closure plan (frontend ↔ backend integration)

This section expands **Subphase 2.2** into an implementation plan focused on making the widget catalog and preview flow reliably tied to backend APIs with contract-level validation.

### Objective

Ensure `widgetCatalogApi` + `useWidgetCatalog` are backed by real backend contracts end-to-end (catalog, categories, preview), with clear fallback behavior only when explicitly intended.

---

### Confirmed integration issues to address

1. **Preview endpoint drift across services**
   - One frontend path used `/api/v1/datasets/preview` while backend datasets routes are mounted at `/api/datasets/*`.
   - This creates route inconsistency risk and environment-dependent 404s.

2. **Dataset identifier ambiguity**
   - Some flows pass a variable named `datasetId` but backend preview expects `dataset_name`.
   - This can silently trigger fallback previews instead of real data.

3. **Contract coverage still too thin for non-mocked confidence**
   - Existing tests cover key paths, but not yet a comprehensive matrix for API error classes, schema drift, and malformed payloads.

---

### Potential contract risks (need explicit decisions)

1. **Category source-of-truth mismatch**
   - Frontend categories are business-taxonomy driven, backend catalog source currently derives from templates/chart types.
   - Need a canonical mapping contract that is versioned and tested.

2. **Preview response transformation assumptions**
   - Current FE transformation assumes first column is label/dimension and another column is numeric value.
   - Must define behavior when backend returns multiple numeric columns, sparse columns, or empty columns list.

3. **Fallback behavior can mask real API failures**
   - Fallback previews are useful UX, but if overused they can hide integration regressions.
   - Need observability and test assertions distinguishing “intentional fallback” vs “unexpected backend failure”.

---

### What must be true for users (minimum viable contract)

For users to trust preview data in the builder:

1. Selecting a widget from catalog must fetch a catalog item that maps to a real dataset and preview config.
2. Preview requests must hit backend preview endpoint with valid typed payload.
3. Successful preview responses must render real data in widget cards.
4. If backend fails, UI must clearly indicate fallback/sample mode (not silently pretend it is live).
5. Save-time payload must remain compatible with dashboard/report schemas used by create/update endpoints.

---

### Implementation plan (sequenced)

#### Step 1 — Lock endpoint and parameter contracts

- Create a shared constants module for builder data endpoints (templates/catalog/preview) and use it in:
  - `services/widgetCatalogApi.ts`
  - `services/reportDataApi.ts`
  - `services/datasetsApi.ts`
- Normalize naming at API boundary:
  - `datasetName` for backend calls
  - convert from UI/internal IDs before request construction

Acceptance criteria:
- No `/api/v1/datasets/preview` calls remain.
- All preview request builders require/provide `dataset_name` from a resolved dataset name.

#### Step 2 — Make catalog contract explicit

- Define canonical DTOs for catalog/categorization returned to UI layer.
- Add deterministic mappers from template-backed source to canonical catalog items.
- Document required fields per item: `id`, `title/name`, `chart_type`, `businessCategory`, `default_config`, `required_dataset`.

Acceptance criteria:
- `getWidgetCatalog()` returns stable canonical shape.
- Missing/invalid fields are rejected (or logged + filtered) deterministically.

#### Step 3 — Harden preview request/response mapping

- Extract request/response transformers into dedicated pure functions:
  - `buildWidgetPreviewRequest(item, datasetName)`
  - `mapChartPreviewResponseToWidgetPreview(response, chartType)`
- Add explicit handling for:
  - empty data rows
  - missing/empty columns
  - multi-metric responses
  - non-numeric value columns

Acceptance criteria:
- Transform behavior is deterministic for all edge cases.
- Fallback mode includes explicit metadata (`isFallback`, reason enum).

#### Step 4 — Increase non-mocked integration confidence

- Keep unit tests for fast feedback, but add contract-style tests that verify fetch URL/method/body + transformation behavior using realistic response fixtures.
- Add failure-path tests for:
  - 400 (validation)
  - 401/403 (auth/entitlement)
  - 404 (dataset/template missing)
  - 5xx (backend failure)
- Assert that these paths either surface actionable errors or mark preview as fallback with reason.

Acceptance criteria:
- Test suite proves endpoint usage, payload shape, and failure semantics.
- No silent fallback on auth/permission errors without signal.

#### Step 5 — Hook/UI behavior alignment

- Ensure `useWidgetPreview` returns enough state for UX clarity:
  - `isLoading`, `error`, `isFallback`, `fallbackReason`
- In preview UI components, show clear badge/text for sample mode vs live data.

Acceptance criteria:
- Users can distinguish live preview from placeholder preview.
- Product metrics can track fallback rate.

---

### Testing matrix (recommended)

1. **Service contract tests**
   - `widgetCatalogApi`: catalog load, category filtering, preview request mapping, response mapping.
2. **Integration tests (frontend service boundary)**
   - templates endpoint + datasets preview endpoint wiring.
   - route consistency checks for all preview entry points.
3. **Regression tests**
   - existing `useWidgetCatalog`, builder context wizard tests, dashboard API tests.
4. **Optional backend contract tests**
   - JSON-schema/OpenAPI assertion for `/api/datasets/preview` request/response fields used by frontend.

---

### Prioritized backlog (2.2-specific)

1. **P0**: Endpoint/path consistency audit and enforcement (all preview paths).
2. **P0**: Dataset ID/name normalization at API boundary.
3. **P1**: Extract + unit-test preview transformers.
4. **P1**: Expand failure-path integration tests with realistic error fixtures.
5. **P2**: Add fallback reason telemetry and UI labeling improvements.

---

### Definition of done for Subphase 2.2

Subphase 2.2 is complete when:

1. Catalog and preview frontend services consistently call the correct backend endpoints.
2. Request/response mappings are explicit, typed, and edge-case-tested.
3. Fallback behavior is intentional, visible to users, and observable to developers.
4. Test coverage includes successful, degraded, and failure paths without relying only on simplistic mocks.
