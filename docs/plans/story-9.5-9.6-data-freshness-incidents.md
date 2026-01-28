# Implementation Plan: Stories 9.5 & 9.6

## Data Freshness Indicators & Incident Communication

**Stories**: 9.5.1 (Data Health Indicators) & 9.6.1 (Incident Communication)
**Branch**: `claude/data-freshness-indicators-dkmSN`
**Created**: 2026-01-28

---

## Executive Summary

This plan implements two related user stories for improving data transparency:

1. **Story 9.5** - Data freshness indicators visible everywhere analytics appear
2. **Story 9.6** - Calm, scoped incident communication via in-app banners

The implementation leverages existing infrastructure (DQ service, health APIs) and established UI patterns (InsightBadge, BillingBanner) to deliver a cohesive experience.

---

## User Stories

### Story 9.5.1 — Data Health Indicators

> As a user, I want to see data freshness and connector health at a glance so that I trust the numbers I'm seeing

**Requirements:**
- "Last synced X hours ago" display
- Green / yellow / red status indicators
- Visible but unobtrusive
- Per connector and per dashboard level

**Acceptance Criteria:**
- [ ] Freshness visible everywhere analytics appear
- [ ] Status updates in near-real time

### Story 9.6.1 — Incident Communication

> As a user, I want to see when the system is degraded so that I understand issues without panic

**Requirements:**
- In-app banner for active incidents
- Link to status page
- Clear scope + ETA messaging
- No email for minor issues

**Acceptance Criteria:**
- [ ] Active incidents show in-app
- [ ] Messaging is clear and scoped

---

## Architecture Overview

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              BACKEND                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐  │
│  │   DQService      │    │  /compact        │    │  /incidents/     │  │
│  │   (existing)     │───▶│  (NEW)           │    │  active (NEW)    │  │
│  └──────────────────┘    └──────────────────┘    └──────────────────┘  │
│                                   │                       │             │
└───────────────────────────────────┼───────────────────────┼─────────────┘
                                    │                       │
                                    ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    DataHealthContext (NEW)                        │  │
│  │    - Smart polling (15s/30s/60s based on health status)          │  │
│  │    - Visibility-aware (pause when tab hidden)                     │  │
│  │    - Provides health state to all components                      │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                    │                    │                    │          │
│                    ▼                    ▼                    ▼          │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐  │
│  │DataFreshnessBadge│  │  IncidentBanner  │  │ DashboardFreshness   │  │
│  │    (header)      │  │    (app top)     │  │    Indicator         │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────┘  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Near-Real-Time Strategy

Use adaptive polling based on health status:

| Status   | Poll Interval | Rationale                          |
|----------|---------------|------------------------------------|
| Healthy  | 60 seconds    | No urgency, minimize server load   |
| Degraded | 30 seconds    | User should see updates sooner     |
| Critical | 15 seconds    | Important to reflect changes fast  |

Additional optimizations:
- **Visibility API**: Pause polling when browser tab is hidden
- **Compact endpoint**: Lightweight response for frequent polling
- **Deduplication**: Skip poll if previous request still pending

---

## Implementation Details

### Phase 1: Backend API Enhancements

#### 1.1 Add Compact Health Endpoint

**File**: `backend/src/api/dq/routes.py`

Add a lightweight endpoint for frequent polling:

```python
class CompactHealthResponse(BaseModel):
    """Lightweight health response for frequent polling."""
    overall_status: str  # healthy, degraded, critical
    health_score: float  # 0-100
    stale_count: int
    critical_count: int
    has_blocking_issues: bool
    oldest_sync_minutes: Optional[int]
    last_checked_at: str

@router.get("/compact", response_model=CompactHealthResponse)
async def get_compact_health(
    request: Request,
    service: DQService = Depends(get_dq_service),
):
    """Lightweight health check for frequent polling."""
    summary = service.get_sync_health_summary()

    oldest_minutes = None
    if summary.connectors:
        sync_minutes = [c.minutes_since_sync for c in summary.connectors
                        if c.minutes_since_sync is not None]
        if sync_minutes:
            oldest_minutes = max(sync_minutes)

    return CompactHealthResponse(
        overall_status=summary.overall_status,
        health_score=summary.health_score,
        stale_count=summary.delayed_count,
        critical_count=summary.error_count,
        has_blocking_issues=summary.has_blocking_issues,
        oldest_sync_minutes=oldest_minutes,
        last_checked_at=datetime.now(timezone.utc).isoformat(),
    )
```

