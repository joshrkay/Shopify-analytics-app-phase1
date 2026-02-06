"""
Admin Backfill Status API — exposes backfill progress to operators.

SECURITY CRITICAL:
- All endpoints require super admin status (DB-verified, not JWT)
- Reuses require_super_admin from admin_backfills module

Story 3.4 - Backfill Status API
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.auth.context_resolver import AuthContext
from src.api.routes.admin_backfills import require_super_admin
from src.api.schemas.backfill_request import (
    BackfillStatusResponse,
    BackfillStatusListResponse,
)
from src.services.backfill_status_service import BackfillStatusService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/backfills",
    tags=["admin-backfills"],
)


@router.get(
    "",
    response_model=BackfillStatusListResponse,
    summary="List backfill requests with status",
    description="Super admin only. Returns all backfill requests with computed progress.",
    responses={
        403: {"description": "Not a super admin"},
    },
)
async def list_backfill_statuses(
    tenant_id: Optional[str] = Query(
        None, description="Filter by target tenant ID"
    ),
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="Filter by effective status: pending, running, paused, failed, completed",
    ),
    deps: tuple[AuthContext, Session] = Depends(require_super_admin),
):
    """List backfill requests with computed status, progress, and ETA."""
    _, db = deps

    service = BackfillStatusService(db)
    results = service.list_requests(
        tenant_id=tenant_id,
        status_filter=status_filter,
    )

    return BackfillStatusListResponse(
        backfills=[BackfillStatusResponse(**r) for r in results],
        total=len(results),
    )


@router.get(
    "/{request_id}/status",
    response_model=BackfillStatusResponse,
    summary="Get detailed backfill status",
    description="Super admin only. Returns detailed status including progress, current chunk, and ETA.",
    responses={
        403: {"description": "Not a super admin"},
        404: {"description": "Backfill request not found"},
    },
)
async def get_backfill_status(
    request_id: str,
    deps: tuple[AuthContext, Session] = Depends(require_super_admin),
):
    """Get detailed status for a single backfill request."""
    _, db = deps

    service = BackfillStatusService(db)
    result = service.get_request_status(request_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Backfill request {request_id} not found",
        )

    return BackfillStatusResponse(**result)
