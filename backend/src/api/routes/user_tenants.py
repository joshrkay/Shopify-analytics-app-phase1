"""
User Tenants API Routes - Get tenants accessible by current user.

Provides endpoints for:
- Listing all tenants the current user has access to
- Getting user's role in a specific tenant

This endpoint is used for:
- Building the store selector in the UI
- Validating tenant access
- Determining available roles

SECURITY:
- Requires authentication
- Only returns tenants user has active access to
- Sources tenant access from UserTenantRole table
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Request, HTTPException, status
from pydantic import BaseModel, Field

from src.platform.tenant_context import TenantContext, get_tenant_context
from src.database.session import get_db_session_sync
from src.services.tenant_members_service import TenantMembersService
from src.services.tenant_selection_service import (
    TenantSelectionService,
    TenantAccessDeniedError,
    TenantNotFoundError,
)
from src.constants.permissions import is_role_allowed_for_billing_tier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["user-tenants"])


# --- Response Models ---


class UserTenantResponse(BaseModel):
    """Information about a tenant the user has access to."""
    id: str = Field(..., description="Tenant ID")
    name: str = Field(..., description="Tenant display name")
    slug: Optional[str] = Field(None, description="URL-friendly identifier")
    billing_tier: str = Field(default="free", description="Billing tier")
    status: str = Field(default="active", description="Tenant status")
    roles: List[str] = Field(default=[], description="User's roles in this tenant")
    valid_roles: List[str] = Field(
        default=[],
        description="Roles that are valid for the current billing tier"
    )
    invalid_roles: List[str] = Field(
        default=[],
        description="Roles that are NOT valid for the current billing tier (may lose access)"
    )
    is_admin: bool = Field(default=False, description="Whether user has admin role")
    is_active_tenant: bool = Field(
        default=False,
        description="Whether this is the currently active tenant"
    )
    has_valid_access: bool = Field(
        default=True,
        description="Whether user has at least one valid role for this tenant"
    )


class UserTenantsListResponse(BaseModel):
    """Response for listing user's tenants."""
    tenants: List[UserTenantResponse]
    total_count: int
    active_tenant_id: Optional[str] = None
    has_multi_tenant_access: bool = False


class TenantAccessResponse(BaseModel):
    """Response for checking access to a specific tenant."""
    has_access: bool
    tenant_id: str
    roles: List[str] = []
    is_admin: bool = False


class SetActiveTenantRequest(BaseModel):
    """Request body for setting active tenant."""
    tenant_id: str = Field(..., description="ID of the tenant to set as active")


class SetActiveTenantResponse(BaseModel):
    """Response for setting active tenant."""
    tenant_id: str = Field(..., description="The newly active tenant ID")
    name: str = Field(..., description="Tenant name")
    previous_tenant_id: Optional[str] = Field(
        None,
        description="Previously active tenant ID (if any)"
    )


# --- Helper Functions ---


def _get_db_session(request: Request):
    """Get database session from request state or create new one."""
    db = getattr(request.state, 'db', None)
    if not db:
        db = next(get_db_session_sync())
    return db


# --- API Endpoints ---


@router.get("/me/tenants", response_model=UserTenantsListResponse)
async def get_my_tenants(request: Request):
    """
    Get all tenants the current user has access to.

    Returns a list of tenants with:
    - Tenant details (name, slug, billing tier, status)
    - User's roles in each tenant
    - Whether user has admin access

    This endpoint queries the UserTenantRole table to build the
    complete list of accessible tenants, combining:
    - Clerk organization memberships (synced via webhooks)
    - Agency grants (added via tenant members API)
    """
    tenant_context = get_tenant_context(request)

    db = _get_db_session(request)
    try:
        service = TenantMembersService(db)
        tenants = service.get_user_tenants(tenant_context.user_id)

        # Mark the active tenant and validate roles against billing tier
        tenant_responses = []
        for t in tenants:
            roles = t.get("roles", [])
            billing_tier = t.get("billing_tier", "free")

            # Validate each role against the billing tier
            valid_roles = []
            invalid_roles = []
            for role in roles:
                if is_role_allowed_for_billing_tier(role, billing_tier):
                    valid_roles.append(role)
                else:
                    invalid_roles.append(role)

            tenant_responses.append(UserTenantResponse(
                id=t["id"],
                name=t["name"],
                slug=t.get("slug"),
                billing_tier=billing_tier,
                status=t.get("status", "active"),
                roles=roles,
                valid_roles=valid_roles,
                invalid_roles=invalid_roles,
                is_admin=t.get("is_admin", False),
                is_active_tenant=(t["id"] == tenant_context.tenant_id),
                has_valid_access=len(valid_roles) > 0,
            ))

        # Determine if user has multi-tenant access
        has_multi_tenant = len(tenant_responses) > 1

        logger.info(
            "Listed user tenants",
            extra={
                "user_id": tenant_context.user_id,
                "tenant_count": len(tenant_responses),
                "active_tenant_id": tenant_context.tenant_id,
            }
        )

        return UserTenantsListResponse(
            tenants=tenant_responses,
            total_count=len(tenant_responses),
            active_tenant_id=tenant_context.tenant_id,
            has_multi_tenant_access=has_multi_tenant,
        )

    finally:
        if not hasattr(request.state, 'db'):
            db.close()


