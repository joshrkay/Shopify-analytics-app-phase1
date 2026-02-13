# CLAUDE.md

This file provides context for AI assistants working on this codebase.

## Project Overview

Shopify Analytics App (MarkInsight / Signals AI) — a multi-tenant SaaS analytics platform embedded in Shopify Admin. Provides AI-powered insights, custom dashboards, and marketing attribution for Shopify merchants.

## Tech Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy, Pydantic, Alembic (migrations)
- **Frontend**: TypeScript, React 18, Vite 5, Shopify Polaris v12, Recharts, react-grid-layout
- **Auth**: Clerk (OAuth2/JWT) — ClerkProvider in main.tsx, useClerkToken hook, `createHeadersAsync()` for token refresh
- **Database**: PostgreSQL 15 with row-level security (RLS) for tenant isolation
- **Cache/Queue**: Redis 7
- **Data Pipeline**: dbt (analytics/), Airbyte for ETL ingestion
- **Embedded Analytics**: Apache Superset
- **LLM Integration**: OpenRouter API
- **Deployment**: Docker, Render.com (render.yaml), GitHub Actions CI

## Repository Structure

```
backend/           Python FastAPI backend (main.py entry point)
  src/
    api/routes/    API route modules (30+)
    api/schemas/   Pydantic request/response schemas
    models/        SQLAlchemy ORM models (57+)
    services/      Business logic layer (30+)
    repositories/  Data access layer
    integrations/  External API clients (Shopify, OpenRouter, Airbyte)
    platform/      Multi-tenant enforcement (TenantContext, CSP middleware)
    auth/          JWT token service
    jobs/          Background job definitions
    workers/       Worker process handlers
    tests/         Test suites (unit, integration, regression, platform, e2e)
  migrations/      Alembic DB migrations
frontend/          React/TypeScript frontend
  src/
    components/    React components
    pages/         Page components
    hooks/         Custom React hooks
    services/      API client services
    contexts/      React contexts (DashboardBuilder, Agency, DataHealth)
    types/         TypeScript type definitions
    tests/         Frontend tests (Vitest)
analytics/         dbt project for data modeling
  models/          raw/ -> staging/ -> canonical/ -> attribution/ -> metrics/ -> marts/
db/                Database management (migrations, RLS policies, retention)
docker/            Dockerfiles (backend, worker, superset)
docs/              Project documentation
config/            Configuration files (plans.json)
scripts/           Utility scripts
.github/workflows/ CI/CD (ci.yml)
```

## Build & Run Commands

### Backend (from `backend/` directory)

```bash
make install            # Install Python dependencies
make test               # Run all tests: PYTHONPATH=. pytest src/tests/ -v --tb=short
make test-unit          # Unit tests (excludes regression)
make test-regression    # Billing regression tests (requires PostgreSQL)
make test-billing       # All billing tests with coverage
make test-platform      # Platform/tenant isolation tests with coverage
make test-raw-rls       # Raw warehouse RLS tests (requires PostgreSQL)
make lint               # Lint: ruff check src/
make format             # Format: ruff format src/
make clean              # Remove __pycache__, .pytest_cache, coverage files
```

### Frontend (from `frontend/` directory)

```bash
npm install             # Install dependencies
npm run dev             # Dev server (Vite, port 3000)
npm run build           # Production build: tsc && vite build
npm run lint            # ESLint with --max-warnings 0
npm run test            # Run tests (Vitest)
npm run test:ui         # Vitest UI
```

### dbt / Analytics (from `analytics/` directory)

```bash
dbt deps --profiles-dir . --project-dir .      # Install dbt packages
dbt compile --profiles-dir . --project-dir .    # Compile models
dbt run --profiles-dir . --project-dir .        # Build all models
dbt test --profiles-dir . --project-dir .       # Run data quality tests
```

### Docker (from project root)

```bash
docker-compose up -d    # Start full local stack (postgres, redis, superset, backend, frontend)
```

