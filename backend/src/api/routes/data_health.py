"""
Data health API routes for monitoring data freshness.

Provides endpoints for:
- Overall data health summary
- Per-source health indicators
- Stale data warnings

SECURITY: All routes require valid tenant context from JWT.
Health data is tenant-scoped - users can only see their own connections.

Story 3.6 - Data Freshness & Health Monitoring
"""

import os
import logging
from typing import Optional, List

from fastapi import APIRouter, Request, HTTPException, status, Depends
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
