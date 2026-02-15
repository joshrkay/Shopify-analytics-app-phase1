"""
FastAPI application entry point for MarkInsight.

Multi-tenant enforcement is enabled via TenantContextMiddleware.
All routes require valid JWT with tenant context.
"""

import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from src.platform.tenant_context import TenantContextMiddleware
from src.platform.csp_middleware import EmbedOnlyCSPMiddleware
from src.middleware.audit_middleware import AuditLoggingMiddleware
from src.api.routes import health
from src.api.routes import debug
from src.api.routes import billing
from src.api.routes import webhooks_shopify
from src.api.routes import admin_plans
from src.api.routes import admin_backfills
from src.api.routes import backfills_status
from src.api.routes import sync
from src.api.routes import data_health
from src.api.routes import backfills
from src.api.routes import embed
from src.api.routes import auth_revoke_tokens
from src.api.routes import dashboards_allowed
from src.api.routes import insights
from src.api.routes import recommendations
from src.api.routes import action_proposals
from src.api.routes import actions
from src.api.routes import llm_config
from src.api.routes import changelog
from src.api.routes import admin_changelog
from src.api.routes import what_changed
from src.api.routes import shopify_ingestion
from src.api.routes import ad_platform_ingestion
from src.api.routes import sources
from src.api.routes import webhooks_clerk
from src.api.routes import tenant_members
from src.api.routes import user_tenants
from src.api.routes import dashboard_bindings
from src.api.dq import routes as sync_health
from src.api.routes import admin_diagnostics
from src.api.routes import agency_access
from src.api.routes import auth_refresh_jwt
from src.api.routes import audit_logs
from src.api.routes import audit_export
from src.api.routes import shopify_embed_entry
from src.api.routes import agency
from src.api.routes import datasets
from src.api.routes import custom_dashboards
from src.api.routes import dashboard_shares
from src.api.routes import report_templates
from src.platform.db_readiness import REQUIRED_IDENTITY_TABLES, check_required_tables
from src.database.session import get_db_session_sync

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Starting MarkInsight API")

    # Check Clerk authentication environment variables
    # These are optional - app can run without them but auth will be disabled
    auth_vars = ["CLERK_FRONTEND_API"]
    env_status = {}
    for var in auth_vars:
        value = os.getenv(var)
        env_status[var] = "set" if value else "missing"

    missing_vars = [var for var in auth_vars if not os.getenv(var)]

    # Store auth configuration status in app state
    app.state.auth_configured = len(missing_vars) == 0

    if missing_vars:
        logger.warning(
            f"Clerk authentication not configured (missing: {missing_vars}). "
            "Protected endpoints will return 503. Set CLERK_FRONTEND_API to enable authentication."
        )
    else:
        logger.info("Clerk authentication configured", extra={"env_status": env_status})

        # JWKS reachability probe — informational only, does not block startup.
        # Logs whether the Clerk JWKS endpoint is reachable so that DNS/config
        # issues are visible in deploy logs before the first request fails.
        clerk_api = os.getenv("CLERK_FRONTEND_API", "").rstrip("/")
        if not clerk_api.startswith("http"):
            clerk_api = f"https://{clerk_api}"
        jwks_url = f"{clerk_api}/.well-known/jwks.json"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(jwks_url)
            if resp.status_code == 200:
                key_count = len(resp.json().get("keys", []))
                logger.info(
                    "JWKS probe: reachable",
                    extra={"url": jwks_url, "key_count": key_count},
                )
            else:
                logger.warning(
                    "JWKS probe: unexpected status",
                    extra={"url": jwks_url, "status": resp.status_code},
                )
        except Exception as e:
            logger.warning(
                "JWKS probe: unreachable",
                extra={"url": jwks_url, "error": f"{type(e).__name__}: {e}"},
            )

    # Database connectivity check — surface misconfigurations in deploy logs
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error(
            "DATABASE_URL is not set. All authenticated endpoints will return 503. "
            "Set DATABASE_URL in the Render environment or fix the fromDatabase binding in render.yaml."
        )
        app.state.database_configured = False
    else:
        # Mask credentials for safe logging
        masked = database_url.split("@")[-1] if "@" in database_url else "(no @ found — URL may be malformed)"
        logger.info("DATABASE_URL configured", extra={"host_db": masked})
        app.state.database_configured = True

    # Check identity schema readiness (required for fail-closed auth enforcement)
    app.state.identity_schema_ready = False
    app.state.identity_schema_missing_tables = []
    try:
        db_gen = get_db_session_sync()
        db = next(db_gen)
        try:
            readiness = check_required_tables(db, REQUIRED_IDENTITY_TABLES)
            app.state.identity_schema_ready = readiness.ready
            app.state.identity_schema_missing_tables = readiness.missing_tables
            if readiness.ready:
                logger.info(
                    "Identity schema readiness check passed",
                    extra={"required_tables": readiness.checked_tables},
                )
            else:
                logger.error(
                    "Identity schema readiness check failed",
                    extra={
                        "required_tables": readiness.checked_tables,
                        "missing_tables": readiness.missing_tables,
                    },
                )
        finally:
            db.close()
    except Exception as e:
        logger.exception("Identity schema readiness check errored", extra={"error": str(e)})

    # Middleware will initialize lazily on first request if auth is configured
    logger.info(
        "Tenant context middleware ready",
        extra={
            "auth_enabled": app.state.auth_configured,
            "identity_schema_ready": app.state.identity_schema_ready,
            "identity_schema_missing_tables": app.state.identity_schema_missing_tables,
        },
    )

    yield

    # Shutdown
    logger.info("Shutting down MarkInsight API")


