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

### API Patterns
- Async routes with `createHeadersAsync()` for Clerk token refresh
- `handleResponse<T>()` for typed error handling on the frontend
- Optimistic locking via `expected_updated_at` (409 on conflict)
- `let cancelled = false` + cleanup in useEffect for cancelled fetches

### Feature Gating
- `<FeatureGate>` component + `useFeatureEntitlement` hook
- `FeatureGateRoute` for route-level gating with redirect loop prevention
- Billing-driven entitlements: AI_INSIGHTS, AI_RECOMMENDATIONS, AI_ACTIONS, CUSTOM_REPORTS

### Frontend Patterns
- Shopify Polaris `<Modal>` with `<Modal.Section>` for dialogs
- React Context for builder session, agency, and data health state (no Redux)
- react-grid-layout for dashboard grids, Recharts for charts

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
