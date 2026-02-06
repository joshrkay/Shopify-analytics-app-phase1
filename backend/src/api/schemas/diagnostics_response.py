"""
Diagnostics API response schemas.

Pydantic models for root cause diagnostics responses.

Story 4.2 - Data Quality Root Cause Signals (Prompt 4.2.7)
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class EvidenceLink(BaseModel):
    """Link to supporting evidence for a root cause hypothesis."""

    label: str = Field(description="Human-readable link label")
    link_type: str = Field(
        description="Type of resource: sync_run, dbt_run, dq_result, log"
    )
    resource_id: Optional[str] = Field(
        None, description="ID of the linked resource"
    )


class RankedCauseResponse(BaseModel):
    """A single ranked root cause hypothesis."""

    rank: int = Field(description="1-based rank (1 = most likely)")
    cause_type: str = Field(
        description="Root cause category (e.g. ingestion_failure, schema_drift)"
    )
    confidence_score: float = Field(
        description="Confidence in this hypothesis (0.0 - 1.0)",
        ge=0.0,
        le=1.0,
    )
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Signal-specific evidence supporting this hypothesis",
    )
    first_seen_at: Optional[str] = Field(
        None, description="ISO timestamp when the signal was first observed"
    )
    suggested_next_step: str = Field(
        description="Operator-facing recommended investigation action"
    )
    evidence_links: list[EvidenceLink] = Field(
        default_factory=list,
        description="Links to related logs, sync runs, and dbt runs",
    )


class AnomalySummaryResponse(BaseModel):
    """Summary of the anomaly that triggered root cause analysis."""

    dataset: str = Field(description="Affected dataset (e.g. shopify_orders)")
    anomaly_type: str = Field(
        description="DQ check type that detected the anomaly"
    )
    detected_at: str = Field(
        description="ISO timestamp when the anomaly was detected"
    )
    connector_id: Optional[str] = Field(
        None, description="Connector associated with the anomaly"
    )
    correlation_id: Optional[str] = Field(
        None, description="Correlation ID linking related DQ events"
    )


class DiagnosticsResponse(BaseModel):
    """Full root cause diagnostics response for an anomaly."""

    signal_id: str = Field(description="Unique ID of this root cause signal")
    anomaly_summary: AnomalySummaryResponse
    ranked_causes: list[RankedCauseResponse] = Field(
        description="Root cause hypotheses ranked by confidence (descending)"
    )
    total_hypotheses: int = Field(
        description="Number of hypotheses returned"
    )
    confidence_sum: float = Field(
        description="Sum of confidence scores across all hypotheses (<= 1.0)"
    )
    analysis_duration_ms: float = Field(
        description="Time taken for root cause analysis in milliseconds"
    )
    investigation_steps: list[str] = Field(
        default_factory=list,
        description="Ordered operator investigation steps based on top causes",
    )
    is_active: bool = Field(
        True, description="Whether this signal is still active"
    )


class DiagnosticsListResponse(BaseModel):
    """List of diagnostics signals for a dataset."""

    signals: list[DiagnosticsResponse]
    total: int
    has_more: bool
