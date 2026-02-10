"""
Dashboard Shares API - Endpoints for sharing custom dashboards.

Mounted at /api/v1/dashboards/{dashboard_id}/shares

All endpoints require owner or admin access to the dashboard.

Phase: Custom Reports & Dashboard Builder
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Depends, status

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session
from src.services.dashboard_share_service import (
    DashboardShareService,
    ShareNotFoundError,
    ShareConflictError,
    ShareValidationError,
)
from src.services.custom_dashboard_service import DashboardNotFoundError
from src.api.schemas.custom_dashboards import (
    CreateShareRequest,
    UpdateShareRequest,
    ShareResponse,
    ShareListResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/dashboards/{dashboard_id}/shares",
    tags=["dashboard-shares"],
)


def _get_share_service(request: Request, db=Depends(get_db_session)) -> DashboardShareService:
    ctx = get_tenant_context(request)
    return DashboardShareService(db, ctx.tenant_id, ctx.user_id)


def _share_to_response(share) -> ShareResponse:
    """Convert a DashboardShare model to response, computing is_expired."""
    now = datetime.now(timezone.utc)
    is_expired = False
    if share.expires_at is not None:
        expiry = share.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        is_expired = expiry < now

    return ShareResponse(
        id=share.id,
        dashboard_id=share.dashboard_id,
        shared_with_user_id=share.shared_with_user_id,
        shared_with_role=share.shared_with_role,
        permission=share.permission,
        granted_by=share.granted_by,
        expires_at=share.expires_at,
        is_expired=is_expired,
        created_at=share.created_at,
        updated_at=share.updated_at,
    )


@router.get("", response_model=ShareListResponse)
async def list_shares(
    dashboard_id: str,
    request: Request,
    service: DashboardShareService = Depends(_get_share_service),
):
    """List all shares for a dashboard."""
    try:
        shares, total = service.list_shares(dashboard_id)
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    return ShareListResponse(
        shares=[_share_to_response(s) for s in shares],
        total=total,
    )


@router.post("", response_model=ShareResponse, status_code=201)
async def create_share(
    dashboard_id: str,
    body: CreateShareRequest,
    request: Request,
    service: DashboardShareService = Depends(_get_share_service),
):
    """Share a dashboard with a user or role."""
    try:
        share = service.create_share(
            dashboard_id=dashboard_id,
            permission=body.permission,
            shared_with_user_id=body.shared_with_user_id,
            shared_with_role=body.shared_with_role,
            expires_at=body.expires_at,
        )
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    except ShareValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ShareConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return _share_to_response(share)


@router.put("/{share_id}", response_model=ShareResponse)
async def update_share(
    dashboard_id: str,
    share_id: str,
    body: UpdateShareRequest,
    request: Request,
    service: DashboardShareService = Depends(_get_share_service),
):
    """Update a share's permission or expiry."""
    try:
        share = service.update_share(
            dashboard_id=dashboard_id,
            share_id=share_id,
            permission=body.permission,
            expires_at=body.expires_at,
        )
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    except ShareNotFoundError:
        raise HTTPException(status_code=404, detail="Share not found")

    return _share_to_response(share)


@router.delete("/{share_id}", status_code=204)
async def revoke_share(
    dashboard_id: str,
    share_id: str,
    request: Request,
    service: DashboardShareService = Depends(_get_share_service),
):
    """Revoke a dashboard share."""
    try:
        service.revoke_share(dashboard_id, share_id)
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    except ShareNotFoundError:
        raise HTTPException(status_code=404, detail="Share not found")
