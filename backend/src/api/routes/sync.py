"""
Sync API routes for triggering and monitoring data syncs.

SECURITY: All routes require valid tenant context from JWT.
Syncs are tenant-scoped - users can only sync their own connections.

Story 3.5 - Sync Orchestration & Retry Logic
"""

import os
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel, Field

from src.platform.tenant_context import get_tenant_context, TenantContext
from src.services.sync_orchestrator import (
    SyncOrchestrator,
    SyncResult,
    SyncOrchestratorError,
    ConnectionNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])


# Request/Response models

class TriggerSyncRequest(BaseModel):
    """Request to trigger a sync."""
    timeout_seconds: Optional[float] = Field(
        3600,
        description="Maximum time to wait for sync completion",
        ge=60,
        le=7200,
    )


class SyncResultResponse(BaseModel):
    """Response with sync result and retry information."""
    connection_id: str
    job_id: Optional[str]
    status: str
    is_successful: bool
    records_synced: int
    bytes_synced: int
    duration_seconds: Optional[float]
    attempt_count: int
    max_retries: int
    error_message: Optional[str]
    completed_at: str


class SyncStateResponse(BaseModel):
    """Response with current sync state."""
    connection_id: str
    status: str
    last_sync_at: Optional[str]
    last_sync_status: Optional[str]
    is_enabled: bool
    can_sync: bool


class FailedConnectionResponse(BaseModel):
    """Information about a failed connection."""
    connection_id: str
    connection_name: str
    last_sync_at: Optional[str]
    last_sync_status: Optional[str]


class FailedConnectionsListResponse(BaseModel):
    """List of failed connections."""
    connections: list[FailedConnectionResponse]
    count: int


# Dependency to get database session
async def get_db_session():
    """Get database session."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured",
        )

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_sync_orchestrator(
    request: Request,
    db_session=Depends(get_db_session),
) -> SyncOrchestrator:
    """Get sync orchestrator instance scoped to current tenant."""
    tenant_ctx = get_tenant_context(request)
    return SyncOrchestrator(db_session, tenant_ctx.tenant_id)


# Routes

@router.post(
    "/trigger/{connection_id}",
    response_model=SyncResultResponse,
    status_code=status.HTTP_200_OK,
)
async def trigger_sync(
    request: Request,
    connection_id: str,
    body: Optional[TriggerSyncRequest] = None,
    orchestrator: SyncOrchestrator = Depends(get_sync_orchestrator),
):
    """
    Trigger a sync for a connection with automatic retry on failure.

    Implements exponential backoff retry logic (up to 3 retries by default).
    Returns the final result after all attempts complete.

    SECURITY: Only syncs connections belonging to the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)
    timeout = body.timeout_seconds if body else 3600

    logger.info(
        "Sync trigger requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
            "connection_id": connection_id,
            "timeout_seconds": timeout,
        },
    )

    try:
        result = await orchestrator.trigger_sync_with_retry(
            connection_id=connection_id,
            timeout_seconds=timeout,
        )

        return SyncResultResponse(
            connection_id=result.connection_id,
            job_id=result.job_id,
            status=result.status,
            is_successful=result.is_successful,
            records_synced=result.records_synced,
            bytes_synced=result.bytes_synced,
            duration_seconds=result.duration_seconds,
            attempt_count=result.attempt_count,
            max_retries=result.max_retries,
            error_message=result.error_message,
            completed_at=result.completed_at.isoformat(),
        )

    except ConnectionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection not found: {connection_id}",
        )
    except SyncOrchestratorError as e:
        logger.error(
            "Sync trigger failed",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "connection_id": connection_id,
                "error": str(e),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/state/{connection_id}",
    response_model=SyncStateResponse,
)
async def get_sync_state(
    request: Request,
    connection_id: str,
    orchestrator: SyncOrchestrator = Depends(get_sync_orchestrator),
):
    """
    Get current sync state for a connection.

    Returns status, last sync time, and whether sync is currently possible.

    SECURITY: Only returns state for connections belonging to the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Sync state requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "connection_id": connection_id,
        },
    )

    try:
        state = orchestrator.get_sync_state(connection_id)

        return SyncStateResponse(
            connection_id=state["connection_id"],
            status=state["status"],
            last_sync_at=state["last_sync_at"],
            last_sync_status=state["last_sync_status"],
            is_enabled=state["is_enabled"],
            can_sync=state["can_sync"],
        )

    except ConnectionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection not found: {connection_id}",
        )


@router.get(
    "/failed",
    response_model=FailedConnectionsListResponse,
)
async def list_failed_connections(
    request: Request,
    orchestrator: SyncOrchestrator = Depends(get_sync_orchestrator),
):
    """
    List all failed connections for the current tenant.

    Useful for monitoring and alerting on sync failures.

    SECURITY: Only returns failed connections belonging to the authenticated tenant.
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Failed connections list requested",
        extra={"tenant_id": tenant_ctx.tenant_id},
    )

    failed = orchestrator.get_failed_connections()

    return FailedConnectionsListResponse(
        connections=[
            FailedConnectionResponse(
                connection_id=conn["connection_id"],
                connection_name=conn["connection_name"],
                last_sync_at=conn["last_sync_at"],
                last_sync_status=conn["last_sync_status"],
            )
            for conn in failed
        ],
        count=len(failed),
    )
