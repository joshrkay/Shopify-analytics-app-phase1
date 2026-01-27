"""
Admin Plans API routes for plan management.

SECURITY: All routes require admin role verification.
These endpoints allow creating, editing, and managing pricing plans.
"""

import os
import logging
from typing import Optional, List

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field, field_validator

from src.platform.tenant_context import get_tenant_context, TenantContext
from src.services.plan_service import (
    PlanService,
    PlanServiceError,
    PlanNotFoundServiceError,
    PlanValidationError,
    ShopifyValidationError
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/plans", tags=["admin-plans"])


# Request/Response models

class FeatureRequest(BaseModel):
    """Feature configuration for a plan."""
    feature_key: str = Field(..., description="Feature identifier", min_length=1, max_length=255)
    is_enabled: bool = Field(True, description="Whether feature is enabled")
    limit_value: Optional[int] = Field(None, description="Usage limit value", ge=0)
    limits: Optional[dict] = Field(None, description="Additional limits configuration")


class CreatePlanRequest(BaseModel):
    """Request to create a new plan."""
    name: str = Field(..., description="Unique plan name (e.g., 'growth')", min_length=1, max_length=100)
    display_name: str = Field(..., description="Human-readable name (e.g., 'Growth')", min_length=1, max_length=255)
    description: Optional[str] = Field(None, description="Plan description", max_length=2000)
    price_monthly_cents: Optional[int] = Field(None, description="Monthly price in cents", ge=0)
    price_yearly_cents: Optional[int] = Field(None, description="Yearly price in cents", ge=0)
    shopify_plan_id: Optional[str] = Field(None, description="Shopify Billing API plan ID", max_length=255)
    is_active: bool = Field(True, description="Whether plan is available for subscriptions")
    features: Optional[List[FeatureRequest]] = Field(None, description="Plan features")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Name must contain only alphanumeric characters, underscores, or hyphens")
        return v.lower()


class UpdatePlanRequest(BaseModel):
    """Request to update a plan."""
    name: Optional[str] = Field(None, description="New plan name", min_length=1, max_length=100)
    display_name: Optional[str] = Field(None, description="New display name", min_length=1, max_length=255)
    description: Optional[str] = Field(None, description="New description", max_length=2000)
    price_monthly_cents: Optional[int] = Field(None, description="New monthly price in cents", ge=0)
    price_yearly_cents: Optional[int] = Field(None, description="New yearly price in cents", ge=0)
    shopify_plan_id: Optional[str] = Field(None, description="New Shopify plan ID", max_length=255)
    is_active: Optional[bool] = Field(None, description="New active status")
    features: Optional[List[FeatureRequest]] = Field(None, description="New features (replaces existing)")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Name must contain only alphanumeric characters, underscores, or hyphens")
        return v.lower() if v else None


class ToggleFeatureRequest(BaseModel):
    """Request to toggle a feature."""
    feature_key: str = Field(..., description="Feature identifier")
    is_enabled: bool = Field(..., description="New enabled status")


class FeatureResponse(BaseModel):
    """Feature information."""
    feature_key: str
    is_enabled: bool
    limit_value: Optional[int] = None
    limits: Optional[dict] = None


class PlanResponse(BaseModel):
    """Full plan information."""
    id: str
    name: str
    display_name: str
    description: Optional[str]
    price_monthly_cents: Optional[int]
    price_yearly_cents: Optional[int]
    shopify_plan_id: Optional[str]
    is_active: bool
    features: List[FeatureResponse]
    created_at: Optional[str]
    updated_at: Optional[str]


class PlansListResponse(BaseModel):
    """List of plans with pagination."""
    plans: List[PlanResponse]
    total: int
    limit: int
    offset: int


class ShopifyValidationRequest(BaseModel):
    """Request to validate Shopify plan sync."""
    shop_domain: str = Field(..., description="Shopify store domain")
    shopify_subscription_id: Optional[str] = Field(None, description="Optional subscription ID to validate")


class ShopifyValidationResponse(BaseModel):
    """Result of Shopify validation."""
    is_valid: bool
    shopify_plan_id: Optional[str]
    plan_name: Optional[str]
    price_amount: Optional[float]
    currency_code: Optional[str]
    error: Optional[str]


# Import shared database session dependency
from src.database.session import get_db_session


def verify_admin_role(request: Request) -> TenantContext:
    """
    Verify that the user has admin role.

    SECURITY: Admin endpoints require explicit admin role.
    """
    tenant_ctx = get_tenant_context(request)

    # Check for admin role
    admin_roles = ["admin", "Admin", "ADMIN", "owner", "Owner", "OWNER"]
    has_admin = any(role in tenant_ctx.roles for role in admin_roles)

    if not has_admin:
        logger.warning("Unauthorized admin access attempt", extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
            "roles": tenant_ctx.roles
        })
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required"
        )

    return tenant_ctx


