"""
Action Proposal model for storing AI-proposed actions requiring approval.

Stores action proposals that convert recommendations into executable actions.
Each proposal requires explicit human approval before any action is taken.

KEY PRINCIPLES:
- NO action executes without explicit approval
- Single campaign scope maximum (no bulk operations)
- Clear risk disclosure for every proposal
- Full audit trail for compliance

SECURITY:
- Tenant isolation via TenantScopedMixin (tenant_id from JWT only)
- Only MERCHANT_ADMIN and AGENCY_ADMIN can approve/reject
- Content hash for deduplication ensures determinism

Story 8.4 - Action Proposals (Approval Required)
"""

import enum
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import (
    Column,
    String,
    Float,
    Enum,
    DateTime,
    Text,
    Index,
    UniqueConstraint,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import JSON

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin
from src.models.ai_recommendation import RiskLevel


# Use JSONB for PostgreSQL, JSON for other databases (testing)
JSONType = JSON().with_variant(JSONB(), "postgresql")

# Default TTL for proposals (7 days)
DEFAULT_PROPOSAL_TTL_DAYS = 7


class ActionType(str, enum.Enum):
    """
    Types of actions that can be proposed.

    Each action type has a maximum scope defined in MAX_SCOPE_RULES.
    """
    REDUCE_BUDGET = "reduce_budget"
    INCREASE_BUDGET = "increase_budget"
    PAUSE_CAMPAIGN = "pause_campaign"
    RESUME_CAMPAIGN = "resume_campaign"
    ADJUST_TARGETING = "adjust_targeting"
    MODIFY_BIDDING = "modify_bidding"


class ActionStatus(str, enum.Enum):
    """
    Status of an action proposal in the approval workflow.

    State transitions:
    - PROPOSED -> APPROVED (user approves)
    - PROPOSED -> REJECTED (user rejects)
    - PROPOSED -> EXPIRED (TTL exceeded)
    - PROPOSED -> CANCELLED (system cancels, e.g., stale data)
    """
    PROPOSED = "proposed"       # Awaiting approval
    APPROVED = "approved"       # Approved, ready for execution
    REJECTED = "rejected"       # User rejected
    EXPIRED = "expired"         # TTL exceeded without decision
    CANCELLED = "cancelled"     # System cancelled (e.g., stale data)


class TargetPlatform(str, enum.Enum):
    """Ad platforms that actions can target."""
    META = "meta"
    GOOGLE = "google"
    TIKTOK = "tiktok"


class TargetEntityType(str, enum.Enum):
    """
    Types of entities that can be targeted by actions.

    Max scope is CAMPAIGN - no account-level or bulk operations.
    """
    CAMPAIGN = "campaign"       # Max scope: single campaign
    AD_SET = "ad_set"          # Ad set / ad group level
    AD = "ad"                   # Individual ad level


# Maximum scope allowed per action type
MAX_SCOPE_RULES: dict[ActionType, TargetEntityType] = {
    ActionType.REDUCE_BUDGET: TargetEntityType.CAMPAIGN,
    ActionType.INCREASE_BUDGET: TargetEntityType.CAMPAIGN,
    ActionType.PAUSE_CAMPAIGN: TargetEntityType.CAMPAIGN,
    ActionType.RESUME_CAMPAIGN: TargetEntityType.CAMPAIGN,
    ActionType.ADJUST_TARGETING: TargetEntityType.AD_SET,
    ActionType.MODIFY_BIDDING: TargetEntityType.AD_SET,
}


def get_default_expiration() -> datetime:
    """Calculate default expiration datetime (7 days from now)."""
    return datetime.now(timezone.utc) + timedelta(days=DEFAULT_PROPOSAL_TTL_DAYS)


class ActionProposal(Base, TimestampMixin, TenantScopedMixin):
    """
    Stores AI-proposed actions that require human approval.

    Each proposal is derived from an AI recommendation and represents
    a concrete, executable action. NO action is executed without
    explicit approval from an authorized user.

    APPROVAL ROLES:
    - MERCHANT_ADMIN: Can approve for their tenant
    - AGENCY_ADMIN: Can approve for tenants in their allowed_tenants

    SCOPE LIMITS:
    - Maximum scope is single campaign (no bulk operations)
    - No account-level changes
    - One entity per proposal

    SECURITY: tenant_id from TenantScopedMixin ensures isolation.
    tenant_id is ONLY extracted from JWT, never from client input.
    """

    __tablename__ = "action_proposals"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Unique proposal identifier (UUID)"
    )

    # Link to source recommendation (REQUIRED)
    source_recommendation_id = Column(
        String(255),
        ForeignKey("ai_recommendations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID of the recommendation this proposal is based on"
    )

    # Action classification
    action_type = Column(
        Enum(ActionType),
        nullable=False,
        index=True,
        comment="Type of action being proposed"
    )

    # Approval status
    status = Column(
        Enum(ActionStatus),
        nullable=False,
        default=ActionStatus.PROPOSED,
        index=True,
        comment="Current status in approval workflow"
    )

    # Target specification
    target_platform = Column(
        Enum(TargetPlatform),
        nullable=False,
        index=True,
        comment="Ad platform (meta, google, tiktok)"
    )

    target_entity_type = Column(
        Enum(TargetEntityType),
        nullable=False,
        comment="Type of entity: campaign, ad_set, ad"
    )

    target_entity_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="External platform ID of the target entity"
    )

    target_entity_name = Column(
        String(500),
        nullable=True,
        comment="Human-readable name of the target entity"
    )

    # Change specification
    proposed_change = Column(
        JSONType,
        nullable=False,
        comment="Change details (e.g., {type: percentage, value: -15})"
    )

    current_value = Column(
        JSONType,
        nullable=True,
        comment="Current state snapshot at proposal time"
    )

    # Impact and risk
    expected_effect = Column(
        Text,
        nullable=False,
        comment="Human-readable description of expected impact"
    )

    risk_disclaimer = Column(
        Text,
        nullable=False,
        comment="Risk disclosure text for user review"
    )

    risk_level = Column(
        Enum(RiskLevel),
        nullable=False,
        default=RiskLevel.MEDIUM,
        index=True,
        comment="Risk level: low, medium, high"
    )

    confidence_score = Column(
        Float,
        nullable=False,
        comment="Confidence score 0.0-1.0"
    )

    # Expiration
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=get_default_expiration,
        index=True,
        comment="Auto-expire if not actioned by this time"
    )

    # Decision tracking
    decided_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the proposal was approved/rejected"
    )

    decided_by_user_id = Column(
        String(255),
        nullable=True,
        comment="User ID who approved/rejected (from JWT)"
    )

    decision_reason = Column(
        Text,
        nullable=True,
        comment="Optional reason for rejection"
    )

    # Deduplication
    content_hash = Column(
        String(64),
        nullable=False,
        index=True,
        comment="SHA256 hash of proposal content for deduplication"
    )

    # Generation metadata
    generated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="When proposal was generated"
    )

    job_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="ID of the ActionProposalJob that generated this"
    )

    # Extensible metadata
    proposal_metadata = Column(
        JSONType,
        nullable=False,
        default=dict,
        comment="Additional metadata for extensibility"
    )

    # Indexes for efficient querying
    __table_args__ = (
        # Tenant + status + created_at for listing pending proposals
        Index(
            "ix_action_proposals_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
            postgresql_ops={"created_at": "DESC"}
        ),
        # Tenant + expires_at for finding expired proposals
        Index(
            "ix_action_proposals_tenant_expires",
            "tenant_id",
            "expires_at"
        ),
        # Tenant + platform for filtering by platform
        Index(
            "ix_action_proposals_tenant_platform",
            "tenant_id",
            "target_platform"
        ),
        # Deduplication: prevent duplicate proposals for same recommendation
        UniqueConstraint(
            "tenant_id",
            "content_hash",
            "source_recommendation_id",
            name="uq_action_proposals_dedup"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ActionProposal("
            f"id={self.id}, "
            f"tenant_id={self.tenant_id}, "
            f"action_type={self.action_type.value if self.action_type else None}, "
            f"status={self.status.value if self.status else None}"
            f")>"
        )

    @property
    def is_pending(self) -> bool:
        """Check if proposal is awaiting a decision."""
        return self.status == ActionStatus.PROPOSED

    @property
    def is_decided(self) -> bool:
        """Check if proposal has been approved or rejected."""
        return self.status in (ActionStatus.APPROVED, ActionStatus.REJECTED)

    @property
    def is_terminal(self) -> bool:
        """Check if proposal has reached a terminal state."""
        return self.status in (
            ActionStatus.APPROVED,
            ActionStatus.REJECTED,
            ActionStatus.EXPIRED,
            ActionStatus.CANCELLED,
        )

    @property
    def is_expired(self) -> bool:
        """Check if proposal has passed its expiration time."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def requires_approval(self) -> bool:
        """Always returns True - all proposals require approval."""
        return True

    def approve(self, user_id: str) -> None:
        """
        Mark proposal as approved.

        Args:
            user_id: ID of the approving user (from JWT)
        """
        if not self.is_pending:
            raise ValueError(f"Cannot approve proposal in status: {self.status}")

        self.status = ActionStatus.APPROVED
        self.decided_at = datetime.now(timezone.utc)
        self.decided_by_user_id = user_id

    def reject(self, user_id: str, reason: str | None = None) -> None:
        """
        Mark proposal as rejected.

        Args:
            user_id: ID of the rejecting user (from JWT)
            reason: Optional reason for rejection
        """
        if not self.is_pending:
            raise ValueError(f"Cannot reject proposal in status: {self.status}")

        self.status = ActionStatus.REJECTED
        self.decided_at = datetime.now(timezone.utc)
        self.decided_by_user_id = user_id
        self.decision_reason = reason

    def expire(self) -> None:
        """Mark proposal as expired (TTL exceeded)."""
        if not self.is_pending:
            raise ValueError(f"Cannot expire proposal in status: {self.status}")

        self.status = ActionStatus.EXPIRED
        self.decided_at = datetime.now(timezone.utc)

    def cancel(self, reason: str) -> None:
        """
        Mark proposal as cancelled by system.

        Args:
            reason: Reason for cancellation (e.g., stale data)
        """
        if not self.is_pending:
            raise ValueError(f"Cannot cancel proposal in status: {self.status}")

        self.status = ActionStatus.CANCELLED
        self.decided_at = datetime.now(timezone.utc)
        self.decision_reason = reason
