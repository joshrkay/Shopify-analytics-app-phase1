"""
Embedded Analytics API routes for Shopify Admin.

Handles:
- JWT token generation for Superset embedding
- Token refresh for long-lived sessions
- Dashboard URL generation with embedded mode

Security:
- All routes require JWT authentication with tenant context
- Requires ANALYTICS_VIEW permission
- Tokens are scoped to specific dashboards
- CSP headers enforce Shopify Admin framing only
"""

import os
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Request, HTTPException, status, Depends, Response
from pydantic import BaseModel, Field

from src.platform.tenant_context import get_tenant_context, TenantContext
from src.platform.rbac import require_permission
from src.constants.permissions import Permission
from src.services.embed_token_service import (
    EmbedTokenService,
    EmbedTokenResult,
    EmbedTokenError,
    TokenExpiredError,
    TokenValidationError,
    get_embed_token_service,
)
from src.services.dashboard_access_service import DashboardAccessService
from src.middleware.rate_limit import rate_limit_dependency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/embed", tags=["embed"])


# Request/Response models
class EmbedTokenRequest(BaseModel):
    """Request to generate an embed token."""
    dashboard_id: str = Field(..., description="Superset dashboard ID to embed")
    tenant_id: Optional[str] = Field(None, description="Tenant ID (ignored, uses JWT context)")
    access_surface: Literal["shopify_embed", "external_app"] = Field(
        "shopify_embed", description="Where the token will be used"
    )


class RefreshTokenRequest(BaseModel):
    """Request to refresh an embed token."""
    current_token: str = Field(..., description="Current JWT token to refresh")
    dashboard_id: Optional[str] = Field(None, description="Dashboard ID (optional, uses token if not provided)")


class EmbedTokenResponse(BaseModel):
    """Response with embed token and metadata."""
    jwt_token: str
    expires_at: str
    refresh_before: str
    dashboard_url: str
    embed_config: dict


class EmbedConfigResponse(BaseModel):
    """Response with embed configuration."""
    superset_url: str
    allowed_dashboards: list[str]
    session_refresh_interval_ms: int
    csp_frame_ancestors: list[str]


class EmbedReadinessResponse(BaseModel):
    """Response with strict embed readiness checks for frontend bootstrap."""
    status: Literal["ready", "not_ready"]
    embed_configured: bool
    superset_url_configured: bool
    allowed_dashboards_configured: bool
    message: Optional[str] = None


# CSP headers for Shopify Admin embedding
def add_embed_csp_headers(response: Response) -> Response:
    """
    Add CSP headers that allow framing from Shopify Admin only.
    """
    # Frame ancestors restricts where this content can be embedded
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.shopify.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.shopify.com; "
        "img-src 'self' data: https:; "
        "font-src 'self' data: https:; "
        "connect-src 'self' https://api.shopify.com https://admin.shopify.com; "
        "frame-ancestors 'self' https://admin.shopify.com https://*.myshopify.com; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    # X-Frame-Options for legacy browser support
    response.headers["X-Frame-Options"] = "ALLOW-FROM https://admin.shopify.com"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    return response


