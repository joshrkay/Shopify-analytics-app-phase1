"""
Custom Dashboards API - CRUD endpoints for user-created dashboards.

Mounted at /api/v1/dashboards

Entitlement gating:
- GET (list/read): No entitlement required (downgraded users can still read)
- POST/PUT/DELETE (write): Requires custom_reports entitlement
- 402 for billing issues, 403 for access denied, 404 for not found, 409 for conflicts

Phase: Custom Reports & Dashboard Builder
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends, Query, status

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session
from src.services.billing_entitlements import BillingEntitlementsService, BillingFeature
from src.services.custom_dashboard_service import (
    CustomDashboardService,
    DashboardNotFoundError,
    DashboardLimitExceededError,
    DashboardConflictError,
    DashboardNameConflictError,
)
from src.services.custom_report_service import (
    CustomReportService,
    ReportNotFoundError,
    ReportNameConflictError,
    DatasetNotFoundError,
)
from src.api.schemas.custom_dashboards import (
    CreateDashboardRequest,
    UpdateDashboardRequest,
    DuplicateDashboardRequest,
    DashboardResponse,
    DashboardListResponse,
    DashboardCountResponse,
    ReportResponse,
    CreateReportRequest,
    UpdateReportRequest,
    ReorderReportsRequest,
    DashboardVersionResponse,
    DashboardVersionDetailResponse,
    VersionListResponse,
    AuditEntryResponse,
    AuditListResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/dashboards", tags=["custom-dashboards"])


# =============================================================================
# Dependency Helpers
# =============================================================================

def _get_dashboard_service(request: Request, db=Depends(get_db_session)) -> CustomDashboardService:
    ctx = get_tenant_context(request)
    return CustomDashboardService(db, ctx.tenant_id, ctx.user_id)


def _get_report_service(request: Request, db=Depends(get_db_session)) -> CustomReportService:
    ctx = get_tenant_context(request)
    return CustomReportService(db, ctx.tenant_id, ctx.user_id)


def _check_write_entitlement(request: Request, db=Depends(get_db_session)):
    """Check custom_reports entitlement for write operations."""
    ctx = get_tenant_context(request)
    ent_service = BillingEntitlementsService(db, ctx.tenant_id)
    result = ent_service.check_feature_entitlement(BillingFeature.CUSTOM_REPORTS)
    if not result.is_entitled:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": f"Custom dashboards require a {result.required_tier or 'paid'} plan",
                "feature": "custom_reports",
                "required_tier": result.required_tier,
                "current_tier": result.current_tier,
            },
        )
    return db


def _get_dashboard_limit(request: Request, db=Depends(get_db_session)) -> Optional[int]:
    """Get the dashboard count limit for this tenant's plan."""
    ctx = get_tenant_context(request)
    ent_service = BillingEntitlementsService(db, ctx.tenant_id)
    return ent_service.get_feature_limit("custom_reports")


# =============================================================================
# Dashboard CRUD
# =============================================================================

@router.get("", response_model=DashboardListResponse)
async def list_dashboards(
    request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    service: CustomDashboardService = Depends(_get_dashboard_service),
):
    """List custom dashboards for the current tenant."""
    dashboards, total = service.list_dashboards(
        status_filter=status_filter,
        offset=offset,
        limit=limit,
    )

    return DashboardListResponse(
        dashboards=[
            _dashboard_to_response(d, service) for d in dashboards
        ],
        total=total,
        offset=offset,
        limit=limit,
        has_more=(offset + limit) < total,
    )


@router.get("/count", response_model=DashboardCountResponse)
async def get_dashboard_count(
    request: Request,
    service: CustomDashboardService = Depends(_get_dashboard_service),
    max_dashboards: Optional[int] = Depends(_get_dashboard_limit),
):
    """Get current dashboard count vs plan limit."""
    current = service.get_dashboard_count()
    can_create = max_dashboards is None or max_dashboards == -1 or current < max_dashboards

    return DashboardCountResponse(
        current_count=current,
        max_count=max_dashboards if max_dashboards and max_dashboards != -1 else None,
        can_create=can_create,
    )


@router.get("/{dashboard_id}", response_model=DashboardResponse)
async def get_dashboard(
    dashboard_id: str,
    request: Request,
    service: CustomDashboardService = Depends(_get_dashboard_service),
):
    """Get a single dashboard with all its reports."""
    try:
        dashboard = service.get_dashboard(dashboard_id)
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    # Draft dashboards only visible to owner
    if dashboard.status == "draft" and dashboard.created_by != get_tenant_context(request).user_id:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    return _dashboard_to_response(dashboard, service)


