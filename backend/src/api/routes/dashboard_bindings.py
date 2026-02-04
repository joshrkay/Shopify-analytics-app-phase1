"""
Dashboard Metric Binding API routes for Story 2.3.

Provides endpoints for:
- Listing current bindings (all dashboards or filtered)
- Resolving effective binding for a dashboard/metric/tenant
- Repointing a dashboard metric to a new version
- Pinning/unpinning tenants to specific versions
- Blast radius analysis for proposed changes

SECURITY:
- Read endpoints require ANALYTICS_VIEW permission
- Write endpoints require ADMIN_SYSTEM_CONFIG permission (Super Admin / Analytics Admin)
- All mutations emit audit events
- Tenant isolation preserved for tenant-level queries
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query

from src.platform.tenant_context import get_tenant_context
from src.platform.rbac import require_permission
from src.constants.permissions import Permission
from src.database.session import get_db_session
from src.governance.metric_versioning import MetricVersionResolver
from src.services.dashboard_metric_binding_service import DashboardMetricBindingService
from src.api.schemas.dashboard_bindings import (
    BindingEntry,
    BindingsListResponse,
    RepointRequest,
    RepointResponse,
    UnpinRequest,
    BlastRadiusRequest,
    BlastRadiusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/dashboard-bindings", tags=["dashboard-bindings"])

# Config paths
CONSUMERS_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "governance" / "consumers.yaml"
METRICS_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "governance" / "metrics_versions.yaml"


def _get_binding_service(db_session) -> DashboardMetricBindingService:
    """Create a DashboardMetricBindingService instance."""
    metric_resolver = MetricVersionResolver(config_path=METRICS_CONFIG_PATH)
    return DashboardMetricBindingService(
        db=db_session,
        consumers_config_path=CONSUMERS_CONFIG_PATH,
        metric_resolver=metric_resolver,
    )


@router.get(
    "",
    response_model=BindingsListResponse,
)
@require_permission(Permission.ANALYTICS_VIEW)
async def list_bindings(
    request: Request,
    db_session=Depends(get_db_session),
    dashboard_id: Optional[str] = Query(None, description="Filter by dashboard"),
    metric_name: Optional[str] = Query(None, description="Filter by metric"),
):
    """
    List all dashboard metric bindings.

    Returns combined view of consumers.yaml defaults + DB overrides.
    Filterable by dashboard_id and metric_name.
    """
    service = _get_binding_service(db_session)
    bindings = service.list_bindings(
        dashboard_id=dashboard_id,
        metric_name=metric_name,
    )

    return BindingsListResponse(
        bindings=[
            BindingEntry(
                dashboard_id=b.dashboard_id,
                metric_name=b.metric_name,
                metric_version=b.metric_version,
                pinned_by=b.pinned_by,
                pinned_at=b.pinned_at,
                reason=b.reason,
                tenant_id=b.tenant_id,
                is_tenant_override=b.is_tenant_override,
            )
            for b in bindings
        ],
        total=len(bindings),
    )


@router.get(
    "/resolve",
    response_model=BindingEntry,
)
@require_permission(Permission.ANALYTICS_VIEW)
async def resolve_binding(
    request: Request,
    dashboard_id: str = Query(..., description="Dashboard identifier"),
    metric_name: str = Query(..., description="Metric name"),
    tenant_id: Optional[str] = Query(None, description="Tenant for tenant-level resolution"),
    db_session=Depends(get_db_session),
):
    """
    Resolve the effective metric version for a dashboard/metric/tenant.

    Resolution order:
    1. Tenant-level DB override
    2. Global DB override
    3. consumers.yaml default
    """
    service = _get_binding_service(db_session)
    binding = service.resolve_binding(
        dashboard_id=dashboard_id,
        metric_name=metric_name,
        tenant_id=tenant_id,
    )

    return BindingEntry(
        dashboard_id=binding.dashboard_id,
        metric_name=binding.metric_name,
        metric_version=binding.metric_version,
        pinned_by=binding.pinned_by,
        pinned_at=binding.pinned_at,
        reason=binding.reason,
        tenant_id=binding.tenant_id,
        is_tenant_override=binding.is_tenant_override,
    )


@router.post(
    "/repoint",
    response_model=RepointResponse,
)
@require_permission(Permission.ADMIN_SYSTEM_CONFIG)
async def repoint_binding(
    request: Request,
    body: RepointRequest,
    db_session=Depends(get_db_session),
):
    """
    Repoint a dashboard's metric to a new version.

    GOVERNANCE:
    - Requires Super Admin or Analytics Admin role
    - Reason is required
    - Sunset versions are blocked
    - Audit event is emitted
    """
    tenant_ctx = get_tenant_context(request)
    service = _get_binding_service(db_session)

    result = service.repoint_dashboard_metric(
        dashboard_id=body.dashboard_id,
        metric_name=body.metric_name,
        new_version=body.new_version,
        repointed_by=tenant_ctx.user_id or "unknown",
        reason=body.reason,
        user_roles=tenant_ctx.roles,
        tenant_id=body.tenant_id,
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error,
        )

    return RepointResponse(
        success=result.success,
        dashboard_id=result.dashboard_id,
        metric_name=result.metric_name,
        old_version=result.old_version,
        new_version=result.new_version,
        reason=result.reason,
        repointed_by=result.repointed_by,
        audit_id=result.audit_id,
    )


@router.post(
    "/unpin",
    response_model=RepointResponse,
)
@require_permission(Permission.ADMIN_SYSTEM_CONFIG)
async def unpin_tenant(
    request: Request,
    body: UnpinRequest,
    db_session=Depends(get_db_session),
):
    """
    Remove a tenant-level pin, reverting to global binding.

    GOVERNANCE:
    - Requires Super Admin or Analytics Admin role
    - Reason is required
    - Audit event is emitted
    """
    tenant_ctx = get_tenant_context(request)
    service = _get_binding_service(db_session)

    result = service.unpin_tenant(
        dashboard_id=body.dashboard_id,
        metric_name=body.metric_name,
        tenant_id=body.tenant_id,
        unpinned_by=tenant_ctx.user_id or "unknown",
        reason=body.reason,
        user_roles=tenant_ctx.roles,
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error,
        )

    return RepointResponse(
        success=result.success,
        dashboard_id=result.dashboard_id,
        metric_name=result.metric_name,
        old_version=result.old_version,
        new_version=result.new_version,
        reason=result.reason,
        repointed_by=result.repointed_by,
        audit_id=result.audit_id,
    )


@router.post(
    "/blast-radius",
    response_model=BlastRadiusResponse,
)
@require_permission(Permission.ANALYTICS_VIEW)
async def get_blast_radius(
    request: Request,
    body: BlastRadiusRequest,
    db_session=Depends(get_db_session),
):
    """
    Calculate blast radius of a proposed metric version change.

    Reports which dashboards and tenants would be affected.
    This is a read-only analysis endpoint - no mutations occur.
    """
    service = _get_binding_service(db_session)
    report = service.get_blast_radius(
        metric_name=body.metric_name,
        from_version=body.from_version,
        to_version=body.to_version,
    )

    return BlastRadiusResponse(
        metric_name=report.metric_name,
        from_version=report.from_version,
        to_version=report.to_version,
        affected_dashboards=report.affected_dashboards,
        affected_tenant_count=report.affected_tenant_count,
        pinned_tenants=report.pinned_tenants,
        is_breaking=report.is_breaking,
    )