def get_plan_service(db_session=Depends(get_db_session)) -> PlanService:
    """Get plan service instance."""
    return PlanService(db_session)


# Routes

@router.get("", response_model=PlansListResponse)
async def list_plans(
    request: Request,
    include_inactive: bool = Query(False, description="Include inactive plans"),
    limit: int = Query(100, ge=1, le=500, description="Maximum plans to return"),
    offset: int = Query(0, ge=0, description="Number of plans to skip"),
    tenant_ctx: TenantContext = Depends(verify_admin_role),
    plan_service: PlanService = Depends(get_plan_service)
):
    """
    List all plans with pagination.

    Requires admin role.
    """
    logger.info("Admin listing plans", extra={
        "tenant_id": tenant_ctx.tenant_id,
        "user_id": tenant_ctx.user_id,
        "include_inactive": include_inactive
    })

    plans, total = plan_service.list_plans(
        include_inactive=include_inactive,
        limit=limit,
        offset=offset
    )

    return PlansListResponse(
        plans=[
            PlanResponse(
                id=p.id,
                name=p.name,
                display_name=p.display_name,
                description=p.description,
                price_monthly_cents=p.price_monthly_cents,
                price_yearly_cents=p.price_yearly_cents,
                shopify_plan_id=p.shopify_plan_id,
                is_active=p.is_active,
                features=[
                    FeatureResponse(**f) for f in p.features
                ],
                created_at=p.created_at.isoformat() if p.created_at else None,
                updated_at=p.updated_at.isoformat() if p.updated_at else None
            )
            for p in plans
        ],
        total=total,
        limit=limit,
        offset=offset
    )


@router.get("/{plan_id}", response_model=PlanResponse)
async def get_plan(
    request: Request,
    plan_id: str,
    tenant_ctx: TenantContext = Depends(verify_admin_role),
    plan_service: PlanService = Depends(get_plan_service)
):
    """
    Get a specific plan by ID.

    Requires admin role.
    """
    logger.info("Admin getting plan", extra={
        "tenant_id": tenant_ctx.tenant_id,
        "user_id": tenant_ctx.user_id,
        "plan_id": plan_id
    })

    try:
        plan = plan_service.get_plan(plan_id)

        return PlanResponse(
            id=plan.id,
            name=plan.name,
            display_name=plan.display_name,
            description=plan.description,
            price_monthly_cents=plan.price_monthly_cents,
            price_yearly_cents=plan.price_yearly_cents,
            shopify_plan_id=plan.shopify_plan_id,
            is_active=plan.is_active,
            features=[
                FeatureResponse(**f) for f in plan.features
            ],
            created_at=plan.created_at.isoformat() if plan.created_at else None,
            updated_at=plan.updated_at.isoformat() if plan.updated_at else None
        )

    except PlanNotFoundServiceError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan not found: {plan_id}"
        )


