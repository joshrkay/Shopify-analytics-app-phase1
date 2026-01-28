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
]