## CI Pipeline (GitHub Actions)

Triggered on push/PR to `main` and `develop`. All jobs must pass for PR merge:

1. **Quality Gates** — Platform gate tests + tenant isolation tests
2. **dbt Validation** — Compile, build, and test all dbt models (requires PostgreSQL service)
3. **Platform Tests** — Full platform test suite with coverage
4. **Billing Regression** — Billing flows + raw warehouse RLS tests (requires PostgreSQL service)

## Key Architectural Patterns

### Multi-Tenancy
- `TenantContextMiddleware` enforces tenant isolation on every request
- PostgreSQL RLS policies at the database level
- Backend uses `SELECT FOR UPDATE` to prevent TOCTOU races (e.g., dashboard limits)

### Authentication & Tenant Provisioning (Critical Path)

The request lifecycle for any authenticated API call is:

```
JWT → TenantContextMiddleware.__call__()
  → _resolve_tenant_from_db()   [own DB session — lazy-syncs User/Tenant/Role, resolves IDs]
  → TenantGuard.enforce_authorization()  [separate DB session — verifies records exist]
  → Route handler
```

**Rules for modifying auth/provisioning code:**

1. **Single provisioning path** — User, Tenant, and UserTenantRole records are created ONLY in `_resolve_tenant_from_db` via `ClerkSyncService`. Do NOT add duplicate bootstrap/creation logic in TenantGuard or elsewhere. Multiple uncoordinated creation paths cause IntegrityError collisions and 503s.

2. **Clerk org_id ≠ Tenant.id** — JWT `org_id` is a Clerk string (e.g., `"org_2abc..."`). `Tenant.id` is an internal UUID string. These are DIFFERENT values stored in different columns (`clerk_org_id` vs `id`). Any code that receives an identifier from JWT must normalize it to `Tenant.id` before passing to TenantGuard or route handlers. Never assume a JWT claim can be used directly as a database primary key.

3. **Lazy sync must handle duplicates** — The lazy sync in `_resolve_tenant_from_db` can race with Clerk webhooks or concurrent requests. Always catch `IntegrityError`, rollback, and re-query. The record you tried to create probably already exists.

4. **Fallback values must be valid** — When `_resolve_tenant_from_db` falls back (DB error, sync failure), the returned `active_tenant_id` may still be a raw Clerk org_id. The `__call__` method must detect this and resolve it before passing to TenantGuard. Never pass an unvalidated identifier to code that uses it in FK relationships.

5. **Fail-closed with clear errors** — The middleware catches `SQLAlchemyError` and returns 503. If you see 503s, check the backend logs for the actual exception type and message (logged at ERROR level). A 503 means a database operation threw — not that the DB is unreachable.

6. **Two DB sessions per request** — `_resolve_tenant_from_db` opens and closes its own session. `__call__` opens a separate session for TenantGuard. Data committed in the first session IS visible to the second (PostgreSQL READ COMMITTED). But uncommitted/rolled-back data is NOT.

### API Patterns
- Async routes with `createHeadersAsync()` for Clerk token refresh
- `handleResponse<T>()` for typed error handling on the frontend — checks `Content-Type` before parsing JSON and surfaces clear errors when HTML is returned (backend down, wrong URL, etc.)
- Optimistic locking via `expected_updated_at` (409 on conflict)
- `let cancelled = false` + cleanup in useEffect for cancelled fetches
- **Always use `createHeadersAsync()`** — NOT `createHeaders()`. The async version waits for the Clerk token to be cached before returning headers. The sync version returns stale/empty tokens on first render, causing 401/403 race conditions. Every `fetch()` call in `frontend/src/services/` must `await createHeadersAsync()`.
- **All frontend API URLs must include `/api` prefix** — e.g., `${API_BASE_URL}/api/billing/entitlements`, not `${API_BASE_URL}/billing/entitlements`. Without it, Vite's SPA fallback serves `index.html` and the frontend gets `"Unexpected token '<'"` errors trying to parse HTML as JSON.

