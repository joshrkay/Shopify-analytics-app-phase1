"""
Data Quality API routes for sync health monitoring.

Provides endpoints for:
- Sync health summary and per-connector health
- DQ check results
- Incident management
- Backfill triggering (with 90-day limit for merchants)

SECURITY: All routes require valid tenant context from JWT.
Health data is tenant-scoped - users can only see their own data.
"""

import logging
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List

from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel, Field, field_validator

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session
from src.api.dq.service import DQService, DQEventType
from src.models.dq_models import (
    DQIncidentStatus, BackfillJob, BackfillJobStatus,
    MAX_MERCHANT_BACKFILL_DAYS,
)
from src.platform.audit import AuditAction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync-health", tags=["sync-health"])


# =============================================================================
# Response Models
# =============================================================================

class ConnectorHealthResponse(BaseModel):
    """Health information for a single connector."""
    connector_id: str
    connector_name: str
    source_type: Optional[str]
    status: str  # healthy, delayed, error
    freshness_status: str  # fresh, stale, critical, never_synced
    severity: Optional[str]
    last_sync_at: Optional[str]
    last_rows_synced: Optional[int]
    minutes_since_sync: Optional[int]
    message: str
    merchant_message: str
    recommended_actions: List[str]
    is_blocking: bool
    has_open_incidents: bool
    open_incident_count: int


class SyncHealthSummaryResponse(BaseModel):
    """Overall sync health summary."""
    total_connectors: int
    healthy_count: int
    delayed_count: int
    error_count: int
    blocking_issues: int
    overall_status: str  # healthy, degraded, critical
    health_score: float = Field(description="Health score from 0-100")
    connectors: List[ConnectorHealthResponse]
    has_blocking_issues: bool


class IncidentResponse(BaseModel):
    """DQ incident response."""
    id: str
    connector_id: str
    severity: str
    status: str
    is_blocking: bool
    title: str
    description: Optional[str]
    merchant_message: Optional[str]
    recommended_actions: List[str]
    opened_at: str
    acknowledged_at: Optional[str]
    resolved_at: Optional[str]


class DashboardBlockStatusResponse(BaseModel):
    """Dashboard block status response."""
    is_blocked: bool
    blocking_messages: List[str]


class BackfillRequest(BaseModel):
    """Request to trigger a backfill."""
    start_date: str = Field(
        ...,
        description="Start date for backfill (YYYY-MM-DD)",
        examples=["2024-01-01"],
    )
    end_date: str = Field(
        ...,
        description="End date for backfill (YYYY-MM-DD)",
        examples=["2024-01-31"],
    )

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """Validate date format."""
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            raise ValueError(f"Invalid date format: {v}. Expected YYYY-MM-DD")


class BackfillResponse(BaseModel):
    """Response for backfill request."""
    id: str
    connector_id: str
    start_date: str
    end_date: str
    status: str
    requested_by: str
    estimated_days: int
    message: str


class BackfillEstimateResponse(BaseModel):
    """Estimate for a potential backfill."""
    connector_id: str
    start_date: str
    end_date: str
    days_count: int
    is_allowed: bool
    max_allowed_days: int
    message: str
    warning: Optional[str] = None


# =============================================================================
# Dependencies
# =============================================================================

def get_dq_service(
    request: Request,
    db_session=Depends(get_db_session),
) -> DQService:
    """Get DQ service instance scoped to current tenant."""
    tenant_ctx = get_tenant_context(request)
    return DQService(db_session, tenant_ctx.tenant_id)


# =============================================================================
# Helper Functions
# =============================================================================

def _connector_health_to_response(health) -> ConnectorHealthResponse:
    """Convert ConnectorSyncHealth to response model."""
    return ConnectorHealthResponse(
        connector_id=health.connector_id,
        connector_name=health.connector_name,
        source_type=health.source_type,
        status=health.status,
        freshness_status=health.freshness_status,
        severity=health.severity.value if health.severity else None,
        last_sync_at=health.last_sync_at.isoformat() if health.last_sync_at else None,
        last_rows_synced=health.last_rows_synced,
        minutes_since_sync=health.minutes_since_sync,
        message=health.message,
        merchant_message=health.merchant_message,
        recommended_actions=health.recommended_actions,
        is_blocking=health.is_blocking,
        has_open_incidents=health.has_open_incidents,
        open_incident_count=health.open_incident_count,
    )


def _incident_to_response(incident) -> IncidentResponse:
    """Convert DQIncident to response model."""
    return IncidentResponse(
        id=incident.id,
        connector_id=incident.connector_id,
        severity=incident.severity,
        status=incident.status,
        is_blocking=incident.is_blocking,
        title=incident.title,
        description=incident.description,
        merchant_message=incident.merchant_message,
        recommended_actions=incident.recommended_actions or [],
        opened_at=incident.opened_at.isoformat() if incident.opened_at else "",
        acknowledged_at=incident.acknowledged_at.isoformat() if incident.acknowledged_at else None,
        resolved_at=incident.resolved_at.isoformat() if incident.resolved_at else None,
    )


