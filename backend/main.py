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

from src.platform.tenant_context import TenantContextMiddleware, get_tenant_context
from src.api.routes import health
from src.api.routes import billing
from src.api.routes import webhooks_shopify
from src.api.routes import admin_plans
from src.api.routes import sync
from src.api.routes import data_health
from src.api.routes import backfills

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

    # Check Frontegg authentication environment variables
    # These are optional - app can run without them but auth will be disabled
    auth_vars = ["FRONTEGG_CLIENT_ID"]
    env_status = {}
    for var in auth_vars:
        value = os.getenv(var)
        env_status[var] = "set" if value else "missing"

    missing_vars = [var for var in auth_vars if not os.getenv(var)]

    # Store auth configuration status in app state
    app.state.auth_configured = len(missing_vars) == 0

    if missing_vars:
        logger.warning(
            f"Frontegg authentication not configured (missing: {missing_vars}). "
            "Protected endpoints will return 503. Set FRONTEGG_CLIENT_ID to enable authentication."
        )
    else:
        logger.info("Frontegg authentication configured", extra={"env_status": env_status})

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CRITICAL: Add tenant context middleware
# Middleware uses lazy initialization - env vars validated in lifespan startup
tenant_middleware = TenantContextMiddleware()
app.middleware("http")(tenant_middleware)


# Include health route (bypasses authentication)
app.include_router(health.router)

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


# Example protected endpoint
@app.get("/api/data")
async def get_data(request: Request):
    """
    Example endpoint that requires tenant context.
    
    tenant_id is extracted from JWT (org_id), never from request.
    """
    tenant_ctx = get_tenant_context(request)
    
    logger.info("Data requested", extra={
        "tenant_id": tenant_ctx.tenant_id,
        "user_id": tenant_ctx.user_id,
        "roles": tenant_ctx.roles
    })
    
    # TODO: Replace with actual data fetching logic
    # Use tenant_ctx.tenant_id to scope queries
    return {
        "tenant_id": tenant_ctx.tenant_id,
        "user_id": tenant_ctx.user_id,
        "data": f"Sample data for tenant {tenant_ctx.tenant_id}",
        "message": "This endpoint demonstrates tenant isolation"
    }


@app.post("/api/data")
async def create_data(request: Request):
    """
    Example endpoint for creating data.
    
    SECURITY: tenant_id from request body is IGNORED.
    Only tenant_id from JWT is used.
    """
    tenant_ctx = get_tenant_context(request)
    body = await request.json()
    
    # Log attempt to include tenant_id in body (for security audit)
    if "tenant_id" in body:
        logger.warning(
            "tenant_id found in request body (ignored)",
            extra={
                "tenant_id_from_jwt": tenant_ctx.tenant_id,
                "tenant_id_from_body": body.get("tenant_id"),
                "user_id": tenant_ctx.user_id
            }
        )
    
    # TODO: Replace with actual data creation logic
    # Use tenant_ctx.tenant_id, NOT body.get("tenant_id")
    return {
        "tenant_id": tenant_ctx.tenant_id,  # Always from JWT
        "user_id": tenant_ctx.user_id,
        "created": True,
        "message": "Data created with tenant_id from JWT context"
    }


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