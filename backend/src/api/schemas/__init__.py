"""
API schemas package.

Contains Pydantic models for request/response validation.
"""

from src.api.schemas.action_proposals import (
    ActionProposalResponse,
    ActionProposalsListResponse,
    ProposalActionResponse,
    ApproveRejectRequest,
    AuditEntryResponse,
    AuditTrailResponse,
    TargetInfo,
    ProposedChange,
)

from src.api.schemas.backfill_request import (
    CreateBackfillRequest,
    BackfillRequestResponse,
    BackfillRequestCreatedResponse,
    BackfillChunkStatus,
    BackfillStatusResponse,
    BackfillStatusListResponse,
    SourceSystem,
)

__all__ = [
    # Action Proposals (Story 8.4)
    "ActionProposalResponse",
    "ActionProposalsListResponse",
    "ProposalActionResponse",
    "ApproveRejectRequest",
    "AuditEntryResponse",
    "AuditTrailResponse",
    "TargetInfo",
    "ProposedChange",
    # Backfill Requests (Story 3.4)
    "CreateBackfillRequest",
    "BackfillRequestResponse",
    "BackfillRequestCreatedResponse",
    "BackfillChunkStatus",
    "BackfillStatusResponse",
    "BackfillStatusListResponse",
    "SourceSystem",
]