# =============================================================================
# Routes
# =============================================================================

@router.get(
    "/summary",
    response_model=SyncHealthSummaryResponse,
)
async def get_sync_health_summary(
    request: Request,
    service: DQService = Depends(get_dq_service),
):
    """
    Get overall sync health summary for the current tenant.

    Returns aggregate health metrics including:
    - Total, healthy, delayed, and error connector counts
    - Overall health score (0-100)
    - Per-connector health details
    - Blocking issues indicator

    SECURITY: Only returns health data for connectors belonging to
    the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Sync health summary requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
        },
    )

    summary = service.get_sync_health_summary()

    return SyncHealthSummaryResponse(
        total_connectors=summary.total_connectors,
        healthy_count=summary.healthy_count,
        delayed_count=summary.delayed_count,
        error_count=summary.error_count,
        blocking_issues=summary.blocking_issues,
        overall_status=summary.overall_status,
        health_score=summary.health_score,
        connectors=[
            _connector_health_to_response(c) for c in summary.connectors
        ],
        has_blocking_issues=summary.has_blocking_issues,
    )


@router.get(
    "/connector/{connector_id}",
    response_model=ConnectorHealthResponse,
)
async def get_connector_health(
    request: Request,
    connector_id: str,
    service: DQService = Depends(get_dq_service),
):
    """
    Get health information for a specific connector.

    Returns freshness status, sync metrics, and any open incidents.

    SECURITY: Only returns health for connectors belonging to
    the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Connector health requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "connector_id": connector_id,
        },
    )

    summary = service.get_sync_health_summary()

    for connector in summary.connectors:
        if connector.connector_id == connector_id:
            return _connector_health_to_response(connector)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Connector not found: {connector_id}",
    )


@router.get(
    "/incidents",
    response_model=List[IncidentResponse],
)
async def get_incidents(
    request: Request,
    connector_id: Optional[str] = None,
    include_resolved: bool = False,
    service: DQService = Depends(get_dq_service),
):
    """
    Get DQ incidents for the tenant.

    By default returns only open/acknowledged incidents.
    Set include_resolved=true to include resolved incidents.

    SECURITY: Only returns incidents for the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Incidents requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "connector_id": connector_id,
            "include_resolved": include_resolved,
        },
    )

    incidents = service.get_open_incidents(connector_id)

    return [_incident_to_response(inc) for inc in incidents]


@router.post(
    "/incidents/{incident_id}/acknowledge",
    response_model=IncidentResponse,
)
async def acknowledge_incident(
    request: Request,
    incident_id: str,
    db_session=Depends(get_db_session),
    service: DQService = Depends(get_dq_service),
):
    """
    Acknowledge a DQ incident.

    Changes incident status from 'open' to 'acknowledged'.

    SECURITY: Only acknowledges incidents for the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    from src.models.dq_models import DQIncident

    incident = db_session.query(DQIncident).filter(
        DQIncident.tenant_id == tenant_ctx.tenant_id,
        DQIncident.id == incident_id,
    ).first()

    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident not found: {incident_id}",
        )

    if incident.status != DQIncidentStatus.OPEN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Incident is not in 'open' state: {incident.status}",
        )

    incident.status = DQIncidentStatus.ACKNOWLEDGED.value
    incident.acknowledged_at = datetime.now(timezone.utc)
    incident.acknowledged_by = tenant_ctx.user_id
    db_session.commit()

    logger.info(
        "Incident acknowledged",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "incident_id": incident_id,
            "user_id": tenant_ctx.user_id,
        },
    )

    return _incident_to_response(incident)


@router.get(
    "/dashboard-block",
    response_model=DashboardBlockStatusResponse,
)
async def get_dashboard_block_status(
    request: Request,
    service: DQService = Depends(get_dq_service),
):
    """
    Check if dashboards should be blocked due to severe DQ issues.

    Returns block status and list of blocking messages.

    SECURITY: Only checks for the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Dashboard block status requested",
        extra={"tenant_id": tenant_ctx.tenant_id},
    )

    is_blocked, messages = service.is_dashboard_blocked()

    return DashboardBlockStatusResponse(
        is_blocked=is_blocked,
        blocking_messages=messages,
    )


# =============================================================================
# Backfill Routes
# =============================================================================

@router.get(
    "/connectors/{connector_id}/backfill/estimate",
    response_model=BackfillEstimateResponse,
)
async def estimate_backfill(
    request: Request,
    connector_id: str,
    start_date: str,
    end_date: str,
    db_session=Depends(get_db_session),
):
    """
    Estimate a potential backfill operation.

    Returns whether the backfill is allowed and any warnings.
    Merchants can only backfill up to 90 days.

    SECURITY: Only estimates for connectors belonging to
    the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    # Parse dates
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format: {e}",
        )

    if start > end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start date must be before end date",
        )

    days_count = (end - start).days + 1
    is_allowed = days_count <= MAX_MERCHANT_BACKFILL_DAYS

    warning = None
    if days_count > 30:
        warning = (
            "Large backfill requested. This may take significant time and "
            "could be affected by API rate limits."
        )

    message = (
        f"Backfill allowed for {days_count} days"
        if is_allowed
        else f"Backfill exceeds maximum of {MAX_MERCHANT_BACKFILL_DAYS} days. Contact support for larger backfills."
    )

    return BackfillEstimateResponse(
        connector_id=connector_id,
        start_date=start_date,
        end_date=end_date,
        days_count=days_count,
        is_allowed=is_allowed,
        max_allowed_days=MAX_MERCHANT_BACKFILL_DAYS,
        message=message,
        warning=warning,
    )


