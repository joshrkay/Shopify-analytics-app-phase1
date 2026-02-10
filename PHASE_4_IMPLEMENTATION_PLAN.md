# Phase 4: Versioning + Sharing + Polish — Implementation Plan

## Executive Summary

Phase 4 builds the frontend UI for version history, sharing controls, audit trail, and navigation integration on top of the **already-complete backend** (API endpoints, services, models, schemas) and **partially-complete frontend** (API service methods, TypeScript types, ShareModal v1). The work is decomposed into 4 sub-phases (4A–4D) across **8 new files** and **4 modified files**, with **27 edge cases** addressed inline.

---

## Architecture Context (What Already Exists)

### Backend (Complete — No Changes Needed)
| Layer | Files | Status |
|-------|-------|--------|
| Models | `dashboard_version.py`, `dashboard_audit.py`, `dashboard_share.py` | Done |
| API Routes | `GET /versions`, `POST /restore/{version}`, `GET /audit`, share CRUD | Done |
| Services | `CustomDashboardService` (versioning, audit), `DashboardShareService` | Done |
| Schemas | `DashboardVersionResponse`, `AuditEntryResponse`, `ShareResponse` | Done |

### Frontend (Partial — API Layer Done, UI Missing)
| Layer | Files | Status |
|-------|-------|--------|
| API Services | `customDashboardsApi.ts` (`listVersions`, `restoreVersion`, `listAuditEntries`) | Done |
| API Services | `dashboardSharesApi.ts` (`listShares`, `createShare`, `updateShare`, `revokeShare`) | Done |
| Types | `DashboardVersion`, `AuditEntry`, `DashboardShare` in `customDashboards.ts` | Done |
| Hooks | `useShares.ts` (fetch + mutations with auto-refetch) | Done |
| Components | `ShareModal.tsx` (basic invite + revoke — needs enhancement) | Done (v1) |
| Routes | `/dashboards`, `/dashboards/:id`, `/dashboards/:id/edit` in `App.tsx` | Done |

### UI Framework
- **Shopify Polaris v12** — Modal, Card, Badge, Banner, Tabs, IndexTable, Spinner, etc.
- **react-grid-layout** — Dashboard grid rendering
- **react-router-dom v6** — Routing with `useParams`, `useNavigate`
- **Clerk** — Auth with `SignedIn`/`SignedOut`, `useClerkToken`

### Patterns to Follow
- **Modals**: Polaris `<Modal>` with `<Modal.Section>` (see `ShareModal.tsx`, `DeleteDashboardModal.tsx`)
- **Hooks**: Custom hooks with `useState`/`useCallback`, `isApiError()` for error extraction (see `useShares.ts`, `useDashboardMutations.ts`)
- **Error handling**: `Banner tone="critical"` for errors, cancelled-fetch pattern in useEffect
- **Feature gating**: `<FeatureGate feature="custom_dashboards" entitlements={entitlements}>` wrapper
- **State**: Local `useState` per component, no Redux/Zustand. Context only for builder session.

---

## Phase 4A: Version History UI

### Goal
Let users browse version history as a timeline, preview historical snapshots, and restore to previous versions with safety confirmations.

### Files to Create

#### 1. `frontend/src/components/dashboards/VersionHistory.tsx`
**Purpose**: Slide-out panel (Polaris Modal, large size) listing dashboard versions as a vertical timeline.

**Component interface**:
```tsx
interface VersionHistoryProps {
  dashboardId: string;
  currentVersionNumber: number;
  open: boolean;
  onClose: () => void;
  onRestore: (dashboard: Dashboard) => void;
}
```

**Implementation steps**:

1. **State management**:
   - `versions: DashboardVersion[]` — fetched from `listVersions(dashboardId)`
   - `total: number` — total version count for pagination
   - `loading: boolean` — initial fetch spinner
   - `loadingMore: boolean` — "Load more" pagination
   - `error: string | null` — fetch error banner
   - `restoring: number | null` — version_number currently being restored (disable other actions)
   - `previewVersion: DashboardVersion | null` — version selected for preview modal
   - `staleWarning: boolean` — shows "New changes available" banner

2. **Data fetching** (in `useEffect` on `open` change):
   - Call `listVersions(dashboardId, 0, 20)` when panel opens
   - Use the cancelled-fetch pattern (see `ShareModal.tsx:71-103` for reference)
   - Store result in `versions` and `total`
   - On error: show `Banner tone="critical"` with retry action

3. **Timeline rendering** (inside `<Modal>` → `<Modal.Section>`):
   - Map over `versions` array, rendering each as a timeline entry:
     ```
     [dot] Version {version_number} — "{change_summary}"
           {formatted_date} by {created_by}
           [Preview] [Restore]
     ```
   - Use Polaris `BlockStack` with a left-border CSS pseudo-element for the timeline line
   - Current version (matching `currentVersionNumber`) gets a `<Badge tone="success">Current</Badge>`
   - "Preview" button opens `VersionPreviewModal`
   - "Restore" button triggers restore flow (see step 5)

