"""
AI Action model for storing executable actions.

Stores AI-generated actions derived from recommendations that can be
executed against external platforms (Meta, Google, Shopify).

Each action represents an executable change with:
- Link to source recommendation
- Target platform and entity
- Action parameters (budget, status, etc.)
- Execution lifecycle tracking
- Before/after state for audit and rollback

SECURITY:
- Tenant isolation via TenantScopedMixin (tenant_id from JWT only)
- Idempotency keys prevent duplicate executions
- Full audit trail via action_execution_logs

PRINCIPLES:
- External platform is source of truth
- No blind retries on failure
- Full before/after state capture
- Rollback support for all executed actions

Story 8.5 - Action Execution (Scoped & Reversible)
"""

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Enum,
    DateTime,
    Text,
    Index,
    UniqueConstraint,
    ForeignKey,
    JSON,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin


# Use JSONB for PostgreSQL, JSON for other databases (testing)
JSONType = JSON().with_variant(JSONB(), "postgresql")


class ActionType(str, enum.Enum):
    """Types of actions the system can execute."""
    PAUSE_CAMPAIGN = "pause_campaign"
    RESUME_CAMPAIGN = "resume_campaign"
    ADJUST_BUDGET = "adjust_budget"
    ADJUST_BID = "adjust_bid"
    UPDATE_TARGETING = "update_targeting"
    UPDATE_SCHEDULE = "update_schedule"


class ActionStatus(str, enum.Enum):
    """
    Action execution status lifecycle.

    State transitions:
    - pending_approval -> approved (user approves)
    - approved -> queued (added to execution queue)
    - queued -> executing (worker picks up)
    - executing -> succeeded (platform confirms)
    - executing -> failed (platform rejects or error)
    - executing -> partially_executed (some ops succeeded)
    - succeeded -> rolled_back (rollback executed)
    - succeeded -> rollback_failed (rollback attempted but failed)
    """
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    QUEUED = "queued"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIALLY_EXECUTED = "partially_executed"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


class ActionTargetEntityType(str, enum.Enum):
    """Types of entities that can be targeted by actions."""
    CAMPAIGN = "campaign"
    AD_SET = "ad_set"
    AD = "ad"
    AD_GROUP = "ad_group"
    KEYWORD = "keyword"


class Platform(str, enum.Enum):
    """Supported external platforms."""
    META = "meta"
    GOOGLE = "google"
    SHOPIFY = "shopify"