def get_service() -> EmbedTokenService:
    """Dependency to get embed token service."""
    try:
        return get_embed_token_service()
    except ValueError as e:
        logger.error("Embed token service not configured", extra={"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedded analytics not configured"
        )


@router.post("/token", response_model=EmbedTokenResponse)
@require_permission(Permission.ANALYTICS_VIEW)
async def generate_embed_token(
    request: Request,
    token_request: EmbedTokenRequest,
    response: Response,
    service: EmbedTokenService = Depends(get_service),
    _rate_limit=Depends(rate_limit_dependency("embed_token")),
):
    """
    Generate a JWT token for embedding Superset dashboard.

    The token is scoped to:
    - The authenticated user
    - The tenant from JWT context
    - The specified dashboard

    Returns URL with embedded mode parameters that hide Superset chrome.
    """
    tenant_ctx = get_tenant_context(request)

    # Log token request (tenant_id from request body is ignored)
    if token_request.tenant_id and token_request.tenant_id != tenant_ctx.tenant_id:
        logger.warning(
            "Embed token request included different tenant_id (ignored)",
            extra={
                "requested_tenant_id": token_request.tenant_id,
                "jwt_tenant_id": tenant_ctx.tenant_id,
                "user_id": tenant_ctx.user_id,
            }
        )

    # Phase 5 — Dashboard Visibility Gate: validate dashboard access
    access_service = DashboardAccessService(
        tenant_id=tenant_ctx.tenant_id,
        roles=tenant_ctx.roles,
        billing_tier=tenant_ctx.billing_tier,
    )
    if not access_service.is_dashboard_allowed(token_request.dashboard_id):
        logger.warning(
            "dashboard.access_denied",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "user_id": tenant_ctx.user_id,
                "dashboard_id": token_request.dashboard_id,
                "billing_tier": tenant_ctx.billing_tier,
                "roles": tenant_ctx.roles,
                "allowed_dashboards": access_service.get_allowed_dashboards(),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dashboard not available for your plan",
        )

    logger.info(
        "Generating embed token",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
            "dashboard_id": token_request.dashboard_id,
        }
    )

    try:
        result = service.generate_embed_token(
            tenant_context=tenant_ctx,
            dashboard_id=token_request.dashboard_id,
            access_surface=token_request.access_surface,
        )

        # Emit auth.jwt_issued and dashboard.viewed audit events
        try:
            from src.services.audit_logger import (
                emit_jwt_issued,
                emit_dashboard_viewed,
            )
            from src.database.session import get_db_session_sync
            from src.platform.audit import get_correlation_id

            db_gen = get_db_session_sync()
            db = next(db_gen)
            try:
                emit_jwt_issued(
                    db=db,
                    tenant_id=tenant_ctx.tenant_id,
                    user_id=tenant_ctx.user_id,
                    dashboard_id=token_request.dashboard_id,
                    access_surface=token_request.access_surface,
                    lifetime_minutes=service.config.default_lifetime_minutes,
                    correlation_id=get_correlation_id(request),
                )
                emit_dashboard_viewed(
                    db=db,
                    tenant_id=tenant_ctx.tenant_id,
                    user_id=tenant_ctx.user_id,
                    dashboard_id=token_request.dashboard_id,
                    access_surface=token_request.access_surface,
                    correlation_id=get_correlation_id(request),
                )
            finally:
                db.close()
        except Exception:
            logger.warning(
                "Failed to emit embed audit events",
                extra={
                    "tenant_id": tenant_ctx.tenant_id,
                    "user_id": tenant_ctx.user_id,
                },
                exc_info=True,
            )

        # Add CSP headers
        add_embed_csp_headers(response)

        return EmbedTokenResponse(
            jwt_token=result.jwt_token,
            expires_at=result.expires_at.isoformat(),
            refresh_before=result.refresh_before.isoformat(),
            dashboard_url=result.dashboard_url,
            embed_config={
                "standalone": True,
                "show_filters": False,
                "show_title": False,
                "hide_chrome": True,
            },
        )

    except EmbedTokenError as e:
        logger.error(
            "Failed to generate embed token",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "error": str(e),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate embed token"
        )