4. **Pagination** ("Load more" pattern):
   - If `versions.length < total`, show a "Load older versions" button at bottom
   - On click: call `listVersions(dashboardId, versions.length, 20)`
   - Append results to existing `versions` array

5. **Restore flow with confirmation**:
   - On "Restore" click, set `restoring = version_number`
   - Show inline confirmation: "Restore to version {N}? This will overwrite the current state."
   - **Edge case — deleted datasets**: Before calling `restoreVersion()`, we cannot pre-check datasets on the frontend (snapshot_json is not returned in the version list response). Instead, after `restoreVersion()` returns successfully, call `onRestore(dashboard)` which refreshes the parent. If the backend's restored reports reference deleted datasets, those reports will show `warnings[]` in their `Report` response — the existing `ViewReportCard`/`ReportCard` components should already render these warnings. Add a post-restore banner: "Dashboard restored to version {N}. Check for any warnings on individual charts."
   - On API error: show error banner, clear `restoring` state
   - On success: call `onRestore(restoredDashboard)`, close panel

6. **Stale version detection** (edge case — concurrent edit):
   - Store `initialVersionCount` when panel first loads
   - **Approach**: On each `listVersions` response, compare `total` to a stored value. If `total` has increased since the panel opened, set `staleWarning = true`
   - Render: `<Banner tone="info">New changes available. <Button onClick={refetch}>Refresh</Button></Banner>`
   - Alternative lightweight approach: Accept the prop `currentVersionNumber` from the parent. If the parent's dashboard re-fetches and the version_number changes, the parent can pass the new value down. Compare against the version list's first entry.

7. **Empty state**:
   - If `versions.length === 0` after loading: show `<EmptyState heading="No version history">This dashboard has no saved versions yet.</EmptyState>`

**Edge case handling summary for 4A**:

| Edge Case | Handling |
|-----------|----------|
| Restoring to version with deleted datasets | Post-restore banner + rely on per-report `warnings[]` from backend |
| Rapid version creation (debounce) | Backend-side concern — versions are created per mutation. Frontend debounce not applicable here since version creation is server-side on each `updateDashboard` call. **Backend change needed (out of scope for this frontend plan)**: debounce in `CustomDashboardService._create_version()` by checking if a version was created within 5 seconds. For now, document as a known limitation. |
| Version preview during concurrent edit | Stale detection via `total` count comparison + "New changes available" banner |
| Version cap (50) | Already enforced by backend `MAX_DASHBOARD_VERSIONS`. Oldest versions pruned automatically. Frontend just renders what the API returns. |

---

#### 2. `frontend/src/components/dashboards/VersionPreviewModal.tsx`
**Purpose**: Modal showing a read-only snapshot of a historical version's dashboard state.

**Component interface**:
```tsx
interface VersionPreviewModalProps {
  dashboardId: string;
  version: DashboardVersion | null;  // null = closed
  onClose: () => void;
  onRestore: (versionNumber: number) => void;
}
```

**Implementation steps**:

1. **Data requirements**:
   - The current `DashboardVersionResponse` schema does NOT include `snapshot_json` (see `backend/src/api/schemas/custom_dashboards.py:330-341`). The version list only returns `id`, `dashboard_id`, `version_number`, `change_summary`, `created_by`, `created_at`.
   - **Backend change needed**: Add a `GET /api/v1/dashboards/{id}/versions/{version_number}` endpoint that returns `DashboardVersionDetailResponse` including `snapshot_json`. **OR** add a query parameter `?include_snapshot=true` to the existing list endpoint for individual version fetch.
   - **Recommended approach**: Add a new API function `getVersion(dashboardId, versionNumber)` to `customDashboardsApi.ts` and a new type `DashboardVersionDetail` extending `DashboardVersion` with `snapshot_json`.

2. **Type additions** (in `customDashboards.ts`):
   ```tsx
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
   ```

3. **API addition** (in `customDashboardsApi.ts`):
   ```tsx
   export async function getVersion(
     dashboardId: string,
     versionNumber: number,
   ): Promise<DashboardVersionDetail> { ... }
   ```

4. **Backend endpoint addition** (in `custom_dashboards.py`):
   ```python
   @router.get("/{dashboard_id}/versions/{version_number}")
   async def get_version_detail(dashboard_id, version_number, ...):
       # Return version with snapshot_json included
   ```

5. **Modal rendering**:
   - Fetch version detail on open (when `version` prop is non-null)
   - Loading state: `<Spinner>` inside modal
   - Render dashboard metadata: name, description, version number, date, author
   - Render reports as a static grid (reuse `ReactGridLayout` with `isDraggable={false}` and `ViewReportCard` — same pattern as `DashboardView.tsx:188-203`)
   - **Note**: Report cards in preview will show config info but **not live data** (no chart preview API call). Show chart type, dataset name, metric labels as a card summary.
   - Footer: "Restore to this version" button + "Close" button