class AIAction(Base, TimestampMixin, TenantScopedMixin):
    """
    Stores executable actions derived from AI recommendations.

    Each action represents a change to be executed on an external platform.
    Actions go through an approval workflow before execution, and include
    full state capture for audit and rollback purposes.

    SECURITY: tenant_id from TenantScopedMixin ensures isolation.
    tenant_id is ONLY extracted from JWT, never from client input.

    IDEMPOTENCY: idempotency_key ensures safe retries without duplicate
    executions on the external platform.
    """

    __tablename__ = "ai_actions"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Unique action identifier (UUID)"
    )

    # Link to source recommendation (REQUIRED)
    recommendation_id = Column(
        String(255),
        ForeignKey("ai_recommendations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID of the recommendation this action is based on"
    )

    # Action specification
    action_type = Column(
        Enum(ActionType),
        nullable=False,
        index=True,
        comment="Type of action to execute"
    )

    platform = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Target platform: meta, google, or shopify"
    )

    target_entity_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="External platform ID of the entity being modified"
    )

    target_entity_type = Column(
        Enum(ActionTargetEntityType),
        nullable=False,
        comment="Type of entity: campaign, ad_set, ad, etc."
    )

    # Action parameters (JSONB for flexibility)
    action_params = Column(
        JSONType,
        nullable=False,
        default=dict,
        comment="Action parameters: {new_budget, currency}, {status}, etc."
    )

    # Status tracking
    status = Column(
        Enum(ActionStatus),
        nullable=False,
        default=ActionStatus.PENDING_APPROVAL,
        index=True,
        comment="Current status in execution lifecycle"
    )

    # Approval tracking
    approved_by = Column(
        String(255),
        nullable=True,
        comment="User ID who approved this action"
    )

    approved_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When action was approved"
    )

    # Execution tracking
    idempotency_key = Column(
        String(255),
        nullable=True,
        unique=True,
        comment="Unique key for safe retries"
    )

    execution_started_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When execution started"
    )

    execution_completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When execution completed (success or failure)"
    )

    # State capture (for audit and rollback)
    before_state = Column(
        JSONType,
        nullable=True,
        comment="Platform state captured BEFORE execution"
    )

    after_state = Column(
        JSONType,
        nullable=True,
        comment="Platform state captured AFTER execution (source of truth)"
    )

    # Rollback support
    rollback_instructions = Column(
        JSONType,
        nullable=True,
        comment="Instructions to reverse this action"
    )

    rollback_executed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When rollback was executed"
    )

    # Error tracking
    error_message = Column(
        Text,
        nullable=True,
        comment="Error message if execution failed"
    )

    error_code = Column(
        String(100),
        nullable=True,
        comment="Error code from platform API"
    )

    retry_count = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of execution retry attempts"
    )

    # Job reference
    job_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="ID of the ActionJob that executed this action"
    )

    # Determinism hash for deduplication
    content_hash = Column(
        String(64),
        nullable=False,
        index=True,
        comment="SHA256 hash of action parameters for deduplication"
    )

    # Relationships
    recommendation = relationship(
        "AIRecommendation",
        lazy="joined"
    )

    execution_logs = relationship(
        "ActionExecutionLog",
        back_populates="action",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )

    # Indexes for efficient querying
    __table_args__ = (
        # Tenant + status for listing actions by status
        Index("ix_ai_actions_tenant_status", "tenant_id", "status"),
        # Tenant + created_at for listing recent actions
        Index(
            "ix_ai_actions_tenant_created",
            "tenant_id",
            "created_at",
            postgresql_ops={"created_at": "DESC"}
        ),
        # Deduplication: prevent identical actions for same recommendation
        UniqueConstraint(
            "tenant_id",
            "content_hash",
            "recommendation_id",
            name="uq_ai_actions_dedup"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AIAction("
            f"id={self.id}, "
            f"tenant_id={self.tenant_id}, "
            f"type={self.action_type.value if self.action_type else None}, "
            f"status={self.status.value if self.status else None}, "
            f"platform={self.platform}"
            f")>"
        )

    # ==========================================================================
    # Status checks
    # ==========================================================================

    @property
    def is_pending_approval(self) -> bool:
        """Check if action is awaiting approval."""
        return self.status == ActionStatus.PENDING_APPROVAL

    @property
    def is_approved(self) -> bool:
        """Check if action has been approved."""
        return self.status == ActionStatus.APPROVED

    @property
    def is_queued(self) -> bool:
        """Check if action is in execution queue."""
        return self.status == ActionStatus.QUEUED

    @property
    def is_executing(self) -> bool:
        """Check if action is currently executing."""
        return self.status == ActionStatus.EXECUTING

    @property
    def is_succeeded(self) -> bool:
        """Check if action execution succeeded."""
        return self.status == ActionStatus.SUCCEEDED

    @property
    def is_failed(self) -> bool:
        """Check if action execution failed."""
        return self.status == ActionStatus.FAILED

    @property
    def is_terminal(self) -> bool:
        """Check if action is in a terminal state (no more transitions)."""
        return self.status in (
            ActionStatus.SUCCEEDED,
            ActionStatus.FAILED,
            ActionStatus.PARTIALLY_EXECUTED,
            ActionStatus.ROLLED_BACK,
            ActionStatus.ROLLBACK_FAILED,
        )

    @property
    def can_be_executed(self) -> bool:
        """Check if action can be executed."""
        return self.status in (ActionStatus.APPROVED, ActionStatus.QUEUED)

    @property
    def can_be_rolled_back(self) -> bool:
        """Check if action can be rolled back."""
        return (
            self.status == ActionStatus.SUCCEEDED
            and self.rollback_instructions is not None
            and self.rollback_executed_at is None
        )

    # ==========================================================================
    # Status transitions
    # ==========================================================================

    def approve(self, user_id: str) -> None:
        """
        Mark action as approved.

        Args:
            user_id: ID of the user approving the action
        """
        if self.status != ActionStatus.PENDING_APPROVAL:
            raise ValueError(
                f"Cannot approve action in status {self.status.value}"
            )
        self.status = ActionStatus.APPROVED
        self.approved_by = user_id
        self.approved_at = datetime.now(timezone.utc)

    def queue_for_execution(self) -> None:
        """Mark action as queued for execution."""
        if self.status != ActionStatus.APPROVED:
            raise ValueError(
                f"Cannot queue action in status {self.status.value}"
            )
        self.status = ActionStatus.QUEUED

    def mark_executing(self, idempotency_key: str) -> None:
        """
        Mark action as currently executing.

        Args:
            idempotency_key: Key for safe retries
        """
        if self.status not in (ActionStatus.APPROVED, ActionStatus.QUEUED):
            raise ValueError(
                f"Cannot execute action in status {self.status.value}"
            )
        self.status = ActionStatus.EXECUTING
        self.idempotency_key = idempotency_key
        self.execution_started_at = datetime.now(timezone.utc)

    def mark_succeeded(
        self,
        before_state: dict,
        after_state: dict,
        rollback_instructions: Optional[dict] = None,
    ) -> None:
        """
        Mark action as successfully executed.

        Args:
            before_state: Platform state before execution
            after_state: Platform state after execution (confirmed)
            rollback_instructions: How to reverse this action
        """
        if self.status != ActionStatus.EXECUTING:
            raise ValueError(
                f"Cannot mark success for action in status {self.status.value}"
            )
        self.status = ActionStatus.SUCCEEDED
        self.before_state = before_state
        self.after_state = after_state
        self.rollback_instructions = rollback_instructions
        self.execution_completed_at = datetime.now(timezone.utc)

    def mark_failed(
        self,
        error_message: str,
        error_code: Optional[str] = None,
        before_state: Optional[dict] = None,
    ) -> None:
        """
        Mark action as failed.

        Args:
            error_message: Human-readable error message
            error_code: Platform-specific error code
            before_state: Platform state captured before failure (if any)
        """
        if self.status != ActionStatus.EXECUTING:
            raise ValueError(
                f"Cannot mark failed for action in status {self.status.value}"
            )
        self.status = ActionStatus.FAILED
        self.error_message = error_message
        self.error_code = error_code
        if before_state:
            self.before_state = before_state
        self.execution_completed_at = datetime.now(timezone.utc)

    def mark_partially_executed(
        self,
        error_message: str,
        before_state: dict,
        after_state: dict,
    ) -> None:
        """
        Mark action as partially executed (some operations succeeded).

        Args:
            error_message: Description of what failed
            before_state: Platform state before execution
            after_state: Platform state after partial execution
        """
        if self.status != ActionStatus.EXECUTING:
            raise ValueError(
                f"Cannot mark partial for action in status {self.status.value}"
            )
        self.status = ActionStatus.PARTIALLY_EXECUTED
        self.error_message = error_message
        self.before_state = before_state
        self.after_state = after_state
        self.execution_completed_at = datetime.now(timezone.utc)

    def mark_rolled_back(self) -> None:
        """Mark action as successfully rolled back."""
        if self.status != ActionStatus.SUCCEEDED:
            raise ValueError(
                f"Cannot rollback action in status {self.status.value}"
            )
        self.status = ActionStatus.ROLLED_BACK
        self.rollback_executed_at = datetime.now(timezone.utc)

    def mark_rollback_failed(self, error_message: str) -> None:
        """
        Mark rollback as failed.

        Args:
            error_message: Why rollback failed
        """
        if self.status != ActionStatus.SUCCEEDED:
            raise ValueError(
                f"Cannot mark rollback failed for action in status {self.status.value}"
            )
        self.status = ActionStatus.ROLLBACK_FAILED
        self.error_message = error_message
        self.rollback_executed_at = datetime.now(timezone.utc)

    def increment_retry(self) -> None:
        """Increment retry count."""
        self.retry_count += 1