### Feature Gating & Entitlements
- `<FeatureGate>` component + `useFeatureEntitlement` hook
- `FeatureGateRoute` for route-level gating with redirect loop prevention
- Billing-driven entitlements: AI_INSIGHTS, AI_RECOMMENDATIONS, AI_ACTIONS, CUSTOM_REPORTS
- **Two entitlement systems exist** — `EntitlementPolicy` (queries `Subscription` table) and `BILLING_TIER_FEATURES` (static dict in `billing_entitlements.py`). The `/api/billing/entitlements` endpoint uses `EntitlementPolicy` when a `Subscription` exists, and falls back to `BILLING_TIER_FEATURES` for free-tier tenants with no subscription. When modifying entitlements logic, update BOTH paths.
- **Frontend entitlements URL** — Must be `${API_BASE_URL}/api/billing/entitlements` (note the `/api` prefix). The Vite dev proxy forwards `/api` to the backend; without it, requests hit the SPA fallback and return HTML instead of JSON.

### Frontend Patterns
- Shopify Polaris `<Modal>` with `<Modal.Section>` for dialogs
- React Context for builder session, agency, and data health state (no Redux)
- react-grid-layout for dashboard grids, Recharts for charts
- **Context Provider Rule**: Every React context hook (e.g., `useAgency`, `useDataHealth`) MUST have its corresponding Provider mounted in the component tree in `App.tsx` before any component that calls the hook. When adding a new context or a new consumer of an existing context, verify the Provider is present in `AppWithOrg()` (or higher). Tests that mock contexts will not catch a missing Provider — always check the real component tree in `App.tsx`.

### Data Pipeline
- dbt model layers: raw -> staging -> canonical -> attribution -> semantic -> metrics -> marts
- Incremental materialization with configurable lookback windows per source
- Tenant isolation enforced in dbt via `tenant_isolation_enforced` var

## Testing

- **Backend**: pytest with asyncio, mock, coverage, timeout, and hypothesis (property-based)
- **Frontend**: Vitest with jsdom, @testing-library/react, @testing-library/user-event
- **dbt**: YAML-defined data quality tests with `+severity: error`
- **Markers**: `@pytest.mark.regression` for billing regression, `@pytest.mark.slow` for slow tests

## Code Quality Rules

- No breaking changes without migration steps
- No TODOs in committed code without tracked issues
- No disabling tests/lint/type checks
- No secret leakage in code or logs
- YAGNI — implement only what the current story requires
- Delete dead code, unused imports, and commented blocks immediately
- Prefer extending existing code over new abstractions
- Every bug fix must include a regression test
- Structured logging via structlog (JSON key/value, correlation IDs)
- Parameterized queries only — no SQL string concatenation

### Frontend-Backend Contract Verification

When adding or modifying frontend API service functions (`frontend/src/services/`), you MUST verify that a corresponding backend route exists in `backend/src/api/routes/` before marking the work as complete. Specifically:

1. **Verify route existence** — Confirm the backend has a matching route for the URL path, HTTP method, and expected request/response shape
2. **Verify field names** — The backend returns snake_case fields; the frontend normalizes to camelCase. Confirm the raw field names match what the backend actually sends
3. **Document missing routes** — If a frontend API function calls a backend route that does not yet exist, you MUST explicitly call this out in the PR description and commit message. Do NOT silently ship frontend code that calls non-existent endpoints
4. **No silent 404s** — Frontend service functions that target missing backend routes will fail at runtime. These must be tracked and scheduled for implementation