6. **Lightweight preview fallback** (if backend change is deferred):
   - If we cannot get `snapshot_json`, the preview modal simply shows:
     - Version metadata (number, date, author, change_summary)
     - A message: "Full preview requires restoring this version"
     - "Restore" and "Close" buttons
   - This is a valid MVP approach that avoids the backend change entirely.

---

### New Hook: `frontend/src/hooks/useVersions.ts`

**Purpose**: Encapsulate version fetching and restore logic, following the pattern of `useShares.ts`.

```tsx
interface UseVersionsResult {
  versions: DashboardVersion[];
  total: number;
  loading: boolean;
  restoring: boolean;
  error: string | null;
  fetchVersions: (offset?: number) => Promise<void>;
  restore: (versionNumber: number) => Promise<Dashboard>;
  clearError: () => void;
}
```

**Implementation**: Same pattern as `useShares.ts` — `useState` for each field, `useCallback` for mutations, `isApiError()` for error messages.

---

## Phase 4B: Sharing UI + Permission Controls

### Goal
Enhance the existing `ShareModal` with user search, permission editing, optional expiry, expired share handling, and add a `SharedBadge` for dashboard cards. Add self-share prevention and share limit enforcement on the frontend.

### Files to Create

#### 3. `frontend/src/components/dashboards/SharedBadge.tsx`
**Purpose**: Small badge shown on dashboard cards when the dashboard is shared with others or shared with the current user.

**Component interface**:
```tsx
interface SharedBadgeProps {
  accessLevel: AccessLevel;  // from Dashboard.access_level
  shareCount?: number;       // number of active shares (for owners)
}
```

**Implementation steps**:

1. **Badge variants**:
   - If `accessLevel === 'owner'` and `shareCount > 0`: Show `<Badge tone="info">Shared ({shareCount})</Badge>`
   - If `accessLevel === 'owner'` and `shareCount === 0`: No badge
   - If `accessLevel === 'admin'`: Show `<Badge tone="info">Shared (Admin)</Badge>`
   - If `accessLevel === 'edit'`: Show `<Badge>Shared (Edit)</Badge>`
   - If `accessLevel === 'view'`: Show `<Badge>Shared (View)</Badge>`

2. **Tooltip**: Wrap in `<Tooltip content="You have {accessLevel} access to this dashboard">` for non-owner access levels

#### 4. `frontend/src/components/dashboards/ShareModal.tsx` (MODIFY existing)
**Purpose**: Enhance the existing ShareModal with the following features.

**Enhancements over current implementation** (`ShareModal.tsx` is 277 lines currently):

1. **User search** (replace raw User ID input):
   - Replace the plain `TextField` for user ID with an autocomplete/search field
   - **Option A (MVP)**: Keep `TextField` but add label "User email or ID" with client-side format validation
   - **Option B (Enhanced)**: Add a Polaris `Autocomplete` component that calls a user search API endpoint (requires backend addition: `GET /api/v1/users/search?q=...`)
   - **Recommended for MVP**: Option A — keep the text field but improve validation and UX

2. **Optional expiry date** (new field):
   - Add a `TextField type="date"` for `expires_at` beneath the permission selector
   - Label: "Expires on (optional)"
   - Pass to `createShare()` body as ISO datetime
   - Validation: expiry must be in the future

3. **Permission editing on existing shares** (new):
   - Currently shares only have a "Revoke" button
   - Add a `<Select>` next to each share showing current permission
   - On change: call `updateShare(dashboardId, shareId, { permission: newValue })`
   - Use `useShares` hook's `update()` method (already exists)

4. **Expired share handling** (edge case):
   - Currently shows `(expired)` text suffix
   - **Enhancement**: Show expired shares in a separate section with:
     - Grayed-out styling (`opacity: 0.6`)
     - `<Badge tone="warning">Expired</Badge>` instead of permission label
     - "Renew" button that opens a date picker to set new `expires_at`
     - "Remove" button that calls `revoke()`

5. **Share count limit display** (edge case):
   - Accept `maxShares?: number` prop (from entitlements)
   - Show count: "Shares: {current}/{max}" below the invite form
   - Disable "Share" button when at limit with tooltip: "Share limit reached. Upgrade for more."
   - For unlimited (Enterprise): show "Shares: {current}" without limit

6. **Self-share prevention** (edge case):
   - Accept `ownerId: string` prop
   - Before calling `createShare()`, check `userId.trim() === ownerId`
   - If match: show `Banner tone="warning"`: "You already own this dashboard."
   - Don't send API call (backend also validates this, but catch it early for UX)

7. **Revoke self-access warning** (edge case):
   - Accept `currentUserId: string` prop
   - When revoking a share where `share.shared_with_user_id === currentUserId`:
     - Show confirmation: "You will lose access to this dashboard. Continue?"
     - Use inline `Banner tone="warning"` with confirm/cancel buttons

