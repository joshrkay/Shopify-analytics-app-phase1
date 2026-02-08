"""
Agency API Routes - Multi-tenant store management for agency users.

Provides endpoints for:
- Listing assigned stores
- Switching active store (updates JWT context)
- Checking store access permissions

SECURITY:
- All endpoints require agency role
- Store access is validated against allowed_tenants[]
- JWT is refreshed with new tenant context on store switch
"""

import logging
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.platform.tenant_context import TenantContext, get_tenant_context
from src.platform.rbac import require_any_permission, has_permission
from src.constants.permissions import Permission, Role, has_multi_tenant_access
from src.services.billing_entitlements import (
    BillingEntitlementsService,
    BillingFeature,
    check_billing_entitlement_decorator,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agency", tags=["agency"])


# --- Request/Response Models ---


class AssignedStoreResponse(BaseModel):
    """Information about an assigned store."""
    tenant_id: str
    store_name: str
    shop_domain: str
    status: str = "active"
    assigned_at: str
    permissions: List[str] = []


class AssignedStoresListResponse(BaseModel):
    """Response for listing assigned stores."""
    stores: List[AssignedStoreResponse]
    total_count: int
    active_tenant_id: str
    max_stores_allowed: int


class SwitchStoreRequest(BaseModel):
    """Request to switch active store."""
    tenant_id: str = Field(..., description="Target tenant ID to switch to")


class SwitchStoreResponse(BaseModel):
    """Response after switching store."""
    success: bool
    jwt_token: str = Field(..., description="New JWT token with updated tenant context")
    active_tenant_id: str
    store: AssignedStoreResponse


class StoreAccessResponse(BaseModel):
    """Response for store access check."""
    has_access: bool
    reason: Optional[str] = None


class UserContextResponse(BaseModel):
    """Current user context information."""
    user_id: str
    tenant_id: str
    org_id: str
    roles: List[str]
    allowed_tenants: List[str]
    billing_tier: str
    is_agency_user: bool


# --- Helper Functions ---


def _get_db_session(request: Request) -> Session:
    """Get database session from request state."""
    db = getattr(request.state, 'db', None)
    if not db:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database session not available"
        )
    return db


def _require_agency_user(tenant_context: TenantContext) -> None:
    """Validate that the user is an agency user."""
    if not tenant_context.is_agency_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only available for agency users"
        )


