"""
Action Proposal Approval Service.

Handles the approval workflow for action proposals.
All approval/rejection decisions create audit trail entries.

SECURITY:
- Only authorized roles can approve/reject (merchant_admin, agency_admin)
- All decisions are logged with user context
- Tenant isolation via tenant_id in all queries

NO AUTO-EXECUTION:
- This service handles approval workflow only
- Actual action execution is handled separately after approval

Story 8.4 - Action Proposals (Approval Required)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session
from sqlalchemy import and_

from src.models.action_proposal import ActionProposal, ActionStatus
from src.models.action_approval_audit import ActionApprovalAudit, AuditAction
from src.services.action_proposal_validation import ActionProposalValidationService
from src.constants.permissions import (
    can_approve_action_proposals,
    get_primary_approver_role,
)


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


class ApprovalError(Exception):
    """Exception raised when approval operation fails."""
    pass


class NotFoundError(Exception):
    """Exception raised when proposal is not found."""
    pass


class PermissionDeniedError(Exception):
    """Exception raised when user lacks permission to approve."""
    pass


class ActionProposalApprovalService:
    """
    Service for handling action proposal approval workflow.

    SECURITY: All operations are tenant-scoped. tenant_id from JWT only.
    All decisions create immutable audit trail entries.
    """

    def __init__(
        self,
        db_session: Session,
        tenant_id: str,
    ):
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id
        self.validator = ActionProposalValidationService()

    def get_proposal(self, proposal_id: str) -> ActionProposal | None:
        """
        Get a proposal by ID.

        Args:
            proposal_id: ID of the proposal

        Returns:
            ActionProposal or None if not found
        """
        return (
            self.db.query(ActionProposal)
            .filter(
                ActionProposal.id == proposal_id,
                ActionProposal.tenant_id == self.tenant_id,
            )
            .first()
        )

    def approve_proposal(
        self,
        proposal_id: str,
        user_id: str,
        user_roles: list[str],
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ActionProposal:
        """
        Approve an action proposal.

        Args:
            proposal_id: ID of the proposal to approve
            user_id: ID of the approving user (from JWT)
            user_roles: List of user's roles (from JWT)
            ip_address: Client IP address (for audit)
            user_agent: Client user agent (for audit)

        Returns:
            Updated ActionProposal

        Raises:
            NotFoundError: If proposal not found
            PermissionDeniedError: If user cannot approve
            ApprovalError: If proposal cannot be approved
        """
        # Validate permission
        if not can_approve_action_proposals(user_roles):
            raise PermissionDeniedError(
                "User does not have permission to approve action proposals"
            )

        # Fetch proposal
        proposal = self.get_proposal(proposal_id)
        if not proposal:
            raise NotFoundError(f"Proposal not found: {proposal_id}")

        # Validate proposal can be approved
        validation_result = self.validator.validate_approver_can_approve(proposal.status)
        if not validation_result.is_valid:
            raise ApprovalError(validation_result.error_message)

        # Check if proposal is expired
        if proposal.is_expired:
            raise ApprovalError("Cannot approve expired proposal")

        # Store previous status for audit
        previous_status = proposal.status

        # Approve the proposal
        proposal.approve(user_id)

        # Create audit entry
        approver_role = get_primary_approver_role(user_roles)
        audit_entry = ActionApprovalAudit.create_entry(
            tenant_id=self.tenant_id,
            action_proposal_id=proposal.id,
            action=AuditAction.APPROVED,
            previous_status=previous_status,
            new_status=ActionStatus.APPROVED,
            performed_by_user_id=user_id,
            performed_by_role=approver_role,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        self.db.add(audit_entry)
        self.db.flush()

        logger.info(
            "Action proposal approved",
            extra={
                "tenant_id": self.tenant_id,
                "proposal_id": proposal.id,
                "user_id": user_id,
                "user_role": approver_role,
            },
        )

        return proposal

    def reject_proposal(
        self,
        proposal_id: str,
        user_id: str,
        user_roles: list[str],
        reason: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ActionProposal:
        """
        Reject an action proposal.

        Args:
            proposal_id: ID of the proposal to reject
            user_id: ID of the rejecting user (from JWT)
            user_roles: List of user's roles (from JWT)
            reason: Optional reason for rejection
            ip_address: Client IP address (for audit)
            user_agent: Client user agent (for audit)

        Returns:
            Updated ActionProposal

        Raises:
            NotFoundError: If proposal not found
            PermissionDeniedError: If user cannot reject
            ApprovalError: If proposal cannot be rejected
        """
        # Validate permission
        if not can_approve_action_proposals(user_roles):
            raise PermissionDeniedError(
                "User does not have permission to reject action proposals"
            )

        # Fetch proposal
        proposal = self.get_proposal(proposal_id)
        if not proposal:
            raise NotFoundError(f"Proposal not found: {proposal_id}")

        # Validate proposal can be rejected
        validation_result = self.validator.validate_approver_can_reject(proposal.status)
        if not validation_result.is_valid:
            raise ApprovalError(validation_result.error_message)

        # Store previous status for audit
        previous_status = proposal.status

        # Reject the proposal
        proposal.reject(user_id, reason)

        # Create audit entry
        approver_role = get_primary_approver_role(user_roles)
        audit_entry = ActionApprovalAudit.create_entry(
            tenant_id=self.tenant_id,
            action_proposal_id=proposal.id,
            action=AuditAction.REJECTED,
            previous_status=previous_status,
            new_status=ActionStatus.REJECTED,
            performed_by_user_id=user_id,
            performed_by_role=approver_role,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        self.db.add(audit_entry)
        self.db.flush()

        logger.info(
            "Action proposal rejected",
            extra={
                "tenant_id": self.tenant_id,
                "proposal_id": proposal.id,
                "user_id": user_id,
                "user_role": approver_role,
                "reason": reason,
            },
        )

        return proposal

    def expire_stale_proposals(self) -> int:
        """
        Expire proposals that have passed their expiration time.

        This should be called by a scheduled job to clean up stale proposals.

        Returns:
            Number of proposals expired
        """
        now = datetime.now(timezone.utc)

        # Find proposals that are pending and expired
        expired_proposals = (
            self.db.query(ActionProposal)
            .filter(
                ActionProposal.tenant_id == self.tenant_id,
                ActionProposal.status == ActionStatus.PROPOSED,
                ActionProposal.expires_at < now,
            )
            .all()
        )

        count = 0
        for proposal in expired_proposals:
            previous_status = proposal.status
            proposal.expire()

            # Create audit entry
            audit_entry = ActionApprovalAudit.create_entry(
                tenant_id=self.tenant_id,
                action_proposal_id=proposal.id,
                action=AuditAction.EXPIRED,
                previous_status=previous_status,
                new_status=ActionStatus.EXPIRED,
                reason="Proposal expired due to TTL",
            )

            self.db.add(audit_entry)
            count += 1

        if count > 0:
            self.db.flush()
            logger.info(
                "Expired stale proposals",
                extra={
                    "tenant_id": self.tenant_id,
                    "count": count,
                },
            )

        return count

    def cancel_proposal(
        self,
        proposal_id: str,
        reason: str,
    ) -> ActionProposal:
        """
        Cancel a proposal (system action).

        Used when a proposal becomes invalid (e.g., campaign deleted).

        Args:
            proposal_id: ID of the proposal to cancel
            reason: Reason for cancellation

        Returns:
            Updated ActionProposal

        Raises:
            NotFoundError: If proposal not found
            ApprovalError: If proposal cannot be cancelled
        """
        proposal = self.get_proposal(proposal_id)
        if not proposal:
            raise NotFoundError(f"Proposal not found: {proposal_id}")

        if not proposal.is_pending:
            raise ApprovalError(
                f"Cannot cancel proposal in status '{proposal.status.value}'"
            )

        previous_status = proposal.status
        proposal.cancel(reason)

        # Create audit entry (system action, no user)
        audit_entry = ActionApprovalAudit.create_entry(
            tenant_id=self.tenant_id,
            action_proposal_id=proposal.id,
            action=AuditAction.CANCELLED,
            previous_status=previous_status,
            new_status=ActionStatus.CANCELLED,
            reason=reason,
        )

        self.db.add(audit_entry)
        self.db.flush()

        logger.info(
            "Action proposal cancelled",
            extra={
                "tenant_id": self.tenant_id,
                "proposal_id": proposal.id,
                "reason": reason,
            },
        )

        return proposal

    def get_audit_trail(
        self,
        proposal_id: str,
    ) -> list[ActionApprovalAudit]:
        """
        Get the audit trail for a proposal.

        Args:
            proposal_id: ID of the proposal

        Returns:
            List of audit entries, ordered by performed_at ascending
        """
        return (
            self.db.query(ActionApprovalAudit)
            .filter(
                ActionApprovalAudit.action_proposal_id == proposal_id,
                ActionApprovalAudit.tenant_id == self.tenant_id,
            )
            .order_by(ActionApprovalAudit.performed_at.asc())
            .all()
        )

    def list_proposals(
        self,
        status: ActionStatus | None = None,
        action_type: str | None = None,
        platform: str | None = None,
        risk_level: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ActionProposal], int]:
        """
        List action proposals with optional filters.

        Args:
            status: Filter by status
            action_type: Filter by action type
            platform: Filter by platform
            risk_level: Filter by risk level
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            Tuple of (list of proposals, total count)
        """
        from src.models.action_proposal import (
            ActionType as AT,
            TargetPlatform as TP,
        )
        from src.models.ai_recommendation import RiskLevel as RL

        query = self.db.query(ActionProposal).filter(
            ActionProposal.tenant_id == self.tenant_id
        )

        # Apply filters
        if status:
            query = query.filter(ActionProposal.status == status)

        if action_type:
            try:
                action_type_enum = AT(action_type)
                query = query.filter(ActionProposal.action_type == action_type_enum)
            except ValueError:
                pass

        if platform:
            try:
                platform_enum = TP(platform)
                query = query.filter(ActionProposal.target_platform == platform_enum)
            except ValueError:
                pass

        if risk_level:
            try:
                risk_level_enum = RL(risk_level)
                query = query.filter(ActionProposal.risk_level == risk_level_enum)
            except ValueError:
                pass

        # Get total count
        total = query.count()

        # Apply ordering and pagination
        proposals = (
            query
            .order_by(ActionProposal.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return proposals, total

    def get_pending_count(self) -> int:
        """Get count of pending proposals for this tenant."""
        return (
            self.db.query(ActionProposal)
            .filter(
                ActionProposal.tenant_id == self.tenant_id,
                ActionProposal.status == ActionStatus.PROPOSED,
            )
            .count()
        )