**Refactored structure** (break up the 277-line file):
- Keep `ShareModal` as the outer component
- Extract `ShareInviteForm` sub-component (invite fields + button)
- Extract `ShareListItem` sub-component (single share row with edit/revoke)
- Extract `ExpiredShareItem` sub-component (expired share with renew/remove)

**Edge case handling summary for 4B**:

| Edge Case | Handling |
|-----------|----------|
| Sharing with yourself | Frontend: check `userId === ownerId` before API call. Backend: 400 "Cannot share with owner" |
| Sharing with user outside tenant | Backend validates tenant access. Frontend shows API error message in banner. |
| Revoking your own edit access | Confirmation dialog warning about losing access |
| Expired share still in list | Separate "Expired" section with renew/remove actions, grayed styling, Badge |
| Owner transfer | Out of MVP scope. No UI action needed. |
| Share count limit | Display count vs limit, disable invite when at limit, tooltip explanation |

---

## Phase 4C: Audit Trail UI

### Goal
Add an audit timeline tab to the version history panel, showing all dashboard actions with icons, actor names, and timestamps, with collapsing of rapid-fire events.

### Files to Create

#### 5. `frontend/src/components/dashboards/AuditTimeline.tsx`
**Purpose**: Tab content showing audit events as a vertical timeline, rendered inside the VersionHistory panel.

**Component interface**:
```tsx
interface AuditTimelineProps {
  dashboardId: string;
}
```

**Implementation steps**:

1. **State management**:
   - `entries: AuditEntry[]` — fetched from `listAuditEntries(dashboardId)`
   - `total: number` — for pagination
   - `loading: boolean`
   - `loadingMore: boolean`
   - `error: string | null`

2. **Data fetching**:
   - Call `listAuditEntries(dashboardId, 0, 50)` on mount
   - Cancelled-fetch pattern in `useEffect`

3. **Event collapsing** (edge case — high-frequency audit events):
   - Before rendering, process the entries array to collapse consecutive same-actor/same-action events within 30 seconds:
   ```tsx
   function collapseEntries(entries: AuditEntry[]): CollapsedAuditEntry[] {
     const result: CollapsedAuditEntry[] = [];
     for (const entry of entries) {
       const prev = result[result.length - 1];
       if (
         prev &&
         prev.action === entry.action &&
         prev.actor_id === entry.actor_id &&
         Math.abs(new Date(prev.created_at).getTime() - new Date(entry.created_at).getTime()) < 30_000
       ) {
         prev.count += 1;
         prev.collapsed_ids.push(entry.id);
       } else {
         result.push({
           ...entry,
           count: 1,
           collapsed_ids: [entry.id],
         });
       }
     }
     return result;
   }
   ```
   - Display collapsed entries as: "{action_label} ({count} changes)" with the timestamp of the first entry

4. **Action icon mapping**:
   ```tsx
   const ACTION_CONFIG: Record<string, { icon: IconSource; label: string; tone?: string }> = {
     created:           { icon: PlusCircleIcon,   label: 'Created dashboard' },
     updated:           { icon: EditIcon,          label: 'Updated dashboard' },
     published:         { icon: CheckCircleIcon,   label: 'Published dashboard', tone: 'success' },
     archived:          { icon: ArchiveIcon,       label: 'Archived dashboard',  tone: 'warning' },
     restored:          { icon: RefreshIcon,       label: 'Restored version' },
     duplicated:        { icon: DuplicateIcon,     label: 'Duplicated dashboard' },
     shared:            { icon: ShareIcon,         label: 'Shared with user' },
     unshared:          { icon: DeleteIcon,        label: 'Revoked share' },
     share_updated:     { icon: EditIcon,          label: 'Updated share' },
     report_added:      { icon: PlusCircleIcon,    label: 'Added chart' },
     report_updated:    { icon: EditIcon,          label: 'Updated chart' },
     report_removed:    { icon: DeleteIcon,        label: 'Removed chart' },
     reports_reordered: { icon: DragHandleIcon,    label: 'Reordered charts' },
   };
   ```
   - Use Polaris `<Icon source={...}>` for each entry

5. **Actor display** (edge case — deleted user):
   - Display `entry.actor_id` as-is (Clerk user IDs are opaque strings)
   - **Enhancement for later**: Call a user lookup API to resolve IDs to names
   - **For deleted users**: If the user lookup returns 404, display "Deleted User" with subdued tone
   - **MVP approach**: Display actor_id with a truncation (first 8 chars + "...") since we don't have a user lookup API yet. Add a `<Tooltip content={entry.actor_id}>` for the full ID.

6. **Timeline entry rendering**:
   ```
   [icon] {action_label} {count > 1 ? `(${count} changes)` : ''}
          {details_summary}
          {relative_time} by {actor_display}
   ```
   - Use `BlockStack gap="100"` for each entry
   - Left border line via CSS (same as VersionHistory timeline)
   - Details summary extracted from `details_json`:
     - `shared`: "Shared with {target} ({permission})"
     - `restored`: "Restored to version {restored_version}"
     - `updated`: "Changed {changes.join(', ')}"
     - etc.

