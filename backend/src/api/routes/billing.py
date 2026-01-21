"""
Billing API routes for subscription management.

All routes require JWT authentication with tenant context.
"""

import os
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field

from src.platform.tenant_context import get_tenant_context, TenantContext
from src.services.billing_service import (
    BillingService,
    BillingServiceError,
    PlanNotFoundError,
    StoreNotFoundError,
    SubscriptionError
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])


# Request/Response models
class CreateCheckoutRequest(BaseModel):
    """Request to create a checkout URL."""
    plan_id: str = Field(..., description="Plan ID to subscribe to")
    return_url: Optional[str] = Field(None, description="URL to redirect after checkout")
    test_mode: Optional[bool] = Field(False, description="Create test charge (no real money)")


class CheckoutResponse(BaseModel):
    """Response with checkout URL."""
    checkout_url: str
    subscription_id: str
    shopify_subscription_id: Optional[str] = None
    success: bool


class SubscriptionResponse(BaseModel):
    """Current subscription information."""
    subscription_id: Optional[str]
    plan_id: str
    plan_name: str
    status: str
    is_active: bool
    current_period_end: Optional[str]
    trial_end: Optional[str]
    can_access_features: bool
    downgraded_reason: Optional[str] = None


class PlanResponse(BaseModel):
    """Plan information."""
    id: str
    name: str
    display_name: str
    description: Optional[str]
    price_monthly_cents: Optional[int]
    price_yearly_cents: Optional[int]
    is_active: bool


class PlansListResponse(BaseModel):
    """List of available plans."""
    plans: list[PlanResponse]


class CallbackResponse(BaseModel):
    """Response after billing callback."""
    success: bool
    subscription_id: Optional[str]
    status: str
    message: str


# Dependency to get database session
async def get_db_session():
    """
    Get database session.

    TODO: Implement proper session management with connection pooling.
    This is a placeholder that should be replaced with actual implementation.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured"
        )

    # Handle Render's postgres:// URL format
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_billing_service(request: Request, db_session=Depends(get_db_session)) -> BillingService:
    """Get billing service with tenant context."""
    tenant_ctx = get_tenant_context(request)
    return BillingService(db_session, tenant_ctx.tenant_id)


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    request: Request,
    checkout_request: CreateCheckoutRequest,
    billing_service: BillingService = Depends(get_billing_service)
):
    """
    Create a Shopify Billing checkout URL.

    The merchant will be redirected to Shopify to approve the charge.
    After approval, they are redirected to the return_url with charge status.

    Returns:
        CheckoutResponse with confirmation URL for redirect
    """
    tenant_ctx = get_tenant_context(request)

    logger.info("Creating checkout URL", extra={
        "tenant_id": tenant_ctx.tenant_id,
        "plan_id": checkout_request.plan_id
    })

    try:
        result = await billing_service.create_checkout_url(
            plan_id=checkout_request.plan_id,
            return_url=checkout_request.return_url,
            test_mode=checkout_request.test_mode or False
        )

        return CheckoutResponse(
            checkout_url=result.checkout_url,
            subscription_id=result.subscription_id,
            shopify_subscription_id=result.shopify_subscription_id,
            success=result.success
        )

    except PlanNotFoundError as e:
        logger.warning("Plan not found", extra={
            "tenant_id": tenant_ctx.tenant_id,
            "plan_id": checkout_request.plan_id
        })
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except StoreNotFoundError as e:
        logger.warning("Store not found", extra={
            "tenant_id": tenant_ctx.tenant_id
        })
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except SubscriptionError as e:
        logger.error("Subscription error", extra={
            "tenant_id": tenant_ctx.tenant_id,
            "error": str(e)
        })
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except BillingServiceError as e:
        logger.error("Billing service error", extra={
            "tenant_id": tenant_ctx.tenant_id,
            "error": str(e)
        })
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create checkout"
        )


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    request: Request,
    billing_service: BillingService = Depends(get_billing_service)
):
    """
    Get current subscription information.

    Returns subscription status, plan details, and access permissions.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info("Getting subscription info", extra={
        "tenant_id": tenant_ctx.tenant_id
    })

    try:
        info = billing_service.get_subscription_info()

        return SubscriptionResponse(
            subscription_id=info.subscription_id,
            plan_id=info.plan_id,
            plan_name=info.plan_name,
            status=info.status,
            is_active=info.is_active,
            current_period_end=info.current_period_end.isoformat() if info.current_period_end else None,
            trial_end=info.trial_end.isoformat() if info.trial_end else None,
            can_access_features=info.can_access_features,
            downgraded_reason=info.downgraded_reason
        )
    except Exception as e:
        logger.error("Error getting subscription", extra={
            "tenant_id": tenant_ctx.tenant_id,
            "error": str(e)
        })
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get subscription information"
        )


@router.get("/callback")
async def billing_callback(
    request: Request,
    shop: str = Query(..., description="Shop domain"),
    charge_id: Optional[str] = Query(None, description="Shopify charge ID"),
    billing_service: BillingService = Depends(get_billing_service)
):
    """
    Handle callback from Shopify Billing after merchant approval/decline.

    This endpoint is called when the merchant returns from Shopify checkout.
    The charge_id parameter indicates the result of the charge.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info("Billing callback received", extra={
        "tenant_id": tenant_ctx.tenant_id,
        "shop": shop,
        "charge_id": charge_id
    })

    # The actual subscription activation happens via webhooks
    # This callback just confirms the redirect happened

    info = billing_service.get_subscription_info()

    return CallbackResponse(
        success=info.is_active or info.status == "pending",
        subscription_id=info.subscription_id,
        status=info.status,
        message="Subscription processing. Status will be updated via webhook."
    )


@router.get("/plans", response_model=PlansListResponse)
async def list_plans(
    request: Request,
    db_session=Depends(get_db_session)
):
    """
    List all available subscription plans.

    Returns active plans that can be subscribed to.
    """
    from src.models.plan import Plan

    tenant_ctx = get_tenant_context(request)

    logger.info("Listing plans", extra={
        "tenant_id": tenant_ctx.tenant_id
    })

    plans = db_session.query(Plan).filter(Plan.is_active == True).all()

    return PlansListResponse(
        plans=[
            PlanResponse(
                id=plan.id,
                name=plan.name,
                display_name=plan.display_name,
                description=plan.description,
                price_monthly_cents=plan.price_monthly_cents,
                price_yearly_cents=plan.price_yearly_cents,
                is_active=plan.is_active
            )
            for plan in plans
        ]
    )


@router.post("/cancel")
async def cancel_subscription(
    request: Request,
    billing_service: BillingService = Depends(get_billing_service)
):
    """
    Request subscription cancellation.

    Note: Actual cancellation is processed by Shopify and confirmed via webhook.
    This endpoint initiates the cancellation request.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info("Cancellation requested", extra={
        "tenant_id": tenant_ctx.tenant_id
    })

    info = billing_service.get_subscription_info()

    if not info.subscription_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found"
        )

    # For Shopify apps, merchants cancel through Shopify admin
    # We just acknowledge the request
    return {
        "message": "To cancel your subscription, please visit your Shopify admin and manage app subscriptions.",
        "subscription_id": info.subscription_id,
        "current_plan": info.plan_name
    }
