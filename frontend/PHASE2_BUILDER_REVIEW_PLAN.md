# Phase 2 Builder Review Plan (Decision-Integrated)

This plan is now updated with your decisions so implementation can proceed in **4–5 incremental PRs** with testing at each step.

---

## Confirmed decisions (from review)

1. **Component location**: Migrate wizard UI to `components/builder/*` (canonical location).
2. **Route strategy**: Keep create and edit flows as separate routes.
3. **Catalog model**: Add business categories (`all`, `roas`, `sales`, `products`, `customers`, `campaigns`) as primary taxonomy.
4. **Preview behavior**:
   - Use live Superset data immediately when available.
   - Fallback to preview/mock data only when live data is unavailable.
   - Display a **watermark** in fallback mode indicating data is not actual/live.
5. **Duplicate widgets**: Allowed (multiple instances of same catalog widget).
6. **Save as template**: Persist full dashboard configuration (widgets + layout + settings/config).
7. **Edit-mode hydration**: Support `uncategorized` fallback bucket when reverse-mapping existing dashboards.
8. **Delivery model**: 4–5 incremental PRs with preserved test coverage.

---

## Implementation status

- ✅ **Phase 1 (PR1): Type + mapping foundation** — implemented in code (type extensions + category mapping helpers + initial unit tests).
- ✅ **Phase 2 (PR2): Catalog service + hook refactor** — implemented in code (service surface + hook query refactor + tests).
- ⏳ **Phase 3 (PR3): Context hardening + hydration rules** — pending.
- ⏳ **Phase 4 (PR4): UI consolidation into `components/builder/*`** — pending.
- ⏳ **Phase 5 (PR5): Live-first preview + save/template completion** — pending.

---

## Current-state implementation inventory (already built)

### Foundations already present

- Wizard type primitives exist in `frontend/src/types/customDashboards.ts` (`BuilderStep`, `WidgetCatalogItem`, `BuilderWizardState`).
- Wizard state/actions/guards already exist in `frontend/src/contexts/DashboardBuilderContext.tsx`.
- Catalog fetch path exists via `frontend/src/hooks/useWidgetCatalog.ts` + `frontend/src/utils/widgetCatalog.ts`.
- Wizard route is already wired at `/dashboards/wizard`.

### Existing UI stacks

- Current wizard UI is mainly under `frontend/src/components/dashboards/wizard/*`.
- Overlapping Step 2 components are already present under `frontend/src/components/builder/*`.

### Gaps still to close

- Requested catalog service API surface (`widgetCatalogApi.ts`) is not yet formalized.
- Business-category type model and metadata are not yet first-class in types.
- Preview fallback watermark behavior is not yet specified/implemented.
- Full Phase 2 test files in the requested matrix are mostly missing.

---

## Target architecture after refactor

### Routing

- Keep separate routes:
  - `/dashboards/wizard` = create flow
  - `/dashboards/:dashboardId/edit` = edit flow

### UI component ownership

- Canonicalize all Phase 2 wizard components under: `frontend/src/components/builder/*`
- Deprecate/remove duplicated implementations under `components/dashboards/wizard/*` after parity is confirmed.

### Data/category model

- Introduce business categories as primary filter taxonomy.
- Keep compatibility mapper from existing chart/template-derived metadata.
- Add `uncategorized` as internal fallback bucket for edit-mode hydration mismatches.

### Preview data policy

- **Primary**: live Superset/real data render.
- **Fallback**: sample/preview render with visible watermark (e.g., “Preview Data — Not Live”).
- Avoid forcing refetch loops unless user changes controls or explicit refresh event occurs.

---

## Incremental PR roadmap (5 PRs)

## PR1 — Type + mapping foundation (Subphase 2.1)

### Scope
- Extend `customDashboards.ts` with:
  - `WidgetCategory` (`all | roas | sales | products | customers | campaigns`)
  - `WidgetCategoryMeta`
  - category-compatible `WidgetCatalogItem` fields (maintain backward compatibility)
  - `BuilderWizardState` updates to hold new category model
