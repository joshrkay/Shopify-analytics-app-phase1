"""
Pydantic schemas for Actions API (Story 8.5).

Request and response models for action execution endpoints.

Story 8.5 - Action Execution (Scoped & Reversible)
"""

from typing import Optional, List, Any
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Nested Models
# =============================================================================


class ActionTargetInfo(BaseModel):
    """Information about the target entity of an action."""

    platform: str = Field(..., description="Ad platform (meta, google, shopify)")
    entity_type: str = Field(..., description="Type of entity: campaign, ad_set, ad, ad_group")
    entity_id: str = Field(..., description="External platform ID of the target")


class StateSnapshot(BaseModel):
    """State snapshot captured before/after execution."""

    captured_at: datetime = Field(..., description="When state was captured")
    data: dict = Field(..., description="State data from platform")


# =============================================================================
# Response Models
# =============================================================================


class ActionResponse(BaseModel):
    """Response model for a single action."""

    model_config = ConfigDict(from_attributes=True)

    action_id: str = Field(..., description="Unique action identifier")
    action_type: str = Field(..., description="Type of action: pause_campaign, adjust_budget, etc.")
    status: str = Field(..., description="Current status in execution lifecycle")
    platform: str = Field(..., description="Target platform: meta, google, shopify")
    target: ActionTargetInfo = Field(..., description="Target entity information")
    action_params: dict = Field(..., description="Action parameters")

    # Approval info
    approved_by: Optional[str] = Field(None, description="User ID who approved")
    approved_at: Optional[datetime] = Field(None, description="When approved")

    # Execution info
    execution_started_at: Optional[datetime] = Field(None, description="When execution started")
    execution_completed_at: Optional[datetime] = Field(None, description="When execution completed")

    # State snapshots
    before_state: Optional[dict] = Field(None, description="Platform state before execution")
    after_state: Optional[dict] = Field(None, description="Platform state after execution")

    # Rollback info
    can_rollback: bool = Field(False, description="Whether this action can be rolled back")
    rollback_executed_at: Optional[datetime] = Field(None, description="When rollback was executed")

    # Error info
    error_message: Optional[str] = Field(None, description="Error message if failed")
    error_code: Optional[str] = Field(None, description="Platform error code if failed")
    retry_count: int = Field(0, description="Number of retry attempts")

    # Metadata
    recommendation_id: str = Field(..., description="Source recommendation ID")
    job_id: Optional[str] = Field(None, description="Execution job ID")
    created_at: datetime = Field(..., description="When action was created")
    updated_at: datetime = Field(..., description="When action was last updated")


class ActionsListResponse(BaseModel):
    """Response model for listing actions."""

    actions: List[ActionResponse]
    total: int = Field(..., description="Total count of matching actions")
    has_more: bool = Field(..., description="Whether more results are available")


class ActionExecutionResponse(BaseModel):
    """Response model for action execution trigger."""

    status: str = Field("ok", description="Operation status")
    action_id: str = Field(..., description="The action ID that was triggered")
    job_id: Optional[str] = Field(None, description="Job ID for async execution")
    new_status: str = Field(..., description="New status of the action")
    message: str = Field(..., description="Human-readable status message")


class ActionRollbackResponse(BaseModel):
    """Response model for action rollback."""

    status: str = Field("ok", description="Operation status")
    action_id: str = Field(..., description="The action ID that was rolled back")
    new_status: str = Field(..., description="New status of the action")
    message: str = Field(..., description="Human-readable status message")


# =============================================================================
# Execution Log Models
# =============================================================================


class ExecutionLogEntry(BaseModel):
    """Response model for a single execution log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Log entry ID")
    event_type: str = Field(..., description="Type of event: execution_started, api_request_sent, etc.")
    event_timestamp: datetime = Field(..., description="When this event occurred")

    # API interaction details
    request_payload: Optional[dict] = Field(None, description="API request sent")
    response_payload: Optional[dict] = Field(None, description="API response received")
    http_status_code: Optional[int] = Field(None, description="HTTP status code")

    # State and error info
    state_snapshot: Optional[dict] = Field(None, description="State at time of event")
    error_details: Optional[dict] = Field(None, description="Error information if failure")

    triggered_by: Optional[str] = Field(None, description="Actor: system, user:id, worker:job_id")


class ExecutionLogsResponse(BaseModel):
    """Response model for action execution logs."""

    action_id: str = Field(..., description="The action this log belongs to")
    entries: List[ExecutionLogEntry] = Field(..., description="Log entries in chronological order")


# =============================================================================
# Job Models
# =============================================================================


class ActionJobResponse(BaseModel):
    """Response model for an action job."""

    model_config = ConfigDict(from_attributes=True)

    job_id: str = Field(..., description="Unique job identifier")
    status: str = Field(..., description="Job status: queued, running, succeeded, failed, partial_success")
    action_count: int = Field(..., description="Number of actions in this job")
    succeeded_count: int = Field(0, description="Number of successfully executed actions")
    failed_count: int = Field(0, description="Number of failed actions")

    started_at: Optional[datetime] = Field(None, description="When job started processing")
    completed_at: Optional[datetime] = Field(None, description="When job completed")

    error_message: Optional[str] = Field(None, description="Error message if job failed")

    created_at: datetime = Field(..., description="When job was created")


class ActionJobsListResponse(BaseModel):
    """Response model for listing action jobs."""

    jobs: List[ActionJobResponse]
    total: int = Field(..., description="Total count of matching jobs")
    has_more: bool = Field(..., description="Whether more results are available")


# =============================================================================
# Request Models
# =============================================================================


class ExecuteActionRequest(BaseModel):
    """Request body for executing an action."""

    # Optional: override parameters (limited subset allowed)
    # If not provided, uses action's original params
    pass


class RollbackActionRequest(BaseModel):
    """Request body for rolling back an action."""

    reason: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional reason for the rollback"
    )


# =============================================================================
# Stats Models
# =============================================================================


class ActionStatsResponse(BaseModel):
    """Response model for action statistics."""

    total_actions: int = Field(..., description="Total number of actions")
    pending_approval: int = Field(0, description="Actions awaiting approval")
    approved: int = Field(0, description="Approved actions not yet executed")
    queued: int = Field(0, description="Actions queued for execution")
    executing: int = Field(0, description="Currently executing actions")
    succeeded: int = Field(0, description="Successfully executed actions")
    failed: int = Field(0, description="Failed actions")
    rolled_back: int = Field(0, description="Rolled back actions")

    # Monthly usage
    actions_this_month: int = Field(0, description="Actions executed this month")
    monthly_limit: Optional[int] = Field(None, description="Monthly action limit (-1 = unlimited)")
