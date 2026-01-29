"""
Shopify ingestion API routes for setting up and managing Shopify data syncs.

SECURITY: All routes require valid tenant context from JWT.
Token validation is performed before any operations.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel, Field

from src.platform.tenant_context import get_tenant_context, TenantContext
from src.database.session import get_db_session
from src.services.shopify_ingestion import (
    ShopifyIngestionService,
    validate_shopify_token,
    setup_shopify_airbyte_source,
    ShopifyTokenValidationResult,
    AutomaticSetupResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/shopify-ingestion", tags=["shopify-ingestion"])


# =============================================================================
# Request/Response Models
# =============================================================================

class ValidateTokenRequest(BaseModel):
    """Request to validate a Shopify access token."""

    shop_domain: str = Field(
        ...,
        description="Shopify store domain (e.g., 'mystore.myshopify.com')",
        min_length=5,
        max_length=255,
    )
    access_token: str = Field(
        ...,
        description="Shopify access token to validate",
        min_length=10,
        max_length=500,
    )


class TokenValidationResponse(BaseModel):
    """Response from token validation."""

    valid: bool
    shop_domain: str
    shop_name: Optional[str] = None
    shop_email: Optional[str] = None
    currency: Optional[str] = None
    country_code: Optional[str] = None
    timezone: Optional[str] = None
    scopes: Optional[list] = None
    error_message: Optional[str] = None


class SetupIngestionRequest(BaseModel):
    """Request to set up Shopify ingestion."""

    shop_domain: str = Field(
        ...,
        description="Shopify store domain (e.g., 'mystore.myshopify.com')",
        min_length=5,
        max_length=255,
    )
    access_token: str = Field(
        ...,
        description="Shopify access token",
        min_length=10,
        max_length=500,
    )
    start_date: Optional[str] = Field(
        None,
        description="Start date for historical sync (ISO format, e.g., '2024-01-01')",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    trigger_initial_sync: bool = Field(
        True,
        description="Whether to trigger initial sync immediately",
    )


class SetupIngestionResponse(BaseModel):
    """Response from ingestion setup."""

    success: bool
    source_id: Optional[str] = None
    connection_id: Optional[str] = None
    internal_connection_id: Optional[str] = None
    error_message: Optional[str] = None


class IngestionStatusResponse(BaseModel):
    """Response with ingestion status."""

    connection_id: str
    connection_name: str
    status: str
    is_enabled: bool
    can_sync: bool
    last_sync_at: Optional[str] = None
    last_sync_status: Optional[str] = None


# =============================================================================
# Routes
# =============================================================================

@router.post(
    "/validate-token",
    response_model=TokenValidationResponse,
    status_code=status.HTTP_200_OK,
)
async def validate_token(
    request: Request,
    body: ValidateTokenRequest,
):
    """
    Validate a Shopify access token.

    This endpoint verifies that the provided access token is valid by making
    a test request to the Shopify GraphQL API. It returns shop information
    if the token is valid.

    SECURITY: Tokens are not stored by this endpoint. They are only validated.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Shopify token validation requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
            "shop_domain": body.shop_domain,
        },
    )

    result = await validate_shopify_token(
        shop_domain=body.shop_domain,
        access_token=body.access_token,
    )

    if not result.valid:
        logger.warning(
            "Shopify token validation failed",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "shop_domain": body.shop_domain,
                "error": result.error_message,
            },
        )

    return TokenValidationResponse(
        valid=result.valid,
        shop_domain=result.shop_domain,
        shop_name=result.shop_name,
        shop_email=result.shop_email,
        currency=result.currency,
        country_code=result.country_code,
        timezone=result.timezone,
        scopes=result.scopes,
        error_message=result.error_message,
    )


@router.post(
    "/setup",
    response_model=SetupIngestionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def setup_ingestion(
    request: Request,
    body: SetupIngestionRequest,
    db_session=Depends(get_db_session),
):
    """
    Set up Shopify data ingestion via Airbyte.

    This endpoint:
    1. Validates the Shopify access token
    2. Creates an Airbyte source for the Shopify store
    3. Creates an Airbyte connection to the data warehouse
    4. Registers the connection in our tracking system
    5. Optionally triggers an initial sync

    SECURITY:
    - Validates token before any operations
    - Access token is stored encrypted in Airbyte, not in our database
    - Tenant isolation is enforced
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Shopify ingestion setup requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
            "shop_domain": body.shop_domain,
        },
    )

    # Step 1: Validate token first
    validation_result = await validate_shopify_token(
        shop_domain=body.shop_domain,
        access_token=body.access_token,
    )

    if not validation_result.valid:
        logger.warning(
            "Shopify ingestion setup failed: invalid token",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "shop_domain": body.shop_domain,
                "error": validation_result.error_message,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid Shopify token: {validation_result.error_message}",
        )

    # Step 2: Set up Airbyte source and connection
    setup_result = await setup_shopify_airbyte_source(
        tenant_id=tenant_ctx.tenant_id,
        shop_domain=body.shop_domain,
        access_token=body.access_token,
        db_session=db_session,
        start_date=body.start_date,
        trigger_initial_sync=body.trigger_initial_sync,
    )

    if not setup_result.success:
        logger.error(
            "Shopify ingestion setup failed",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "shop_domain": body.shop_domain,
                "error": setup_result.error_message,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=setup_result.error_message,
        )

    logger.info(
        "Shopify ingestion setup completed",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "shop_domain": body.shop_domain,
            "source_id": setup_result.source_id,
            "connection_id": setup_result.connection_id,
        },
    )

    return SetupIngestionResponse(
        success=True,
        source_id=setup_result.source_id,
        connection_id=setup_result.connection_id,
        internal_connection_id=setup_result.internal_connection_id,
    )


@router.get(
    "/status/{connection_id}",
    response_model=IngestionStatusResponse,
)
async def get_ingestion_status(
    request: Request,
    connection_id: str,
    db_session=Depends(get_db_session),
):
    """
    Get the status of a Shopify ingestion connection.

    SECURITY: Only returns status for connections belonging to the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Shopify ingestion status requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "connection_id": connection_id,
        },
    )

    service = ShopifyIngestionService(db_session, tenant_ctx.tenant_id)
    status_info = service.get_sync_status(connection_id)

    if not status_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection not found: {connection_id}",
        )

    return IngestionStatusResponse(
        connection_id=status_info["connection_id"],
        connection_name=status_info["connection_name"],
        status=status_info["status"],
        is_enabled=status_info["is_enabled"],
        can_sync=status_info["can_sync"],
        last_sync_at=status_info["last_sync_at"],
        last_sync_status=status_info["last_sync_status"],
    )


@router.post(
    "/trigger-sync/{connection_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
async def trigger_sync(
    request: Request,
    connection_id: str,
    db_session=Depends(get_db_session),
):
    """
    Trigger a sync for an existing Shopify ingestion connection.

    SECURITY: Only triggers syncs for connections belonging to the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Shopify sync trigger requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "connection_id": connection_id,
        },
    )

    service = ShopifyIngestionService(db_session, tenant_ctx.tenant_id)

    try:
        result = await service.trigger_incremental_sync(
            connection_id=connection_id,
            wait_for_completion=False,
        )

        return {
            "success": result.success,
            "job_id": result.job_id,
            "connection_id": result.connection_id,
            "synced_at": result.synced_at.isoformat() if result.synced_at else None,
        }

    except Exception as e:
        logger.error(
            "Shopify sync trigger failed",
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
