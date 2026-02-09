"""
Pydantic schemas for Action Proposals API.

Request and response models for action proposal endpoints.

Story 8.4 - Action Proposals (Approval Required)
"""

from typing import Optional, List, Any
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Nested Models
# =============================================================================


class TargetInfo(BaseModel):
    """Information about the target entity of an action."""

    platform: str = Field(..., description="Ad platform (meta, google, tiktok)")
    entity_type: str = Field(..., description="Type of entity: campaign, ad_set, ad")
    entity_id: str = Field(..., description="External platform ID of the target")
    entity_name: Optional[str] = Field(None, description="Human-readable name")


class ProposedChange(BaseModel):
    """Details of the proposed change."""

    type: str = Field(..., description="Type of change: percentage, absolute, status, etc.")
    value: Any = Field(..., description="The change value")
    description: Optional[str] = Field(None, description="Human-readable description")


# =============================================================================
# Response Models
# =============================================================================


class ActionProposalResponse(BaseModel):
    """Response model for a single action proposal."""

    model_config = ConfigDict(from_attributes=True)

    proposal_id: str = Field(..., description="Unique proposal identifier")
    action_type: str = Field(..., description="Type of action being proposed")
    status: str = Field(..., description="Current status: proposed, approved, rejected, expired, cancelled")
    target: TargetInfo = Field(..., description="Target entity information")
    proposed_change: dict = Field(..., description="Details of the proposed change")
    current_value: Optional[dict] = Field(None, description="Current state snapshot")
    expected_effect: str = Field(..., description="Human-readable expected impact")
    risk_disclaimer: str = Field(..., description="Risk disclosure text")
    risk_level: str = Field(..., description="Risk level: low, medium, high")
    confidence_score: float = Field(..., ge=0, le=1, description="Confidence score 0.0-1.0")
    requires_approval: bool = Field(True, description="Always true - all proposals require approval")
    expires_at: datetime = Field(..., description="Expiration time for the proposal")
    created_at: datetime = Field(..., description="When the proposal was created")
    decided_at: Optional[datetime] = Field(None, description="When approved/rejected")
    decided_by: Optional[str] = Field(None, description="User ID who approved/rejected")
    decision_reason: Optional[str] = Field(None, description="Reason for rejection")
    source_recommendation_id: Optional[str] = Field(None, description="Source recommendation ID")


class ActionProposalsListResponse(BaseModel):
    """Response model for listing action proposals."""

    proposals: List[ActionProposalResponse]
    total: int = Field(..., description="Total count of matching proposals")
    has_more: bool = Field(..., description="Whether more results are available")
    pending_count: int = Field(0, description="Count of proposals awaiting decision")


class ProposalActionResponse(BaseModel):
    """Response model for proposal actions (approve, reject)."""

    status: str = Field("ok", description="Operation status")
    proposal_id: str = Field(..., description="The proposal ID that was actioned")
    new_status: str = Field(..., description="New status of the proposal")


# =============================================================================
# Request Models
# =============================================================================


class ApproveRejectRequest(BaseModel):
    """Request body for approving or rejecting a proposal."""

    reason: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional reason (required for rejection, optional for approval)"
    )


# =============================================================================
# Audit Models
# =============================================================================


class AuditEntryResponse(BaseModel):
    """Response model for a single audit entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Audit entry ID")
    action: str = Field(..., description="Type of action: created, approved, rejected, expired, cancelled")
    performed_at: datetime = Field(..., description="When the action was performed")
    performed_by: Optional[str] = Field(None, description="User ID who performed the action")
    performed_by_role: Optional[str] = Field(None, description="Role at time of action")
    previous_status: Optional[str] = Field(None, description="Status before the action")
    new_status: str = Field(..., description="Status after the action")
    reason: Optional[str] = Field(None, description="Optional reason or notes")


class AuditTrailResponse(BaseModel):
    """Response model for the full audit trail of a proposal."""

    proposal_id: str = Field(..., description="The proposal this audit trail belongs to")
    entries: List[AuditEntryResponse] = Field(..., description="Audit entries in chronological order")