7. **Pagination**: Same "Load more" pattern as VersionHistory

8. **Empty state**: "No audit events recorded yet."

**Edge case handling summary for 4C**:

| Edge Case | Handling |
|-----------|----------|
| High-frequency audit events | `collapseEntries()` function merges same-actor/same-action within 30s window |
| Deleted user in audit trail | Show truncated actor_id with tooltip; future: user lookup with "Deleted User" fallback |

---

### Integration: Version History Panel with Audit Tab

The `VersionHistory.tsx` component will include **two tabs** (Polaris `<Tabs>`):

1. **"Versions" tab** — Version timeline (described in 4A)
2. **"Activity" tab** — Audit timeline (AuditTimeline component)

This keeps both features in a single slide-out panel, matching the spec "Tab in version history panel showing audit events."

---

## Phase 4D: Integration + Navigation Polish

### Goal
Wire up all routes with FeatureGate, add navigation entries, add CTA on Analytics page, create the DashboardCard component, and integrate custom dashboards into the Analytics dropdown.

### Files to Modify

#### 6. `frontend/src/App.tsx` — Add Dashboard Routes with FeatureGate

**Current state** (92 lines): Has routes for `/analytics`, `/paywall`, `/insights`, `/approvals`, `/whats-new`, admin routes. **No dashboard routes**.

**Changes**:

1. **Add imports**:
   ```tsx
   import { DashboardList } from './pages/DashboardList';
   import { DashboardView } from './pages/DashboardView';
   import { DashboardBuilder } from './pages/DashboardBuilder';
   import { FeatureGate } from './components/FeatureGate';
   import { useEntitlements } from './hooks/useEntitlements';
   ```

2. **Add entitlements fetching** in `AuthenticatedApp`:
   ```tsx
   function AuthenticatedApp() {
     useClerkToken();
     const { entitlements } = useEntitlements();
     // ...
   }
   ```
   - **Note**: Need to create `useEntitlements` hook or inline `fetchEntitlements` with useEffect

3. **Add routes** inside `<Routes>`:
   ```tsx
   <Route path="/dashboards" element={
     <FeatureGateRoute feature="custom_dashboards" entitlements={entitlements}>
       <DashboardList />
     </FeatureGateRoute>
   } />
   <Route path="/dashboards/:dashboardId" element={<DashboardView />} />
   <Route path="/dashboards/:dashboardId/edit" element={
     <FeatureGateRoute feature="custom_dashboards" entitlements={entitlements}>
       <DashboardBuilder />
     </FeatureGateRoute>
   } />
   ```

4. **FeatureGateRoute component** (new, inline or separate):
   - If not entitled: `<Navigate to={`/paywall?feature=custom_reports`} replace />`
   - **Edge case — redirect loop**: Check if current path equals the redirect target. If `location.pathname === '/paywall'`, don't redirect again. Implementation:
     ```tsx
     function FeatureGateRoute({ feature, entitlements, children }) {
       const location = useLocation();
       const isEntitled = isFeatureEntitled(entitlements, feature);

       if (entitlements === null) return <SkeletonPage />; // Still loading
       if (!isEntitled) {
         const target = `/paywall?feature=${feature}`;
         // Prevent redirect loop
         if (location.pathname === '/paywall') return <Paywall />;
         return <Navigate to={target} replace />;
       }
       return <>{children}</>;
     }
     ```

5. **Deep link handling** (edge case — shared dashboard link after auth):
   - Clerk's `<RedirectToSignIn>` already handles `returnTo` via its default behavior — after sign-in, the user returns to the URL they tried to access
   - Verify: The `<SignedOut>` block uses `<RedirectToSignIn />` which by default preserves the current URL as the return destination
   - **If Clerk doesn't auto-preserve**: Change to `<RedirectToSignIn redirectUrl={window.location.href} />` (check Clerk docs for exact prop name — it may be `afterSignInUrl` or `returnBackUrl`)

6. **Note on DashboardView access**: The `/dashboards/:dashboardId` route is NOT wrapped in FeatureGate because shared dashboards should be viewable by users on any plan. The backend handles access control via shares.

---

#### 7. `frontend/src/components/layout/AppHeader.tsx` — Add "Dashboards" Nav Item

**Current state** (59 lines): Right-aligned header with `ChangelogBadge` and `WhatChangedButton`. No navigation links.

**Changes**:

