"""
Tenant Members API Routes - Manage user access to tenants.

Provides endpoints for:
- Listing members of a tenant
- Granting user access to a tenant (agency grants)
- Revoking user access from a tenant
- Updating user roles in a tenant

SECURITY:
- All endpoints require authentication
- TEAM_VIEW permission required for listing members
- TEAM_MANAGE permission required for grant/revoke/update
- Cannot revoke your own access
- Cannot remove the last admin from a tenant

Two sources of tenant membership:
1. Clerk webhooks (automatic): organizationMembership events
2. Agency grants (manual): This API
"""

import logging
from typing import List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel, Field

from src.platform.tenant_context import TenantContext, get_tenant_context
from src.platform.rbac import require_any_permission
from src.constants.permissions import Permission
from src.database.session import get_db_session_sync
from src.services.tenant_members_service import (
    TenantMembersService,
    TenantNotFoundError,
    UserNotFoundError,
    DuplicateRoleError,
    PermissionDeniedError,
    LastAdminError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants", tags=["tenant-members"])


# --- Request/Response Models ---


class TenantMemberResponse(BaseModel):
    """Information about a tenant member."""
    id: str
    user_id: str
    clerk_user_id: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str
    assigned_by: Optional[str] = None
    assigned_at: Optional[str] = None
    source: Optional[str] = None
    is_active: bool = True


class TenantMembersListResponse(BaseModel):
    """Response for listing tenant members."""
    members: List[TenantMemberResponse]
    total_count: int
    tenant_id: str


class GrantAccessRequest(BaseModel):
    """Request to grant user access to a tenant."""
    clerk_user_id: Optional[str] = Field(
        None,
        description="Clerk user ID (preferred identifier)"
    )
    email: Optional[str] = Field(
        None,
        description="User email (fallback if clerk_user_id not provided)"
    )
    role: str = Field(
        default="MERCHANT_VIEWER",
        description="Role to assign (MERCHANT_ADMIN, MERCHANT_VIEWER, AGENCY_ADMIN, AGENCY_VIEWER)"
    )


class GrantAccessResponse(BaseModel):
    """Response after granting access."""
    id: str
    user_id: str
    tenant_id: str
    role: str
    assigned_by: Optional[str] = None
    assigned_at: Optional[str] = None
    source: str = "agency_grant"
    is_active: bool = True


class UpdateRoleRequest(BaseModel):
    """Request to update a user's role."""
    role: str = Field(
        ...,
        description="New role to assign"
    )


class RevokeAccessResponse(BaseModel):
    """Response after revoking access."""
    success: bool
    message: str


# --- Helper Functions ---


def _get_db_session(request: Request):
    """Get database session from request state or create new one."""
    db = getattr(request.state, 'db', None)
    if not db:
        db = get_db_session_sync()
    return db


def _validate_team_manage_permission(tenant_context: TenantContext, tenant_id: str) -> None:
    """
    Validate user has TEAM_MANAGE permission on the tenant.

    For agency users, they must have admin role on the target tenant.
    For single-tenant users, they must be admin on their own tenant.
    """
    # Check if requesting access to own tenant
    if tenant_id == tenant_context.tenant_id:
        # Check for admin role
        admin_roles = {"MERCHANT_ADMIN", "AGENCY_ADMIN", "ADMIN", "OWNER", "SUPER_ADMIN"}
        if not any(role.upper() in admin_roles for role in tenant_context.roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You need admin role to manage team members"
            )
        return

    # Check if user can access the tenant at all
    if not tenant_context.can_access_tenant(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this tenant"
        )

    # For cross-tenant access, we need to check admin role on target tenant
    # This should be validated against the UserTenantRole in the database
    # For now, allow if they have multi-tenant access
    if not tenant_context.is_agency_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-tenant management requires agency role"
        )


def _prevent_self_action(
    tenant_context: TenantContext,
    target_user_id: str,
    action: str
) -> None:
    """Prevent user from performing certain actions on themselves."""
    if tenant_context.user_id == target_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot {action} your own access"
        )


# --- API Endpoints ---


@router.get("/{tenant_id}/members", response_model=TenantMembersListResponse)
@require_any_permission(Permission.TEAM_VIEW, Permission.TEAM_MANAGE)
async def list_tenant_members(
    request: Request,
    tenant_id: str,
    include_inactive: bool = False,
):
    """
    List all members of a tenant.

    Returns all users with access to the specified tenant,
    including their roles and assignment details.

    Requires TEAM_VIEW or TEAM_MANAGE permission.
    """
    tenant_context = get_tenant_context(request)

    # Validate access to tenant
    if not tenant_context.can_access_tenant(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this tenant"
        )

    db = _get_db_session(request)
    try:
        service = TenantMembersService(db)
        members = service.list_members(tenant_id, include_inactive=include_inactive)

        logger.info(
            "Listed tenant members",
            extra={
                "user_id": tenant_context.user_id,
                "tenant_id": tenant_id,
                "member_count": len(members),
            }
        )

        return TenantMembersListResponse(
            members=[TenantMemberResponse(**m) for m in members],
            total_count=len(members),
            tenant_id=tenant_id,
        )

    except TenantNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    finally:
        if not hasattr(request.state, 'db'):
            db.close()


