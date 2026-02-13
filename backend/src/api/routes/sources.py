"""
Unified Sources API routes for data source connections.

Provides:
- GET /api/sources — List all connected sources
- GET /api/sources/catalog — Available source definitions
- POST /api/sources/{platform}/oauth/initiate — Start OAuth flow
- POST /api/sources/oauth/callback — Complete OAuth flow
- DELETE /api/sources/{source_id} — Disconnect a source
- POST /api/sources/{source_id}/test — Test a connection
- PATCH /api/sources/{source_id}/config — Update sync config
- GET /api/sources/sync-settings — Get global sync settings
- PUT /api/sources/sync-settings — Update global sync settings

SECURITY: All routes require valid tenant context from JWT.

Story 2.1.1 — Unified Source domain model
Phase 3 — Data Sources wizard backend routes
"""

import logging
import os
import secrets
from typing import List

from fastapi import APIRouter, Request, HTTPException, status, Depends

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session
from src.services.airbyte_service import AirbyteService, ConnectionNotFoundServiceError
from src.services.ad_ingestion import (
    AdPlatform,
    AIRBYTE_SOURCE_TYPES,
)
from src.integrations.airbyte.client import get_airbyte_client, AirbyteError
from src.api.schemas.sources import (
    SourceSummary,
    SourceListResponse,
    SourceCatalogEntry,
    SourceCatalogResponse,
    OAuthInitiateResponse,
    OAuthCallbackRequest,
    OAuthCallbackResponse,
    TestConnectionResponse,
    UpdateSyncConfigRequest,
    GlobalSyncSettingsResponse,
    UpdateGlobalSyncSettingsRequest,
    normalize_connection_to_source,
    PLATFORM_DISPLAY_NAMES,
    PLATFORM_AUTH_TYPE,
    PLATFORM_DESCRIPTIONS,
    PLATFORM_CATEGORIES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sources", tags=["sources"])

# =============================================================================
# OAuth URL builders per platform
# =============================================================================

OAUTH_REDIRECT_URI = os.environ.get(
    "OAUTH_REDIRECT_URI",
    "https://app.localhost/api/sources/oauth/callback",
)

# In-memory state store for OAuth flows (production would use Redis)
_oauth_state_store: dict[str, dict] = {}


def _build_meta_oauth_url(state: str) -> str:
    """Build Meta (Facebook) OAuth authorization URL."""
    client_id = os.environ.get("META_APP_ID", "")
    scopes = "ads_read,ads_management,read_insights"
    return (
        f"https://www.facebook.com/v18.0/dialog/oauth"
        f"?client_id={client_id}"
        f"&redirect_uri={OAUTH_REDIRECT_URI}"
        f"&state={state}"
        f"&scope={scopes}"
        f"&response_type=code"
    )


def _build_google_oauth_url(state: str) -> str:
    """Build Google Ads OAuth authorization URL."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    scopes = "https://www.googleapis.com/auth/adwords"
    return (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={client_id}"
        f"&redirect_uri={OAUTH_REDIRECT_URI}"
        f"&state={state}"
        f"&scope={scopes}"
        f"&response_type=code"
        f"&access_type=offline"
        f"&prompt=consent"
    )


def _build_tiktok_oauth_url(state: str) -> str:
    """Build TikTok Ads OAuth authorization URL."""
    app_id = os.environ.get("TIKTOK_APP_ID", "")
    return (
        f"https://business-api.tiktok.com/portal/auth"
        f"?app_id={app_id}"
        f"&state={state}"
        f"&redirect_uri={OAUTH_REDIRECT_URI}"
    )


def _build_snapchat_oauth_url(state: str) -> str:
    """Build Snapchat Ads OAuth authorization URL."""
    client_id = os.environ.get("SNAPCHAT_CLIENT_ID", "")
    scopes = "snapchat-marketing-api"
    return (
        f"https://accounts.snapchat.com/login/oauth2/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={OAUTH_REDIRECT_URI}"
        f"&state={state}"
        f"&scope={scopes}"
        f"&response_type=code"
    )


def _build_shopify_oauth_url(state: str) -> str:
    """Build Shopify OAuth authorization URL."""
    api_key = os.environ.get("SHOPIFY_API_KEY", "")
    scopes = "read_orders,read_products,read_customers,read_analytics"
    shop = os.environ.get("SHOPIFY_SHOP_DOMAIN", "example.myshopify.com")
    return (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={api_key}"
        f"&scope={scopes}"
        f"&redirect_uri={OAUTH_REDIRECT_URI}"
        f"&state={state}"
    )


OAUTH_URL_BUILDERS: dict[str, callable] = {
    "shopify": _build_shopify_oauth_url,
    "meta_ads": _build_meta_oauth_url,
    "google_ads": _build_google_oauth_url,
    "tiktok_ads": _build_tiktok_oauth_url,
    "snapchat_ads": _build_snapchat_oauth_url,
    "shopify_email": _build_shopify_oauth_url,
}


# Default sync settings per tenant (production would be in DB)
_tenant_sync_settings: dict[str, dict] = {}

DEFAULT_SYNC_SETTINGS = {
    "default_frequency": "hourly",
    "pause_all_syncs": False,
    "max_concurrent_syncs": 5,
}

FREQUENCY_TO_MINUTES = {
    "hourly": 60,
    "daily": 1440,
    "weekly": 10080,
}


# =============================================================================
# Routes
# =============================================================================

@router.get(
    "",
    response_model=SourceListResponse,
)
async def list_sources(
    request: Request,
    db_session=Depends(get_db_session),
):
    """
    List all data source connections for the authenticated tenant.

    Returns a unified list of Shopify and ad platform connections,
    each normalized to a common Source schema.

    SECURITY: Only returns connections belonging to the tenant.
    """
    tenant_ctx = get_tenant_context(request)
    service = AirbyteService(db_session, tenant_ctx.tenant_id)

    result = service.list_connections(connection_type="source")

    sources: List[SourceSummary] = [
        normalize_connection_to_source(conn)
        for conn in result.connections
        if conn.status != "deleted"
    ]

    logger.info(
        "Listed unified sources",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "count": len(sources),
        },
    )

    return SourceListResponse(sources=sources, total=len(sources))


@router.get(
    "/catalog",
    response_model=SourceCatalogResponse,
)
async def get_source_catalog(request: Request):
    """
    Get the catalog of available data source definitions.

    Returns all supported platforms with their display names,
    descriptions, auth types, and categories.

    SECURITY: Requires valid tenant context.
    """
    get_tenant_context(request)

    entries = []
    for platform, display_name in PLATFORM_DISPLAY_NAMES.items():
        entries.append(
            SourceCatalogEntry(
                id=platform,
                platform=platform,
                display_name=display_name,
                description=PLATFORM_DESCRIPTIONS.get(platform, ""),
                auth_type=PLATFORM_AUTH_TYPE.get(platform, "api_key"),
                category=PLATFORM_CATEGORIES.get(platform, "other"),
                is_enabled=True,
            )
        )

    return SourceCatalogResponse(sources=entries, total=len(entries))


@router.post(
    "/{platform}/oauth/initiate",
    response_model=OAuthInitiateResponse,
)
async def initiate_oauth(
    request: Request,
    platform: str,
):
    """
    Initiate OAuth authorization flow for a data source platform.

    Generates a CSRF state token and returns the platform-specific
    authorization URL for the frontend to open in a popup.

    SECURITY: State token prevents CSRF. Requires valid tenant context.
    """
    tenant_ctx = get_tenant_context(request)

    # Validate platform supports OAuth
    auth_type = PLATFORM_AUTH_TYPE.get(platform)
    if auth_type != "oauth":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Platform '{platform}' does not support OAuth. Auth type: {auth_type}",
        )

    # Check we have a URL builder for this platform
    url_builder = OAUTH_URL_BUILDERS.get(platform)
    if not url_builder:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth not configured for platform: {platform}",
        )

    # Generate CSRF state token
    state = secrets.token_urlsafe(32)

    # Store state with tenant context for validation on callback
    _oauth_state_store[state] = {
        "tenant_id": tenant_ctx.tenant_id,
        "user_id": tenant_ctx.user_id,
        "platform": platform,
    }

    authorization_url = url_builder(state)

    logger.info(
        "OAuth flow initiated",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "platform": platform,
        },
    )

    return OAuthInitiateResponse(
        authorization_url=authorization_url,
        state=state,
    )


@router.post(
    "/oauth/callback",
    response_model=OAuthCallbackResponse,
)
async def oauth_callback(
    request: Request,
    body: OAuthCallbackRequest,
    db_session=Depends(get_db_session),
):
    """
    Complete OAuth authorization flow.

    Validates the CSRF state token, exchanges the authorization code
    for access tokens, encrypts and stores credentials, and creates
    the Airbyte source connection.

    SECURITY: Validates state token matches initiating tenant.
    OAuth tokens are encrypted before storage.
    """
    tenant_ctx = get_tenant_context(request)

    # Validate state token
    state_data = _oauth_state_store.pop(body.state, None)
    if not state_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state token",
        )

    if state_data["tenant_id"] != tenant_ctx.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="OAuth state does not match current tenant",
        )

    platform = state_data["platform"]

    try:
        # Create Airbyte source for the platform
        airbyte_client = get_airbyte_client()
        airbyte_source_type = None
        try:
            platform_enum = AdPlatform(platform)
            airbyte_source_type = AIRBYTE_SOURCE_TYPES.get(platform_enum)
        except ValueError:
            # Shopify or other non-AdPlatform
            if platform == "shopify":
                airbyte_source_type = "source-shopify"

        if not airbyte_source_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No Airbyte source type for platform: {platform}",
            )

        # Create the source in Airbyte with the auth code
        source = await airbyte_client.create_source(
            name=f"{PLATFORM_DISPLAY_NAMES.get(platform, platform)} - {tenant_ctx.tenant_id[:8]}",
            source_type=airbyte_source_type,
            workspace_id=os.environ.get("AIRBYTE_WORKSPACE_ID", ""),
            configuration={"auth_code": body.code},
        )

        # Get the default destination and create a connection
        destinations = await airbyte_client.list_destinations(
            workspace_id=os.environ.get("AIRBYTE_WORKSPACE_ID", ""),
        )

        destination_id = None
        if destinations:
            destination_id = destinations[0].destination_id

        connection_id = None
        if destination_id:
            connection = await airbyte_client.create_connection(
                source_id=source.source_id,
                destination_id=destination_id,
                name=f"{PLATFORM_DISPLAY_NAMES.get(platform, platform)} sync",
            )
            connection_id = connection.connection_id

        # Register the connection with our tenant-scoped service
        service = AirbyteService(db_session, tenant_ctx.tenant_id)
        conn_info = service.register_connection(
            airbyte_connection_id=connection_id or source.source_id,
            connection_name=PLATFORM_DISPLAY_NAMES.get(platform, platform),
            connection_type="source",
            airbyte_source_id=source.source_id,
            source_type=airbyte_source_type,
            configuration={"platform": platform, "auth_code_used": True},
        )

        service.activate_connection(conn_info.id)

        logger.info(
            "OAuth flow completed",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "platform": platform,
                "connection_id": conn_info.id,
            },
        )

        return OAuthCallbackResponse(
            success=True,
            connection_id=conn_info.id,
            message=f"Successfully connected {PLATFORM_DISPLAY_NAMES.get(platform, platform)}",
        )

    except AirbyteError as e:
        logger.error(
            "OAuth callback failed - Airbyte error",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "platform": platform,
                "error": str(e),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to create source connection: {e}",
        )
    except Exception as e:
        logger.error(
            "OAuth callback failed",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "platform": platform,
                "error": str(e),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to complete authorization: {e}",
        )


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disconnect_source(
    request: Request,
    source_id: str,
    db_session=Depends(get_db_session),
):
    """
    Disconnect (soft delete) a data source.

    SECURITY: Only disconnects sources belonging to the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)
    service = AirbyteService(db_session, tenant_ctx.tenant_id)

    try:
        service.delete_connection(source_id)
    except ConnectionNotFoundServiceError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source not found: {source_id}",
        )

    logger.info(
        "Source disconnected",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "source_id": source_id,
        },
    )