#### 1.2 Add Active Incidents Endpoint

**File**: `backend/src/api/dq/routes.py`

Add endpoint specifically for incident banners:

```python
class ActiveIncidentBanner(BaseModel):
    """Active incident for banner display."""
    id: str
    severity: str
    title: str
    message: str
    scope: str  # e.g., "Meta Ads connector" or "All data sources"
    eta: Optional[str]
    status_page_url: Optional[str]
    started_at: str

class ActiveIncidentsResponse(BaseModel):
    """Active incidents for banner display."""
    incidents: List[ActiveIncidentBanner]
    has_critical: bool
    has_blocking: bool

@router.get("/incidents/active", response_model=ActiveIncidentsResponse)
async def get_active_incidents(
    request: Request,
    service: DQService = Depends(get_dq_service),
):
    """Get active incidents for banner display."""
    incidents = service.get_open_incidents()

    banner_incidents = []
    has_critical = False
    has_blocking = False

    for inc in incidents:
        if inc.status in ('open', 'acknowledged'):
            scope = service.get_incident_scope(inc)
            eta = service.get_incident_eta(inc)

            banner_incidents.append(ActiveIncidentBanner(
                id=inc.id,
                severity=inc.severity,
                title=inc.title,
                message=inc.merchant_message or inc.description or "System issue detected",
                scope=scope,
                eta=eta,
                status_page_url=os.environ.get("STATUS_PAGE_URL"),
                started_at=inc.opened_at.isoformat() if inc.opened_at else "",
            ))

            if inc.severity == 'critical':
                has_critical = True
            if inc.is_blocking:
                has_blocking = True

    return ActiveIncidentsResponse(
        incidents=banner_incidents,
        has_critical=has_critical,
        has_blocking=has_blocking,
    )
```

#### 1.3 Add Scope and ETA Methods to DQService

**File**: `backend/src/api/dq/service.py`

```python
def get_incident_scope(self, incident: DQIncident) -> str:
    """Generate human-readable scope for incident."""
    # Get connector info
    connector = self._get_connector(incident.connector_id)
    if connector:
        return f"{connector.connector_name} connector"
    return "Data pipeline"

def get_incident_eta(self, incident: DQIncident) -> Optional[str]:
    """Estimate resolution time based on incident type."""
    # Default ETAs based on severity
    eta_map = {
        'warning': '1-2 hours',
        'high': '2-4 hours',
        'critical': 'Investigating - updates every 30 minutes',
    }
    return eta_map.get(incident.severity)
```

---

### Phase 2: Frontend Context & State Management

#### 2.1 Create DataHealthContext

**New File**: `frontend/src/contexts/DataHealthContext.tsx`

```typescript
/**
 * DataHealthContext Provider
 *
 * Provides app-wide data health state with smart polling:
 * - Adaptive poll frequency based on health status
 * - Pauses when browser tab is hidden
 * - Exposes health and incident state for badges/banners
 *
 * Story 9.5 & 9.6 - Data Freshness & Incident Communication
 */

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  type ReactNode,
} from 'react';

// Types
export interface CompactHealth {
  overallStatus: 'healthy' | 'degraded' | 'critical';
  healthScore: number;
  staleCount: number;
  criticalCount: number;
  hasBlockingIssues: boolean;
  oldestSyncMinutes: number | null;
  lastCheckedAt: string;
}

export interface ActiveIncident {
  id: string;
  severity: 'warning' | 'high' | 'critical';
  title: string;
  message: string;
  scope: string;
  eta: string | null;
  statusPageUrl: string | null;
  startedAt: string;
}

interface DataHealthState {
  health: CompactHealth | null;
  activeIncidents: ActiveIncident[];
  loading: boolean;
  error: string | null;
  lastUpdated: Date | null;
}

interface DataHealthContextValue extends DataHealthState {
  refresh: () => Promise<void>;
  acknowledgeIncident: (id: string) => Promise<void>;
  // Computed helpers
  hasStaleData: boolean;
  hasCriticalIssues: boolean;
  hasBlockingIssues: boolean;
  shouldShowBanner: boolean;
  mostSevereIncident: ActiveIncident | null;
  freshnessLabel: string;
}

const POLL_INTERVALS = {
  healthy: 60000,   // 1 minute
  degraded: 30000,  // 30 seconds
  critical: 15000,  // 15 seconds
};

const DataHealthContext = createContext<DataHealthContextValue | null>(null);

export function DataHealthProvider({ children }: { children: ReactNode }) {
  // Implementation with smart polling, visibility API integration
  // ... (see detailed implementation)
}

export function useDataHealth(): DataHealthContextValue {
  const context = useContext(DataHealthContext);
  if (!context) {
    throw new Error('useDataHealth must be used within DataHealthProvider');
  }
  return context;
}

// Convenience hooks
export function useFreshnessStatus() {
  const { health, freshnessLabel, hasStaleData, hasCriticalIssues } = useDataHealth();
  return { health, freshnessLabel, hasStaleData, hasCriticalIssues };
}

export function useActiveIncidents() {
  const { activeIncidents, shouldShowBanner, mostSevereIncident } = useDataHealth();
  return { activeIncidents, shouldShowBanner, mostSevereIncident };
}
```