1. **Add navigation links** to the left side of the header:
   ```tsx
   import { Button, Badge as PolarisBadge } from '@shopify/polaris';

   // Inside the component:
   const isOnDashboardsPage = location.pathname.startsWith('/dashboards');

   return (
     <Box ...>
       <InlineStack align="space-between" gap="400" blockAlign="center">
         {/* Left: Navigation */}
         <InlineStack gap="300" blockAlign="center">
           <Button
             variant={location.pathname === '/analytics' ? 'primary' : 'plain'}
             onClick={() => navigate('/analytics')}
           >
             Analytics
           </Button>
           <Button
             variant={isOnDashboardsPage ? 'primary' : 'plain'}
             onClick={() => navigate('/dashboards')}
           >
             Dashboards
           </Button>
         </InlineStack>

         {/* Right: Status indicators (existing) */}
         <InlineStack gap="400" blockAlign="center">
           {/* existing ChangelogBadge and WhatChangedButton */}
         </InlineStack>
       </InlineStack>
     </Box>
   );
   ```

2. **Dashboard count badge** (optional enhancement):
   - Fetch dashboard count via `getDashboardCount()` on mount
   - Show as `<Badge>{count}</Badge>` next to "Dashboards" text
   - Only show if count > 0
   - **Decision**: This adds an API call on every page load. **Defer to post-MVP** unless explicitly requested. Keep the nav item simple for now.

---

#### 8. `frontend/src/pages/Analytics.tsx` — Add "Create Custom Dashboard" CTA

**Current state** (221 lines): Embed page with dashboard selector, health indicators, incident banner.

**Changes**:

1. **Add CTA section** after the embedded dashboard:
   ```tsx
   import { fetchEntitlements, isFeatureEntitled } from '../services/entitlementsApi';

   // Inside component, after existing useEffect:
   const [entitlements, setEntitlements] = useState(null);
   useEffect(() => {
     fetchEntitlements().then(setEntitlements).catch(console.error);
   }, []);

   const canCreateDashboards = isFeatureEntitled(entitlements, 'custom_dashboards');
   ```

2. **Render CTA card** below the embedded dashboard section:
   ```tsx
   <Layout.Section>
     <Card>
       <BlockStack gap="300">
         <Text as="h2" variant="headingMd">
           Want more? Build your own dashboard
         </Text>
         <Text as="p" tone="subdued">
           Create custom dashboards with the metrics that matter most to your business.
         </Text>
         <InlineStack>
           <Button
             variant="primary"
             onClick={() => navigate('/dashboards')}
           >
             {canCreateDashboards ? 'Create Custom Dashboard' : 'Learn More'}
           </Button>
         </InlineStack>
       </BlockStack>
     </Card>
   </Layout.Section>
   ```

3. **Custom dashboards in the Analytics dropdown** (edge case):
   - Add a "Custom" section separator in the dashboard selector
   - Fetch published custom dashboards: `listDashboards({ status: 'published', limit: 5 })`
   - Append to `dashboardOptions` with a "Custom" group label
   - If user has >5 custom dashboards, add a "View all" option that navigates to `/dashboards`
   - **Implementation detail**: Polaris `<Select>` supports option groups. Use:
     ```tsx
     const customOptions = customDashboards.map(d => ({
       label: d.name,
       value: `custom:${d.id}`,
     }));

     const allOptions = [
       // System dashboards
       ...dashboardOptions,
       // Separator
       ...(customOptions.length > 0 ? [
         { label: '── Custom Dashboards ──', value: '__separator__', disabled: true },
         ...customOptions,
         ...(hasMoreCustom ? [{ label: 'View all dashboards...', value: '__view_all__' }] : []),
       ] : []),
     ];
     ```
   - Handle selection: if `value.startsWith('custom:')`, navigate to `/dashboards/{id}`
   - If `value === '__view_all__'`, navigate to `/dashboards`

---

#### 9. `frontend/src/components/dashboards/DashboardCard.tsx` — New Component

**Purpose**: Card component for displaying a dashboard in list/grid views. Used in DashboardList and potentially Analytics page.

**Component interface**:
```tsx
interface DashboardCardProps {
  dashboard: Dashboard;
  onEdit?: (dashboardId: string) => void;
  onView?: (dashboardId: string) => void;
  onDuplicate?: (dashboard: Dashboard) => void;
  onDelete?: (dashboard: Dashboard) => void;
  onShare?: (dashboardId: string) => void;
  showActions?: boolean;
  compact?: boolean;  // For Analytics page usage
}
```

**Implementation steps**:

1. **Card layout**:
   ```
   ┌─────────────────────────────┐
   │ Dashboard Name    [Status]  │
   │ Description text...         │
   │ 5 charts · Updated Mar 10  │
   │ [SharedBadge]               │
   │ ─────────────────────────── │
   │ [Edit] [View] [Share] [···] │
   └─────────────────────────────┘
   ```

2. **Status badge**: Reuse the `STATUS_BADGE_TONE` / `STATUS_BADGE_PROGRESS` pattern from `DashboardList.tsx`

3. **Shared badge**: Include `<SharedBadge accessLevel={dashboard.access_level} />`

4. **Action buttons**: Conditionally render based on `showActions` and access level:
   - Owner: Edit, View, Share, Duplicate, Delete
   - Admin: Edit, View, Share
   - Edit: Edit, View
   - View: View only