@router.post("/token/refresh", response_model=EmbedTokenResponse)
@require_permission(Permission.ANALYTICS_VIEW)
async def refresh_embed_token(
    request: Request,
    refresh_request: RefreshTokenRequest,
    response: Response,
    service: EmbedTokenService = Depends(get_service),
    _rate_limit=Depends(rate_limit_dependency("embed_token_refresh", limit=60)),
):
    """
    Refresh an embed token before expiry.

    Allows silent token refresh to maintain long-running sessions
    without user interruption.

    Tokens can be refreshed:
    - Before expiry (recommended)
    - Up to 10 minutes after expiry (grace period)
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Refreshing embed token",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
        }
    )

    try:
        result = service.refresh_token(
            old_token=refresh_request.current_token,
            tenant_context=tenant_ctx,
        )

        # Emit auth.jwt_refresh audit event
        # Add CSP headers
        add_embed_csp_headers(response)

        return EmbedTokenResponse(
            jwt_token=result.jwt_token,
            expires_at=result.expires_at.isoformat(),
            refresh_before=result.refresh_before.isoformat(),
            dashboard_url=result.dashboard_url,
            embed_config={
                "standalone": True,
                "show_filters": False,
                "show_title": False,
                "hide_chrome": True,
            },
        )

    except TokenExpiredError as e:
        logger.warning(
            "Token refresh failed - expired beyond grace period",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "error": str(e),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired. Please request a new token."
        )

    except TokenValidationError as e:
        logger.warning(
            "Token refresh failed - validation error",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "error": str(e),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    except EmbedTokenError as e:
        logger.error(
            "Failed to refresh embed token",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "error": str(e),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to refresh embed token"
        )


@router.get("/config", response_model=EmbedConfigResponse)
@require_permission(Permission.ANALYTICS_VIEW)
async def get_embed_config(
    request: Request,
    response: Response,
):
    """
    Get embed configuration for frontend initialization.

    Returns:
    - Superset URL
    - Allowed dashboards for tenant
    - Session refresh interval
    - CSP frame ancestors
    """
    tenant_ctx = get_tenant_context(request)

    superset_url = os.getenv("SUPERSET_EMBED_URL", "https://analytics.example.com")
    refresh_interval_minutes = int(os.getenv("EMBED_TOKEN_REFRESH_INTERVAL_MINUTES", "55"))

    # Use tenant-aware dashboard access rules so frontend receives
    # real dashboards available for this user and plan.
    access_service = DashboardAccessService(
        tenant_id=tenant_ctx.tenant_id,
        roles=tenant_ctx.roles,
        billing_tier=tenant_ctx.billing_tier,
    )
    allowed_dashboards = access_service.get_allowed_dashboards()

    # Add CSP headers
    add_embed_csp_headers(response)

    logger.info(
        "Returning embed config",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
        }
    )

    return EmbedConfigResponse(
        superset_url=superset_url,
        allowed_dashboards=allowed_dashboards,
        session_refresh_interval_ms=refresh_interval_minutes * 60 * 1000,
        csp_frame_ancestors=["self", "https://admin.shopify.com", "https://*.myshopify.com"],
    )




@router.get("/health/readiness", response_model=EmbedReadinessResponse)
async def embed_readiness(response: Response):
    """
    Readiness check for embed service.

    Stricter than /health: validates all configuration required by frontend
    bootstrap flow before calling authenticated embed endpoints.
    """
    jwt_secret_configured = bool(os.getenv("SUPERSET_JWT_SECRET"))
    superset_url = os.getenv("SUPERSET_EMBED_URL", "")
    allowed_dashboards = os.getenv("ALLOWED_EMBED_DASHBOARDS", "")

    superset_url_configured = bool(superset_url.strip())
    allowed_dashboards_configured = bool(
        [d.strip() for d in allowed_dashboards.split(",") if d.strip()]
    )

    add_embed_csp_headers(response)

    if not jwt_secret_configured:
        return EmbedReadinessResponse(
            status="not_ready",
            embed_configured=False,
            superset_url_configured=superset_url_configured,
            allowed_dashboards_configured=allowed_dashboards_configured,
            message="SUPERSET_JWT_SECRET not configured",
        )

    if not superset_url_configured:
        return EmbedReadinessResponse(
            status="not_ready",
            embed_configured=True,
            superset_url_configured=False,
            allowed_dashboards_configured=allowed_dashboards_configured,
            message="SUPERSET_EMBED_URL not configured",
        )

    if not allowed_dashboards_configured:
        return EmbedReadinessResponse(
            status="not_ready",
            embed_configured=True,
            superset_url_configured=True,
            allowed_dashboards_configured=False,
            message="ALLOWED_EMBED_DASHBOARDS not configured",
        )

    return EmbedReadinessResponse(
        status="ready",
        embed_configured=True,
        superset_url_configured=True,
        allowed_dashboards_configured=allowed_dashboards_configured,
        message=(
            "ALLOWED_EMBED_DASHBOARDS not configured (using tenant defaults)"
            if not allowed_dashboards_configured
            else None
        ),
    )


@router.get("/health")
async def embed_health(response: Response):
    """
    Health check for embed service.

    Verifies that SUPERSET_JWT_SECRET is configured.
    Does not require authentication.
    """
    jwt_secret_configured = bool(os.getenv("SUPERSET_JWT_SECRET"))
    superset_url = os.getenv("SUPERSET_EMBED_URL", "")

    # Add CSP headers even for health check
    add_embed_csp_headers(response)

    if not jwt_secret_configured:
        return {
            "status": "unhealthy",
            "embed_configured": False,
            "message": "SUPERSET_JWT_SECRET not configured",
        }

    return {
        "status": "healthy",
        "embed_configured": True,
        "superset_url_configured": bool(superset_url),
    }
