"""
Ad platform ingestion API routes for connecting and syncing ad platform data via Airbyte.

SECURITY: All routes require valid tenant context from JWT.
Uses AdIngestionService for tenant-scoped connection and sync operations.
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session
from src.services.ad_ingestion import (
    AdIngestionService,
    AdPlatform,
    AIRBYTE_SOURCE_TYPES,
    AccountNotFoundError,
    SyncError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ad-platform-ingestion", tags=["ad-platform-ingestion"])


# =============================================================================
# Response Models
# =============================================================================

class PlatformInfo(BaseModel):
    """Supported ad platform info."""
    id: str
    display_name: str
    airbyte_source_type: str


class ConnectionSummary(BaseModel):
    """Summary of an ad platform connection."""
    id: str
    platform: str
    account_id: str
    account_name: str
    connection_id: str
    airbyte_connection_id: str
    status: str
    is_enabled: bool
    last_sync_at: Optional[str] = None
    last_sync_status: Optional[str] = None


class ConnectionStatusResponse(BaseModel):
    """Sync/health status for a connection."""
    connection_id: str
    status: str
    is_enabled: bool
    is_active: bool
    can_sync: bool
    last_sync_at: Optional[str] = None
    last_sync_status: Optional[str] = None


class TriggerSyncResponse(BaseModel):
    """Response from triggering a sync."""
    success: bool
    job_id: str
    connection_id: str
    status: str


# =============================================================================
# Routes
# =============================================================================

@router.get(
    "/platforms",
    response_model=List[PlatformInfo],
)
async def list_platforms(request: Request):
    """
    List supported ad platforms for ingestion via Airbyte.

    SECURITY: Requires valid tenant context.
    """
    get_tenant_context(request)
    platforms = [
        PlatformInfo(
            id=p.value,
            display_name=p.name.replace("_", " ").title(),
            airbyte_source_type=AIRBYTE_SOURCE_TYPES[p],
        )
        for p in AdPlatform
    ]
    return platforms


@router.get(
    "/connections",
    response_model=List[ConnectionSummary],
)
async def list_connections(
    request: Request,
    platform: Optional[str] = None,
    is_enabled: Optional[bool] = None,
    db_session=Depends(get_db_session),
):
    """
    List ad platform connections for the authenticated tenant.

    SECURITY: Only returns connections belonging to the tenant.
    """
    tenant_ctx = get_tenant_context(request)
    service = AdIngestionService(db_session, tenant_ctx.tenant_id)
    platform_enum = None
    if platform:
        try:
            platform_enum = AdPlatform(platform)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid platform: {platform}. Valid: {[p.value for p in AdPlatform]}",
            )
    accounts = service.list_ad_accounts(platform=platform_enum, is_enabled=is_enabled)
    return [
        ConnectionSummary(
            id=a.id,
            platform=a.platform,
            account_id=a.account_id,
            account_name=a.account_name,
            connection_id=a.connection_id,
            airbyte_connection_id=a.airbyte_connection_id,
            status=a.status,
            is_enabled=a.is_enabled,
            last_sync_at=a.last_sync_at.isoformat() if a.last_sync_at else None,
            last_sync_status=a.last_sync_status,
        )
        for a in accounts
    ]


@router.get(
    "/connections/{connection_id}",
    response_model=ConnectionSummary,
)
async def get_connection(
    request: Request,
    connection_id: str,
    db_session=Depends(get_db_session),
):
    """
    Get a single ad platform connection by ID.

    SECURITY: Only returns connection if it belongs to the tenant.
    """
    tenant_ctx = get_tenant_context(request)
    service = AdIngestionService(db_session, tenant_ctx.tenant_id)
    account = service.get_ad_account(connection_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection not found: {connection_id}",
        )
    return ConnectionSummary(
        id=account.id,
        platform=account.platform,
        account_id=account.account_id,
        account_name=account.account_name,
        connection_id=account.connection_id,
        airbyte_connection_id=account.airbyte_connection_id,
        status=account.status,
        is_enabled=account.is_enabled,
        last_sync_at=account.last_sync_at.isoformat() if account.last_sync_at else None,
        last_sync_status=account.last_sync_status,
    )


@router.get(
    "/connections/{connection_id}/status",
    response_model=ConnectionStatusResponse,
)
async def get_connection_status(
    request: Request,
    connection_id: str,
    db_session=Depends(get_db_session),
):
    """
    Get sync health/status for an ad platform connection.

    SECURITY: Only returns status for connections belonging to the tenant.
    """
    tenant_ctx = get_tenant_context(request)
    service = AdIngestionService(db_session, tenant_ctx.tenant_id)
    try:
        health = service.get_sync_health(connection_id)
        return ConnectionStatusResponse(**health)
    except AccountNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection not found: {connection_id}",
        )


class AccountInfo(BaseModel):
    """Discoverable ad account info."""
    id: str
    account_id: str
    account_name: str
    platform: str
    is_enabled: bool


class AccountListResponse(BaseModel):
    """Response for listing available accounts."""
    accounts: List[AccountInfo]


class UpdateAccountsRequest(BaseModel):
    """Request body for updating selected accounts."""
    account_ids: List[str]


@router.get(
    "/connections/{connection_id}/accounts",
    response_model=AccountListResponse,
)
async def list_available_accounts(
    request: Request,
    connection_id: str,
    db_session=Depends(get_db_session),
):
    """
    List discoverable ad accounts for a connection after OAuth.

    Returns all accounts the authenticated user has access to on
    the ad platform, so they can select which ones to sync.

    SECURITY: Only returns accounts for connections belonging to the tenant.
    """
    tenant_ctx = get_tenant_context(request)
    service = AdIngestionService(db_session, tenant_ctx.tenant_id)

    account = service.get_ad_account(connection_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection not found: {connection_id}",
        )

    # List all ad accounts for the same platform
    try:
        platform_enum = AdPlatform(account.platform)
    except ValueError:
        logger.error(
            "Invalid platform value found for connection",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "connection_id": connection_id,
                "platform": account.platform,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error: invalid platform '{account.platform}' for connection",
        )

    all_accounts = service.list_ad_accounts(platform=platform_enum)

    accounts = [
        AccountInfo(
            id=a.id,
            account_id=a.account_id,
            account_name=a.account_name,
            platform=a.platform,
            is_enabled=a.is_enabled,
        )
        for a in all_accounts
    ]

    logger.info(
        "Listed available accounts",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "connection_id": connection_id,
            "count": len(accounts),
        },
    )

    return AccountListResponse(accounts=accounts)


@router.put(
    "/connections/{connection_id}/accounts",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_selected_accounts(
    request: Request,
    connection_id: str,
    body: UpdateAccountsRequest,
    db_session=Depends(get_db_session),
):
    """
    Update which ad accounts are selected for syncing.

    Enables the specified accounts and disables all others.

    SECURITY: Only modifies accounts belonging to the tenant.
    """
    tenant_ctx = get_tenant_context(request)
    service = AdIngestionService(db_session, tenant_ctx.tenant_id)

    # Verify connection exists
    account = service.get_ad_account(connection_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection not found: {connection_id}",
        )

    # Get all accounts for this platform
    try:
        platform_enum = AdPlatform(account.platform)
    except ValueError:
        logger.error(
            "Invalid platform value found for connection",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "connection_id": connection_id,
                "platform": account.platform,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error: invalid platform '{account.platform}' for connection",
        )

    all_accounts = service.list_ad_accounts(platform=platform_enum)

    # Enable selected, disable unselected
    for acct in all_accounts:
        if acct.id in body.account_ids:
            service.enable_ad_account(acct.id)
        else:
            service.disable_ad_account(acct.id)

    logger.info(
        "Updated selected accounts",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "connection_id": connection_id,
            "selected_count": len(body.account_ids),
        },
    )


@router.post(
    "/connections/{connection_id}/trigger-sync",
    response_model=TriggerSyncResponse,
    status_code=status.HTTP_200_OK,
)
async def trigger_sync(
    request: Request,
    connection_id: str,
    db_session=Depends(get_db_session),
):
    """
    Trigger a sync for an ad platform connection.

    SECURITY: Only triggers syncs for connections belonging to the tenant.
    """
    tenant_ctx = get_tenant_context(request)
    service = AdIngestionService(db_session, tenant_ctx.tenant_id)
    try:
        result = await service.trigger_sync(connection_id)
        return TriggerSyncResponse(
            success=True,
            job_id=result.job_id,
            connection_id=result.connection_id,
            status=result.status,
        )
    except AccountNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection not found: {connection_id}",
        )
    except SyncError as e:
        logger.warning(
            "Ad platform sync trigger failed",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "connection_id": connection_id,
                "error": str(e),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