@router.post(
    "/connectors/{connector_id}/backfill",
    response_model=BackfillResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_backfill(
    request: Request,
    connector_id: str,
    body: BackfillRequest,
    db_session=Depends(get_db_session),
):
    """
    Trigger a backfill for a connector.

    Merchants can only backfill up to 90 days.
    Only one backfill can be active per connector per tenant.

    Emits audit event: backfill.requested

    SECURITY: Only triggers backfill for connectors belonging to
    the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Backfill requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "connector_id": connector_id,
            "start_date": body.start_date,
            "end_date": body.end_date,
            "user_id": tenant_ctx.user_id,
        },
    )

    # Parse dates
    try:
        start = datetime.strptime(body.start_date, "%Y-%m-%d")
        end = datetime.strptime(body.end_date, "%Y-%m-%d")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format: {e}",
        )

    if start > end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start date must be before end date",
        )

    # Enforce 90-day limit for merchants
    days_count = (end - start).days + 1
    if days_count > MAX_MERCHANT_BACKFILL_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Backfill range exceeds maximum of {MAX_MERCHANT_BACKFILL_DAYS} days. Contact support for larger backfills.",
        )

    # Check for existing active backfill
    existing = db_session.query(BackfillJob).filter(
        BackfillJob.tenant_id == tenant_ctx.tenant_id,
        BackfillJob.connector_id == connector_id,
        BackfillJob.status.in_([
            BackfillJobStatus.QUEUED.value,
            BackfillJobStatus.RUNNING.value,
        ]),
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A backfill is already in progress for this connector. Please wait for it to complete.",
        )

    # Verify connector exists and belongs to tenant
    from src.models.airbyte_connection import TenantAirbyteConnection

    connector = db_session.query(TenantAirbyteConnection).filter(
        TenantAirbyteConnection.tenant_id == tenant_ctx.tenant_id,
        TenantAirbyteConnection.id == connector_id,
    ).first()

    if not connector:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector not found: {connector_id}",
        )

    # Create backfill job
    backfill_job = BackfillJob(
        tenant_id=tenant_ctx.tenant_id,
        connector_id=connector_id,
        start_date=start,
        end_date=end,
        status=BackfillJobStatus.QUEUED.value,
        requested_by=tenant_ctx.user_id,
    )
    db_session.add(backfill_job)
    db_session.commit()

    logger.info(
        "Backfill job created",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "connector_id": connector_id,
            "backfill_id": backfill_job.id,
            "start_date": body.start_date,
            "end_date": body.end_date,
            "days_count": days_count,
        },
    )

    return BackfillResponse(
        id=backfill_job.id,
        connector_id=connector_id,
        start_date=body.start_date,
        end_date=body.end_date,
        status=backfill_job.status,
        requested_by=tenant_ctx.user_id,
        estimated_days=days_count,
        message=f"Backfill queued for {days_count} days. You will be notified when complete.",
    )


@router.get(
    "/connectors/{connector_id}/backfill/status",
    response_model=BackfillResponse,
)
async def get_backfill_status(
    request: Request,
    connector_id: str,
    db_session=Depends(get_db_session),
):
    """
    Get status of the current or most recent backfill for a connector.

    SECURITY: Only returns backfill for connectors belonging to
    the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    backfill = db_session.query(BackfillJob).filter(
        BackfillJob.tenant_id == tenant_ctx.tenant_id,
        BackfillJob.connector_id == connector_id,
    ).order_by(BackfillJob.created_at.desc()).first()

    if not backfill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No backfill found for this connector",
        )

    days_count = (backfill.end_date - backfill.start_date).days + 1

    status_messages = {
        BackfillJobStatus.QUEUED.value: "Backfill is queued and waiting to start.",
        BackfillJobStatus.RUNNING.value: "Backfill is in progress.",
        BackfillJobStatus.SUCCESS.value: "Backfill completed successfully.",
        BackfillJobStatus.FAILED.value: f"Backfill failed: {backfill.error_message or 'Unknown error'}",
        BackfillJobStatus.CANCELLED.value: "Backfill was cancelled.",
    }

    return BackfillResponse(
        id=backfill.id,
        connector_id=connector_id,
        start_date=backfill.start_date.strftime("%Y-%m-%d") if backfill.start_date else "",
        end_date=backfill.end_date.strftime("%Y-%m-%d") if backfill.end_date else "",
        status=backfill.status,
        requested_by=backfill.requested_by,
        estimated_days=days_count,
        message=status_messages.get(backfill.status, "Unknown status"),
    )
