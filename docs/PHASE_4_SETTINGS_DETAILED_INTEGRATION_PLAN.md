# Phase 4: Settings — Detailed Integration Plan

## Overview

**Goal:** Deliver a production-ready, 8-tab Settings experience that exposes already-implemented backend capabilities through a unified frontend UX.

**Non-goal:** Backend feature development. Existing backend routes/services already cover the required domains.

### Architectural conclusion
The backend is mature across team, billing, notifications, AI config, audit/security, entitlements, and tenant isolation. Phase 4 is a frontend integration and orchestration effort.

### Production tab scope (8 tabs)
1. Data Sources
2. Sync Settings
3. Notifications
4. Account
5. Team
6. Billing
7. API Keys
8. AI Insights

### Dev-only wireframe tabs (excluded from production)
- Error States
- Loading States

---

## Wireframe-to-Production Mapping

| Wireframe Tab | Source | Production Strategy |
|---|---|---|
| Data Sources | inline in `Settings.tsx` | Reuse connected source cards from Phase 3 |
| Sync Settings | inline in `Settings.tsx` | New settings panel (schedule, processing, storage, failure behavior) |
| Notifications | inline in `Settings.tsx` | New preferences matrix + quiet hours + reports |
| Account | inline in `Settings.tsx` (stub) | Delegate profile/account management to Clerk `<UserProfile />` |
| Team | `settings/TeamSettings.tsx` | New member management experience (list, invite, roles) |
| Billing | `settings/BillingSettings.tsx` | New plan/usage/payment/invoice experience |
| API Keys | not in wireframes | New key management tab using backend/adapter endpoint |
| AI Insights | `settings/AISettings.tsx` | New provider + feature flag + usage UI |

---

## Backend Capability Inventory (Read-only Integration)

| Domain | Backend Route(s) | Service Layer | Readiness |
|---|---|---|---|
| Team Management | `tenant_members.py` | `tenant_members_service.py` | Mature |
| Billing & Plans | `billing.py` | `billing_service.py` | Mature |
| Notifications | `notifications.py` | `notification_service.py` | Mature |
| AI / LLM Config | `llm_config.py` | inline route logic | Mature |
| Audit & Security | `audit.py` | `audit_logger.py` | Mature |
| Entitlements | billing integration | `billing_entitlements.py` | Mature |
| Tenant isolation | `user_tenants.py` | `tenant_guard.py` | Mature |

**Implication:** Settings frontend should focus on strict API contracts, optimistic UX where safe, and robust error/loading states.

---

## Delivery Plan by Subphase

## Subphase 4.1 — Settings Type Definitions

### Goal
Create canonical TypeScript contracts for all 8 settings domains, mapped to backend model shapes and safe frontend conventions.

### New file
- `frontend/src/types/settingsTypes.ts`

### Type groups to define
- Team: `TeamMember`, `TeamInvite`, `RoleDefinition`
- Billing: `BillingPlan`, `PlanLimits`, `Subscription`, `Invoice`, `PaymentMethod`, `UsageMetrics`
- Notifications: `NotificationPreferences`, `DeliveryMethods`, `SyncNotificationMatrix`, `PerformanceAlert`, `ReportSchedule`, `QuietHoursConfig`
- AI/LLM: `AIProvider`, `AIProviderConfig`, `AIConfiguration`, `AIFeatureFlags`, `AIUsageStats`
- Sync: `SyncConfiguration`, `SyncScheduleConfig`, `DataProcessingConfig`, `StorageConfig`, `ErrorHandlingConfig`
- Account: `AccountProfile`
- API keys: `ApiKey`
- Tab navigation: `SettingsTab`

### Data contract rules
- Never expose raw secret material in frontend types (e.g., API keys).
- Preserve backend enum semantics with explicit unions.
- Prefer nullable/optional only where backend can legitimately omit fields.
- Keep domain types composable for form schemas and React Query cache keys.

