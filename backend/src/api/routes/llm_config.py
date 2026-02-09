"""
LLM Configuration API routes for Story 8.8 - Model Routing & Prompt Governance.

Provides endpoints for:
- Viewing/updating org LLM configuration
- Managing prompt templates
- Viewing usage statistics

SECURITY: All routes require valid tenant context from JWT.
Configurations are tenant-scoped - users can only see their own data.
Requires LLM_ROUTING entitlement (Growth+ tiers).

Story 8.8 - Model Routing & Prompt Governance
"""

import logging
from typing import Optional, List
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session
from src.models.llm_routing import (
    LLMModelRegistry,
    LLMOrgConfig,
    LLMPromptTemplate,
    LLMUsageLog,
)
from src.services.billing_entitlements import BillingEntitlementsService
from src.api.dependencies.entitlements import check_ai_insights_entitlement as check_llm_routing_entitlement

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["llm-config"])


# =============================================================================
# Response Models
# =============================================================================


class ModelRegistryResponse(BaseModel):
    """Response model for a registered LLM model."""

    model_config = ConfigDict(from_attributes=True)

    model_id: str
    display_name: str
    provider: str
    context_window: int
    max_output_tokens: int
    cost_per_input_token: str
    cost_per_output_token: str
    capabilities: List[str]
    tier_restriction: Optional[str] = None


class OrgConfigResponse(BaseModel):
    """Response model for organization LLM configuration."""

    model_config = ConfigDict(from_attributes=True)

    primary_model_id: str
    fallback_model_id: Optional[str] = None
    max_tokens_per_request: int
    temperature: float
    monthly_token_budget: Optional[int] = None


class OrgConfigUpdateRequest(BaseModel):
    """Request model for updating organization LLM configuration."""
    primary_model_id: Optional[str] = None
    fallback_model_id: Optional[str] = None
    max_tokens_per_request: Optional[int] = Field(None, ge=1, le=32000)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    monthly_token_budget: Optional[int] = Field(None, ge=0)


class PromptTemplateResponse(BaseModel):
    """Response model for a prompt template."""

    model_config = ConfigDict(from_attributes=True)

    template_id: str
    template_key: str
    version: int
    template_content: str
    variables: List[str]
    is_active: bool
    is_system: bool
    created_at: datetime


class PromptTemplateCreateRequest(BaseModel):
    """Request model for creating a custom prompt template."""
    template_key: str = Field(..., min_length=1, max_length=100)
    template_content: str = Field(..., min_length=1)
    variables: List[str] = Field(default_factory=list)


class UsageStatsResponse(BaseModel):
    """Response model for usage statistics."""
    total_tokens: int
    total_cost_usd: float
    request_count: int
    success_count: int
    fallback_count: int
    period_days: int


