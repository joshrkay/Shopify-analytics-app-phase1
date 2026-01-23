"""
Backfill API routes for triggering dbt model reprocessing.

SECURITY: All routes require valid tenant context from JWT.
Backfills are tenant-scoped - users can only backfill their own data.

Story 4.8 - Backfills & Reprocessing
"""

import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel, Field, field_validator

from src.platform.tenant_context import get_tenant_context, TenantContext
from src.services.backfill_service import (
    BackfillService,
    BackfillServiceError,
    InvalidDateRangeError,
    DbtExecutionError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backfills", tags=["backfills"])


# Request/Response models

class TriggerBackfillRequest(BaseModel):
    """Request to trigger a backfill."""
    model_selector: str = Field(
        ...,
        description="dbt model selector (e.g., 'fact_orders', 'facts', 'fact_orders+')",
        min_length=1,
        max_length=200,
    )
    start_date: str = Field(
        ...,
        description="Start date for backfill (YYYY-MM-DD or YYYY-MM-DD HH:MI:SS)",
        examples=["2024-01-01", "2024-01-01 00:00:00"],
    )
    end_date: str = Field(
        ...,
        description="End date for backfill (YYYY-MM-DD or YYYY-MM-DD HH:MI:SS)",
        examples=["2024-01-31", "2024-01-31 23:59:59"],
    )

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        """Validate date format."""
        try:
            # Try parsing as ISO format
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return v
        except ValueError:
            raise ValueError(
                f"Invalid date format: {v}. Expected YYYY-MM-DD or YYYY-MM-DD HH:MI:SS"
            )


class BackfillResultResponse(BaseModel):
    """Response with backfill execution result."""
    backfill_id: str
    tenant_id: str
    model_selector: str
    start_date: str
    end_date: str
    status: str
    is_successful: bool
    rows_affected: Optional[int] = None
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None
    completed_at: str


# Dependency to get database session
async def get_db_session():
    """Get synchronous database session."""
    import os
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


async def get_audit_db_session():
    """Get async database session for audit logging."""
    import os
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        # Return None if database not configured (audit logging is optional)
        yield None
        return

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    try:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        AsyncSessionLocal = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )

        session = AsyncSessionLocal()
        try:
            yield session
        finally:
            await session.close()
    except Exception as e:
        logger.warning(f"Failed to create audit DB session: {e}")
        yield None


def get_backfill_service(
    request: Request,
    db_session=Depends(get_db_session),
    audit_db=Depends(get_audit_db_session),
) -> BackfillService:
    """Get backfill service instance scoped to current tenant."""
    tenant_ctx = get_tenant_context(request)
    return BackfillService(db_session, tenant_ctx.tenant_id, audit_db)


# Routes

@router.post(
    "/trigger",
    response_model=BackfillResultResponse,
    status_code=status.HTTP_200_OK,
)
async def trigger_backfill(
    request: Request,
    body: TriggerBackfillRequest,
    service: BackfillService = Depends(get_backfill_service),
):
    """
    Trigger a dbt backfill for the specified date range.

    Executes dbt run with date range variables to reprocess historical data.
    All backfills are tenant-scoped and audited.

    SECURITY: Only backfills data for the authenticated tenant.
    Models must filter by tenant_id to prevent cross-tenant access.

    Example:
        POST /api/backfills/trigger
        {
            "model_selector": "fact_orders",
            "start_date": "2024-01-01",
            "end_date": "2024-01-31"
        }
    """
    tenant_ctx = get_tenant_context(request)

    logger.info(
        "Backfill trigger requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
            "model_selector": body.model_selector,
            "start_date": body.start_date,
            "end_date": body.end_date,
        },
    )

    try:
        result = await service.execute_backfill(
            model_selector=body.model_selector,
            start_date=body.start_date,
            end_date=body.end_date,
        )

        return BackfillResultResponse(
            backfill_id=result.backfill_id,
            tenant_id=result.tenant_id,
            model_selector=result.model_selector,
            start_date=result.start_date,
            end_date=result.end_date,
            status=result.status,
            is_successful=result.is_successful,
            rows_affected=result.rows_affected,
            duration_seconds=result.duration_seconds,
            error_message=result.error_message,
            completed_at=result.completed_at.isoformat(),
        )

    except InvalidDateRangeError as e:
        logger.warning(
            "Invalid date range for backfill",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "error": str(e),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except DbtExecutionError as e:
        logger.error(
            "dbt execution failed",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "error": str(e),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backfill execution failed: {str(e)}",
        )
    except BackfillServiceError as e:
        logger.error(
            "Backfill service error",
            extra={
                "tenant_id": tenant_ctx.tenant_id,
                "error": str(e),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
