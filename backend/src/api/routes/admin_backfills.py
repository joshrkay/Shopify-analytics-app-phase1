"""
Admin Backfill Request API.

SECURITY CRITICAL:
- All endpoints require super admin status (DB-verified, not JWT)
- tenant_id is the TARGET tenant, not the caller's tenant
- All operations are audit-logged

Story 3.4 - Backfill Request API
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.auth.middleware import require_auth
from src.auth.context_resolver import AuthContext
from src.database.session import get_db_session
from src.services.super_admin_service import SuperAdminService
from src.api.schemas.backfill_request import (
    CreateBackfillRequest,
    BackfillRequestCreatedResponse,
    BackfillRequestResponse,
)
from src.services.backfill_validator import (
    BackfillValidator,
    BackfillValidationError,
    TenantNotFoundError,
    TenantNotActiveError,
    DateRangeExceededError,
    OverlappingBackfillError,
    compute_idempotency_key,
)
from src.models.historical_backfill import (
    HistoricalBackfillRequest,
    HistoricalBackfillStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/backfills", tags=["admin-backfills"])


def require_super_admin(
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db_session),
) -> tuple[AuthContext, Session]:
    """
    Dependency requiring super admin status from database.

    SECURITY: Checks database directly, ignoring JWT claims.
    """
    service = SuperAdminService(
        session=db,
        actor_clerk_user_id=auth.clerk_user_id,
        correlation_id=getattr(request.state, "correlation_id", None),
    )

    if not service.is_super_admin():
        logger.warning(
            "Non-super-admin attempted admin backfill endpoint",
            extra={
                "clerk_user_id": auth.clerk_user_id,
                "path": request.url.path,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )

    return auth, db


@router.post(
    "",
    response_model=BackfillRequestCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a historical backfill",
    description="Super admin only. Creates a backfill request for a tenant and source system.",
    responses={
        200: {"description": "Idempotent match - existing request returned"},
        201: {"description": "New backfill request created"},
        400: {"description": "Validation error"},
        403: {"description": "Not a super admin"},
        404: {"description": "Target tenant not found"},
        409: {"description": "Overlapping active backfill exists"},
    },
)
async def create_backfill_request(
    request: Request,
    body: CreateBackfillRequest,
    deps: tuple[AuthContext, Session] = Depends(require_super_admin),
):
    """
    Request a historical data backfill for a tenant.

    Idempotent: Same (tenant_id, source_system, start_date, end_date)
    returns the same backfill request record.
    """
    auth, db = deps
    correlation_id = (
        getattr(request.state, "correlation_id", None) or str(uuid.uuid4())
    )

    logger.info(
        "Admin backfill request received",
        extra={
            "admin_clerk_user_id": auth.clerk_user_id,
            "target_tenant_id": body.tenant_id,
            "source_system": body.source_system.value,
            "start_date": body.start_date.isoformat(),
            "end_date": body.end_date.isoformat(),
            "correlation_id": correlation_id,
        },
    )

    validator = BackfillValidator(db)

    try:
        existing, is_new = validator.validate_and_prepare(
            tenant_id=body.tenant_id,
            source_system=body.source_system.value,
            start_date=body.start_date,
            end_date=body.end_date,
        )

        if not is_new and existing:
            from src.services.audit_logger import emit_backfill_requested

            emit_backfill_requested(
                db, existing, correlation_id=correlation_id,
            )

            response_data = BackfillRequestCreatedResponse(
                backfill_request=_to_response(existing),
                created=False,
                message="Existing backfill request returned (idempotent match)",
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=response_data.model_dump(mode="json"),
            )

        # Create new backfill request
        idempotency_key = compute_idempotency_key(
            body.tenant_id,
            body.source_system.value,
            body.start_date,
            body.end_date,
        )

        new_request = HistoricalBackfillRequest(
            tenant_id=body.tenant_id,
            source_system=body.source_system.value,
            start_date=body.start_date,
            end_date=body.end_date,
            status=HistoricalBackfillStatus.PENDING,
            reason=body.reason,
            requested_by=auth.clerk_user_id,
            idempotency_key=idempotency_key,
        )

        db.add(new_request)
        db.flush()

        from src.services.audit_logger import emit_backfill_requested

        emit_backfill_requested(
            db, new_request, correlation_id=correlation_id,
        )

        logger.info(
            "Admin backfill request created",
            extra={
                "backfill_id": new_request.id,
                "tenant_id": body.tenant_id,
                "source_system": body.source_system.value,
                "admin_clerk_user_id": auth.clerk_user_id,
                "correlation_id": correlation_id,
            },
        )

        return BackfillRequestCreatedResponse(
            backfill_request=_to_response(new_request),
            created=True,
            message="Backfill request created successfully",
        )

    except TenantNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except TenantNotActiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except DateRangeExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except OverlappingBackfillError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except BackfillValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


def _to_response(record: HistoricalBackfillRequest) -> BackfillRequestResponse:
    """Convert model to response schema."""
    status_val = (
        record.status.value
        if isinstance(record.status, HistoricalBackfillStatus)
        else record.status
    )
    return BackfillRequestResponse(
        id=record.id,
        tenant_id=record.tenant_id,
        source_system=record.source_system,
        start_date=record.start_date.isoformat() if record.start_date else "",
        end_date=record.end_date.isoformat() if record.end_date else "",
        status=status_val,
        reason=record.reason,
        requested_by=record.requested_by,
        idempotency_key=record.idempotency_key,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