5. **Compact mode**: For Analytics page integration — show only name, status badge, and shared badge in a smaller card

---

## Cross-Cutting Concerns

### Backend Changes Required (Summary)

While the plan is primarily frontend, these backend additions would significantly improve the UX:

| Change | Priority | Description |
|--------|----------|-------------|
| `GET /versions/{version_number}` endpoint | Medium | Return single version with `snapshot_json` for preview modal |
| `versions_count` in `DashboardResponse` | Low | Enable stale detection in version history panel |
| Version creation debounce (5s window) | Low | Batch rapid edits into single version |
| `GET /users/search` endpoint | Low | User search for share modal autocomplete |

**For MVP**: All of these can be deferred. The frontend plan includes fallback approaches for each.

### New Shared Utilities

#### `frontend/src/utils/dateFormatters.ts`
```tsx
export function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return formatDate(dateString);  // fallback to absolute date
}

export function formatDate(dateString: string): string {
  // Same as DashboardList.tsx:63-74
}
```

#### `frontend/src/hooks/useVersions.ts`
Version history hook (described in 4A).

#### `frontend/src/hooks/useAuditEntries.ts`
Audit trail hook following same pattern as `useVersions`.

---

## Implementation Order & Dependencies

```
Week 1: Foundation (4A + hooks)
├── Step 1: Create useVersions hook
├── Step 2: Create dateFormatters utility
├── Step 3: Create VersionHistory component (timeline + restore)
├── Step 4: Create VersionPreviewModal (metadata-only MVP)
└── Step 5: Wire into DashboardBuilder (add "History" secondary action)

Week 2: Sharing + Audit (4B + 4C)
├── Step 6: Create SharedBadge component
├── Step 7: Enhance ShareModal (expiry, editing, expired shares, limits)
├── Step 8: Create useAuditEntries hook
├── Step 9: Create AuditTimeline component
└── Step 10: Add Tabs to VersionHistory (Versions + Activity)

Week 3: Integration (4D)
├── Step 11: Create DashboardCard component
├── Step 12: Update App.tsx (routes + FeatureGate)
├── Step 13: Update AppHeader.tsx (nav items)
├── Step 14: Update Analytics.tsx (CTA + custom dashboard dropdown)
└── Step 15: End-to-end testing of all flows
```

### Dependency Graph
```
useVersions ──────→ VersionHistory ──→ VersionPreviewModal
                         ↓
useAuditEntries ──→ AuditTimeline ──→ (tab in VersionHistory)

SharedBadge ──→ DashboardCard ──→ DashboardList (existing)
                                 ↘ Analytics.tsx

ShareModal (enhanced) ← useShares (existing)

FeatureGateRoute ──→ App.tsx routes
                 ──→ AppHeader.tsx nav
```

---

## File Inventory

### New Files (8)
| # | File | Phase | Est. Lines |
|---|------|-------|------------|
| 1 | `frontend/src/components/dashboards/VersionHistory.tsx` | 4A | ~280 |
| 2 | `frontend/src/components/dashboards/VersionPreviewModal.tsx` | 4A | ~150 |
| 3 | `frontend/src/hooks/useVersions.ts` | 4A | ~90 |
| 4 | `frontend/src/hooks/useAuditEntries.ts` | 4C | ~80 |
| 5 | `frontend/src/components/dashboards/AuditTimeline.tsx` | 4C | ~200 |
| 6 | `frontend/src/components/dashboards/SharedBadge.tsx` | 4B | ~45 |
| 7 | `frontend/src/components/dashboards/DashboardCard.tsx` | 4D | ~150 |
| 8 | `frontend/src/utils/dateFormatters.ts` | shared | ~30 |

### Modified Files (4+)
| # | File | Phase | Changes |
|---|------|-------|---------|
| 1 | `frontend/src/App.tsx` | 4D | Add dashboard routes with FeatureGateRoute, imports (~30 lines added) |
| 2 | `frontend/src/components/layout/AppHeader.tsx` | 4D | Add nav links for Analytics + Dashboards (~20 lines added) |
| 3 | `frontend/src/pages/Analytics.tsx` | 4D | Add CTA card + custom dashboard dropdown (~50 lines added) |
| 4 | `frontend/src/components/dashboards/ShareModal.tsx` | 4B | Enhance with expiry, editing, limits, expired handling (~120 lines added/changed) |
| 5 | `frontend/src/pages/DashboardBuilder.tsx` | 4A | Add "History" button opening VersionHistory panel (~15 lines added) |
| 6 | `frontend/src/pages/DashboardView.tsx` | 4A | Add "History" button for owner/admin (~10 lines added) |
| 7 | `frontend/src/types/customDashboards.ts` | 4A | Add VersionSnapshot, DashboardVersionDetail types (~25 lines added) |
| 8 | `frontend/src/services/customDashboardsApi.ts` | 4A | Add getVersion() function (~15 lines added) |

