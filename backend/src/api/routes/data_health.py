"""
Data health API routes for monitoring data freshness.

Provides endpoints for:
- Overall data health summary
- Per-source health indicators
- Stale data warnings
- Freshness SLA configuration (per source, per billing tier)

SECURITY: All routes require valid tenant context from JWT.
Health data is tenant-scoped - users can only see their own connections.

Story 3.6 - Data Freshness & Health Monitoring
"""

import os
import logging
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from pydantic import BaseModel, Field

from src.platform.tenant_context import get_tenant_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data-health", tags=["data-health"])


# =============================================================================
# Response Models
# =============================================================================

class SourceHealthResponse(BaseModel):
    """Health information for a single data source."""
    connection_id: str
    connection_name: str
    source_type: Optional[str]
    status: str
    is_enabled: bool
    freshness_status: str
    last_sync_at: Optional[str]
    last_sync_status: Optional[str]
    sync_frequency_minutes: int
    minutes_since_sync: Optional[int]
    expected_next_sync_at: Optional[str]
    is_stale: bool
    is_healthy: bool
    warning_message: Optional[str]


class DataHealthSummaryResponse(BaseModel):
    """Overall data health summary."""
    total_sources: int
    healthy_sources: int
    stale_sources: int
    critical_sources: int
    never_synced_sources: int
    disabled_sources: int
    failed_sources: int
    overall_health_score: float = Field(
        description="Health score from 0-100"
    )
    has_warnings: bool
    sources: List[SourceHealthResponse]


class StaleSourcesResponse(BaseModel):
    """List of stale data sources."""
    stale_sources: List[SourceHealthResponse]
    count: int


class SourceSLAResponse(BaseModel):
    """SLA thresholds for a single source across all tiers."""
    source_name: str
    tiers: Dict[str, Dict[str, int]]


class FreshnessSLAConfigResponse(BaseModel):
    """Full freshness SLA configuration."""
    version: int
    default_tier: str
    tiers: List[str]
    sources: Dict[str, Dict[str, Dict[str, int]]]


# Merchant data health response (Story 4.3)
from src.models.merchant_data_health import MerchantDataHealthResponse


# =============================================================================
# Dependencies
# =============================================================================

# Import shared database session dependency
from src.database.session import get_db_session


def get_data_health_service(
    request: Request,
    db_session=Depends(get_db_session),
):
    """Get data health service instance scoped to current tenant."""
    from src.services.data_health_service import DataHealthService

    tenant_ctx = get_tenant_context(request)
    return DataHealthService(db_session, tenant_ctx.tenant_id)


# =============================================================================
# Helper Functions
# =============================================================================

def _source_health_to_response(health_info) -> SourceHealthResponse:
    """Convert SourceHealthInfo to response model."""
    return SourceHealthResponse(
        connection_id=health_info.connection_id,
        connection_name=health_info.connection_name,
        source_type=health_info.source_type,
        status=health_info.status,
        is_enabled=health_info.is_enabled,
        freshness_status=health_info.freshness_status.value,
        last_sync_at=(
            health_info.last_sync_at.isoformat()
            if health_info.last_sync_at else None
        ),
        last_sync_status=health_info.last_sync_status,
        sync_frequency_minutes=health_info.sync_frequency_minutes,
        minutes_since_sync=health_info.minutes_since_sync,
        expected_next_sync_at=(
            health_info.expected_next_sync_at.isoformat()
            if health_info.expected_next_sync_at else None
        ),
        is_stale=health_info.is_stale,
        is_healthy=health_info.is_healthy,
        warning_message=health_info.warning_message,
    )


# =============================================================================
# Routes
# =============================================================================

@router.get(
    "/summary",
    response_model=DataHealthSummaryResponse,
)
async def get_data_health_summary(
    request: Request,
    service=Depends(get_data_health_service),
):
    """
    Get overall data health summary for the current tenant.

    Returns aggregate health metrics including:
    - Total, healthy, stale, and critical source counts
    - Overall health score (0-100)
    - Per-source health details
    - Warning indicators

    SECURITY: Only returns health data for connections belonging to
    the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Data health summary requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
        },
    )

    summary = service.get_data_health_summary()

    return DataHealthSummaryResponse(
        total_sources=summary.total_sources,
        healthy_sources=summary.healthy_sources,
        stale_sources=summary.stale_sources,
        critical_sources=summary.critical_sources,
        never_synced_sources=summary.never_synced_sources,
        disabled_sources=summary.disabled_sources,
        failed_sources=summary.failed_sources,
        overall_health_score=summary.overall_health_score,
        has_warnings=summary.has_warnings,
        sources=[
            _source_health_to_response(s) for s in summary.sources
        ],
    )


@router.get(
    "/source/{connection_id}",
    response_model=SourceHealthResponse,
)
async def get_source_health(
    request: Request,
    connection_id: str,
    service=Depends(get_data_health_service),
):
    """
    Get health information for a specific data source.

    Returns freshness status, last sync time, and warning messages
    for the specified connection.

    SECURITY: Only returns health for connections belonging to
    the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Source health requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "connection_id": connection_id,
        },
    )

    health = service.get_source_health(connection_id)

    if not health:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection not found: {connection_id}",
        )

    return _source_health_to_response(health)