@router.get("/me/tenants/{tenant_id}/access", response_model=TenantAccessResponse)
async def check_my_tenant_access(request: Request, tenant_id: str):
    """
    Check if current user has access to a specific tenant.

    Returns:
    - Whether user has access
    - User's roles in the tenant
    - Whether user has admin access

    Used to validate before switching to a tenant or performing actions.
    """
    tenant_context = get_tenant_context(request)

    db = _get_db_session(request)
    try:
        service = TenantMembersService(db)

        # Check if user has any access
        has_access = service.check_user_has_access(
            clerk_user_id=tenant_context.user_id,
            tenant_id=tenant_id,
        )

        if not has_access:
            return TenantAccessResponse(
                has_access=False,
                tenant_id=tenant_id,
                roles=[],
                is_admin=False,
            )

        # Get roles for this tenant
        is_admin = service.check_user_is_admin(
            clerk_user_id=tenant_context.user_id,
            tenant_id=tenant_id,
        )

        # Get all tenants and find this one to get roles
        tenants = service.get_user_tenants(tenant_context.user_id)
        roles = []
        for t in tenants:
            if t["id"] == tenant_id:
                roles = t.get("roles", [])
                break

        return TenantAccessResponse(
            has_access=True,
            tenant_id=tenant_id,
            roles=roles,
            is_admin=is_admin,
        )

    finally:
        if not hasattr(request.state, 'db'):
            db.close()


@router.get("/me/context")
async def get_my_context(request: Request):
    """
    Get the current user's full context.

    Returns comprehensive user information including:
    - User identity (user_id, org_id)
    - Active tenant context
    - All accessible tenants (from database)
    - Roles and permissions
    - Billing tier

    This is useful for initializing the frontend state.
    """
    tenant_context = get_tenant_context(request)

    db = _get_db_session(request)
    try:
        service = TenantMembersService(db)
        tenants = service.get_user_tenants(tenant_context.user_id)

        # Build allowed_tenants list from database
        allowed_tenant_ids = [t["id"] for t in tenants]

        logger.info(
            "Got user context",
            extra={
                "user_id": tenant_context.user_id,
                "tenant_count": len(tenants),
                "active_tenant_id": tenant_context.tenant_id,
            }
        )

        return {
            "user_id": tenant_context.user_id,
            "org_id": tenant_context.org_id,
            "active_tenant_id": tenant_context.tenant_id,
            "billing_tier": tenant_context.billing_tier,
            "roles": tenant_context.roles,
            "is_agency_user": tenant_context.is_agency_user or len(tenants) > 1,
            "allowed_tenants": allowed_tenant_ids,
            "tenants": [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "roles": t.get("roles", []),
                    "is_admin": t.get("is_admin", False),
                    "is_active": t["id"] == tenant_context.tenant_id,
                }
                for t in tenants
            ],
        }

    finally:
        if not hasattr(request.state, 'db'):
            db.close()


@router.post("/me/active-tenant", response_model=SetActiveTenantResponse)
async def set_active_tenant(request: Request, body: SetActiveTenantRequest):
    """
    Set the user's active tenant.

    SECURITY:
    - Validates user has access to the requested tenant via database
    - Never trusts tenant_id from client without validation
    - Emits audit event on invalid access attempts

    Args:
        body: Request with tenant_id to set as active

    Returns:
        Tenant details and previous active tenant

    Raises:
        403: If user doesn't have access to the tenant
        404: If tenant doesn't exist
    """
    tenant_context = get_tenant_context(request)

    # Extract client info for audit logging
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip_address = forwarded_for.split(",")[0].strip()
    else:
        ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    db = _get_db_session(request)
    try:
        service = TenantSelectionService(db)

        result = service.set_active_tenant(
            clerk_user_id=tenant_context.user_id,
            tenant_id=body.tenant_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        db.commit()

        logger.info(
            "User set active tenant",
            extra={
                "user_id": tenant_context.user_id,
                "tenant_id": body.tenant_id,
                "previous_tenant_id": result.get("previous_tenant_id"),
            }
        )

        return SetActiveTenantResponse(
            tenant_id=result["tenant_id"],
            name=result["name"],
            previous_tenant_id=result.get("previous_tenant_id"),
        )

    except TenantNotFoundError as e:
        logger.warning(
            "Attempt to set non-existent tenant as active",
            extra={
                "user_id": tenant_context.user_id,
                "requested_tenant_id": body.tenant_id,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant not found: {body.tenant_id}"
        )

    except TenantAccessDeniedError as e:
        logger.warning(
            "Attempt to set unauthorized tenant as active",
            extra={
                "user_id": tenant_context.user_id,
                "requested_tenant_id": body.tenant_id,
            }
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied to tenant: {body.tenant_id}"
        )

    finally:
        if not hasattr(request.state, 'db'):
            db.close()