# Create FastAPI app
app = FastAPI(
    title="MarkInsight API",
    description="Multi-tenant analytics platform with strict tenant isolation",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware (configure for your frontend domain)
# Include Shopify Admin in CORS origins for embedding
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
if "https://admin.shopify.com" not in cors_origins:
    cors_origins.append("https://admin.shopify.com")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSP middleware for Shopify Admin embedding (only applied to /api/v1/embed routes)
app.add_middleware(EmbedOnlyCSPMiddleware)

# CRITICAL: Add tenant context middleware
# Middleware uses lazy initialization - env vars validated in lifespan startup
tenant_middleware = TenantContextMiddleware()
app.middleware("http")(tenant_middleware)
app.add_middleware(AuditLoggingMiddleware)


# Include health route (bypasses authentication)
app.include_router(health.router)

# Include debug routes (bypasses authentication)
app.include_router(debug.router)

# Include billing routes (requires authentication)
app.include_router(billing.router)

# Include Shopify webhook routes (uses HMAC verification, not JWT)
app.include_router(webhooks_shopify.router)

# Include admin routes (requires admin role)
app.include_router(admin_plans.router)

# Include admin backfill routes (requires super admin)
# Story 3.4 - Backfill Request API
app.include_router(admin_backfills.router)

# Include backfill status routes (requires super admin)
# Story 3.4 - Backfill Status API
app.include_router(backfills_status.router)

# Include sync routes (requires authentication)
app.include_router(sync.router)

# Include data health routes (requires authentication)
app.include_router(data_health.router)

# Include backfill routes (requires authentication)
app.include_router(backfills.router)

# Include embed routes for Shopify Admin embedding (requires authentication)
app.include_router(embed.router)

# Include token revocation routes (Phase 1 - JWT Issuance)
app.include_router(auth_revoke_tokens.router)

# Include dashboard access routes (Phase 5 - Dashboard Visibility Gate)
app.include_router(dashboards_allowed.router)

# Include sync health routes for data quality monitoring (requires authentication)
app.include_router(sync_health.router)

# Include AI insights routes (requires authentication and AI_INSIGHTS entitlement)
app.include_router(insights.router)

# Include AI recommendations routes (requires authentication and AI_RECOMMENDATIONS entitlement)
app.include_router(recommendations.router)

# Include action proposals routes (requires authentication and AI_ACTIONS entitlement)
# Story 8.4 - Action Proposals (Approval Required)
app.include_router(action_proposals.router)

# Include actions routes (requires authentication and AI_ACTIONS entitlement)
# Story 8.5 - Action Execution (Scoped & Reversible)
app.include_router(actions.router)

# Include LLM config routes (requires authentication and AI entitlement)
# Story 8.8 - Model Routing & Prompt Governance
app.include_router(llm_config.router)

# Include changelog routes (requires authentication)
# Story 9.7 - In-App Changelog & Release Notes
app.include_router(changelog.router)

# Include admin changelog routes (requires ADMIN_SYSTEM_CONFIG permission)
# Story 9.7 - In-App Changelog & Release Notes
app.include_router(admin_changelog.router)

# Include what-changed routes (requires authentication, read-only)
# Story 9.8 - "What Changed?" Debug Panel
app.include_router(what_changed.router)

# Include Shopify ingestion routes (requires authentication)
# Shopify data source setup and sync management
app.include_router(shopify_ingestion.router)

# Include ad platform ingestion routes (requires authentication)
# Ad platform data source setup and sync via Airbyte
app.include_router(ad_platform_ingestion.router)

# Include unified sources routes (requires authentication)
# Story 2.1.1 - Unified Source domain model
app.include_router(sources.router)

# Include Clerk webhook routes (uses Svix signature verification, not JWT)
# Epic 1.1 - Identity synchronization from Clerk
app.include_router(webhooks_clerk.router)

# Include tenant members routes (requires authentication and TEAM_MANAGE permission)
# Epic 1.1 - Agency tenant access management
app.include_router(tenant_members.router)

# Include user tenants routes (requires authentication)
# Epic 1.1 - Get tenants accessible by current user
app.include_router(user_tenants.router)

# Include dashboard metric binding routes (requires authentication)
# Story 2.3 - Metric → Dashboard Binding, Consumption & Safety
app.include_router(dashboard_bindings.router)

# Include admin diagnostics routes (requires admin role)
# Story 4.2 - Data Quality Root Cause Signals
app.include_router(admin_diagnostics.router)

# Include agency access routes (requires authentication)
# Story 5.5.2 - Agency Access Request + Tenant Approval Workflow
app.include_router(agency_access.router)

# Include auth JWT refresh routes (requires authentication)
# Story 5.5.3 - Tenant Selector + JWT Refresh for Active Tenant Context
app.include_router(auth_refresh_jwt.router)
app.include_router(audit_logs.router)
app.include_router(audit_export.router)

# Custom Reports & Dashboard Builder (requires authentication + custom_reports entitlement for writes)
app.include_router(custom_dashboards.router)
app.include_router(dashboard_shares.router)
app.include_router(report_templates.router)

# Include dataset discovery + chart preview routes (requires authentication)
# Phase 2A/2B - Dataset Discovery & Chart Preview
app.include_router(datasets.router)

# Include agency routes (requires authentication and agency role)
# Story 5.5.1 - Agency Store Management
app.include_router(agency.router)


# ---------------------------------------------------------------------------
# Serve the built React frontend (bundled into /app/backend/static by Docker)
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).resolve().parent / "static"