def _validate_tenant_access(tenant_context: TenantContext, tenant_id: str) -> None:
    """Validate that user has access to the specified tenant."""
    if not tenant_context.can_access_tenant(tenant_id):
        logger.warning(
            "Unauthorized tenant access attempt",
            extra={
                "user_id": tenant_context.user_id,
                "requested_tenant_id": tenant_id,
                "allowed_tenants": tenant_context.allowed_tenants,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this store"
        )


def _generate_jwt_token(
    user_id: str,
    tenant_id: str,
    roles: List[str],
    allowed_tenants: List[str],
    billing_tier: str,
    org_id: str,
    access_surface: str = "external_app",
    access_expiring_at: Optional[datetime] = None,
) -> str:
    """
    Generate a new JWT token with updated tenant context.

    Args:
        access_surface: "shopify_embed" or "external_app"
        access_expiring_at: Grace period expiry (Story 5.5.4)

    NOTE: In production, this should call your auth service (e.g., Clerk)
    to issue a new token. This is a placeholder implementation.
    """
    import jwt
    import os

    jwt_secret = os.getenv("JWT_SECRET", "development-secret-change-in-prod")

    payload = {
        "sub": user_id,
        "user_id": user_id,
        "org_id": org_id,
        "tenant_id": tenant_id,
        "active_tenant_id": tenant_id,
        "roles": roles,
        "allowed_tenants": allowed_tenants,
        "billing_tier": billing_tier,
        "access_surface": access_surface,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }

    if access_expiring_at:
        payload["access_expiring_at"] = access_expiring_at.isoformat()

    return jwt.encode(payload, jwt_secret, algorithm="HS256")


def _get_store_info_from_tenant(
    db: Session,
    tenant_id: str,
    tenant_context: TenantContext
) -> AssignedStoreResponse:
    """
    Get store information for a tenant.

    Queries the ShopifyStore model for actual store data.
    Falls back to placeholder data if store not found (for new/pending stores).
    """
    from src.models.store import ShopifyStore

    store = db.query(ShopifyStore).filter(
        ShopifyStore.tenant_id == tenant_id
    ).first()

    if store:
        return AssignedStoreResponse(
            tenant_id=tenant_id,
            store_name=store.shop_name or store.shop_domain,
            shop_domain=store.shop_domain,
            status=store.status or "active",
            assigned_at=(store.installed_at or store.created_at or datetime.now(timezone.utc)).isoformat(),
            permissions=["analytics:view", "store:view"],
        )

    # Fallback for stores not yet in database (pending setup)
    logger.debug("Store not found in database, using placeholder", extra={
        "tenant_id": tenant_id
    })
    return AssignedStoreResponse(
        tenant_id=tenant_id,
        store_name=f"Store {tenant_id[-4:]}",
        shop_domain=f"pending-{tenant_id[-4:]}.myshopify.com",
        status="pending",
        assigned_at=datetime.now(timezone.utc).isoformat(),
        permissions=["analytics:view", "store:view"],
    )


# --- API Endpoints ---


@router.get("/stores", response_model=AssignedStoresListResponse)
@require_any_permission(Permission.AGENCY_STORES_VIEW, Permission.MULTI_TENANT_ACCESS)
async def list_assigned_stores(request: Request):
    """
    List all stores assigned to the current agency user.

    Returns stores from the allowed_tenants[] JWT claim.
    """
    tenant_context = get_tenant_context(request)
    _require_agency_user(tenant_context)

    db = _get_db_session(request)

    # Get entitlements for max stores
    entitlements = BillingEntitlementsService(db, tenant_context.tenant_id)
    max_stores = entitlements.get_max_agency_stores()

    # Build store list from allowed_tenants
    stores = []
    for tenant_id in tenant_context.allowed_tenants:
        store_info = _get_store_info_from_tenant(db, tenant_id, tenant_context)
        stores.append(store_info)

    logger.info(
        "Listed assigned stores for agency user",
        extra={
            "user_id": tenant_context.user_id,
            "store_count": len(stores),
            "active_tenant_id": tenant_context.tenant_id,
        }
    )

    return AssignedStoresListResponse(
        stores=stores,
        total_count=len(stores),
        active_tenant_id=tenant_context.tenant_id,
        max_stores_allowed=max_stores,
    )


@router.post("/stores/switch", response_model=SwitchStoreResponse)
@require_any_permission(Permission.AGENCY_STORES_SWITCH, Permission.MULTI_TENANT_ACCESS)
async def switch_active_store(request: Request, body: SwitchStoreRequest):
    """
    Switch the active store for an agency user.

    This endpoint:
    1. Validates the user has access to the target store
    2. Generates a new JWT with the updated tenant context
    3. Returns the new token and store information

    The client should use the returned JWT for subsequent requests.
    """
    tenant_context = get_tenant_context(request)
    _require_agency_user(tenant_context)

    target_tenant_id = body.tenant_id

    # Validate access to target tenant
    _validate_tenant_access(tenant_context, target_tenant_id)

    db = _get_db_session(request)

    # Generate new JWT with updated tenant context
    new_token = _generate_jwt_token(
        user_id=tenant_context.user_id,
        tenant_id=target_tenant_id,
        roles=tenant_context.roles,
        allowed_tenants=tenant_context.allowed_tenants,
        billing_tier=tenant_context.billing_tier,
        org_id=tenant_context.org_id,
    )

    # Get store info
    store_info = _get_store_info_from_tenant(db, target_tenant_id, tenant_context)

    logger.info(
        "Agency user switched active store",
        extra={
            "user_id": tenant_context.user_id,
            "from_tenant_id": tenant_context.tenant_id,
            "to_tenant_id": target_tenant_id,
        }
    )

    return SwitchStoreResponse(
        success=True,
        jwt_token=new_token,
        active_tenant_id=target_tenant_id,
        store=store_info,
    )


@router.get("/stores/{tenant_id}/access", response_model=StoreAccessResponse)
@require_any_permission(Permission.AGENCY_STORES_VIEW, Permission.MULTI_TENANT_ACCESS)
async def check_store_access(request: Request, tenant_id: str):
    """
    Check if the current user has access to a specific store.

    Used to validate access before attempting operations on a store.
    """
    tenant_context = get_tenant_context(request)
    _require_agency_user(tenant_context)

    has_access = tenant_context.can_access_tenant(tenant_id)

    if not has_access:
        return StoreAccessResponse(
            has_access=False,
            reason="Store is not in your allowed stores list"
        )

    return StoreAccessResponse(has_access=True)


@router.get("/me", response_model=UserContextResponse)
async def get_user_context(request: Request):
    """
    Get the current user's context information.

    Returns user ID, roles, allowed tenants, and agency status.
    """
    tenant_context = get_tenant_context(request)

    return UserContextResponse(
        user_id=tenant_context.user_id,
        tenant_id=tenant_context.tenant_id,
        org_id=tenant_context.org_id,
        roles=tenant_context.roles,
        allowed_tenants=tenant_context.allowed_tenants,
        billing_tier=tenant_context.billing_tier,
        is_agency_user=tenant_context.is_agency_user,
    )


# --- Cross-Store Reporting Endpoints ---


@router.get("/reports/summary")
@require_any_permission(Permission.AGENCY_REPORTS_VIEW)
@check_billing_entitlement_decorator(BillingFeature.AGENCY_ACCESS)
async def get_cross_store_summary(request: Request):
    """
    Get a summary report across all assigned stores.

    Requires AGENCY_REPORTS_VIEW permission and agency billing entitlement.
    Aggregates metrics from subscriptions and billing events across all allowed tenants.
    """
    tenant_context = get_tenant_context(request)
    _require_agency_user(tenant_context)

    db = _get_db_session(request)

    # Query aggregated metrics across all allowed tenants
    from src.models.store import ShopifyStore
    from src.models.subscription import Subscription, SubscriptionStatus

    # Get store count and status
    stores = db.query(ShopifyStore).filter(
        ShopifyStore.tenant_id.in_(tenant_context.allowed_tenants)
    ).all()

    active_stores = [s for s in stores if s.status == "active"]

    # Get active subscriptions across all tenants
    active_subs = db.query(Subscription).filter(
        Subscription.tenant_id.in_(tenant_context.allowed_tenants),
        Subscription.status == SubscriptionStatus.ACTIVE.value
    ).count()

    logger.info(
        "Cross-store summary requested",
        extra={
            "user_id": tenant_context.user_id,
            "tenant_count": len(tenant_context.allowed_tenants),
            "stores_found": len(stores),
            "active_stores": len(active_stores),
        }
    )

    # Note: Order/revenue metrics would require querying the analytics layer (dbt models)
    # This provides the billing/subscription summary from the platform layer
    return {
        "summary": {
            "total_stores": len(tenant_context.allowed_tenants),
            "active_stores": len(active_stores),
            "stores_with_data": len(stores),
            "active_subscriptions": active_subs,
            "total_orders_30d": None,  # Requires analytics layer query
            "total_revenue_30d": None,  # Requires analytics layer query
        },
        "stores": [
            {
                "tenant_id": s.tenant_id,
                "shop_domain": s.shop_domain,
                "status": s.status,
            }
            for s in stores
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Order/revenue metrics available via analytics dashboard",
    }
