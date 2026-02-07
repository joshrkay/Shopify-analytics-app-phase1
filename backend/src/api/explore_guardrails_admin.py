"""
Admin API for Explore guardrail bypass exceptions.

Endpoints:
- POST   /api/admin/explore-guardrails/requests
- POST   /api/admin/explore-guardrails/{exception_id}/approve
- POST   /api/admin/explore-guardrails/{exception_id}/revoke
- GET    /api/admin/explore-guardrails/active

SECURITY:
- Only super admins can request bypasses.
- Only analytics tech leads or security engineers can approve.
- Tenant isolation enforced via tenant_id from AuthContext.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.auth.context_resolver import AuthContext
from src.auth.middleware import require_auth
from src.database.session import get_db_session
from src.services.explore_guardrail_service import ExploreGuardrailService


router = APIRouter(prefix="/api/admin/explore-guardrails", tags=["admin", "guardrails"])


class GuardrailBypassRequest(BaseModel):
    user_id: str
    dataset_names: List[str]
    reason: str
    duration_minutes: int = Field(ge=1, le=60)


class GuardrailBypassResponse(BaseModel):
    id: str
    user_id: str
    dataset_names: List[str]
    reason: str
    status: str
    expires_at: datetime


class GuardrailBypassApproveResponse(BaseModel):
    id: str
    status: str
    approved_by: str
    approved_at: datetime


class GuardrailBypassRevokeResponse(BaseModel):
    id: str
    status: str
    revoked_at: datetime


def _get_roles(auth: AuthContext) -> List[str]:
    return list(auth.current_roles or [])


def _require_super_admin(auth: AuthContext) -> None:
    if not auth.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )


def _require_tenant(auth: AuthContext) -> str:
    if not auth.current_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context required",
        )
    return auth.current_tenant_id


@router.post(
    "/requests",
    response_model=GuardrailBypassResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a guardrail bypass",
)
async def request_guardrail_bypass(
    request: Request,
    body: GuardrailBypassRequest,
    auth: AuthContext = Depends(require_auth),
    db_session: Session = Depends(get_db_session),
):
    _require_super_admin(auth)
    tenant_id = _require_tenant(auth)

    service = ExploreGuardrailService(db_session=db_session, tenant_id=tenant_id)
    try:
        exception = service.request_exception(
            requestor_id=auth.user_id,
            requestor_roles=_get_roles(auth),
            user_id=body.user_id,
            dataset_names=body.dataset_names,
            reason=body.reason,
            duration_minutes=body.duration_minutes,
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return GuardrailBypassResponse(
        id=exception.id,
        user_id=exception.user_id,
        dataset_names=exception.dataset_names,
        reason=exception.reason,
        status=exception.status.value,
        expires_at=exception.expires_at,
    )


@router.post(
    "/{exception_id}/approve",
    response_model=GuardrailBypassApproveResponse,
    summary="Approve a guardrail bypass",
)
async def approve_guardrail_bypass(
    exception_id: str,
    auth: AuthContext = Depends(require_auth),
    db_session: Session = Depends(get_db_session),
):
    tenant_id = _require_tenant(auth)
    service = ExploreGuardrailService(db_session=db_session, tenant_id=tenant_id)
    try:
        exception = service.approve_exception(
            approver_id=auth.user_id,
            approver_roles=_get_roles(auth),
            exception_id=exception_id,
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return GuardrailBypassApproveResponse(
        id=exception.id,
        status=exception.status.value,
        approved_by=exception.approved_by or "",
        approved_at=exception.approved_at or datetime.now(timezone.utc),
    )


@router.post(
    "/{exception_id}/revoke",
    response_model=GuardrailBypassRevokeResponse,
    summary="Revoke a guardrail bypass",
)
async def revoke_guardrail_bypass(
    exception_id: str,
    auth: AuthContext = Depends(require_auth),
    db_session: Session = Depends(get_db_session),
):
    tenant_id = _require_tenant(auth)
    service = ExploreGuardrailService(db_session=db_session, tenant_id=tenant_id)
    try:
        exception = service.revoke_exception(
            actor_id=auth.user_id,
            actor_roles=_get_roles(auth),
            exception_id=exception_id,
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return GuardrailBypassRevokeResponse(
        id=exception.id,
        status=exception.status.value,
        revoked_at=exception.revoked_at or datetime.now(timezone.utc),
    )


@router.get(
    "/active",
    response_model=List[GuardrailBypassResponse],
    summary="List active guardrail bypasses",
)
async def list_active_guardrail_bypasses(
    auth: AuthContext = Depends(require_auth),
    db_session: Session = Depends(get_db_session),
    user_id: Optional[str] = None,
):
    tenant_id = _require_tenant(auth)
    service = ExploreGuardrailService(db_session=db_session, tenant_id=tenant_id)
    exceptions = service.list_active_exceptions(user_id=user_id)
    return [
        GuardrailBypassResponse(
            id=exception.id,
            user_id=exception.user_id,
            dataset_names=exception.dataset_names,
            reason=exception.reason,
            status=exception.status.value,
            expires_at=exception.expires_at,
        )
        for exception in exceptions
    ]