**Previously missing backend routes** — All 10 routes below were implemented in Phase 3:
- `GET /api/sources/catalog` — Source catalog/definitions (`getAvailableSources`) ✅
- `POST /api/sources/{platform}/oauth/initiate` — OAuth flow start (`initiateOAuth`) ✅
- `POST /api/sources/oauth/callback` — OAuth callback (`completeOAuth`) ✅
- `DELETE /api/sources/{id}` — Disconnect source (`disconnectSource`) ✅
- `POST /api/sources/{id}/test` — Connection test (`testConnection`) ✅
- `PATCH /api/sources/{id}/config` — Sync config update (`updateSyncConfig`) ✅
- `GET /api/ad-platform-ingestion/connections/{id}/accounts` — Account discovery (`getAvailableAccounts`) ✅
- `PUT /api/ad-platform-ingestion/connections/{id}/accounts` — Account selection (`updateSelectedAccounts`) ✅
- `GET /api/sources/sync-settings` — Global sync settings (`getGlobalSyncSettings`) ✅
- `PUT /api/sources/sync-settings` — Global sync settings update (`updateGlobalSyncSettings`) ✅

## Engineering Workflow

This project follows a structured development cycle using Claude Code plugins.

### Standard Development Cycle

1. **Plan** — `/workflows:plan` — Before writing code, create a structured plan
   - Define the problem, constraints, and approach
   - Break work into discrete, reviewable units
   - Identify files that will be touched

2. **Work** — `/workflows:work` — Execute the plan with tracking
   - Follow the plan step by step
   - Use git worktrees for isolation when appropriate
   - Commit frequently with clear messages

3. **Review** — Use PR Review Toolkit agents for multi-pass review
   - Bug detection and edge cases
   - CLAUDE.md compliance check
   - Historical context review (does this match project patterns?)
   - Security scan via Trail of Bits skills

4. **Compound** — `/workflows:compound` — Capture learnings
   - Document patterns discovered during this work
   - Update project knowledge for future sessions
   - Note any architectural decisions and their rationale

### Security Requirements

All PRs touching authentication, data handling, API endpoints, or infrastructure
must include a security review pass using Trail of Bits skills before merge.
Focus areas:
- Input validation and injection vectors
- Authentication and authorization flows
- Secrets management
- Dependency vulnerabilities

### Review Standards

Code review uses parallel agents. At minimum, every PR should pass:
- Bug detection agent
- Code quality agent
- Security scan (for changes in scope above)

### Daily Workflow Examples

#### Starting a New Feature

```
You: /workflows:plan
     "I need to add rate limiting to the API gateway"
Claude: [creates structured plan with tasks, affected files, risks]

You: /workflows:work
     [executes plan, commits incrementally]

You: "Review this PR with the PR review toolkit — run all agents"
Claude: [runs 5 parallel review agents, reports findings]

You: /workflows:compound
     [captures what was learned about the rate limiting approach]
```

#### Quick Bug Fix (Lighter Process)

For small fixes, you can skip the full plan step:

```
You: "Fix the null pointer in UserService.getProfile — review when done"
Claude: [fixes bug, runs review agents, reports]

You: /workflows:compound
     [optional but recommended — even small fixes teach patterns]
```

#### Security-Focused Work

When touching sensitive code paths:

```
You: "Audit the authentication middleware for vulnerabilities"
Claude: [uses Trail of Bits skills — static analysis, variant analysis,
         differential review against known vulnerability patterns]
```

## Environment Variables

Key variables (see `.env.example` for full list):
- `DATABASE_URL` — PostgreSQL connection string
- `REDIS_URL` — Redis connection string
- `CLERK_SECRET_KEY` / `VITE_CLERK_PUBLISHABLE_KEY` — Auth
- `SHOPIFY_API_KEY` / `SHOPIFY_API_SECRET` — Shopify OAuth + webhooks
- `OPENROUTER_API_KEY` — LLM integration
- `ENCRYPTION_KEY` — Secret encryption (base64)
- `AIRBYTE_WORKSPACE_ID` / `AIRBYTE_API_TOKEN` — ETL
- `SUPERSET_JWT_SECRET` / `SUPERSET_SECRET_KEY` — Embedded analytics