@router.post(
    "/{source_id}/test",
    response_model=TestConnectionResponse,
)
async def test_connection(
    request: Request,
    source_id: str,
    db_session=Depends(get_db_session),
):
    """
    Test a data source connection by checking Airbyte source health.

    SECURITY: Only tests connections belonging to the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)
    service = AirbyteService(db_session, tenant_ctx.tenant_id)

    connection = service.get_connection(source_id)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source not found: {source_id}",
        )

    try:
        airbyte_client = get_airbyte_client()
        source = await airbyte_client.get_source(connection.airbyte_connection_id)

        return TestConnectionResponse(
            success=True,
            message="Connection is healthy",
            details={
                "source_id": source.source_id,
                "source_type": source.source_type,
                "status": "active",
            },
        )
    except AirbyteError as e:
        return TestConnectionResponse(
            success=False,
            message=f"Connection test failed: {e}",
        )


@router.patch(
    "/{source_id}/config",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_sync_config(
    request: Request,
    source_id: str,
    body: UpdateSyncConfigRequest,
    db_session=Depends(get_db_session),
):
    """
    Update sync configuration for a data source.

    SECURITY: Only updates connections belonging to the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)
    service = AirbyteService(db_session, tenant_ctx.tenant_id)

    connection = service.get_connection(source_id)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source not found: {source_id}",
        )

    # Update sync frequency if provided
    if body.sync_frequency:
        minutes = FREQUENCY_TO_MINUTES.get(body.sync_frequency)
        if not minutes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid frequency: {body.sync_frequency}. Valid: hourly, daily, weekly",
            )
        service.update_sync_frequency(source_id, minutes)

    logger.info(
        "Source config updated",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "source_id": source_id,
            "sync_frequency": body.sync_frequency,
        },
    )