@router.post("", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
async def create_plan(
    request: Request,
    plan_request: CreatePlanRequest,
    tenant_ctx: TenantContext = Depends(verify_admin_role),
    plan_service: PlanService = Depends(get_plan_service)
):
    """
    Create a new plan.

    Requires admin role.
    Changes apply instantly - no deployment required.
    """
    logger.info("Admin creating plan", extra={
        "tenant_id": tenant_ctx.tenant_id,
        "user_id": tenant_ctx.user_id,
        "plan_name": plan_request.name
    })

    try:
        features = None
        if plan_request.features:
            features = [f.model_dump() for f in plan_request.features]

        plan = plan_service.create_plan(
            name=plan_request.name,
            display_name=plan_request.display_name,
            description=plan_request.description,
            price_monthly_cents=plan_request.price_monthly_cents,
            price_yearly_cents=plan_request.price_yearly_cents,
            shopify_plan_id=plan_request.shopify_plan_id,
            is_active=plan_request.is_active,
            features=features
        )

        logger.info("Plan created by admin", extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
            "plan_id": plan.id
        })

        return PlanResponse(
            id=plan.id,
            name=plan.name,
            display_name=plan.display_name,
            description=plan.description,
            price_monthly_cents=plan.price_monthly_cents,
            price_yearly_cents=plan.price_yearly_cents,
            shopify_plan_id=plan.shopify_plan_id,
            is_active=plan.is_active,
            features=[
                FeatureResponse(**f) for f in plan.features
            ],
            created_at=plan.created_at.isoformat() if plan.created_at else None,
            updated_at=plan.updated_at.isoformat() if plan.updated_at else None
        )

    except PlanValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except PlanServiceError as e:
        logger.error("Failed to create plan", extra={
            "tenant_id": tenant_ctx.tenant_id,
            "error": str(e)
        })
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create plan"
        )


@router.patch("/{plan_id}", response_model=PlanResponse)
async def update_plan(
    request: Request,
    plan_id: str,
    plan_request: UpdatePlanRequest,
    tenant_ctx: TenantContext = Depends(verify_admin_role),
    plan_service: PlanService = Depends(get_plan_service)
):
    """
    Update an existing plan.

    Requires admin role.
    Changes apply instantly - no deployment required.
    """
    logger.info("Admin updating plan", extra={
        "tenant_id": tenant_ctx.tenant_id,
        "user_id": tenant_ctx.user_id,
        "plan_id": plan_id
    })

    try:
        features = None
        if plan_request.features is not None:
            features = [f.model_dump() for f in plan_request.features]

        plan = plan_service.update_plan(
            plan_id=plan_id,
            name=plan_request.name,
            display_name=plan_request.display_name,
            description=plan_request.description,
            price_monthly_cents=plan_request.price_monthly_cents,
            price_yearly_cents=plan_request.price_yearly_cents,
            shopify_plan_id=plan_request.shopify_plan_id,
            is_active=plan_request.is_active,
            features=features
        )

        logger.info("Plan updated by admin", extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
            "plan_id": plan_id
        })

        return PlanResponse(
            id=plan.id,
            name=plan.name,
            display_name=plan.display_name,
            description=plan.description,
            price_monthly_cents=plan.price_monthly_cents,
            price_yearly_cents=plan.price_yearly_cents,
            shopify_plan_id=plan.shopify_plan_id,
            is_active=plan.is_active,
            features=[
                FeatureResponse(**f) for f in plan.features
            ],
            created_at=plan.created_at.isoformat() if plan.created_at else None,
            updated_at=plan.updated_at.isoformat() if plan.updated_at else None
        )

    except PlanNotFoundServiceError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan not found: {plan_id}"
        )
    except PlanValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except PlanServiceError as e:
        logger.error("Failed to update plan", extra={
            "tenant_id": tenant_ctx.tenant_id,
            "plan_id": plan_id,
            "error": str(e)
        })
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update plan"
        )