@router.get(
    "/stale",
    response_model=StaleSourcesResponse,
)
async def get_stale_sources(
    request: Request,
    service=Depends(get_data_health_service),
):
    """
    Get all data sources with stale data.

    Returns enabled sources that have not synced within their
    expected frequency window. Useful for monitoring dashboards
    and alerting.

    SECURITY: Only returns stale sources belonging to
    the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Stale sources requested",
        extra={"tenant_id": tenant_ctx.tenant_id},
    )

    stale = service.get_stale_sources()

    return StaleSourcesResponse(
        stale_sources=[
            _source_health_to_response(s) for s in stale
        ],
        count=len(stale),
    )


@router.get(
    "/sources",
    response_model=List[SourceHealthResponse],
)
async def get_all_sources_health(
    request: Request,
    service=Depends(get_data_health_service),
):
    """
    Get health information for all data sources.

    Returns freshness status and health indicators for every
    connection belonging to the tenant.

    SECURITY: Only returns health for connections belonging to
    the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "All sources health requested",
        extra={"tenant_id": tenant_ctx.tenant_id},
    )

    sources = service.get_all_sources_health()

    return [_source_health_to_response(s) for s in sources]


# =============================================================================
# Freshness SLA Configuration Endpoints
# =============================================================================

@router.get(
    "/freshness-sla",
    response_model=FreshnessSLAConfigResponse,
)
async def get_freshness_sla_config(request: Request):
    """
    Return the full freshness SLA configuration.

    Exposes per-source, per-tier warn/error thresholds (in minutes)
    from config/data_freshness_sla.yml. This is the same config that
    dbt macros reference, ensuring a single source of truth.

    SECURITY: SLA configuration is not tenant-specific data; it is
    global platform config. Authentication is still required.
    """
    from src.config.freshness_sla import get_freshness_sla_loader

    tenant_ctx = get_tenant_context(request)
    logger.info(
        "Freshness SLA config requested",
        extra={"tenant_id": tenant_ctx.tenant_id},
    )

    loader = get_freshness_sla_loader()
    return FreshnessSLAConfigResponse(**loader.get_all())


@router.get(
    "/freshness-sla/{source_name}",
    response_model=SourceSLAResponse,
)
async def get_source_freshness_sla(
    request: Request,
    source_name: str,
    tier: Optional[str] = Query(
        None,
        description="Filter to a specific billing tier (free, growth, enterprise)",
    ),
):
    """
    Return freshness SLA thresholds for a specific ingestion source.

    Args:
        source_name: SLA source key, e.g. 'shopify_orders', 'email'.
        tier: Optional billing tier filter.

    SECURITY: Authentication required. Config is global (not tenant data).
    """
    from src.config.freshness_sla import get_freshness_sla_loader

    tenant_ctx = get_tenant_context(request)
    logger.info(
        "Source freshness SLA requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "source_name": source_name,
            "tier": tier,
        },
    )

    loader = get_freshness_sla_loader()

    if source_name not in loader.source_names:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown SLA source: {source_name}",
        )

    all_tiers = loader.get_source_all_tiers(source_name)

    if tier:
        if tier not in loader.tiers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown tier: {tier}. Valid tiers: {loader.tiers}",
            )
        all_tiers = {tier: all_tiers[tier]}

    return SourceSLAResponse(source_name=source_name, tiers=all_tiers)


# =============================================================================
# Merchant Data Health Endpoint (Story 4.3)
# =============================================================================

@router.get(
    "/merchant",
    response_model=MerchantDataHealthResponse,
)
async def get_merchant_data_health(
    request: Request,
    db_session=Depends(get_db_session),
):
    """
    Get the merchant-facing data health state.

    Returns a simplified trust indicator combining data availability
    and data quality into one of three states:
    - healthy: All data current, all features enabled
    - delayed: Some data delayed, AI insights paused
    - unavailable: Data temporarily unavailable

    Response fields are merchant-safe and never expose internal
    system details, SLA thresholds, or error codes.

    SECURITY: tenant_id from JWT only. Response scoped to tenant.
    """
    from src.services.merchant_data_health import MerchantDataHealthService

    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Merchant data health requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
        },
    )

    service = MerchantDataHealthService(
        db_session=db_session,
        tenant_id=tenant_ctx.tenant_id,
        billing_tier=getattr(tenant_ctx, "billing_tier", "free"),
    )
    result = service.evaluate()

    return MerchantDataHealthResponse(
        health_state=result.state.value,
        last_updated=result.evaluated_at.isoformat(),
        user_safe_message=result.message,
        ai_insights_enabled=result.ai_insights_enabled,
        dashboards_enabled=result.dashboards_enabled,
        exports_enabled=result.exports_enabled,
    )