@router.post("", response_model=DashboardResponse, status_code=201)
async def create_dashboard(
    body: CreateDashboardRequest,
    request: Request,
    _ent=Depends(_check_write_entitlement),
    service: CustomDashboardService = Depends(_get_dashboard_service),
    max_dashboards: Optional[int] = Depends(_get_dashboard_limit),
):
    """Create a new custom dashboard."""
    try:
        dashboard = service.create_dashboard(
            name=body.name,
            description=body.description,
            max_dashboards=max_dashboards,
        )
    except DashboardLimitExceededError as e:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": f"Dashboard limit reached ({e.current_count}/{e.max_count})",
                "current_count": e.current_count,
                "max_count": e.max_count,
            },
        )
    except DashboardNameConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return _dashboard_to_response(dashboard, service)


@router.put("/{dashboard_id}", response_model=DashboardResponse)
async def update_dashboard(
    dashboard_id: str,
    body: UpdateDashboardRequest,
    request: Request,
    _ent=Depends(_check_write_entitlement),
    service: CustomDashboardService = Depends(_get_dashboard_service),
):
    """Update dashboard metadata or layout."""
    try:
        dashboard = service.update_dashboard(
            dashboard_id=dashboard_id,
            name=body.name,
            description=body.description,
            layout_json=body.layout_json,
            filters_json=[f.model_dump() for f in body.filters_json] if body.filters_json else None,
            expected_updated_at=body.expected_updated_at,
        )
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    except DashboardConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except DashboardNameConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return _dashboard_to_response(dashboard, service)


@router.delete("/{dashboard_id}", status_code=204)
async def archive_dashboard(
    dashboard_id: str,
    request: Request,
    _ent=Depends(_check_write_entitlement),
    service: CustomDashboardService = Depends(_get_dashboard_service),
):
    """Archive (soft-delete) a dashboard. Owner only."""
    try:
        service.archive_dashboard(dashboard_id)
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")


@router.post("/{dashboard_id}/publish", response_model=DashboardResponse)
async def publish_dashboard(
    dashboard_id: str,
    request: Request,
    _ent=Depends(_check_write_entitlement),
    service: CustomDashboardService = Depends(_get_dashboard_service),
):
    """Publish a draft dashboard."""
    try:
        dashboard = service.publish_dashboard(dashboard_id)
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    return _dashboard_to_response(dashboard, service)


@router.post("/{dashboard_id}/duplicate", response_model=DashboardResponse, status_code=201)
async def duplicate_dashboard(
    dashboard_id: str,
    body: DuplicateDashboardRequest,
    request: Request,
    _ent=Depends(_check_write_entitlement),
    service: CustomDashboardService = Depends(_get_dashboard_service),
    max_dashboards: Optional[int] = Depends(_get_dashboard_limit),
):
    """Duplicate a dashboard and all its reports."""
    try:
        dashboard = service.duplicate_dashboard(
            dashboard_id=dashboard_id,
            new_name=body.new_name,
            max_dashboards=max_dashboards,
        )
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    except DashboardLimitExceededError as e:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": f"Dashboard limit reached ({e.current_count}/{e.max_count})",
                "current_count": e.current_count,
                "max_count": e.max_count,
            },
        )
    except DashboardNameConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return _dashboard_to_response(dashboard, service)


# =============================================================================
# Version History
# =============================================================================

@router.get("/{dashboard_id}/versions", response_model=VersionListResponse)
async def list_versions(
    dashboard_id: str,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    service: CustomDashboardService = Depends(_get_dashboard_service),
):
    """List version history for a dashboard."""
    try:
        versions, total = service.list_versions(dashboard_id, offset, limit)
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    return VersionListResponse(
        versions=[
            DashboardVersionResponse.model_validate(v) for v in versions
        ],
        total=total,
    )


@router.get("/{dashboard_id}/versions/{version_number}", response_model=DashboardVersionDetailResponse)
async def get_version_detail(
    dashboard_id: str,
    version_number: int,
    request: Request,
    service: CustomDashboardService = Depends(_get_dashboard_service),
):
    """Get a single version with its full snapshot for preview."""
    try:
        version = service.get_version(dashboard_id, version_number)
    except DashboardNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return DashboardVersionDetailResponse.model_validate(version)


