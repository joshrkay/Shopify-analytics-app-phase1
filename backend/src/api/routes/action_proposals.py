"""
Action Proposals API routes.

Provides endpoints for:
- Listing action proposals
- Getting single proposal with details
- Approving/rejecting proposals
- Viewing audit trail

SECURITY:
- All routes require valid tenant context from JWT
- Proposals are tenant-scoped - users can only see their own
- Only MERCHANT_ADMIN and AGENCY_ADMIN can approve/reject
- Entitlement check enforced for AI_ACTIONS feature

NO AUTO-EXECUTION:
- This API handles approval workflow only
- Actual action execution is a separate concern

Story 8.4 - Action Proposals (Approval Required)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session
from src.models.action_proposal import (
    ActionProposal,
    ActionType,
    ActionStatus,
    TargetPlatform,
)
from src.models.ai_recommendation import RiskLevel
from src.services.billing_entitlements import (
    BillingEntitlementsService,
    BillingFeature,
)
from src.services.action_proposal_approval_service import (
    ActionProposalApprovalService,
    NotFoundError,
    PermissionDeniedError,
    ApprovalError,
)
from src.constants.permissions import (
    can_view_action_proposals,
    can_approve_action_proposals,
    can_view_action_proposal_audit,
)
from src.api.schemas.action_proposals import (
    ActionProposalResponse,
    ActionProposalsListResponse,
    ProposalActionResponse,
    ApproveRejectRequest,
    AuditEntryResponse,
    AuditTrailResponse,
    TargetInfo,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/action-proposals", tags=["action-proposals"])


# =============================================================================
# Dependencies
# =============================================================================


def check_ai_actions_entitlement(
    request: Request,
    db_session=Depends(get_db_session),
):
    """
    Dependency to check AI actions entitlement.

    Raises 402 Payment Required if tenant is not entitled.
    """
    tenant_ctx = get_tenant_context(request)
    service = BillingEntitlementsService(db_session, tenant_ctx.tenant_id)
    result = service.check_feature_entitlement(BillingFeature.AI_ACTIONS)

    if not result.is_entitled:
        logger.warning(
            "AI actions access denied - not entitled",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "current_tier": result.current_tier,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Action Proposals requires a {result.required_tier or 'Growth'} plan",
        )

    return db_session


def check_view_permission(request: Request):
    """Check if user has permission to view action proposals."""
    tenant_ctx = get_tenant_context(request)

    if not can_view_action_proposals(tenant_ctx.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view action proposals",
        )


def check_approve_permission(request: Request):
    """Check if user has permission to approve/reject action proposals."""
    tenant_ctx = get_tenant_context(request)

    if not can_approve_action_proposals(tenant_ctx.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to approve or reject action proposals",
        )


def check_audit_permission(request: Request):
    """Check if user has permission to view audit trail."""
    tenant_ctx = get_tenant_context(request)

    if not can_view_action_proposal_audit(tenant_ctx.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view audit trail",
        )


# =============================================================================
# Helper Functions
# =============================================================================


def _proposal_to_response(proposal: ActionProposal) -> ActionProposalResponse:
    """Convert ActionProposal model to response model."""
    return ActionProposalResponse(
        proposal_id=proposal.id,
        action_type=proposal.action_type.value if proposal.action_type else "",
        status=proposal.status.value if proposal.status else "",
        target=TargetInfo(
            platform=proposal.target_platform.value if proposal.target_platform else "",
            entity_type=proposal.target_entity_type.value if proposal.target_entity_type else "",
            entity_id=proposal.target_entity_id or "",
            entity_name=proposal.target_entity_name,
        ),
        proposed_change=proposal.proposed_change or {},
        current_value=proposal.current_value,
        expected_effect=proposal.expected_effect or "",
        risk_disclaimer=proposal.risk_disclaimer or "",
        risk_level=proposal.risk_level.value if proposal.risk_level else "",
        confidence_score=proposal.confidence_score or 0,
        requires_approval=True,  # Always true
        expires_at=proposal.expires_at,
        created_at=proposal.created_at,
        decided_at=proposal.decided_at,
        decided_by=proposal.decided_by_user_id,
        decision_reason=proposal.decision_reason,
        source_recommendation_id=proposal.source_recommendation_id,
    )


# =============================================================================
# Routes
# =============================================================================


@router.get(
    "",
    response_model=ActionProposalsListResponse,
    dependencies=[Depends(check_view_permission)],
)
async def list_action_proposals(
    request: Request,
    db_session=Depends(check_ai_actions_entitlement),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filter by status"
    ),
    action_type: Optional[str] = Query(
        None, description="Filter by action type"
    ),
    platform: Optional[str] = Query(
        None, description="Filter by platform (meta, google, tiktok)"
    ),
    risk_level: Optional[str] = Query(
        None, description="Filter by risk level (low, medium, high)"
    ),
    limit: int = Query(20, le=100, description="Maximum proposals to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """
    List action proposals for the current tenant.

    Proposals are sorted by created_at (newest first).
    By default returns all proposals; use status filter to get only pending.

    SECURITY: Only returns proposals belonging to the authenticated tenant.
    Requires AI_ACTIONS entitlement and ACTION_PROPOSALS_VIEW permission.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Action proposals list requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "status": status_filter,
            "action_type": action_type,
        },
    )

    # Create approval service for listing
    service = ActionProposalApprovalService(db_session, tenant_ctx.tenant_id)

    # Parse status if provided
    status_enum = None
    if status_filter:
        try:
            status_enum = ActionStatus(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}",
            )

    # Get proposals
    proposals, total = service.list_proposals(
        status=status_enum,
        action_type=action_type,
        platform=platform,
        risk_level=risk_level,
        limit=limit + 1,  # Fetch one extra to check has_more
        offset=offset,
    )

    has_more = len(proposals) > limit
    proposals = proposals[:limit]

    # Get pending count
    pending_count = service.get_pending_count()

    return ActionProposalsListResponse(
        proposals=[_proposal_to_response(p) for p in proposals],
        total=total,
        has_more=has_more,
        pending_count=pending_count,
    )


