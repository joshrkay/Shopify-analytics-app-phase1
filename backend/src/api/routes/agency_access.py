"""
Agency Access API Routes - Manage agency-to-tenant access requests.

Provides endpoints for:
- Creating agency access requests (agency users)
- Listing pending requests (tenant admins)
- Approving/denying requests (tenant admins)
- Listing own requests (agency users)
- Cancelling own pending requests (agency users)

SECURITY:
- Approve/deny validates tenant_context.tenant_id matches the request's tenant_id
- Agency access requires explicit tenant approval
- No cross-tenant rollups: one active tenant context at a time

Story 5.5.2 - Agency Access Request + Tenant Approval Workflow
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Request, HTTPException, status
from pydantic import BaseModel, Field

from src.platform.tenant_context import get_tenant_context
from src.platform.rbac import require_any_permission
from src.constants.permissions import Permission
from src.database.session import get_db_session_sync
from src.services.agency_access_service import (
    AgencyAccessService,
    RequestNotFoundError,
    DuplicateRequestError,
    InvalidStatusTransitionError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agency-access", tags=["agency-access"])


# --- Request/Response Models ---


class CreateAccessRequestBody(BaseModel):
    """Request body for creating an agency access request."""
    tenant_id: str = Field(..., description="Target tenant ID to request access to")
    requested_role_slug: str = Field(
        default="agency_viewer",
        description="Role template slug (agency_admin or agency_viewer)",
    )
    requesting_org_id: Optional[str] = Field(
        None, description="Optional organization ID of the requesting agency"
    )
    message: Optional[str] = Field(
        None, description="Optional custom message for the tenant admin"
    )


class ReviewRequestBody(BaseModel):
    """Request body for approving or denying an access request."""
    review_note: Optional[str] = Field(
        None, description="Optional note from the reviewer"
    )


class AgencyAccessRequestResponse(BaseModel):
    """Response for an agency access request."""
    id: str
    requesting_user_id: str
    requesting_org_id: Optional[str] = None
    tenant_id: str
    requested_role_slug: str
    message: Optional[str] = None
    status: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    review_note: Optional[str] = None
    expires_at: Optional[str] = None
    created_at: Optional[str] = None


class AgencyAccessRequestListResponse(BaseModel):
    """Response for listing agency access requests."""
    requests: List[AgencyAccessRequestResponse]
    total_count: int


# --- Helper Functions ---


def _get_db_session(request: Request):
    """Get database session from request state or create new one."""
    db = getattr(request.state, "db", None)
    if not db:
        db = next(get_db_session_sync())
    return db


# --- API Endpoints ---


@router.post("/requests", response_model=AgencyAccessRequestResponse)
@require_any_permission(Permission.MULTI_TENANT_ACCESS)
async def create_access_request(
    request: Request,
    body: CreateAccessRequestBody,
):
    """
    Create an agency access request.

    Agency users call this to request access to a tenant's data.
    The request starts in PENDING status and must be approved by a tenant admin.

    Requires MULTI_TENANT_ACCESS permission.
    """
    tenant_context = get_tenant_context(request)
    db = _get_db_session(request)

    try:
        service = AgencyAccessService(db)
        # Look up the internal user ID from the clerk_user_id
        from src.models.user import User

        user = db.query(User).filter(
            User.clerk_user_id == tenant_context.user_id
        ).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        result = service.request_access(
            requesting_user_id=user.id,
            tenant_id=body.tenant_id,
            requested_role_slug=body.requested_role_slug,
            requesting_org_id=body.requesting_org_id,
            message=body.message,
        )
        db.commit()

        logger.info(
            "Agency access request created",
            extra={
                "request_id": result["id"],
                "user_id": tenant_context.user_id,
                "target_tenant_id": body.tenant_id,
            },
        )

        return AgencyAccessRequestResponse(**result)

    except DuplicateRequestError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    finally:
        if not hasattr(request.state, "db"):
            db.close()


@router.get("/requests/pending", response_model=AgencyAccessRequestListResponse)
@require_any_permission(Permission.TEAM_MANAGE)
async def list_pending_requests(request: Request):
    """
    List all pending agency access requests for the current tenant.

    Used by tenant admins to see incoming agency access requests.

    Requires TEAM_MANAGE permission.
    """
    tenant_context = get_tenant_context(request)
    db = _get_db_session(request)

    try:
        service = AgencyAccessService(db)
        results = service.list_pending_requests(tenant_context.tenant_id)

        return AgencyAccessRequestListResponse(
            requests=[AgencyAccessRequestResponse(**r) for r in results],
            total_count=len(results),
        )
    finally:
        if not hasattr(request.state, "db"):
            db.close()


@router.post(
    "/requests/{request_id}/approve",
    response_model=AgencyAccessRequestResponse,
)
@require_any_permission(Permission.TEAM_MANAGE)
async def approve_request(
    request: Request,
    request_id: str,
    body: ReviewRequestBody,
):
    """
    Approve an agency access request.

    On approval:
    1. Updates request status to APPROVED
    2. Creates UserRoleAssignment (data-driven RBAC)
    3. Creates UserTenantRole (backward compatibility)
    4. Emits audit event

    Requires TEAM_MANAGE permission.
    Tenant admin can only approve requests for their own tenant.
    """
    tenant_context = get_tenant_context(request)
    db = _get_db_session(request)

    try:
        service = AgencyAccessService(db)

        # Validate the request belongs to the current tenant
        access_request = service._get_request(request_id)
        if access_request.tenant_id != tenant_context.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only approve requests for your own tenant",
            )

        result = service.approve_request(
            request_id=request_id,
            reviewed_by=tenant_context.user_id,
            review_note=body.review_note,
        )
        db.commit()

        logger.info(
            "Agency access request approved",
            extra={
                "request_id": request_id,
                "approved_by": tenant_context.user_id,
                "tenant_id": tenant_context.tenant_id,
            },
        )

        return AgencyAccessRequestResponse(**result)

    except RequestNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        )
    except InvalidStatusTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    finally:
        if not hasattr(request.state, "db"):
            db.close()


@router.post(
    "/requests/{request_id}/deny",
    response_model=AgencyAccessRequestResponse,
)
@require_any_permission(Permission.TEAM_MANAGE)
async def deny_request(
    request: Request,
    request_id: str,
    body: ReviewRequestBody,
):
    """
    Deny an agency access request.

    Requires TEAM_MANAGE permission.
    Tenant admin can only deny requests for their own tenant.
    """
    tenant_context = get_tenant_context(request)
    db = _get_db_session(request)

    try:
        service = AgencyAccessService(db)

        # Validate the request belongs to the current tenant
        access_request = service._get_request(request_id)
        if access_request.tenant_id != tenant_context.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only deny requests for your own tenant",
            )

        result = service.deny_request(
            request_id=request_id,
            reviewed_by=tenant_context.user_id,
            review_note=body.review_note,
        )
        db.commit()

        logger.info(
            "Agency access request denied",
            extra={
                "request_id": request_id,
                "denied_by": tenant_context.user_id,
                "tenant_id": tenant_context.tenant_id,
            },
        )

        return AgencyAccessRequestResponse(**result)

    except RequestNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        )
    except InvalidStatusTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    finally:
        if not hasattr(request.state, "db"):
            db.close()


@router.get("/requests/mine", response_model=AgencyAccessRequestListResponse)
async def list_my_requests(request: Request):
    """
    List all access requests made by the current user.

    Used by agency users to track the status of their requests.

    Requires authentication only (no specific permission).
    """
    tenant_context = get_tenant_context(request)
    db = _get_db_session(request)

    try:
        from src.models.user import User

        user = db.query(User).filter(
            User.clerk_user_id == tenant_context.user_id
        ).first()
        if not user:
            return AgencyAccessRequestListResponse(requests=[], total_count=0)

        service = AgencyAccessService(db)
        results = service.list_requests_by_user(user.id)

        return AgencyAccessRequestListResponse(
            requests=[AgencyAccessRequestResponse(**r) for r in results],
            total_count=len(results),
        )
    finally:
        if not hasattr(request.state, "db"):
            db.close()


@router.post(
    "/requests/{request_id}/cancel",
    response_model=AgencyAccessRequestResponse,
)
async def cancel_request(
    request: Request,
    request_id: str,
):
    """
    Cancel a pending agency access request.

    Only the requesting user can cancel their own request.

    Requires authentication only (no specific permission).
    """
    tenant_context = get_tenant_context(request)
    db = _get_db_session(request)

    try:
        from src.models.user import User

        user = db.query(User).filter(
            User.clerk_user_id == tenant_context.user_id
        ).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        service = AgencyAccessService(db)
        result = service.cancel_request(
            request_id=request_id,
            cancelled_by=user.id,
        )
        db.commit()

        logger.info(
            "Agency access request cancelled",
            extra={
                "request_id": request_id,
                "cancelled_by": tenant_context.user_id,
            },
        )

        return AgencyAccessRequestResponse(**result)

    except RequestNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        )
    except InvalidStatusTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    finally:
        if not hasattr(request.state, "db"):
            db.close()