### Backend model mapping
| Frontend Type | Backend Model/Source | Notes |
|---|---|---|
| `TeamMember` | user + tenant role assignment | View-model join |
| `TeamInvite` | `tenant_invite.py` | Direct map |
| `BillingPlan` | `plan.py` | Direct map |
| `Subscription` | `subscription.py` | Direct map |
| `Invoice` | billing event stream | Transform invoice-like events |
| `PaymentMethod` | provider proxy via billing routes | Tokenized, no PCI exposure |
| `NotificationPreferences` | notification preference record | Nested JSON-compatible shape |
| `AIConfiguration` | llm routing/config | Secret-safe config representation |
| `SyncConfiguration` | config endpoints | Composite response may be required |
| `ApiKey` | key management endpoint/model | If absent, add adapter endpoint in integration layer |

### Tests (18)
- `frontend/src/types/__tests__/settingsTypes.test.ts`

Test matrix:
1. Team (4)
   - `TeamMember` required field coverage
   - `TeamInvite` requires email + role
   - invite roles exclude `owner`
   - `RoleDefinition.permissions` is non-empty
2. Billing (4)
   - `PlanLimits` supports unlimited sentinel (`-1`)
   - `Subscription.status` union completeness
   - `Invoice.status` union completeness
   - usage used/limit pair integrity
3. Notifications (4)
   - `DeliveryMethods` channel completeness
   - `SyncNotificationMatrix` event completeness
   - `PerformanceAlert.channels` matches delivery shape
   - `QuietHoursConfig.days` value validity
4. AI (3)
   - `AIProvider` union coverage
   - `AIConfiguration` excludes raw key
   - `AIFeatureFlags` default behavior validation
5. Sync (3)
   - schedule frequency options
   - processing format fields required
   - error strategy union completeness

### Exit criteria
- All types exported from a single index entry point.
- Tests pass in CI.
- No `any` in settings domain contracts.

---

## Subphase 4.2 — API Services & React Query Hooks

### Goal
Implement a typed API service + hook layer for each tab with consistent cache keys, mutation invalidation, and error handling.

### Files
- `frontend/src/services/settingsApi.ts` (new)
- `frontend/src/hooks/settings/` (new folder)
  - `useSettingsTeam.ts`
  - `useSettingsBilling.ts`
  - `useSettingsNotifications.ts`
  - `useSettingsAI.ts`
  - `useSettingsSync.ts`
  - `useSettingsApiKeys.ts`
  - `useSettingsAccount.ts`

### Contract patterns
- Query keys: `['settings', domain, tenantId]`
- Domain-specific mutations invalidate only related keys.
- Normalize server errors to one shared `SettingsApiError` shape.
- Add request cancellation support for tab switches.

### Integration details
- Team: list members, invite member, update role, deactivate/remove.
- Billing: fetch plan/subscription/usage, list invoices, open provider portal actions.
- Notifications: get/save preference document with partial patch support.
- AI: get config, set provider, rotate key (write-only), test connection, toggle features.
- Sync: get/set schedule, processing defaults, storage retention, retry strategy.
- API Keys: list/create/revoke (show secret once on create response only).
- Account: read minimal profile for display; route deep profile edits to Clerk.

### Exit criteria
- All hooks typed with `settingsTypes.ts`.
- Retry/backoff and toasts aligned with app conventions.
- No duplicate HTTP logic inside components.

---

## Subphase 4.3 — Settings Page Shell & Tab Navigation

### Goal
Create the settings route, tab shell, and lazy-loaded tab panels.

### Files
- `frontend/src/pages/SettingsPage.tsx` (new)
- `frontend/src/components/settings/SettingsLayout.tsx` (new)
- Router update in app route registry

### UX requirements
- 8 production tabs only.
- URL-driven tab state (`/settings/:tab?`) with default tab fallback.
- Unsaved-change guard for mutable tabs.
- Permission/entitlement gating per tab.

### Exit criteria
- Deep links resolve directly to a tab.
- Keyboard-accessible tab navigation.
- Loading skeletons and error boundaries at tab-panel level.

---

## Subphase 4.4 — Data Sources & Sync Tabs

### Goal
Connect Data Sources (existing cards) and build Sync settings management.

### Data Sources plan
- Reuse existing source card/list components from Phase 3.
- Add settings-specific actions (re-auth, pause, manual sync) when supported.

