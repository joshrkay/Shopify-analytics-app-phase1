"""
Report Templates API routes.

Provides endpoints for the template gallery and instantiation:
- List templates (filtered by billing tier and category)
- Get template details
- Instantiate template into user's dashboard
- Admin CRUD for templates

SECURITY: All routes require valid tenant context from JWT.
List/get/instantiate require CUSTOM_REPORTS entitlement.
Create/update/delete require admin role.

Phase 2C - Template System Backend
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session
from src.api.dependencies.entitlements import check_custom_reports_entitlement
from src.constants.permissions import roles_have_permission, Permission
from src.services.report_template_service import ReportTemplateService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _require_admin_role(tenant_ctx) -> None:
    """Enforce admin role on the current request. Raises 403 if not admin."""
    if not roles_have_permission(tenant_ctx.roles, Permission.ADMIN_SYSTEM_CONFIG):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )


# =============================================================================
# Response Models
# =============================================================================


class TemplateResponse(BaseModel):
    """Response model for a single template."""

    id: str = Field(..., description="Template ID")
    name: str = Field(..., description="Template name")
    description: str = Field("", description="Template description")
    category: str = Field(..., description="Template category")
    thumbnail_url: Optional[str] = Field(None, description="Gallery thumbnail URL")
    min_billing_tier: str = Field(..., description="Minimum billing tier required")
    report_count: int = Field(..., description="Number of reports in the template")
    version: int = Field(..., description="Template version")


class TemplateListResponse(BaseModel):
    """Response model for template list."""

    templates: list[TemplateResponse] = Field(..., description="Available templates")
    total: int = Field(..., description="Total template count")


class TemplateDetailResponse(BaseModel):
    """Response model with full template config."""

    id: str = Field(..., description="Template ID")
    name: str = Field(..., description="Template name")
    description: str = Field("", description="Template description")
    category: str = Field(..., description="Template category")
    thumbnail_url: Optional[str] = Field(None, description="Gallery thumbnail URL")
    min_billing_tier: str = Field(..., description="Minimum billing tier required")
    config_json: dict[str, Any] = Field(..., description="Full template configuration")
    is_active: bool = Field(..., description="Whether template is active")
    version: int = Field(..., description="Template version")


class InstantiateRequest(BaseModel):
    """Request to instantiate a template."""

    dashboard_name: Optional[str] = Field(
        None, description="Custom name for the new dashboard (uses template name if omitted)"
    )


class InstantiateResponse(BaseModel):
    """Response from template instantiation."""

    success: bool = Field(..., description="Whether instantiation succeeded")
    dashboard_id: Optional[str] = Field(None, description="Created dashboard ID")
    report_ids: list[str] = Field(default_factory=list, description="Created report IDs")
    error: Optional[str] = Field(None, description="Error message if failed")


class CreateTemplateRequest(BaseModel):
    """Request to create a template (admin-only)."""

    name: str = Field(..., description="Template name", max_length=255)
    description: str = Field("", description="Template description")
    category: str = Field(..., description="Template category")
    config_json: dict[str, Any] = Field(..., description="Template configuration")
    min_billing_tier: str = Field("free", description="Minimum billing tier")
    thumbnail_url: Optional[str] = Field(None, description="Gallery thumbnail URL")


class UpdateTemplateRequest(BaseModel):
    """Request to update a template (admin-only)."""

    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    category: Optional[str] = None
    config_json: Optional[dict[str, Any]] = None
    min_billing_tier: Optional[str] = None
    thumbnail_url: Optional[str] = None
    is_active: Optional[bool] = None


# =============================================================================
# Routes
# =============================================================================


@router.get(
    "",
    response_model=TemplateListResponse,
)
async def list_templates(
    request: Request,
    db_session=Depends(check_custom_reports_entitlement),
    category: Optional[str] = Query(None, description="Filter by category"),
):
    """
    List active templates available for the user's billing tier.

    Templates are filtered by billing tier from JWT - only templates at or below
    the user's tier are shown. Deactivated templates are excluded.

    SECURITY: Requires valid tenant context and CUSTOM_REPORTS entitlement.
    Billing tier sourced from JWT, never from client input.
    """
    tenant_ctx = get_tenant_context(request)
    billing_tier = tenant_ctx.billing_tier
    logger.info(
        "Template list requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "category": category,
            "billing_tier": billing_tier,
        },
    )

    service = ReportTemplateService(db_session, tenant_ctx.tenant_id)
    templates = service.list_templates(billing_tier=billing_tier, category=category)

    return TemplateListResponse(
        templates=[
            TemplateResponse(
                id=t.id,
                name=t.name,
                description=t.description,
                category=t.category,
                thumbnail_url=t.thumbnail_url,
                min_billing_tier=t.min_billing_tier,
                report_count=t.report_count,
                version=t.version,
            )
            for t in templates
        ],
        total=len(templates),
    )


@router.get(
    "/{template_id}",
    response_model=TemplateDetailResponse,
)
async def get_template(
    request: Request,
    template_id: str,
    db_session=Depends(check_custom_reports_entitlement),
):
    """
    Get full template details including config.

    SECURITY: Requires valid tenant context and CUSTOM_REPORTS entitlement.
    """
    tenant_ctx = get_tenant_context(request)

    service = ReportTemplateService(db_session, tenant_ctx.tenant_id)
    template = service.get_template(template_id)

    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )

    return TemplateDetailResponse(
        id=template.id,
        name=template.name,
        description=template.description or "",
        category=template.category.value if template.category else "",
        thumbnail_url=template.thumbnail_url,
        min_billing_tier=template.min_billing_tier or "free",
        config_json=template.config_json or {},
        is_active=template.is_active,
        version=template.version or 1,
    )


@router.post(
    "/{template_id}/instantiate",
    response_model=InstantiateResponse,
)
async def instantiate_template(
    request: Request,
    template_id: str,
    body: InstantiateRequest,
    db_session=Depends(check_custom_reports_entitlement),
):
    """
    Instantiate a template into the user's dashboard.

    Creates a dashboard with all reports defined in the template.
    Atomic: if any report fails to create, the entire operation rolls back.

    Abstract chart types (line, bar, etc.) are mapped to current
    Superset viz_type plugins during instantiation.

    SECURITY: Requires valid tenant context and CUSTOM_REPORTS entitlement.
    """
    tenant_ctx = get_tenant_context(request)
    logger.info(
        "Template instantiation requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "template_id": template_id,
        },
    )

    service = ReportTemplateService(db_session, tenant_ctx.tenant_id)
    result = service.instantiate_template(
        template_id,
        dashboard_name=body.dashboard_name,
        user_billing_tier=tenant_ctx.billing_tier,
    )

    if not result.success:
        # Distinguish "not found" from other errors
        if result.error and "not found" in result.error.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result.error,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error or "Instantiation failed",
        )

    return InstantiateResponse(
        success=result.success,
        dashboard_id=result.dashboard_id,
        report_ids=result.report_ids,
    )


# =============================================================================
# Admin Routes
# =============================================================================


@router.post(
    "",
    response_model=TemplateDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    request: Request,
    body: CreateTemplateRequest,
    db_session=Depends(get_db_session),
):
    """
    Create a new report template (admin-only).

    SECURITY: Requires valid tenant context. Admin role enforced.
    """
    tenant_ctx = get_tenant_context(request)
    _require_admin_role(tenant_ctx)
    logger.info(
        "Template creation requested",
        extra={"tenant_id": tenant_ctx.tenant_id, "name": body.name},
    )

    service = ReportTemplateService(db_session, tenant_ctx.tenant_id)
    try:
        template = service.create_template(
            name=body.name,
            description=body.description,
            category=body.category,
            config_json=body.config_json,
            min_billing_tier=body.min_billing_tier,
            thumbnail_url=body.thumbnail_url,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return TemplateDetailResponse(
        id=template.id,
        name=template.name,
        description=template.description or "",
        category=template.category.value if template.category else "",
        thumbnail_url=template.thumbnail_url,
        min_billing_tier=template.min_billing_tier or "free",
        config_json=template.config_json or {},
        is_active=template.is_active,
        version=template.version or 1,
    )


@router.put(
    "/{template_id}",
    response_model=TemplateDetailResponse,
)
async def update_template(
    request: Request,
    template_id: str,
    body: UpdateTemplateRequest,
    db_session=Depends(get_db_session),
):
    """
    Update a report template (admin-only). Bumps version.

    SECURITY: Requires valid tenant context. Admin role enforced.
    """
    tenant_ctx = get_tenant_context(request)
    _require_admin_role(tenant_ctx)

    service = ReportTemplateService(db_session, tenant_ctx.tenant_id)
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    try:
        template = service.update_template(template_id, **updates)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )

    return TemplateDetailResponse(
        id=template.id,
        name=template.name,
        description=template.description or "",
        category=template.category.value if template.category else "",
        thumbnail_url=template.thumbnail_url,
        min_billing_tier=template.min_billing_tier or "free",
        config_json=template.config_json or {},
        is_active=template.is_active,
        version=template.version or 1,
    )


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_template(
    request: Request,
    template_id: str,
    db_session=Depends(get_db_session),
):
    """
    Deactivate a template (hide from gallery, admin-only).

    Existing dashboards created from this template continue working.
    Does not physically delete the template record.

    SECURITY: Requires valid tenant context. Admin role enforced.
    """
    tenant_ctx = get_tenant_context(request)
    _require_admin_role(tenant_ctx)
    logger.info(
        "Template deactivation requested",
        extra={"tenant_id": tenant_ctx.tenant_id, "template_id": template_id},
    )

    service = ReportTemplateService(db_session, tenant_ctx.tenant_id)
    if not service.deactivate_template(template_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )
