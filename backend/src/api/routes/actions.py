"""
Actions API routes for Story 8.5.

Provides endpoints for:
- Listing actions and their status
- Getting action details and execution logs
- Triggering action execution
- Rolling back executed actions
- Viewing action jobs

SECURITY:
- All routes require valid tenant context from JWT
- Actions are tenant-scoped - users can only see their own
- Execute/rollback require appropriate permissions
- Entitlement check enforced for AI_ACTIONS feature

EXTERNAL PLATFORM IS SOURCE OF TRUTH:
- All state confirmations come from the platform
- No blind retries - user must explicitly re-trigger

Story 8.5 - Action Execution (Scoped & Reversible)
"""

import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session
from src.models.ai_action import AIAction, ActionStatus, ActionType
from src.models.action_execution_log import ActionExecutionLog
from src.models.action_job import ActionJob, ActionJobStatus
from src.api.dependencies.entitlements import check_ai_actions_entitlement
from src.services.action_execution_service import ActionExecutionService
from src.services.action_rollback_service import ActionRollbackService
from src.services.action_job_dispatcher import ActionJobDispatcher
from src.constants.permissions import (
    can_view_actions,
    can_execute_actions,
    can_rollback_actions,
    can_view_action_audit,
)
from src.api.schemas.actions import (
    ActionResponse,
    ActionsListResponse,
    ActionExecutionResponse,
    ActionRollbackResponse,
    ExecutionLogEntry,
    ExecutionLogsResponse,
    ActionJobResponse,
    ActionJobsListResponse,
    ActionStatsResponse,
    ActionTargetInfo,
    RollbackActionRequest,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/actions", tags=["actions"])


# =============================================================================
# Dependencies
# =============================================================================


def check_view_permission(request: Request):
    """Check if user has permission to view actions."""
    tenant_ctx = get_tenant_context(request)

    if not can_view_actions(tenant_ctx.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view actions",
        )


def check_execute_permission(request: Request):
    """Check if user has permission to execute actions."""
    tenant_ctx = get_tenant_context(request)

    if not can_execute_actions(tenant_ctx.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to execute actions",
        )


def check_rollback_permission(request: Request):
    """Check if user has permission to rollback actions."""
    tenant_ctx = get_tenant_context(request)

    if not can_rollback_actions(tenant_ctx.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to rollback actions",
        )


def check_audit_permission(request: Request):
    """Check if user has permission to view execution logs."""
    tenant_ctx = get_tenant_context(request)

    if not can_view_action_audit(tenant_ctx.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view execution logs",
        )


# =============================================================================
# Helper Functions
# =============================================================================


def _action_to_response(action: AIAction) -> ActionResponse:
    """Convert AIAction model to response model."""
    return ActionResponse(
        action_id=action.id,
        action_type=action.action_type.value if action.action_type else "",
        status=action.status.value if action.status else "",
        platform=action.platform or "",
        target=ActionTargetInfo(
            platform=action.platform or "",
            entity_type=action.target_entity_type.value if action.target_entity_type else "",
            entity_id=action.target_entity_id or "",
        ),
        action_params=action.action_params or {},
        approved_by=action.approved_by,
        approved_at=action.approved_at,
        execution_started_at=action.execution_started_at,
        execution_completed_at=action.execution_completed_at,
        before_state=action.before_state,
        after_state=action.after_state,
        can_rollback=action.can_be_rolled_back,
        rollback_executed_at=action.rollback_executed_at,
        error_message=action.error_message,
        error_code=action.error_code,
        retry_count=action.retry_count,
        recommendation_id=action.recommendation_id,
        job_id=action.job_id,
        created_at=action.created_at,
        updated_at=action.updated_at,
    )


def _job_to_response(job: ActionJob) -> ActionJobResponse:
    """Convert ActionJob model to response model."""
    return ActionJobResponse(
        job_id=job.job_id,
        status=job.status.value if job.status else "",
        action_count=len(job.action_ids) if job.action_ids else 0,
        succeeded_count=job.succeeded_count or 0,
        failed_count=job.failed_count or 0,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        created_at=job.created_at,
    )


# =============================================================================
# Action Routes
# =============================================================================


@router.get(
    "",
    response_model=ActionsListResponse,
    dependencies=[Depends(check_view_permission)],
)
async def list_actions(
    request: Request,
    db_session=Depends(check_ai_actions_entitlement),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filter by status"
    ),
    action_type: Optional[str] = Query(
        None, description="Filter by action type"
    ),
    platform: Optional[str] = Query(
        None, description="Filter by platform (meta, google, shopify)"
    ),
    limit: int = Query(20, le=100, description="Maximum actions to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """
    List actions for the current tenant.

    Actions are sorted by created_at (newest first).

    SECURITY: Only returns actions belonging to the authenticated tenant.
    Requires AI_ACTIONS entitlement and ACTIONS_VIEW permission.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Actions list requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "status": status_filter,
            "action_type": action_type,
        },
    )

    # Build query
    query = (
        db_session.query(AIAction)
        .filter(AIAction.tenant_id == tenant_ctx.tenant_id)
    )

    # Apply filters
    if status_filter:
        try:
            status_enum = ActionStatus(status_filter)
            query = query.filter(AIAction.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}",
            )

    if action_type:
        try:
            type_enum = ActionType(action_type)
            query = query.filter(AIAction.action_type == type_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid action type: {action_type}",
            )

    if platform:
        query = query.filter(AIAction.platform == platform)

    # Get total count
    total = query.count()

    # Get paginated results
    actions = (
        query
        .order_by(AIAction.created_at.desc())
        .offset(offset)
        .limit(limit + 1)
        .all()
    )

    has_more = len(actions) > limit
    actions = actions[:limit]

    return ActionsListResponse(
        actions=[_action_to_response(a) for a in actions],
        total=total,
        has_more=has_more,
    )