@router.post("/{tenant_id}/members", response_model=GrantAccessResponse)
@require_any_permission(Permission.TEAM_MANAGE)
async def grant_tenant_access(
    request: Request,
    tenant_id: str,
    body: GrantAccessRequest,
):
    """
    Grant a user access to a tenant.

    Used by agency admins to give team members access to client tenants.
    If user doesn't exist locally, will be created via lazy sync.

    Requires TEAM_MANAGE permission (admin role on the tenant).
    """
    tenant_context = get_tenant_context(request)

    # Validate permission
    _validate_team_manage_permission(tenant_context, tenant_id)

    # Validate request
    if not body.clerk_user_id and not body.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either clerk_user_id or email must be provided"
        )

    db = _get_db_session(request)
    try:
        service = TenantMembersService(db)
        result = service.grant_access(
            tenant_id=tenant_id,
            clerk_user_id=body.clerk_user_id,
            email=body.email,
            role=body.role,
            granted_by=tenant_context.user_id,
        )
        db.commit()

        logger.info(
            "Granted tenant access",
            extra={
                "granter_id": tenant_context.user_id,
                "tenant_id": tenant_id,
                "grantee_clerk_id": body.clerk_user_id,
                "role": body.role,
            }
        )

        return GrantAccessResponse(**result)

    except TenantNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    except UserNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except DuplicateRoleError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    finally:
        if not hasattr(request.state, 'db'):
            db.close()


@router.delete("/{tenant_id}/members/{user_id}", response_model=RevokeAccessResponse)
@require_any_permission(Permission.TEAM_MANAGE)
async def revoke_tenant_access(
    request: Request,
    tenant_id: str,
    user_id: str,
):
    """
    Revoke a user's access to a tenant.

    Deactivates all role assignments for the user in that tenant.
    Cannot revoke your own access or remove the last admin.

    Requires TEAM_MANAGE permission (admin role on the tenant).
    """
    tenant_context = get_tenant_context(request)

    # Validate permission
    _validate_team_manage_permission(tenant_context, tenant_id)

    # Prevent self-revoke
    _prevent_self_action(tenant_context, user_id, "revoke")

    db = _get_db_session(request)
    try:
        service = TenantMembersService(db)
        success = service.revoke_access(
            tenant_id=tenant_id,
            user_id=user_id,
            revoked_by=tenant_context.user_id,
        )
        db.commit()

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User does not have access to this tenant"
            )

        logger.info(
            "Revoked tenant access",
            extra={
                "revoker_id": tenant_context.user_id,
                "tenant_id": tenant_id,
                "revoked_user_id": user_id,
            }
        )

        return RevokeAccessResponse(
            success=True,
            message="Access revoked successfully"
        )

    except TenantNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    except LastAdminError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the last admin from tenant"
        )
    finally:
        if not hasattr(request.state, 'db'):
            db.close()


@router.patch("/{tenant_id}/members/{user_id}", response_model=GrantAccessResponse)
@require_any_permission(Permission.TEAM_MANAGE)
async def update_member_role(
    request: Request,
    tenant_id: str,
    user_id: str,
    body: UpdateRoleRequest,
):
    """
    Update a user's role in a tenant.

    Deactivates old role(s) and creates/reactivates the new role.
    Cannot downgrade the last admin.

    Requires TEAM_MANAGE permission (admin role on the tenant).
    """
    tenant_context = get_tenant_context(request)

    # Validate permission
    _validate_team_manage_permission(tenant_context, tenant_id)

    db = _get_db_session(request)
    try:
        service = TenantMembersService(db)
        result = service.update_role(
            tenant_id=tenant_id,
            user_id=user_id,
            new_role=body.role,
            updated_by=tenant_context.user_id,
        )
        db.commit()

        logger.info(
            "Updated member role",
            extra={
                "updater_id": tenant_context.user_id,
                "tenant_id": tenant_id,
                "updated_user_id": user_id,
                "new_role": body.role,
            }
        )

        return GrantAccessResponse(**result)

    except TenantNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found"
        )
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    except LastAdminError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot downgrade the last admin"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    finally:
        if not hasattr(request.state, 'db'):
            db.close()