- Add mapper helpers:
  - template/report -> catalog item
  - dashboard(report set) -> wizard category bucket (`uncategorized` fallback)

### Tests
- Add `builderTypes.test.ts`
- Keep `dashboardTypes.test.ts` green (regression)

### Exit criteria
- Types compile without API/service regressions.

---

## PR2 — Catalog service + hook refactor (Subphase 2.2)

### Scope
- Add `frontend/src/services/widgetCatalogApi.ts` with:
  - `getWidgetCatalog()`
  - `getWidgetCategories()`
  - `getWidgetPreview(widgetId, datasetId?)`
- Refactor `useWidgetCatalog` to React Query (`queryKey: ["widget-catalog"]`, staleTime 30m).
- Preserve compatibility adapter so existing callers are not broken during migration.

### Tests
- Add `widgetCatalogApi.test.ts`
- Add `useWidgetCatalog.test.ts`
- Regression check for existing dataset/chart preview hooks

### Exit criteria
- Catalog loading/filtering stable and typed.

---

## PR3 — Context hardening + duplicate policy + hydration (Subphase 2.3)

### Scope
- Enforce duplicate-widget policy: allow multiple instances with unique generated IDs.
- Add explicit guard logic for step transitions.
- Add/verify dashboard->wizard hydration with `uncategorized` fallback.
- Ensure dirty/clean lifecycle is deterministic for create/edit/save paths.

### Tests
- Add `builderContext.wizard.test.tsx`
- Add targeted integration tests for full state transitions
- Regression: existing builder tests remain green

### Exit criteria
- Wizard state transitions and conversions fully test-backed.

---

## PR4 — UI consolidation into `components/builder` (Subphases 2.4 + 2.5)

### Scope
- Migrate Step 1 + Step 2 components into `components/builder/*`.
- Update imports/usages in route/page composition.
- Remove/reduce duplicated wizard components once parity confirmed.
- Keep route separation (`/dashboards/wizard` stays create path).
- Preserve ReportConfigurator bridge from layout step.

### Tests
- Add component unit tests:
  - `WidgetCatalogCard`, `CategorySidebar`, `SelectedWidgetsList`, `BuilderStepNav`, `BuilderToolbar`
  - `LayoutWidgetPlaceholder`, `LayoutCustomizer`, `LayoutControls`
- Add integration tests for Step 1 and Step 2 flows

### Exit criteria
- Single canonical builder UI stack, no active duplicates.

---

## PR5 — Preview + save/template flow completion (Subphase 2.6)

### Scope
- Implement live-first preview behavior with fallback watermark:
  - live data if available
  - fallback preview + watermark if not
- Complete “Save as Template” using full configuration payload.
- Finalize publish/save behavior alignment with existing mutations.
- Keep create/edit routes separate but ensure consistent shared state contracts.

### Tests
- Add `PreviewWidget.test.tsx`, `DashboardPreview.test.tsx`, `SaveFlow.test.ts`
- Add `DashboardBuilder.integration.test.tsx`
- Add `Phase2.e2e.test.tsx` + `Phase2.regression.test.tsx`

### Exit criteria
- Full create/edit/preview/save/template/publish path covered and green.

---

## Regression strategy per PR

### Must pass each PR
- Existing: `dashboardBuilder.test.tsx`
- Existing: `dashboardApi.test.ts`
- Any impacted chart rendering tests
- ReportConfigurator modal/component regression checks

### Must pass by end of PR5
- New Phase 2 unit + integration + e2e + regression suites
- Route sanity: `/dashboards`, `/dashboards/wizard`, `/dashboards/:dashboardId/edit`
- No duplicate active UI stacks in runtime path

---

## Final acceptance criteria

Phase 2 is considered complete when:

1. Wizard UI is canonicalized in `components/builder/*`.
2. Business category model is active with edit fallback bucket support.
3. Live-first preview works; fallback preview clearly watermarked.
4. Duplicate widgets are supported with stable IDs.
5. Save-as-template persists full dashboard configuration.
6. Create and edit routes remain separate and stable.
7. Phase 2 test matrix is implemented and green.