@router.post("/{dashboard_id}/restore/{version_number}", response_model=DashboardResponse)
async def restore_version(
    dashboard_id: str,
    version_number: int,
    request: Request,
    _ent=Depends(_check_write_entitlement),
    service: CustomDashboardService = Depends(_get_dashboard_service),
):
    """Restore a dashboard to a previous version."""
    try:
        dashboard = service.restore_version(dashboard_id, version_number)
    except DashboardNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return _dashboard_to_response(dashboard, service)


# =============================================================================
# Audit Trail
# =============================================================================

@router.get("/{dashboard_id}/audit", response_model=AuditListResponse)
async def list_audit_entries(
    dashboard_id: str,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    service: CustomDashboardService = Depends(_get_dashboard_service),
):
    """List audit trail for a dashboard."""
    try:
        entries, total = service.list_audit_entries(dashboard_id, offset, limit)
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    return AuditListResponse(
        entries=[
            AuditEntryResponse.model_validate(e) for e in entries
        ],
        total=total,
    )


# =============================================================================
# Reports (nested under dashboard)
# =============================================================================

@router.get("/{dashboard_id}/reports", response_model=list[ReportResponse])
async def list_reports(
    dashboard_id: str,
    request: Request,
    service: CustomReportService = Depends(_get_report_service),
):
    """List all reports in a dashboard."""
    try:
        reports = service.list_reports(dashboard_id)
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    return [ReportResponse.model_validate(r) for r in reports]


@router.post("/{dashboard_id}/reports", response_model=ReportResponse, status_code=201)
async def add_report(
    dashboard_id: str,
    body: CreateReportRequest,
    request: Request,
    _ent=Depends(_check_write_entitlement),
    service: CustomReportService = Depends(_get_report_service),
):
    """Add a report/chart to a dashboard."""
    try:
        report = service.add_report(
            dashboard_id=dashboard_id,
            name=body.name,
            description=body.description,
            chart_type=body.chart_type,
            dataset_name=body.dataset_name,
            config_json=body.config_json.model_dump(),
            position_json=body.position_json.model_dump(),
        )
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    except DatasetNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ReportNameConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return ReportResponse.model_validate(report)


@router.put("/{dashboard_id}/reports/{report_id}", response_model=ReportResponse)
async def update_report(
    dashboard_id: str,
    report_id: str,
    body: UpdateReportRequest,
    request: Request,
    _ent=Depends(_check_write_entitlement),
    service: CustomReportService = Depends(_get_report_service),
):
    """Update a report's configuration."""
    try:
        report = service.update_report(
            dashboard_id=dashboard_id,
            report_id=report_id,
            name=body.name,
            description=body.description,
            chart_type=body.chart_type,
            config_json=body.config_json.model_dump() if body.config_json else None,
            position_json=body.position_json.model_dump() if body.position_json else None,
        )
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    except ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found")
    except ReportNameConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return ReportResponse.model_validate(report)


@router.delete("/{dashboard_id}/reports/{report_id}", status_code=204)
async def remove_report(
    dashboard_id: str,
    report_id: str,
    request: Request,
    _ent=Depends(_check_write_entitlement),
    service: CustomReportService = Depends(_get_report_service),
):
    """Remove a report from a dashboard."""
    try:
        service.remove_report(dashboard_id, report_id)
    except (DashboardNotFoundError, ReportNotFoundError):
        raise HTTPException(status_code=404, detail="Report not found")


@router.put("/{dashboard_id}/reports/reorder")
async def reorder_reports(
    dashboard_id: str,
    body: ReorderReportsRequest,
    request: Request,
    _ent=Depends(_check_write_entitlement),
    service: CustomReportService = Depends(_get_report_service),
):
    """Reorder reports within a dashboard."""
    try:
        reports = service.reorder_reports(dashboard_id, body.report_ids)
    except DashboardNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    return [ReportResponse.model_validate(r) for r in reports]


# =============================================================================
# Response Builder
# =============================================================================

def _dashboard_to_response(
    dashboard,
    service: CustomDashboardService,
) -> DashboardResponse:
    """Convert a CustomDashboard model to DashboardResponse."""
    access_level = service.get_access_level(dashboard)

    return DashboardResponse(
        id=dashboard.id,
        name=dashboard.name,
        description=dashboard.description,
        status=dashboard.status,
        layout_json=dashboard.layout_json or {},
        filters_json=dashboard.filters_json,
        template_id=dashboard.template_id,
        is_template_derived=dashboard.is_template_derived,
        version_number=dashboard.version_number,
        reports=[ReportResponse.model_validate(r) for r in dashboard.reports],
        access_level=access_level,
        created_by=dashboard.created_by,
        created_at=dashboard.created_at,
        updated_at=dashboard.updated_at,
    )