@router.get(
    "/{proposal_id}",
    response_model=ActionProposalResponse,
    dependencies=[Depends(check_view_permission)],
)
async def get_action_proposal(
    request: Request,
    proposal_id: str,
    db_session=Depends(check_ai_actions_entitlement),
):
    """
    Get a single action proposal by ID.

    SECURITY: Only returns proposal if it belongs to the authenticated tenant.
    Requires AI_ACTIONS entitlement and ACTION_PROPOSALS_VIEW permission.
    """
    tenant_ctx = get_tenant_context(request)

    service = ActionProposalApprovalService(db_session, tenant_ctx.tenant_id)
    proposal = service.get_proposal(proposal_id)

    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action proposal not found",
        )

    return _proposal_to_response(proposal)


@router.post(
    "/{proposal_id}/approve",
    response_model=ProposalActionResponse,
    dependencies=[Depends(check_approve_permission)],
)
async def approve_action_proposal(
    request: Request,
    proposal_id: str,
    body: Optional[ApproveRejectRequest] = None,
    db_session=Depends(check_ai_actions_entitlement),
):
    """
    Approve an action proposal.

    Only users with MERCHANT_ADMIN or AGENCY_ADMIN role can approve.
    Approved proposals can then be executed (in a separate step).

    SECURITY:
    - Requires AI_ACTIONS entitlement
    - Requires ACTION_PROPOSALS_APPROVE permission
    - Creates audit trail entry
    """
    tenant_ctx = get_tenant_context(request)

    # Get client info for audit
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    service = ActionProposalApprovalService(db_session, tenant_ctx.tenant_id)

    try:
        proposal = service.approve_proposal(
            proposal_id=proposal_id,
            user_id=tenant_ctx.user_id,
            user_roles=tenant_ctx.roles,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db_session.commit()

        logger.info(
            "Action proposal approved via API",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "proposal_id": proposal_id,
                "user_id": tenant_ctx.user_id,
            },
        )

        return ProposalActionResponse(
            status="ok",
            proposal_id=proposal_id,
            new_status=proposal.status.value,
        )

    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action proposal not found",
        )
    except PermissionDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except ApprovalError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/{proposal_id}/reject",
    response_model=ProposalActionResponse,
    dependencies=[Depends(check_approve_permission)],
)
async def reject_action_proposal(
    request: Request,
    proposal_id: str,
    body: Optional[ApproveRejectRequest] = None,
    db_session=Depends(check_ai_actions_entitlement),
):
    """
    Reject an action proposal.

    Only users with MERCHANT_ADMIN or AGENCY_ADMIN role can reject.
    An optional reason can be provided for the rejection.

    SECURITY:
    - Requires AI_ACTIONS entitlement
    - Requires ACTION_PROPOSALS_APPROVE permission
    - Creates audit trail entry
    """
    tenant_ctx = get_tenant_context(request)

    # Get client info for audit
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    reason = body.reason if body else None

    service = ActionProposalApprovalService(db_session, tenant_ctx.tenant_id)

    try:
        proposal = service.reject_proposal(
            proposal_id=proposal_id,
            user_id=tenant_ctx.user_id,
            user_roles=tenant_ctx.roles,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db_session.commit()

        logger.info(
            "Action proposal rejected via API",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "proposal_id": proposal_id,
                "user_id": tenant_ctx.user_id,
                "reason": reason,
            },
        )

        return ProposalActionResponse(
            status="ok",
            proposal_id=proposal_id,
            new_status=proposal.status.value,
        )

    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action proposal not found",
        )
    except PermissionDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except ApprovalError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/{proposal_id}/audit",
    response_model=AuditTrailResponse,
    dependencies=[Depends(check_audit_permission)],
)
async def get_proposal_audit_trail(
    request: Request,
    proposal_id: str,
    db_session=Depends(check_ai_actions_entitlement),
):
    """
    Get the audit trail for an action proposal.

    Returns all state changes for the proposal in chronological order.

    SECURITY:
    - Requires AI_ACTIONS entitlement
    - Requires ACTION_PROPOSALS_AUDIT permission
    - Only admin roles can view audit trail
    """
    tenant_ctx = get_tenant_context(request)

    service = ActionProposalApprovalService(db_session, tenant_ctx.tenant_id)

    # Check proposal exists
    proposal = service.get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action proposal not found",
        )

    # Get audit trail
    audit_entries = service.get_audit_trail(proposal_id)

    return AuditTrailResponse(
        proposal_id=proposal_id,
        entries=[
            AuditEntryResponse(
                id=entry.id,
                action=entry.action.value if entry.action else "",
                performed_at=entry.performed_at,
                performed_by=entry.performed_by_user_id,
                performed_by_role=entry.performed_by_role,
                previous_status=entry.previous_status.value if entry.previous_status else None,
                new_status=entry.new_status.value if entry.new_status else "",
                reason=entry.reason,
            )
            for entry in audit_entries
        ],
    )


@router.get(
    "/stats/pending",
    response_model=dict,
    dependencies=[Depends(check_view_permission)],
)
async def get_pending_proposals_count(
    request: Request,
    db_session=Depends(check_ai_actions_entitlement),
):
    """
    Get count of pending action proposals.

    Useful for displaying badge counts in the UI.

    SECURITY: Returns count only for the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    service = ActionProposalApprovalService(db_session, tenant_ctx.tenant_id)
    count = service.get_pending_count()

    return {"pending_count": count}
