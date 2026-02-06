"""
Pydantic schemas for Admin Backfill Request API.

Story 3.4 - Backfill Request API
"""

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceSystem(str, Enum):
    """Supported source systems for backfill."""
    SHOPIFY = "shopify"
    FACEBOOK = "facebook"
    GOOGLE = "google"
    TIKTOK = "tiktok"
    PINTEREST = "pinterest"
    SNAPCHAT = "snapchat"
    AMAZON = "amazon"
    KLAVIYO = "klaviyo"
    RECHARGE = "recharge"
    GA4 = "ga4"


class CreateBackfillRequest(BaseModel):
    """Request body for POST /api/v1/admin/backfills."""
    tenant_id: str = Field(
        ...,
        description="Target tenant ID for the backfill",
        min_length=1,
        max_length=255,
        examples=["tenant_abc123"],
    )
    source_system: SourceSystem = Field(
        ...,
        description="Source system to backfill data from",
        examples=["shopify"],
    )
    start_date: date = Field(
        ...,
        description="Start date for backfill (YYYY-MM-DD)",
        examples=["2024-01-01"],
    )
    end_date: date = Field(
        ...,
        description="End date for backfill (YYYY-MM-DD)",
        examples=["2024-03-31"],
    )
    reason: str = Field(
        ...,
        description="Human-readable reason for the backfill request",
        min_length=10,
        max_length=500,
        examples=["Data gap detected after connector migration on 2024-01-15"],
    )

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date > self.end_date:
            raise ValueError(
                f"start_date ({self.start_date}) must be before or equal to end_date ({self.end_date})"
            )
        if self.end_date > date.today():
            raise ValueError("end_date cannot be in the future")
        return self


class BackfillRequestResponse(BaseModel):
    """Response model for a backfill request."""
    id: str
    tenant_id: str
    source_system: str
    start_date: str
    end_date: str
    status: str
    reason: str
    requested_by: str
    idempotency_key: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BackfillRequestCreatedResponse(BaseModel):
    """Response when a backfill request is created or returned (idempotent)."""
    backfill_request: BackfillRequestResponse
    created: bool = Field(
        ..., description="True if newly created, False if existing returned"
    )
    message: str


class BackfillChunkStatus(BaseModel):
    """Status of a single backfill chunk (date slice)."""
    chunk_index: int
    chunk_start_date: str
    chunk_end_date: str
    status: str
    attempt: int = 0
    duration_seconds: Optional[float] = None
    rows_affected: Optional[int] = None
    error_message: Optional[str] = None


class BackfillStatusResponse(BaseModel):
    """Detailed status response for a single backfill request."""
    id: str
    tenant_id: str
    source_system: str
    start_date: str
    end_date: str
    status: str = Field(
        description="Effective status: pending, running, paused, failed, completed"
    )
    percent_complete: float = Field(
        description="Percentage of chunks completed (0-100)"
    )
    total_chunks: int
    completed_chunks: int
    failed_chunks: int
    current_chunk: Optional[BackfillChunkStatus] = Field(
        None, description="Currently executing date slice"
    )
    failure_reasons: List[str] = Field(
        default_factory=list, description="Error messages from failed chunks"
    )
    estimated_seconds_remaining: Optional[float] = Field(
        None, description="Estimated seconds to completion based on avg chunk duration"
    )
    reason: str
    requested_by: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BackfillStatusListResponse(BaseModel):
    """Paginated list of backfill request statuses."""
    backfills: List[BackfillStatusResponse]
    total: int
