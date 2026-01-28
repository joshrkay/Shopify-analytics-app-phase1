"""
Action Approval Audit model for tracking approval workflow events.

Provides an immutable audit trail for all action proposal decisions.
Required for compliance and security auditing.

SECURITY:
- Immutable records (no update/delete operations)
- Captures user context: user_id, role, IP, user agent
- Tenant isolation via TenantScopedMixin

Story 8.4 - Action Proposals (Approval Required)
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    String,
    Enum,
    DateTime,
    Text,
    Index,
    ForeignKey,
)

from src.db_base import Base
from src.models.base import TenantScopedMixin
from src.models.action_proposal import ActionStatus


class AuditAction(str, enum.Enum):
    """
    Types of audit events that are recorded.

    Each state transition creates an immutable audit record.
    """
    CREATED = "created"         # Proposal was created
    APPROVED = "approved"       # User approved the proposal
    REJECTED = "rejected"       # User rejected the proposal
    EXPIRED = "expired"         # System expired the proposal (TTL)
    CANCELLED = "cancelled"     # System cancelled the proposal


class ActionApprovalAudit(Base, TenantScopedMixin):
    """
    Immutable audit trail for action proposal decisions.

    Every state change to an ActionProposal creates a new audit record.
    These records cannot be modified or deleted once created.

    CAPTURED CONTEXT:
    - User identity (user_id from JWT)
    - User role at time of action
    - Client metadata (IP address, user agent)
    - State transition (previous -> new status)
    - Optional reason/notes

    SECURITY: tenant_id from TenantScopedMixin ensures isolation.
    tenant_id is ONLY extracted from JWT, never from client input.

    NOTE: This model intentionally does NOT inherit TimestampMixin
    because audit records should only have created_at (immutable).
    """

    __tablename__ = "action_approval_audit"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Unique audit entry identifier (UUID)"
    )

    # Link to action proposal
    action_proposal_id = Column(
        String(255),
        ForeignKey("action_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID of the action proposal this audit entry relates to"
    )

    # Audit event type
    action = Column(
        Enum(AuditAction),
        nullable=False,
        index=True,
        comment="Type of audit event"
    )

    # State transition
    previous_status = Column(
        Enum(ActionStatus),
        nullable=True,
        comment="Status before the action (null for CREATED)"
    )

    new_status = Column(
        Enum(ActionStatus),
        nullable=False,
        comment="Status after the action"
    )

    # User context (null for system actions like EXPIRED)
    performed_by_user_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="User ID who performed the action (null for system)"
    )

    performed_by_role = Column(
        String(100),
        nullable=True,
        comment="User's role at the time of action"
    )

    # Optional reason/notes
    reason = Column(
        Text,
        nullable=True,
        comment="Optional reason or notes for the action"
    )

    # Client metadata for compliance
    ip_address = Column(
        String(45),  # IPv6 max length
        nullable=True,
        comment="Client IP address (for compliance auditing)"
    )

    user_agent = Column(
        String(500),
        nullable=True,
        comment="Client user agent (for compliance auditing)"
    )

    # Immutable timestamp (no updated_at - records cannot be modified)
    performed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="When the action was performed"
    )

    # Indexes for efficient querying
    __table_args__ = (
        # Tenant + proposal for getting audit history
        Index(
            "ix_action_approval_audit_tenant_proposal",
            "tenant_id",
            "action_proposal_id"
        ),
        # Tenant + performed_at for chronological listing
        Index(
            "ix_action_approval_audit_tenant_performed",
            "tenant_id",
            "performed_at",
            postgresql_ops={"performed_at": "DESC"}
        ),
        # User ID for finding all actions by a user
        Index(
            "ix_action_approval_audit_user",
            "performed_by_user_id"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ActionApprovalAudit("
            f"id={self.id}, "
            f"proposal_id={self.action_proposal_id}, "
            f"action={self.action.value if self.action else None}, "
            f"user={self.performed_by_user_id}"
            f")>"
        )

    @classmethod
    def create_entry(
        cls,
        tenant_id: str,
        action_proposal_id: str,
        action: AuditAction,
        new_status: ActionStatus,
        previous_status: ActionStatus | None = None,
        performed_by_user_id: str | None = None,
        performed_by_role: str | None = None,
        reason: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> "ActionApprovalAudit":
        """
        Factory method to create an audit entry.

        Args:
            tenant_id: Tenant ID (from JWT)
            action_proposal_id: ID of the related action proposal
            action: Type of audit event
            new_status: Status after the action
            previous_status: Status before the action (null for CREATED)
            performed_by_user_id: User who performed the action (null for system)
            performed_by_role: User's role at time of action
            reason: Optional reason/notes
            ip_address: Client IP for compliance
            user_agent: Client user agent for compliance

        Returns:
            New ActionApprovalAudit instance (not yet persisted)
        """
        return cls(
            tenant_id=tenant_id,
            action_proposal_id=action_proposal_id,
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            performed_by_user_id=performed_by_user_id,
            performed_by_role=performed_by_role,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent,
        )