#### 2.2 Add API Service Functions

**File**: `frontend/src/services/syncHealthApi.ts` (extend existing)

```typescript
// Add new types
export interface CompactHealth {
  overall_status: 'healthy' | 'degraded' | 'critical';
  health_score: number;
  stale_count: number;
  critical_count: number;
  has_blocking_issues: boolean;
  oldest_sync_minutes: number | null;
  last_checked_at: string;
}

export interface ActiveIncidentBanner {
  id: string;
  severity: 'warning' | 'high' | 'critical';
  title: string;
  message: string;
  scope: string;
  eta: string | null;
  status_page_url: string | null;
  started_at: string;
}

export interface ActiveIncidentsResponse {
  incidents: ActiveIncidentBanner[];
  has_critical: boolean;
  has_blocking: boolean;
}

// Add new API functions
export async function getCompactHealth(): Promise<CompactHealth> {
  const response = await fetch(`${API_BASE_URL}/api/sync-health/compact`, {
    method: 'GET',
    headers: createHeaders(),
  });
  return handleResponse<CompactHealth>(response);
}

export async function getActiveIncidents(): Promise<ActiveIncidentsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/sync-health/incidents/active`, {
    method: 'GET',
    headers: createHeaders(),
  });
  return handleResponse<ActiveIncidentsResponse>(response);
}
```

---

### Phase 3: UI Components

#### 3.1 DataFreshnessBadge (Header Indicator)

**New File**: `frontend/src/components/health/DataFreshnessBadge.tsx`

Pattern: Follow `InsightBadge.tsx`

```typescript
/**
 * DataFreshnessBadge Component
 *
 * Compact badge showing data freshness status.
 * Designed for header/navigation placement.
 *
 * Visual states:
 * - Green dot: All data fresh
 * - Yellow badge + time: Some data stale (shows oldest)
 * - Red badge: Critical issues
 *
 * Story 9.5 - Data Freshness visible everywhere
 */

interface DataFreshnessBadgeProps {
  onClick?: () => void;
  showLabel?: boolean;
  compact?: boolean;
}