class UsageLogResponse(BaseModel):
    """Response model for a single usage log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    prompt_template_key: Optional[str]
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    cost_usd: float
    was_fallback: bool
    response_status: str
    created_at: datetime


class UsageLogListResponse(BaseModel):
    """Response model for listing usage logs."""
    logs: List[UsageLogResponse]
    total: int
    has_more: bool


# =============================================================================
# Routes: Models
# =============================================================================


@router.get(
    "/models",
    response_model=List[ModelRegistryResponse],
)
async def list_available_models(
    request: Request,
    db_session=Depends(check_llm_routing_entitlement),
):
    """
    List all available LLM models.

    Returns models from the registry that are enabled.
    Models may be restricted to certain billing tiers.
    """
    tenant_ctx = get_tenant_context(request)

    # Get billing tier to filter models
    entitlements = BillingEntitlementsService(db_session, tenant_ctx.tenant_id)
    billing_tier = entitlements.get_billing_tier()

    # Query enabled models
    models = db_session.query(LLMModelRegistry).filter(
        LLMModelRegistry.is_enabled == True
    ).all()

    # Filter by tier restriction
    result = []
    for model in models:
        if model.tier_restriction:
            # Check if current tier meets restriction
            tier_order = {"free": 0, "growth": 1, "enterprise": 2}
            required_tier_level = tier_order.get(model.tier_restriction, 2)
            current_tier_level = tier_order.get(billing_tier, 0)

            if current_tier_level < required_tier_level:
                continue

        result.append(ModelRegistryResponse(
            model_id=model.model_id,
            display_name=model.display_name,
            provider=model.provider,
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
            cost_per_input_token=str(model.cost_per_input_token),
            cost_per_output_token=str(model.cost_per_output_token),
            capabilities=model.capabilities or [],
            tier_restriction=model.tier_restriction,
        ))

    logger.info(
        "Listed available models",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "model_count": len(result),
            "billing_tier": billing_tier,
        },
    )

    return result


# =============================================================================
# Routes: Organization Configuration
# =============================================================================


@router.get(
    "/config",
    response_model=OrgConfigResponse,
)
async def get_org_config(
    request: Request,
    db_session=Depends(check_llm_routing_entitlement),
):
    """
    Get organization LLM configuration.

    Returns default configuration if none is set.
    """
    tenant_ctx = get_tenant_context(request)

    config = db_session.query(LLMOrgConfig).filter(
        LLMOrgConfig.tenant_id == tenant_ctx.tenant_id
    ).first()

    if config:
        return OrgConfigResponse(
            primary_model_id=config.primary_model_id,
            fallback_model_id=config.fallback_model_id,
            max_tokens_per_request=config.max_tokens_per_request,
            temperature=float(config.temperature),
            monthly_token_budget=config.monthly_token_budget,
        )

    # Return defaults
    return OrgConfigResponse(
        primary_model_id="anthropic/claude-3-haiku",
        fallback_model_id=None,
        max_tokens_per_request=2048,
        temperature=0.7,
        monthly_token_budget=None,
    )


@router.put(
    "/config",
    response_model=OrgConfigResponse,
)
async def update_org_config(
    request: Request,
    config_update: OrgConfigUpdateRequest,
    db_session=Depends(check_llm_routing_entitlement),
):
    """
    Update organization LLM configuration.

    Creates configuration if it doesn't exist.
    Only specified fields are updated.
    """
    tenant_ctx = get_tenant_context(request)

    # Validate model IDs if provided
    if config_update.primary_model_id:
        model = db_session.query(LLMModelRegistry).filter(
            LLMModelRegistry.model_id == config_update.primary_model_id,
            LLMModelRegistry.is_enabled == True,
        ).first()
        if not model:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid primary model: {config_update.primary_model_id}",
            )

    if config_update.fallback_model_id:
        model = db_session.query(LLMModelRegistry).filter(
            LLMModelRegistry.model_id == config_update.fallback_model_id,
            LLMModelRegistry.is_enabled == True,
        ).first()
        if not model:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid fallback model: {config_update.fallback_model_id}",
            )

    # Get or create config
    config = db_session.query(LLMOrgConfig).filter(
        LLMOrgConfig.tenant_id == tenant_ctx.tenant_id
    ).first()

    if not config:
        config = LLMOrgConfig(
            tenant_id=tenant_ctx.tenant_id,
            primary_model_id=config_update.primary_model_id or "anthropic/claude-3-haiku",
            max_tokens_per_request=config_update.max_tokens_per_request or 2048,
            temperature=Decimal(str(config_update.temperature or 0.7)),
        )
        db_session.add(config)
    else:
        # Update only provided fields
        if config_update.primary_model_id is not None:
            config.primary_model_id = config_update.primary_model_id
        if config_update.fallback_model_id is not None:
            config.fallback_model_id = config_update.fallback_model_id
        if config_update.max_tokens_per_request is not None:
            config.max_tokens_per_request = config_update.max_tokens_per_request
        if config_update.temperature is not None:
            config.temperature = Decimal(str(config_update.temperature))
        if config_update.monthly_token_budget is not None:
            config.monthly_token_budget = config_update.monthly_token_budget

    db_session.commit()
    db_session.refresh(config)

    logger.info(
        "Org LLM config updated",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "primary_model": config.primary_model_id,
        },
    )

    return OrgConfigResponse(
        primary_model_id=config.primary_model_id,
        fallback_model_id=config.fallback_model_id,
        max_tokens_per_request=config.max_tokens_per_request,
        temperature=float(config.temperature),
        monthly_token_budget=config.monthly_token_budget,
    )


# =============================================================================
# Routes: Prompt Templates
# =============================================================================


@router.get(
    "/templates",
    response_model=List[PromptTemplateResponse],
)
async def list_prompt_templates(
    request: Request,
    db_session=Depends(check_llm_routing_entitlement),
    include_system: bool = Query(True, description="Include system templates"),
):
    """
    List available prompt templates.

    Returns tenant-specific templates and optionally system templates.
    """
    tenant_ctx = get_tenant_context(request)

    # Get tenant templates
    query = db_session.query(LLMPromptTemplate).filter(
        LLMPromptTemplate.is_active == True,
    )

    if include_system:
        # Include both tenant and system templates
        from sqlalchemy import or_
        query = query.filter(
            or_(
                LLMPromptTemplate.tenant_id == tenant_ctx.tenant_id,
                LLMPromptTemplate.tenant_id.is_(None),
            )
        )
    else:
        query = query.filter(
            LLMPromptTemplate.tenant_id == tenant_ctx.tenant_id
        )

    templates = query.order_by(
        LLMPromptTemplate.template_key,
        LLMPromptTemplate.version.desc(),
    ).all()

    return [
        PromptTemplateResponse(
            template_id=t.id,
            template_key=t.template_key,
            version=t.version,
            template_content=t.template_content,
            variables=t.variables or [],
            is_active=t.is_active,
            is_system=t.is_system,
            created_at=t.created_at,
        )
        for t in templates
    ]


@router.get(
    "/templates/{template_key}",
    response_model=PromptTemplateResponse,
)
async def get_prompt_template(
    request: Request,
    template_key: str,
    db_session=Depends(check_llm_routing_entitlement),
    version: Optional[int] = Query(None, description="Specific version"),
):
    """
    Get a specific prompt template by key.

    Returns tenant-specific template if exists, otherwise system template.
    """
    tenant_ctx = get_tenant_context(request)

    # Try tenant template first
    query = db_session.query(LLMPromptTemplate).filter(
        LLMPromptTemplate.template_key == template_key,
        LLMPromptTemplate.tenant_id == tenant_ctx.tenant_id,
        LLMPromptTemplate.is_active == True,
    )
    if version is not None:
        query = query.filter(LLMPromptTemplate.version == version)

    template = query.order_by(LLMPromptTemplate.version.desc()).first()

    # Fall back to system template
    if not template:
        query = db_session.query(LLMPromptTemplate).filter(
            LLMPromptTemplate.template_key == template_key,
            LLMPromptTemplate.tenant_id.is_(None),
            LLMPromptTemplate.is_system == True,
            LLMPromptTemplate.is_active == True,
        )
        if version is not None:
            query = query.filter(LLMPromptTemplate.version == version)

        template = query.order_by(LLMPromptTemplate.version.desc()).first()

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template not found: {template_key}",
        )

    return PromptTemplateResponse(
        template_id=template.id,
        template_key=template.template_key,
        version=template.version,
        template_content=template.template_content,
        variables=template.variables or [],
        is_active=template.is_active,
        is_system=template.is_system,
        created_at=template.created_at,
    )


@router.post(
    "/templates",
    response_model=PromptTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_prompt_template(
    request: Request,
    template_req: PromptTemplateCreateRequest,
    db_session=Depends(check_llm_routing_entitlement),
):
    """
    Create a custom prompt template.

    Enterprise tier required for custom templates.
    Creates a new version if template_key already exists.
    """
    tenant_ctx = get_tenant_context(request)

    # Check enterprise tier for custom templates
    entitlements = BillingEntitlementsService(db_session, tenant_ctx.tenant_id)
    billing_tier = entitlements.get_billing_tier()

    if billing_tier != "enterprise":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Custom prompt templates require Enterprise plan",
        )

    # Get latest version for this template_key
    latest = db_session.query(LLMPromptTemplate).filter(
        LLMPromptTemplate.tenant_id == tenant_ctx.tenant_id,
        LLMPromptTemplate.template_key == template_req.template_key,
    ).order_by(LLMPromptTemplate.version.desc()).first()

    new_version = (latest.version + 1) if latest else 1

    # Deactivate previous versions
    if latest:
        db_session.query(LLMPromptTemplate).filter(
            LLMPromptTemplate.tenant_id == tenant_ctx.tenant_id,
            LLMPromptTemplate.template_key == template_req.template_key,
        ).update({LLMPromptTemplate.is_active: False})

    # Create new template
    template = LLMPromptTemplate(
        tenant_id=tenant_ctx.tenant_id,
        template_key=template_req.template_key,
        version=new_version,
        template_content=template_req.template_content,
        variables=template_req.variables,
        is_active=True,
        is_system=False,
        created_by=tenant_ctx.user_id,
    )

    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    logger.info(
        "Custom prompt template created",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "template_key": template_req.template_key,
            "version": new_version,
        },
    )

    return PromptTemplateResponse(
        template_id=template.id,
        template_key=template.template_key,
        version=template.version,
        template_content=template.template_content,
        variables=template.variables or [],
        is_active=template.is_active,
        is_system=template.is_system,
        created_at=template.created_at,
    )


# =============================================================================
# Routes: Usage Statistics
# =============================================================================


@router.get(
    "/usage/stats",
    response_model=UsageStatsResponse,
)
async def get_usage_stats(
    request: Request,
    db_session=Depends(check_llm_routing_entitlement),
    days: int = Query(30, ge=1, le=365, description="Number of days"),
):
    """
    Get LLM usage statistics for the tenant.
    """
    tenant_ctx = get_tenant_context(request)

    from src.services.llm_routing_service import LLMRoutingService

    service = LLMRoutingService(db_session, tenant_ctx.tenant_id)
    stats = service.get_usage_stats(days=days)

    return UsageStatsResponse(**stats)


@router.get(
    "/usage/logs",
    response_model=UsageLogListResponse,
)
async def list_usage_logs(
    request: Request,
    db_session=Depends(check_llm_routing_entitlement),
    limit: int = Query(50, le=100, description="Maximum logs to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    model_id: Optional[str] = Query(None, description="Filter by model"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
):
    """
    List LLM usage logs for the tenant.

    Returns logs sorted by created_at (newest first).
    """
    tenant_ctx = get_tenant_context(request)

    query = db_session.query(LLMUsageLog).filter(
        LLMUsageLog.tenant_id == tenant_ctx.tenant_id
    )

    if model_id:
        query = query.filter(LLMUsageLog.model_id == model_id)
    if status_filter:
        query = query.filter(LLMUsageLog.response_status == status_filter)

    total = query.count()

    logs = (
        query.order_by(LLMUsageLog.created_at.desc())
        .offset(offset)
        .limit(limit + 1)
        .all()
    )

    has_more = len(logs) > limit
    logs = logs[:limit]

    return UsageLogListResponse(
        logs=[
            UsageLogResponse(
                id=log.id,
                model_id=log.model_id,
                prompt_template_key=log.prompt_template_key,
                input_tokens=log.input_tokens,
                output_tokens=log.output_tokens,
                total_tokens=log.total_tokens,
                latency_ms=log.latency_ms,
                cost_usd=float(log.cost_usd),
                was_fallback=log.was_fallback,
                response_status=log.response_status,
                created_at=log.created_at,
            )
            for log in logs
        ],
        total=total,
        has_more=has_more,
    )