@router.get(
    "/stats",
    response_model=ActionStatsResponse,
    dependencies=[Depends(check_view_permission)],
)
async def get_action_stats(
    request: Request,
    db_session=Depends(check_ai_actions_entitlement),
):
    """
    Get action statistics for the current tenant.

    Includes counts by status and monthly usage.

    SECURITY: Returns stats only for the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    # Count by status
    from sqlalchemy import func

    status_counts = (
        db_session.query(AIAction.status, func.count(AIAction.id))
        .filter(AIAction.tenant_id == tenant_ctx.tenant_id)
        .group_by(AIAction.status)
        .all()
    )

    counts = {status.value: count for status, count in status_counts}

    # Get monthly usage
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    actions_this_month = (
        db_session.query(func.count(AIAction.id))
        .filter(
            AIAction.tenant_id == tenant_ctx.tenant_id,
            AIAction.execution_completed_at >= month_start,
            AIAction.status.in_([
                ActionStatus.SUCCEEDED,
                ActionStatus.PARTIALLY_EXECUTED,
            ]),
        )
        .scalar()
    ) or 0

    # Get monthly limit from billing
    service = BillingEntitlementsService(db_session, tenant_ctx.tenant_id)
    result = service.check_feature_entitlement(BillingFeature.AI_ACTIONS)
    monthly_limit = result.details.get("monthly_limit") if result.details else None

    return ActionStatsResponse(
        total_actions=sum(counts.values()),
        pending_approval=counts.get("pending_approval", 0),
        approved=counts.get("approved", 0),
        queued=counts.get("queued", 0),
        executing=counts.get("executing", 0),
        succeeded=counts.get("succeeded", 0),
        failed=counts.get("failed", 0),
        rolled_back=counts.get("rolled_back", 0),
        actions_this_month=actions_this_month,
        monthly_limit=monthly_limit,
    )


@router.get(
    "/{action_id}",
    response_model=ActionResponse,
    dependencies=[Depends(check_view_permission)],
)
async def get_action(
    request: Request,
    action_id: str,
    db_session=Depends(check_ai_actions_entitlement),
):
    """
    Get a single action by ID.

    SECURITY: Only returns action if it belongs to the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    action = (
        db_session.query(AIAction)
        .filter(
            AIAction.id == action_id,
            AIAction.tenant_id == tenant_ctx.tenant_id,
        )
        .first()
    )

    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action not found",
        )

    return _action_to_response(action)


@router.post(
    "/{action_id}/execute",
    response_model=ActionExecutionResponse,
    dependencies=[Depends(check_execute_permission)],
)
async def execute_action(
    request: Request,
    action_id: str,
    db_session=Depends(check_ai_actions_entitlement),
):
    """
    Trigger execution of an approved action.

    The action must be in APPROVED or QUEUED status.
    Execution is performed synchronously and confirms with external platform.

    SECURITY:
    - Requires AI_ACTIONS entitlement
    - Requires ACTIONS_EXECUTE permission
    - Creates audit trail entry

    EXTERNAL PLATFORM IS SOURCE OF TRUTH:
    - State is captured before and after execution
    - Platform response determines success/failure
    """
    tenant_ctx = get_tenant_context(request)

    # Verify action exists and belongs to tenant
    action = (
        db_session.query(AIAction)
        .filter(
            AIAction.id == action_id,
            AIAction.tenant_id == tenant_ctx.tenant_id,
        )
        .first()
    )

    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action not found",
        )

    if not action.can_be_executed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action cannot be executed in status {action.status.value}",
        )

    # Execute the action
    execution_service = ActionExecutionService(db_session, tenant_ctx.tenant_id)

    try:
        result = await execution_service.execute_action(action)
        db_session.commit()

        logger.info(
            "Action executed via API",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "action_id": action_id,
                "user_id": tenant_ctx.user_id,
                "result_status": result.status.value if result else None,
            },
        )

        if result and result.status.value == "success":
            return ActionExecutionResponse(
                status="ok",
                action_id=action_id,
                job_id=action.job_id,
                new_status=action.status.value,
                message="Action executed successfully",
            )
        else:
            return ActionExecutionResponse(
                status="error",
                action_id=action_id,
                job_id=action.job_id,
                new_status=action.status.value,
                message=result.error_message if result else "Execution failed",
            )

    except Exception as e:
        logger.error(
            "Action execution failed",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "action_id": action_id,
                "error": str(e),
            },
            exc_info=True,
        )
        db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Action execution failed. Please try again.",
        )


@router.post(
    "/{action_id}/rollback",
    response_model=ActionRollbackResponse,
    dependencies=[Depends(check_rollback_permission)],
)
async def rollback_action(
    request: Request,
    action_id: str,
    body: Optional[RollbackActionRequest] = None,
    db_session=Depends(check_ai_actions_entitlement),
):
    """
    Rollback a previously executed action.

    The action must be in SUCCEEDED status and have rollback instructions.
    Rollback restores the platform state to before execution.

    SECURITY:
    - Requires AI_ACTIONS entitlement
    - Requires ACTIONS_ROLLBACK permission
    - Creates audit trail entry

    EXTERNAL PLATFORM IS SOURCE OF TRUTH:
    - Rollback sends reverse API calls to platform
    - Platform response determines success/failure
    """
    tenant_ctx = get_tenant_context(request)

    # Verify action exists and belongs to tenant
    action = (
        db_session.query(AIAction)
        .filter(
            AIAction.id == action_id,
            AIAction.tenant_id == tenant_ctx.tenant_id,
        )
        .first()
    )

    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action not found",
        )

    if not action.can_be_rolled_back:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action cannot be rolled back",
        )

    # Execute rollback
    rollback_service = ActionRollbackService(db_session, tenant_ctx.tenant_id)

    try:
        success = await rollback_service.rollback_action(
            action,
            triggered_by=f"user:{tenant_ctx.user_id}",
        )
        db_session.commit()

        logger.info(
            "Action rollback via API",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "action_id": action_id,
                "user_id": tenant_ctx.user_id,
                "success": success,
            },
        )

        if success:
            return ActionRollbackResponse(
                status="ok",
                action_id=action_id,
                new_status=action.status.value,
                message="Action rolled back successfully",
            )
        else:
            return ActionRollbackResponse(
                status="error",
                action_id=action_id,
                new_status=action.status.value,
                message="Rollback failed. Check action details for more information.",
            )

    except Exception as e:
        logger.error(
            "Action rollback failed",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "action_id": action_id,
                "error": str(e),
            },
            exc_info=True,
        )
        db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Rollback failed. Please try again.",
        )


# =============================================================================
# Execution Log Routes
# =============================================================================