export function DataFreshnessBadge({
  onClick,
  showLabel = false,
  compact = false,
}: DataFreshnessBadgeProps) {
  const { health, freshnessLabel, hasStaleData, hasCriticalIssues, loading } = useDataHealth();

  // Badge tone based on status
  const getTone = () => {
    if (hasCriticalIssues) return 'critical';
    if (hasStaleData) return 'attention';
    return 'success';
  };

  // Short time display for badge
  const getTimeDisplay = () => {
    if (!health?.oldestSyncMinutes) return null;
    const minutes = health.oldestSyncMinutes;
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h`;
    return `${Math.floor(hours / 24)}d`;
  };

  // Render badge with tooltip
}
```

#### 3.2 IncidentBanner (App-Wide Banner)

**New File**: `frontend/src/components/health/IncidentBanner.tsx`

Pattern: Follow `BillingBanner.tsx`

```typescript
/**
 * IncidentBanner Component
 *
 * Displays calm, scoped incident communication.
 * Shows at top of app when active incidents exist.
 *
 * Features:
 * - Severity-based tone (info/warning/critical)
 * - Scope messaging (which connector/data affected)
 * - ETA when available
 * - Status page link
 * - Dismissible (acknowledges incident)
 *
 * Story 9.6 - Incident Communication
 */

interface IncidentBannerProps {
  onDismiss?: (incidentId: string) => void;
  maxIncidents?: number;
}

export function IncidentBanner({
  onDismiss,
  maxIncidents = 1,
}: IncidentBannerProps) {
  const { activeIncidents, shouldShowBanner, mostSevereIncident, acknowledgeIncident } = useDataHealth();

  if (!shouldShowBanner || activeIncidents.length === 0) {
    return null;
  }

  const getBannerTone = (severity: string) => {
    switch (severity) {
      case 'critical': return 'critical';
      case 'high': return 'warning';
      default: return 'info';
    }
  };

  // Render Banner with:
  // - Title based on scope (e.g., "Meta Ads data may be delayed")
  // - Message with ETA
  // - Status page link
  // - Dismiss action
}
```

#### 3.3 DashboardFreshnessIndicator

**New File**: `frontend/src/components/health/DashboardFreshnessIndicator.tsx`

For placement on Analytics page:

```typescript
/**
 * DashboardFreshnessIndicator Component
 *
 * Shows data freshness summary within dashboard context.
 * More detailed than header badge.
 *
 * Variants:
 * - compact: Inline text with icon
 * - detailed: Card with per-connector breakdown
 *
 * Story 9.5 - Freshness visible where analytics appear
 */

interface DashboardFreshnessIndicatorProps {
  variant?: 'compact' | 'detailed';
}

export function DashboardFreshnessIndicator({
  variant = 'compact',
}: DashboardFreshnessIndicatorProps) {
  const { health, freshnessLabel, hasStaleData } = useDataHealth();

  if (variant === 'compact') {
    // Inline display: "✓ All data fresh" or "⚠ Some data 2h old"
  }

  // Detailed: Card with connector list
}
```

---

### Phase 4: App Integration

#### 4.1 Create AppLayout Component

**New File**: `frontend/src/components/AppLayout.tsx`

```typescript
/**
 * AppLayout Component
 *
 * Wraps pages with common elements:
 * - Incident banner at top
 * - Data freshness badge in header area
 */

import { Page, Layout } from '@shopify/polaris';
import { IncidentBanner } from './health/IncidentBanner';
import { DataFreshnessBadge } from './health/DataFreshnessBadge';

interface AppLayoutProps {
  children: ReactNode;
  title?: string;
  showFreshnessBadge?: boolean;
}

export function AppLayout({
  children,
  title,
  showFreshnessBadge = true,
}: AppLayoutProps) {
  return (
    <>
      <IncidentBanner />
      <Page
        title={title}
        titleMetadata={showFreshnessBadge ? <DataFreshnessBadge onClick={() => {}} /> : undefined}
      >
        {children}
      </Page>
    </>
  );
}
```

#### 4.2 Update App.tsx

**File**: `frontend/src/App.tsx`

```typescript
import { DataHealthProvider } from './contexts/DataHealthContext';

function App() {
  return (
    <AppProvider i18n={enTranslations}>
      <DataHealthProvider>
        <BrowserRouter>
          <Routes>
            {/* Routes unchanged */}
          </Routes>
        </BrowserRouter>
      </DataHealthProvider>
    </AppProvider>
  );
}
```

#### 4.3 Update Analytics Page

**File**: `frontend/src/pages/Analytics.tsx`

Add freshness indicator before dashboard:

```typescript
import { DashboardFreshnessIndicator } from '../components/health/DashboardFreshnessIndicator';
import { AppLayout } from '../components/AppLayout';

function Analytics() {
  return (
    <AppLayout title="Analytics" showFreshnessBadge>
      <Layout>
        {/* Freshness indicator above dashboard */}
        <Layout.Section>
          <DashboardFreshnessIndicator variant="compact" />
        </Layout.Section>

        {/* Existing dashboard content */}
        <Layout.Section>
          {/* Dashboard selector and embedded superset */}
        </Layout.Section>
      </Layout>
    </AppLayout>
  );
}
```

---

## File Summary

### New Files

| File | Description |
|------|-------------|
| `frontend/src/contexts/DataHealthContext.tsx` | App-wide health state with smart polling |
| `frontend/src/components/health/DataFreshnessBadge.tsx` | Header badge for freshness status |
| `frontend/src/components/health/IncidentBanner.tsx` | App-wide incident banner |
| `frontend/src/components/health/DashboardFreshnessIndicator.tsx` | Dashboard-level freshness display |
| `frontend/src/components/AppLayout.tsx` | Shared layout with banner/badge |

### Modified Files

| File | Changes |
|------|---------|
| `backend/src/api/dq/routes.py` | Add `/compact` and `/incidents/active` endpoints |
| `backend/src/api/dq/service.py` | Add `get_incident_scope()` and `get_incident_eta()` methods |
| `frontend/src/services/syncHealthApi.ts` | Add `getCompactHealth()` and `getActiveIncidents()` functions |
| `frontend/src/App.tsx` | Wrap with `DataHealthProvider` |
| `frontend/src/pages/Analytics.tsx` | Add freshness indicator and use `AppLayout` |

---

## Testing Strategy

### Unit Tests

**Backend:**
- `test_compact_health_endpoint` - Verify lightweight response
- `test_active_incidents_endpoint` - Verify incident filtering
- `test_incident_scope_generation` - Verify scope text
- `test_incident_eta_generation` - Verify ETA estimates

**Frontend:**
- `DataHealthContext` - State management, polling logic
- `DataFreshnessBadge` - Render states, tone mapping
- `IncidentBanner` - Render states, dismiss handling

### Integration Tests

- Context + API: Verify data flow from backend to context
- Polling behavior: Interval changes based on status
- Visibility API: Polling pauses when tab hidden

### E2E Tests

- Badge appears in Analytics page header
- Banner shows when incidents are active
- Badge updates after status change
- Banner dismisses and acknowledges incident

---

## UX Guidelines

### Color Semantics (Polaris Tones)

| Status | Tone | Use |
|--------|------|-----|
| Fresh/Healthy | `success` | All data within SLA |
| Stale/Degraded | `attention` | Some data outside SLA |
| Critical | `critical` | Blocking issues or failures |

### Messaging Principles

1. **Be specific**: "Meta Ads data may be delayed" not "System issue"
2. **Provide ETA**: "Expected resolution: 2 hours"
3. **Stay calm**: Avoid panic language
4. **Link to details**: Status page or SyncHealth page

### Visibility Guidelines

- Badge: Always visible but unobtrusive (small, in header)
- Banner: Only when active incidents, dismissible
- Dashboard indicator: Brief, doesn't dominate the view

---

## Implementation Sequence

### Week 1: Backend + API

1. Add `CompactHealthResponse` model and `/compact` endpoint
2. Add `ActiveIncidentsResponse` model and `/incidents/active` endpoint
3. Add `get_incident_scope()` and `get_incident_eta()` to DQService
4. Write backend unit tests

### Week 2: Frontend Context + API

1. Create `DataHealthContext.tsx` with smart polling
2. Extend `syncHealthApi.ts` with new functions
3. Integrate provider in `App.tsx`
4. Write context unit tests

### Week 3: UI Components

1. Create `DataFreshnessBadge.tsx`
2. Create `IncidentBanner.tsx`
3. Create `DashboardFreshnessIndicator.tsx`
4. Create `AppLayout.tsx`
5. Write component tests

### Week 4: Integration + Polish

1. Update `Analytics.tsx` with layout and indicator
2. Update other pages as needed
3. Add CSS animations (subtle pulse on status change)
4. E2E tests and accessibility review

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Time to notice stale data | < 60 seconds |
| Banner visibility for incidents | 100% of active incidents |
| False positive rate | < 1% |
| User confusion (support tickets) | Decrease vs. current |

---

## Dependencies

- Existing `DQService` and sync health infrastructure
- Existing `InsightBadge` and `BillingBanner` patterns
- Shopify Polaris Badge and Banner components
- Page Visibility API (browser standard)

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Polling overload | Adaptive intervals, visibility-aware |
| Stale data in context | Force refresh on tab focus |
| Banner fatigue | Allow dismiss, scope messaging |
| False positives | Clear severity thresholds |

---

## References

- Existing patterns:
  - `frontend/src/components/insights/InsightBadge.tsx` (badge pattern)
  - `frontend/src/components/BillingBanner.tsx` (banner pattern)
  - `frontend/src/contexts/AgencyContext.tsx` (context pattern)
- Backend services:
  - `backend/src/api/dq/routes.py` (existing health API)
  - `backend/src/api/dq/service.py` (health calculations)
