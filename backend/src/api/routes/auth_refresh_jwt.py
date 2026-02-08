"""
JWT Refresh endpoint for tenant context switching.

Issues a new JWT when an agency user switches active tenant.
Validates tenant access against DB (not just JWT claims).
Includes access_surface claim and grace period banner flag.

Story 5.5.3 - Tenant Selector + JWT Refresh for Active Tenant Context
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, status
from pydantic import BaseModel, Field

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session_sync
from src.models.user_tenant_roles import UserTenantRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# --- Request/Response Models ---


class RefreshJWTRequest(BaseModel):
    """Request body for JWT refresh."""
    tenant_id: str = Field(..., description="Target tenant ID to switch to")
    access_surface: str = Field(
        default="external_app",
        description="Access surface: shopify_embed or external_app",
    )


class RefreshJWTResponse(BaseModel):
    """Response after JWT refresh."""
    jwt_token: str
    active_tenant_id: str
    access_surface: str
    access_expiring_at: Optional[str] = None


# --- Endpoint ---


@router.post("/refresh-jwt", response_model=RefreshJWTResponse)
async def refresh_jwt(request: Request, body: RefreshJWTRequest):
    """
    Refresh JWT with updated tenant context.

    Issues a new JWT when switching active tenant. Validates:
    1. Target tenant is in allowed_tenants
    2. User has active DB access to target tenant
    3. Access is not expired (grace period check)

    Returns access_expiring_at if tenant is in grace period revocation.
    Returns 403 if access has expired.
    """
    tenant_context = get_tenant_context(request)
    target_tenant_id = body.tenant_id

    # Validate target tenant is in allowed_tenants
    if not tenant_context.can_access_tenant(target_tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this tenant",
        )

    db = next(get_db_session_sync())
    try:
        # Validate active DB access
        from src.models.user import User

        user = db.query(User).filter(
            User.clerk_user_id == tenant_context.user_id
        ).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        active_role = (
            db.query(UserTenantRole)
            .filter(
                UserTenantRole.user_id == user.id,
                UserTenantRole.tenant_id == target_tenant_id,
                UserTenantRole.is_active == True,  # noqa: E712
            )
            .first()
        )
        if not active_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No active access to this tenant",
            )

        # Check grace period revocation (Story 5.5.4)
        access_expiring_at = None
        try:
            from src.services.access_revocation_service import AccessRevocationService

            revocation_service = AccessRevocationService(db)
            revocation = revocation_service.get_active_revocation(
                user.id, target_tenant_id
            )
            if revocation:
                if revocation.get("is_expired"):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Access to this tenant has expired",
                        headers={"X-Error-Code": "ACCESS_EXPIRED"},
                    )
                access_expiring_at_str = revocation.get("grace_period_ends_at")
                if access_expiring_at_str:
                    from datetime import datetime

                    access_expiring_at = datetime.fromisoformat(
                        access_expiring_at_str
                    )
        except ImportError:
            pass  # Service not yet available during incremental deployment

        # Generate new JWT
        from src.api.routes.agency import _generate_jwt_token

        new_token = _generate_jwt_token(
            user_id=tenant_context.user_id,
            tenant_id=target_tenant_id,
            roles=tenant_context.roles,
            allowed_tenants=tenant_context.allowed_tenants,
            billing_tier=tenant_context.billing_tier,
            org_id=tenant_context.org_id,
            access_surface=body.access_surface,
            access_expiring_at=access_expiring_at,
        )

        # Update active tenant in user metadata
        try:
            from src.services.tenant_selection_service import TenantSelectionService

            selection_service = TenantSelectionService(db)
            selection_service.set_active_tenant(
                clerk_user_id=tenant_context.user_id,
                tenant_id=target_tenant_id,
            )
        except Exception:
            logger.debug(
                "Active tenant metadata update skipped",
                extra={"user_id": tenant_context.user_id},
                exc_info=True,
            )

        # Emit audit events
        previous_tenant_id = tenant_context.tenant_id
        try:
            from src.services.audit_logger import (
                emit_jwt_refresh,
                emit_tenant_context_switched,
            )

            emit_jwt_refresh(
                db=db,
                tenant_id=target_tenant_id,
                user_id=tenant_context.user_id,
                previous_tenant_id=previous_tenant_id,
                access_surface=body.access_surface,
            )
            if target_tenant_id != previous_tenant_id:
                emit_tenant_context_switched(
                    db=db,
                    tenant_id=target_tenant_id,
                    user_id=tenant_context.user_id,
                    previous_tenant_id=previous_tenant_id,
                )
        except Exception:
            logger.debug("Audit event emission skipped", exc_info=True)

        db.commit()

        logger.info(
            "JWT refreshed for tenant switch",
            extra={
                "user_id": tenant_context.user_id,
                "from_tenant_id": previous_tenant_id,
                "to_tenant_id": target_tenant_id,
                "access_surface": body.access_surface,
            },
        )

        return RefreshJWTResponse(
            jwt_token=new_token,
            active_tenant_id=target_tenant_id,
            access_surface=body.access_surface,
            access_expiring_at=(
                access_expiring_at.isoformat() if access_expiring_at else None
            ),
        )

    finally:
        db.close()