### Sync tab plan
- Sections: schedule, data processing defaults, storage/retention, failure handling.
- Add “Reset to defaults” for safe rollback.
- Surface last backup/last sync metadata.

### Exit criteria
- Sync settings round-trip persists and refetches correctly.
- Source cards render current connection status consistently with dashboards pages.

---

## Subphase 4.5 — Team Management & Account Tabs

### Goal
Ship complete team administration UI and Clerk-backed account experience.

### Team tab
- Member table with role badges and status indicators.
- Invite modal with role selector (`admin|editor|viewer`).
- Role update + deactivate/remove actions with confirmation.
- Tenant-aware permission guards (owners/admins only for privileged actions).

### Account tab
- Embed Clerk profile container for account management.
- Display local profile summary (name/email/timezone/avatar).
- Keep auth/session/security actions delegated to Clerk UX.

### Exit criteria
- Team role updates reflect immediately (optimistic where safe).
- Invite and membership mutations are audit-friendly and error surfaced.

---

## Subphase 4.6 — Billing & AI Configuration Tabs

### Goal
Deliver billing lifecycle controls and AI provider configuration with safe key handling.

### Billing tab
- Plan card (current plan, status, renewal/cancel date).
- Usage meters mapped to plan limits.
- Invoice history and download links.
- Payment method display + “Manage billing” portal action.
- Upgrade/downgrade and cancellation flows with confirmation copy.

### AI tab
- Provider selection (OpenAI, Anthropic, Google).
- Secret-safe API key state (`hasApiKey`, never raw key).
- Connection test action and status indicator.
- Feature toggles (insights, recommendations, predictions, anomaly detection).
- Usage statistics panel.

### Exit criteria
- Billing actions route correctly to backend/provider flows.
- AI key rotation never leaks secrets into logs/state.

---

## Subphase 4.7 — Notifications, Final Assembly & Regression

### Goal
Complete notification settings UX, integrate all tabs, and execute regression hardening.

### Notifications tab
- Delivery method master toggles (in-app/email/sms/slack).
- Sync event matrix by channel.
- Performance alert rules list.
- Report schedules.
- Quiet hours with day/time controls and critical override.

### Final assembly
- Integrate all tab modules under a unified settings route.
- Add telemetry events for settings changes.
- Verify tenant isolation in every tab fetch/mutation.

### Regression checklist
- Cross-tab navigation preserves unsaved state prompts.
- Concurrent mutation conflicts handled with refetch/merge messaging.
- Mobile/tablet responsiveness and accessibility pass.
- Error and loading states present for each tab panel.

### Exit criteria
- End-to-end smoke checks pass for all 8 tabs.
- No dev-only wireframe tabs shipped.
- Documentation updated.

---

## Cross-Cutting Technical Decisions

1. **No backend endpoint creation by default** in Phase 4, except optional adapter for API Keys if absent.
2. **React Query as the single async state layer** for settings data.
3. **Tenant-safe query keys** and mutation guards for multi-tenancy correctness.
4. **Secret-safe contracts** for AI/API key handling.
5. **Feature and entitlement gating** at tab and action level.

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| API Keys endpoint not present | Medium | Implement frontend adapter abstraction; hide tab if unavailable |
| Contract mismatches between wireframe and backend | Medium | Use typed service transforms and explicit normalization |
| Complex forms across tabs | Medium | Shared form primitives + schema validation per section |
| Permission inconsistencies | High | Centralize guards; verify owner/admin gates in UI |
| Regression due to broad settings surface | High | Subphase-based rollout + targeted smoke suite |

---

## Rollout Strategy

1. Ship behind a settings feature flag.
2. Enable for internal tenant(s) first.
3. Collect errors and telemetry for one sprint.
4. Gradually ramp to all tenants.
5. Remove legacy settings entry points if any.

---

## Definition of Done (Phase 4)

- 8 production tabs implemented and routed.
- All tabs integrated with existing backend services (or validated adapters).
- Types, API hooks, and UI pass lint/typecheck/tests.
- Accessibility baseline satisfied.
- No Error/Loading demo tabs in production build.
- Documentation reflects final architecture and behavior.
