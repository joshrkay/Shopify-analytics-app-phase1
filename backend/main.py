"""
FastAPI application entry point for AI Growth Analytics.

Multi-tenant enforcement is enabled via TenantContextMiddleware.
All routes require valid JWT with tenant context.
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from src.platform.tenant_context import TenantContextMiddleware
from src.platform.csp_middleware import EmbedOnlyCSPMiddleware
from src.api.routes import health
from src.api.routes import debug
from src.api.routes import billing
from src.api.routes import webhooks_shopify
from src.api.routes import admin_plans
from src.api.routes import sync
from src.api.routes import data_health
from src.api.routes import backfills
from src.api.routes import embed
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
from src.api.routes import webhooks_clerk
from src.api.routes import tenant_members
from src.api.routes import user_tenants
from src.api.routes import dashboard_bindings
from src.api.dq import routes as sync_health

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
    logger.info("Starting AI Growth Analytics API")

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

    # Middleware will initialize lazily on first request if auth is configured
    logger.info(
        "Tenant context middleware ready",
        extra={"auth_enabled": app.state.auth_configured}
    )

    yield

    # Shutdown
    logger.info("Shutting down AI Growth Analytics API")


# Create FastAPI app
app = FastAPI(
    title="AI Growth Analytics API",
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

# Include sync routes (requires authentication)
app.include_router(sync.router)

# Include data health routes (requires authentication)
app.include_router(data_health.router)

# Include backfill routes (requires authentication)
app.include_router(backfills.router)

# Include embed routes for Shopify Admin embedding (requires authentication)
app.include_router(embed.router)

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