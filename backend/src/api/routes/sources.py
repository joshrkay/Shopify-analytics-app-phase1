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

import json
import logging
import os
import secrets
from typing import List, Optional

from fastapi import APIRouter, Request, HTTPException, status, Depends

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session
from src.services.airbyte_service import (
    AirbyteService,
    ConnectionNotFoundServiceError,
    DuplicateConnectionError,
)
from src.services.ad_ingestion import (
    AdPlatform,
    AIRBYTE_SOURCE_TYPES,
)
from src.integrations.airbyte.client import get_airbyte_client, AirbyteError
from src.integrations.airbyte.models import (
    SourceCreationRequest,
    ConnectionCreationRequest,
)
from src.api.schemas.sources import (
    SourceSummary,
    SourceListResponse,
    SourceCatalogEntry,
    SourceCatalogResponse,
    OAuthInitiateRequest,
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

# OAuth state TTL in seconds (10 minutes)
OAUTH_STATE_TTL_SECONDS = 600

# Sync settings key prefix for Redis
_SYNC_SETTINGS_REDIS_PREFIX = "sync_settings:"
_SYNC_SETTINGS_TTL_SECONDS = 86400  # 24 hours


# =============================================================================
# Redis-backed OAuth state store with in-memory fallback
# =============================================================================

def _get_redis_client():
    """Get the singleton RedisClient. Returns None if unavailable."""
    try:
        from src.entitlements.cache import RedisClient
        client = RedisClient()
        if client.available:
            return client
    except Exception:
        pass
    return None


# In-memory fallback when Redis is unavailable
_oauth_state_store_fallback: dict[str, dict] = {}


def _store_oauth_state(state: str, data: dict) -> None:
    """Store OAuth state in Redis (with TTL) or in-memory fallback."""
    redis = _get_redis_client()
    if redis:
        redis.set(f"oauth_state:{state}", json.dumps(data), OAUTH_STATE_TTL_SECONDS)
    else:
        _oauth_state_store_fallback[state] = data


def _pop_oauth_state(state: str) -> Optional[dict]:
    """Retrieve and delete OAuth state from Redis or in-memory fallback."""
    redis = _get_redis_client()
    if redis:
        raw = redis.get(f"oauth_state:{state}")
        if raw:
            redis.delete(f"oauth_state:{state}")
            return json.loads(raw)
        return None
    return _oauth_state_store_fallback.pop(state, None)


# =============================================================================
# DB-backed sync settings helpers
# =============================================================================

_GLOBAL_SETTINGS_CONNECTION_NAME = "__global_sync_settings__"

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


def _get_sync_settings_from_db(service: AirbyteService) -> dict:
    """Load global sync settings from the DB via a sentinel connection record."""
    result = service.list_connections(
        connection_type="source",
    )
    for conn in result.connections:
        if conn.connection_name == _GLOBAL_SETTINGS_CONNECTION_NAME:
            # Settings stored in the sync_frequency_minutes field as JSON
            if conn.sync_frequency_minutes:
                try:
                    return json.loads(conn.sync_frequency_minutes)
                except (json.JSONDecodeError, TypeError):
                    pass
            break
    return DEFAULT_SYNC_SETTINGS.copy()


def _save_sync_settings_to_db(service: AirbyteService, settings: dict) -> None:
    """Persist global sync settings to the DB via a sentinel connection record."""
    result = service.list_connections(connection_type="source")
    sentinel_id = None
    for conn in result.connections:
        if conn.connection_name == _GLOBAL_SETTINGS_CONNECTION_NAME:
            sentinel_id = conn.id
            break

    settings_json = json.dumps(settings)

    if sentinel_id:
        # Update existing sentinel record's sync_frequency_minutes field
        connection = service._repository.get_by_id(sentinel_id)
        if connection:
            connection.sync_frequency_minutes = settings_json
            service.db.commit()
    else:
        # Create sentinel connection to hold settings
        service.register_connection(
            airbyte_connection_id=f"settings-{service.tenant_id[:16]}",
            connection_name=_GLOBAL_SETTINGS_CONNECTION_NAME,
            connection_type="source",
            source_type="settings",
            configuration={"type": "global_sync_settings"},
            sync_frequency_minutes=settings_json,
        )


# =============================================================================
# OAuth URL builders
# =============================================================================

def _build_meta_oauth_url(state: str, **kwargs) -> str:
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


def _build_google_oauth_url(state: str, **kwargs) -> str:
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


def _build_tiktok_oauth_url(state: str, **kwargs) -> str:
    """Build TikTok Ads OAuth authorization URL."""
    app_id = os.environ.get("TIKTOK_APP_ID", "")
    return (
        f"https://business-api.tiktok.com/portal/auth"
        f"?app_id={app_id}"
        f"&state={state}"
        f"&redirect_uri={OAUTH_REDIRECT_URI}"
    )


def _build_snapchat_oauth_url(state: str, **kwargs) -> str:
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


def _build_shopify_oauth_url(state: str, shop_domain: Optional[str] = None, **kwargs) -> str:
    """Build Shopify OAuth authorization URL.

    Args:
        state: CSRF state token.
        shop_domain: The merchant's *.myshopify.com domain.
            Required for multi-tenant Shopify OAuth.
    """
    api_key = os.environ.get("SHOPIFY_API_KEY", "")
    scopes = "read_orders,read_products,read_customers,read_analytics"
    if not shop_domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="shop_domain is required for Shopify OAuth",
        )
    return (
        f"https://{shop_domain}/admin/oauth/authorize"
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
        and conn.connection_name != _GLOBAL_SETTINGS_CONNECTION_NAME
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
    body: Optional[OAuthInitiateRequest] = None,
):
    """
    Initiate OAuth authorization flow for a data source platform.

    Generates a CSRF state token and returns the platform-specific
    authorization URL for the frontend to open in a popup.

    For Shopify, the request body must include ``shop_domain``.

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

    # Extract shop_domain for Shopify platforms
    shop_domain = body.shop_domain if body else None

    # Generate CSRF state token
    state = secrets.token_urlsafe(32)

    # Store state with tenant context for validation on callback
    state_data = {
        "tenant_id": tenant_ctx.tenant_id,
        "user_id": tenant_ctx.user_id,
        "platform": platform,
    }
    if shop_domain:
        state_data["shop_domain"] = shop_domain
    _store_oauth_state(state, state_data)

    authorization_url = url_builder(state, shop_domain=shop_domain)

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
    state_data = _pop_oauth_state(body.state)
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
    shop_domain = state_data.get("shop_domain")

    try:
        # Create Airbyte source for the platform
        airbyte_client = get_airbyte_client()
        airbyte_source_type = None
        try:
            platform_enum = AdPlatform(platform)
            airbyte_source_type = AIRBYTE_SOURCE_TYPES.get(platform_enum)
        except ValueError:
            # Shopify or other non-AdPlatform
            if platform in ("shopify", "shopify_email"):
                airbyte_source_type = "source-shopify"

        if not airbyte_source_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No Airbyte source type for platform: {platform}",
            )

        # Build source configuration
        source_config: dict = {"auth_code": body.code}
        if shop_domain:
            source_config["shop"] = shop_domain

        # Create the source in Airbyte using SourceCreationRequest
        source_request = SourceCreationRequest(
            name=f"{PLATFORM_DISPLAY_NAMES.get(platform, platform)} - {tenant_ctx.tenant_id[:8]}",
            source_type=airbyte_source_type,
            configuration=source_config,
        )
        source = await airbyte_client.create_source(source_request)

        # Get the default destination and create a connection
        destinations = await airbyte_client.list_destinations()

        destination_id = None
        if destinations:
            destination_id = destinations[0].destination_id

        connection_id = None
        if destination_id:
            conn_request = ConnectionCreationRequest(
                source_id=source.source_id,
                destination_id=destination_id,
                name=f"{PLATFORM_DISPLAY_NAMES.get(platform, platform)} sync",
            )
            connection = await airbyte_client.create_connection(conn_request)
            connection_id = connection.connection_id

        if not connection_id:
            logger.error(
                "No Airbyte destination available — cannot create connection pipeline. "
                "The Airbyte workspace may not be fully configured.",
                extra={
                    "tenant_id": tenant_ctx.tenant_id,
                    "platform": platform,
                    "source_id": source.source_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Data pipeline could not be established: no destination configured "
                    "in the sync workspace. Please contact support."
                ),
            )

        # Build configuration for tenant registration
        reg_config: dict = {"platform": platform, "auth_code_used": True}
        if shop_domain:
            reg_config["shop_domain"] = shop_domain

        # Register the connection with our tenant-scoped service.
        # IMPORTANT: airbyte_connection_id must be the actual Airbyte
        # pipeline/connection ID — never a source ID — because downstream
        # sync operations call POST /connections/{id}/sync with this value.
        service = AirbyteService(db_session, tenant_ctx.tenant_id)
        conn_info = service.register_connection(
            airbyte_connection_id=connection_id,
            connection_name=PLATFORM_DISPLAY_NAMES.get(platform, platform),
            connection_type="source",
            airbyte_source_id=source.source_id,
            source_type=airbyte_source_type,
            configuration=reg_config,
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

    except HTTPException:
        raise
    except DuplicateConnectionError as e:
        logger.warning(
            "OAuth callback rejected — duplicate connection",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "platform": platform,
                "error": str(e),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
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
            detail="Failed to create source connection via Airbyte",
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
            detail="Failed to complete authorization. Please try again.",
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
    Test a data source connection by running Airbyte's check_connection.

    Uses the airbyte_source_id (not the connection ID) to validate that
    the external platform credentials are still valid and reachable.

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

    # Resolve the Airbyte source ID for the check_connection call.
    # The connection record stores the airbyte_source_id separately from
    # the airbyte_connection_id (which is the pipeline ID).
    raw_conn = service._repository.get_by_id(source_id)
    airbyte_source_id = (
        raw_conn.airbyte_source_id if raw_conn else None
    ) or connection.airbyte_connection_id

    try:
        airbyte_client = get_airbyte_client()
        result = await airbyte_client.check_source_connection(airbyte_source_id)

        check_status = result.get("status", "unknown")
        if check_status == "succeeded":
            return TestConnectionResponse(
                success=True,
                message="Connection is healthy",
                details={
                    "source_id": airbyte_source_id,
                    "status": "active",
                },
            )
        return TestConnectionResponse(
            success=False,
            message=result.get("message", "Connection check did not succeed"),
            details={"status": check_status},
        )
    except AirbyteError:
        return TestConnectionResponse(
            success=False,
            message="Connection test failed — unable to reach source",
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
async def get_global_sync_settings(
    request: Request,
    db_session=Depends(get_db_session),
):
    """
    Get global sync settings for the authenticated tenant.

    SECURITY: Requires valid tenant context.
    """
    tenant_ctx = get_tenant_context(request)
    service = AirbyteService(db_session, tenant_ctx.tenant_id)

    # Try Redis cache first
    redis = _get_redis_client()
    cache_key = f"{_SYNC_SETTINGS_REDIS_PREFIX}{tenant_ctx.tenant_id}"
    if redis:
        cached = redis.get(cache_key)
        if cached:
            try:
                return GlobalSyncSettingsResponse(**json.loads(cached))
            except (json.JSONDecodeError, TypeError):
                pass

    settings = _get_sync_settings_from_db(service)

    # Cache in Redis
    if redis:
        redis.set(cache_key, json.dumps(settings), _SYNC_SETTINGS_TTL_SECONDS)

    return GlobalSyncSettingsResponse(**settings)


@router.put(
    "/sync-settings",
    response_model=GlobalSyncSettingsResponse,
)
async def update_global_sync_settings(
    request: Request,
    body: UpdateGlobalSyncSettingsRequest,
    db_session=Depends(get_db_session),
):
    """
    Update global sync settings for the authenticated tenant.

    SECURITY: Requires valid tenant context.
    """
    tenant_ctx = get_tenant_context(request)
    service = AirbyteService(db_session, tenant_ctx.tenant_id)

    current = _get_sync_settings_from_db(service)

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

    _save_sync_settings_to_db(service, current)

    # Invalidate Redis cache
    redis = _get_redis_client()
    if redis:
        cache_key = f"{_SYNC_SETTINGS_REDIS_PREFIX}{tenant_ctx.tenant_id}"
        redis.set(cache_key, json.dumps(current), _SYNC_SETTINGS_TTL_SECONDS)

    logger.info(
        "Global sync settings updated",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "settings": current,
        },
    )

    return GlobalSyncSettingsResponse(**current)