@router.post("/{plan_id}/features/toggle", response_model=FeatureResponse)
async def toggle_feature(
    request: Request,
    plan_id: str,
    feature_request: ToggleFeatureRequest,
    tenant_ctx: TenantContext = Depends(verify_admin_role),
    plan_service: PlanService = Depends(get_plan_service)
):
    """
    Toggle a specific feature on/off for a plan.

    Requires admin role.
    Changes apply instantly.
    """
    logger.info("Admin toggling feature", extra={
        "tenant_id": tenant_ctx.tenant_id,
        "user_id": tenant_ctx.user_id,
        "plan_id": plan_id,
        "feature_key": feature_request.feature_key,
        "is_enabled": feature_request.is_enabled
    })

    try:
        feature = plan_service.toggle_feature(
            plan_id=plan_id,
            feature_key=feature_request.feature_key,
            is_enabled=feature_request.is_enabled
        )

        return FeatureResponse(**feature)

    except PlanNotFoundServiceError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan not found: {plan_id}"
        )
    except PlanServiceError as e:
        logger.error("Failed to toggle feature", extra={
            "tenant_id": tenant_ctx.tenant_id,
            "plan_id": plan_id,
            "error": str(e)
        })
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to toggle feature"
        )


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    request: Request,
    plan_id: str,
    tenant_ctx: TenantContext = Depends(verify_admin_role),
    plan_service: PlanService = Depends(get_plan_service)
):
    """
    Delete a plan.

    WARNING: Consider using PATCH to set is_active=false instead.
    Hard deletion will remove all plan features.

    Requires admin role.
    """
    logger.warning("Admin deleting plan", extra={
        "tenant_id": tenant_ctx.tenant_id,
        "user_id": tenant_ctx.user_id,
        "plan_id": plan_id
    })

    try:
        plan_service.delete_plan(plan_id)
        return None

    except PlanNotFoundServiceError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan not found: {plan_id}"
        )


@router.post("/{plan_id}/validate-shopify", response_model=ShopifyValidationResponse)
async def validate_shopify_sync(
    request: Request,
    plan_id: str,
    validation_request: ShopifyValidationRequest,
    tenant_ctx: TenantContext = Depends(verify_admin_role),
    plan_service: PlanService = Depends(get_plan_service)
):
    """
    Validate that a plan can be synced to Shopify Billing.

    Verifies:
    - Shopify API access is working
    - Plan configuration is valid for Shopify Billing
    - Any existing Shopify subscription is accessible

    Requires admin role.
    """
    from src.models.store import ShopifyStore

    logger.info("Admin validating Shopify sync", extra={
        "tenant_id": tenant_ctx.tenant_id,
        "user_id": tenant_ctx.user_id,
        "plan_id": plan_id,
        "shop_domain": validation_request.shop_domain
    })

    # Get store's access token
    # In production, this would need proper tenant scoping
    db_session = plan_service.db
    store = db_session.query(ShopifyStore).filter(
        ShopifyStore.shop_domain == validation_request.shop_domain,
        ShopifyStore.status == "active"
    ).first()

    if not store or not store.access_token_encrypted:
        return ShopifyValidationResponse(
            is_valid=False,
            shopify_plan_id=None,
            plan_name=None,
            price_amount=None,
            currency_code=None,
            error=f"Store not found or no access token: {validation_request.shop_domain}"
        )

    # Decrypt the access token using platform secrets module
    from src.platform.secrets import decrypt_secret, validate_encryption_configured
    if validate_encryption_configured():
        try:
            access_token = await decrypt_secret(store.access_token_encrypted)
        except Exception as e:
            logger.warning("Failed to decrypt token, using as-is", extra={"error": str(e)})
            access_token = store.access_token_encrypted
    else:
        access_token = store.access_token_encrypted

    try:
        result = await plan_service.sync_plan_to_shopify(
            plan_id=plan_id,
            shop_domain=validation_request.shop_domain,
            access_token=access_token
        )

        return ShopifyValidationResponse(
            is_valid=result.is_valid,
            shopify_plan_id=result.shopify_plan_id,
            plan_name=result.plan_name,
            price_amount=result.price_amount,
            currency_code=result.currency_code,
            error=result.error
        )

    except PlanNotFoundServiceError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan not found: {plan_id}"
        )
    except Exception as e:
        logger.error("Shopify validation failed", extra={
            "tenant_id": tenant_ctx.tenant_id,
            "plan_id": plan_id,
            "error": str(e)
        })
        return ShopifyValidationResponse(
            is_valid=False,
            shopify_plan_id=None,
            plan_name=None,
            price_amount=None,
            currency_code=None,
            error=str(e)
        )