if STATIC_DIR.is_dir():
    # Mount Vite's hashed asset files (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(request: Request, full_path: str):
        """
        SPA catch-all: serve the file if it exists in static/, otherwise
        serve index.html so React Router can handle client-side routing.

        This MUST be registered after all API routes so /api/* and /health
        are matched first.
        """
        # Try to serve an exact static file (e.g. favicon.ico, vite.svg)
        file_path = STATIC_DIR / full_path
        if full_path and file_path.is_file():
            return FileResponse(str(file_path))

        # Everything else → index.html (React Router handles the route)
        return FileResponse(str(STATIC_DIR / "index.html"))
else:
    logger.warning(
        "Frontend static directory not found at %s — "
        "falling back to bootstrap page. Build the frontend and "
        "copy dist/ to backend/static/ to serve the full UI.",
        STATIC_DIR,
    )
    # Keep the shopify_embed_entry bootstrap fallback if static dir missing
    app.include_router(shopify_embed_entry.router)


# Global exception handler for tenant isolation errors
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle unhandled exceptions with proper logging."""
    tenant_id = "unknown"
    if hasattr(request.state, "tenant_context"):
        tenant_id = request.state.tenant_context.tenant_id
    
    logger.error(
        "Unhandled exception",
        extra={
            "tenant_id": tenant_id,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "path": request.url.path
        },
        exc_info=True
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": "An unexpected error occurred"
        }
    )


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=os.getenv("ENV") == "development"
    )
