"""
Report Templates API - Endpoints for browsing and instantiating templates.

Mounted at /api/v1/templates

Phase: Custom Reports & Dashboard Builder
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends, Query, status

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session
from src.services.billing_entitlements import BillingEntitlementsService, BillingFeature
from src.services.report_template_service import (
    ReportTemplateService,
    TemplateNotFoundError,
    TemplateRequirementsError,
)
from src.services.custom_dashboard_service import (
    CustomDashboardService,
    DashboardLimitExceededError,
)
from src.api.schemas.custom_dashboards import (
    TemplateResponse,
    TemplateListResponse,
    DashboardResponse,
    ReportResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/templates", tags=["report-templates"])


def _get_template_service(request: Request, db=Depends(get_db_session)) -> ReportTemplateService:
    ctx = get_tenant_context(request)
    ent_service = BillingEntitlementsService(db, ctx.tenant_id)
    tier = ent_service.get_billing_tier()
    return ReportTemplateService(db, tier)


@router.get("", response_model=TemplateListResponse)
async def list_templates(
    request: Request,
    category: Optional[str] = Query(None),
    service: ReportTemplateService = Depends(_get_template_service),
):
    """List available dashboard templates."""
    templates = service.list_templates(category=category)

    return TemplateListResponse(
        templates=[TemplateResponse.model_validate(t) for t in templates],
        total=len(templates),
    )


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: str,
    request: Request,
    service: ReportTemplateService = Depends(_get_template_service),
):
    """Get a single template with full details."""
    try:
        template = service.get_template(template_id)
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")

    return TemplateResponse.model_validate(template)


@router.post("/{template_id}/instantiate", response_model=DashboardResponse, status_code=201)
async def instantiate_template(
    template_id: str,
    request: Request,
    name: str = Query(..., min_length=1, max_length=255, description="Name for new dashboard"),
    db=Depends(get_db_session),
):
    """Create a new dashboard from a template."""
    ctx = get_tenant_context(request)

    # Check custom_reports entitlement
    ent_service = BillingEntitlementsService(db, ctx.tenant_id)
    result = ent_service.check_feature_entitlement(BillingFeature.CUSTOM_REPORTS)
    if not result.is_entitled:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Custom dashboards require a {result.required_tier or 'paid'} plan",
        )

    # Check dashboard count limit before creating
    max_dashboards = ent_service.get_feature_limit("custom_reports")
    if max_dashboards is not None and max_dashboards != -1:
        dashboard_service = CustomDashboardService(db, ctx.tenant_id, ctx.user_id)
        current_count = dashboard_service.get_dashboard_count()
        if current_count >= max_dashboards:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "message": f"Dashboard limit reached ({current_count}/{max_dashboards})",
                    "current_count": current_count,
                    "max_count": max_dashboards,
                },
            )

    tier = ent_service.get_billing_tier()
    template_service = ReportTemplateService(db, tier)

    try:
        dashboard = template_service.instantiate_template(
            template_id=template_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            dashboard_name=name,
        )
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")
    except TemplateRequirementsError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(e),
                "missing_datasets": e.missing_datasets,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=402, detail=str(e))

    dashboard_service = CustomDashboardService(db, ctx.tenant_id, ctx.user_id)
    access_level = dashboard_service.get_access_level(dashboard)

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