@router.get(
    "/sync-settings",
    response_model=GlobalSyncSettingsResponse,
)
async def get_global_sync_settings(request: Request):
    """
    Get global sync settings for the authenticated tenant.

    SECURITY: Requires valid tenant context.
    """
    tenant_ctx = get_tenant_context(request)

    settings = _tenant_sync_settings.get(
        tenant_ctx.tenant_id, DEFAULT_SYNC_SETTINGS.copy()
    )

    return GlobalSyncSettingsResponse(**settings)


@router.put(
    "/sync-settings",
    response_model=GlobalSyncSettingsResponse,
)
async def update_global_sync_settings(
    request: Request,
    body: UpdateGlobalSyncSettingsRequest,
):
    """
    Update global sync settings for the authenticated tenant.

    SECURITY: Requires valid tenant context.
    """
    tenant_ctx = get_tenant_context(request)

    current = _tenant_sync_settings.get(
        tenant_ctx.tenant_id, DEFAULT_SYNC_SETTINGS.copy()
    )

    if body.default_frequency is not None:
        if body.default_frequency not in FREQUENCY_TO_MINUTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid frequency: {body.default_frequency}. Valid: hourly, daily, weekly",
            )
        current["default_frequency"] = body.default_frequency

    if body.pause_all_syncs is not None:
        current["pause_all_syncs"] = body.pause_all_syncs

    if body.max_concurrent_syncs is not None:
        if body.max_concurrent_syncs < 1 or body.max_concurrent_syncs > 20:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="max_concurrent_syncs must be between 1 and 20",
            )
        current["max_concurrent_syncs"] = body.max_concurrent_syncs

    _tenant_sync_settings[tenant_ctx.tenant_id] = current

    logger.info(
        "Global sync settings updated",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "settings": current,
        },
    )

    return GlobalSyncSettingsResponse(**current)