---

## Edge Case Summary Matrix

| # | Edge Case | Phase | Severity | Frontend Handling | Backend Status |
|---|-----------|-------|----------|-------------------|----------------|
| 1 | Restoring to version with deleted datasets | 4A | High | Post-restore banner + per-report warnings[] | Done (restore returns warnings) |
| 2 | Rapid version creation (10 edits in 1 min) | 4A | Medium | N/A (server-side) — document as known limitation | Needs 5s debounce in _create_version |
| 3 | Version preview during concurrent edit | 4A | Medium | Compare total count on refetch → "New changes available" banner | Done (total returned in response) |
| 4 | Sharing with yourself | 4B | Low | Pre-check userId === ownerId → warning banner | Done (400 error) |
| 5 | Sharing with user outside tenant | 4B | Medium | Show API error message in banner | Done (400 error) |
| 6 | Revoking your own edit access | 4B | Medium | Confirmation dialog warning about losing access | N/A (frontend only) |
| 7 | Expired share still in list | 4B | Low | Separate grayed "Expired" section with renew/remove | Done (is_expired field) |
| 8 | Owner transfer | 4B | Low | Not in MVP — no UI needed | Not implemented |
| 9 | Share count limit (Free/Growth: 5) | 4B | Medium | Show count/limit, disable invite at limit | Needs check_limit() in share service |
| 10 | High-frequency audit events | 4C | Medium | collapseEntries() — merge same-actor/action within 30s | N/A (frontend collapsing) |
| 11 | Deleted user in audit trail | 4C | Low | Show truncated actor_id with tooltip; "Deleted User" fallback | N/A (no user lookup API yet) |
| 12 | FeatureGate redirect loop | 4D | High | Check location !== '/paywall' before redirecting | N/A (frontend routing) |
| 13 | Deep link to shared dashboard after auth | 4D | High | Clerk returnTo preserves URL after sign-in | N/A (Clerk handles) |
| 14 | Custom dashboards in Analytics dropdown (50+) | 4D | Medium | Show 5 most recent + "View all" link | Done (list endpoint has pagination) |
| 15 | Version cap (50 per dashboard) | 4A | Low | Backend enforces; frontend renders what API returns | Done |
| 16 | TOCTOU on dashboard count limit | 4D | High | Backend SELECT FOR UPDATE; frontend shows error if 402 | Done |
| 17 | Downgrade preserves read access | 4D | Medium | FeatureGate only wraps write routes; view route always accessible | Done |
| 18 | Optimistic locking (409 conflict) | 4A | High | DashboardBuilderContext already handles; restore refreshes state | Done |

---

## Testing Strategy

### Manual Test Scenarios

1. **Version History flow**: Create dashboard → make 3 edits → open history → verify 4 versions shown (1 create + 3 updates) → restore to version 2 → verify state matches version 2
2. **Version preview**: Open version history → click Preview on version 1 → verify metadata shown → close modal
3. **Concurrent edit detection**: Open history in tab A → make edit in tab B → return to tab A → verify "New changes available" banner appears on refresh
4. **Share with expiry**: Share dashboard → set expiry to tomorrow → verify share appears → manually expire (or mock) → verify "Expired" badge
5. **Self-share prevention**: Try sharing dashboard with own user ID → verify warning message
6. **Revoke own access**: Share dashboard with self from another account → revoke → verify confirmation dialog
7. **Audit collapsing**: Reorder 5 reports rapidly → open audit → verify entries collapsed into "Reordered charts (5 changes)"
8. **FeatureGate redirect**: Navigate to /dashboards as Free user → verify redirect to /paywall?feature=custom_reports
9. **Deep link**: Copy /dashboards/abc-123 URL → sign out → paste URL → sign in → verify redirect to /dashboards/abc-123
10. **Analytics CTA**: Visit Analytics page → verify "Create Custom Dashboard" card shown → click → verify navigation to /dashboards
11. **Analytics dropdown**: Publish 2 custom dashboards → visit Analytics → verify custom section in dropdown

### Unit Test Focus Areas
- `collapseEntries()` function — test edge cases (empty, single entry, all same action, cross-actor, boundary timing)
- `formatRelativeTime()` — test all time ranges
- `FeatureGateRoute` — test entitled, not entitled, loading states, redirect loop prevention
- `SharedBadge` — test all access level variants

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Version preview requires backend change | High | Medium | MVP fallback: metadata-only preview with "Restore to see full state" |
| User search for sharing needs backend endpoint | Medium | Low | MVP: keep text input with format validation |
| Polaris v12 Modal size limitations for timeline | Low | Low | Use `large` modal size; timeline scrolls within Modal.Section |
| Performance with 50 versions in timeline | Low | Medium | Paginate at 20, "Load more" button |
| Clerk returnTo behavior varies by version | Medium | Medium | Test with current Clerk version; add explicit `afterSignInUrl` if needed |