@router.get(
    "/{action_id}/logs",
    response_model=ExecutionLogsResponse,
    dependencies=[Depends(check_audit_permission)],
)
async def get_action_logs(
    request: Request,
    action_id: str,
    db_session=Depends(check_ai_actions_entitlement),
):
    """
    Get execution logs for an action.

    Returns all log entries in chronological order.

    SECURITY:
    - Requires AI_ACTIONS entitlement
    - Requires ACTIONS_AUDIT permission
    """
    tenant_ctx = get_tenant_context(request)

    # Verify action exists and belongs to tenant
    action = (
        db_session.query(AIAction)
        .filter(
            AIAction.id == action_id,
            AIAction.tenant_id == tenant_ctx.tenant_id,
        )
        .first()
    )

    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action not found",
        )

    # Get log entries
    logs = (
        db_session.query(ActionExecutionLog)
        .filter(ActionExecutionLog.action_id == action_id)
        .order_by(ActionExecutionLog.event_timestamp.asc())
        .all()
    )

    return ExecutionLogsResponse(
        action_id=action_id,
        entries=[
            ExecutionLogEntry(
                id=log.id,
                event_type=log.event_type.value if log.event_type else "",
                event_timestamp=log.event_timestamp,
                request_payload=log.request_payload,
                response_payload=log.response_payload,
                http_status_code=log.http_status_code,
                state_snapshot=log.state_snapshot,
                error_details=log.error_details,
                triggered_by=log.triggered_by,
            )
            for log in logs
        ],
    )


# =============================================================================
# Job Routes
# =============================================================================


@router.get(
    "/jobs",
    response_model=ActionJobsListResponse,
    dependencies=[Depends(check_view_permission)],
)
async def list_action_jobs(
    request: Request,
    db_session=Depends(check_ai_actions_entitlement),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filter by job status"
    ),
    limit: int = Query(20, le=100, description="Maximum jobs to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """
    List action jobs for the current tenant.

    Jobs are sorted by created_at (newest first).

    SECURITY: Only returns jobs belonging to the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    query = (
        db_session.query(ActionJob)
        .filter(ActionJob.tenant_id == tenant_ctx.tenant_id)
    )

    if status_filter:
        try:
            status_enum = ActionJobStatus(status_filter)
            query = query.filter(ActionJob.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}",
            )

    total = query.count()

    jobs = (
        query
        .order_by(ActionJob.created_at.desc())
        .offset(offset)
        .limit(limit + 1)
        .all()
    )

    has_more = len(jobs) > limit
    jobs = jobs[:limit]

    return ActionJobsListResponse(
        jobs=[_job_to_response(j) for j in jobs],
        total=total,
        has_more=has_more,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=ActionJobResponse,
    dependencies=[Depends(check_view_permission)],
)
async def get_action_job(
    request: Request,
    job_id: str,
    db_session=Depends(check_ai_actions_entitlement),
):
    """
    Get a single action job by ID.

    SECURITY: Only returns job if it belongs to the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    job = (
        db_session.query(ActionJob)
        .filter(
            ActionJob.job_id == job_id,
            ActionJob.tenant_id == tenant_ctx.tenant_id,
        )
        .first()
    )

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action job not found",
        )

    return _job_to_response(job)


@router.get(
    "/jobs/{job_id}/actions",
    response_model=ActionsListResponse,
    dependencies=[Depends(check_view_permission)],
)
async def get_job_actions(
    request: Request,
    job_id: str,
    db_session=Depends(check_ai_actions_entitlement),
):
    """
    Get all actions belonging to a job.

    SECURITY: Only returns actions if job belongs to the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    # Verify job exists and belongs to tenant
    job = (
        db_session.query(ActionJob)
        .filter(
            ActionJob.job_id == job_id,
            ActionJob.tenant_id == tenant_ctx.tenant_id,
        )
        .first()
    )

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action job not found",
        )

    # Get actions for this job
    actions = (
        db_session.query(AIAction)
        .filter(AIAction.job_id == job_id)
        .order_by(AIAction.created_at.asc())
        .all()
    )

    return ActionsListResponse(
        actions=[_action_to_response(a) for a in actions],
        total=len(actions),
        has_more=False,
    )
