"""
Unit tests for Action Proposal models.

Tests cover:
- ActionProposal model creation and validation
- ActionApprovalAudit model creation
- Status transitions and validation
- Scope rules validation

Story 8.4 - Action Proposals (Approval Required)
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta

from src.models.action_proposal import (
    ActionProposal,
    ActionType,
    ActionStatus,
    TargetPlatform,
    TargetEntityType,
    MAX_SCOPE_RULES,
    DEFAULT_PROPOSAL_TTL_DAYS,
    get_default_expiration,
)
from src.models.action_approval_audit import (
    ActionApprovalAudit,
    AuditAction,
)
from src.models.ai_recommendation import RiskLevel


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tenant_id():
    """Test tenant ID."""
    return "test-tenant-123"


@pytest.fixture
def sample_proposal(tenant_id):
    """Create a sample action proposal."""
    return ActionProposal(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        source_recommendation_id=str(uuid.uuid4()),
        action_type=ActionType.REDUCE_BUDGET,
        status=ActionStatus.PROPOSED,
        target_platform=TargetPlatform.META,
        target_entity_type=TargetEntityType.CAMPAIGN,
        target_entity_id="campaign_123",
        target_entity_name="Summer Sale Campaign",
        proposed_change={"type": "percentage", "value": -15},
        current_value={"budget": 1000.00},
        expected_effect="Budget will decrease by 15%",
        risk_disclaimer="Reducing budget may decrease impressions.",
        risk_level=RiskLevel.MEDIUM,
        confidence_score=0.85,
        expires_at=get_default_expiration(),
        content_hash="abc123def456",
        generated_at=datetime.now(timezone.utc),
        proposal_metadata={},
    )


# =============================================================================
# ActionProposal Model Tests
# =============================================================================


class TestActionProposalModel:
    """Tests for ActionProposal model."""

    def test_creates_with_required_fields(self, tenant_id):
        """Should create ActionProposal with required fields."""
        proposal = ActionProposal(
            tenant_id=tenant_id,
            source_recommendation_id=str(uuid.uuid4()),
            action_type=ActionType.PAUSE_CAMPAIGN,
            status=ActionStatus.PROPOSED,
            target_platform=TargetPlatform.GOOGLE,
            target_entity_type=TargetEntityType.CAMPAIGN,
            target_entity_id="campaign_456",
            proposed_change={"type": "status", "value": "paused"},
            expected_effect="Campaign will stop serving ads.",
            risk_disclaimer="Pausing may affect campaign learning.",
            risk_level=RiskLevel.LOW,
            confidence_score=0.9,
            content_hash="xyz789",
        )

        assert proposal.tenant_id == tenant_id
        assert proposal.action_type == ActionType.PAUSE_CAMPAIGN
        assert proposal.status == ActionStatus.PROPOSED
        assert proposal.requires_approval is True

    def test_is_pending_returns_true_for_proposed_status(self, sample_proposal):
        """is_pending should return True for PROPOSED status."""
        assert sample_proposal.status == ActionStatus.PROPOSED
        assert sample_proposal.is_pending is True

    def test_is_pending_returns_false_for_terminal_status(self, sample_proposal):
        """is_pending should return False for terminal statuses."""
        sample_proposal.status = ActionStatus.APPROVED
        assert sample_proposal.is_pending is False

        sample_proposal.status = ActionStatus.REJECTED
        assert sample_proposal.is_pending is False

    def test_is_decided_returns_true_for_approved_rejected(self, sample_proposal):
        """is_decided should return True for APPROVED or REJECTED."""
        sample_proposal.status = ActionStatus.APPROVED
        assert sample_proposal.is_decided is True

        sample_proposal.status = ActionStatus.REJECTED
        assert sample_proposal.is_decided is True

    def test_is_decided_returns_false_for_proposed(self, sample_proposal):
        """is_decided should return False for PROPOSED."""
        assert sample_proposal.is_decided is False

    def test_is_terminal_for_all_terminal_statuses(self, sample_proposal):
        """is_terminal should return True for all terminal statuses."""
        terminal_statuses = [
            ActionStatus.APPROVED,
            ActionStatus.REJECTED,
            ActionStatus.EXPIRED,
            ActionStatus.CANCELLED,
        ]

        for status in terminal_statuses:
            sample_proposal.status = status
            assert sample_proposal.is_terminal is True, f"Failed for {status}"

    def test_is_terminal_false_for_proposed(self, sample_proposal):
        """is_terminal should return False for PROPOSED."""
        assert sample_proposal.is_terminal is False

    def test_is_expired_returns_true_when_past_expiration(self, sample_proposal):
        """is_expired should return True when past expires_at."""
        sample_proposal.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        assert sample_proposal.is_expired is True

    def test_is_expired_returns_false_when_before_expiration(self, sample_proposal):
        """is_expired should return False when before expires_at."""
        sample_proposal.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        assert sample_proposal.is_expired is False

    def test_requires_approval_always_true(self, sample_proposal):
        """requires_approval should always return True."""
        assert sample_proposal.requires_approval is True

        # Even after approval
        sample_proposal.status = ActionStatus.APPROVED
        assert sample_proposal.requires_approval is True


class TestActionProposalStatusTransitions:
    """Tests for ActionProposal status transition methods."""

    def test_approve_sets_approved_status(self, sample_proposal):
        """approve() should set status to APPROVED."""
        user_id = "user-123"
        sample_proposal.approve(user_id)

        assert sample_proposal.status == ActionStatus.APPROVED
        assert sample_proposal.decided_by_user_id == user_id
        assert sample_proposal.decided_at is not None

    def test_approve_raises_if_not_pending(self, sample_proposal):
        """approve() should raise ValueError if not in PROPOSED status."""
        sample_proposal.status = ActionStatus.APPROVED

        with pytest.raises(ValueError, match="Cannot approve proposal"):
            sample_proposal.approve("user-123")

    def test_reject_sets_rejected_status(self, sample_proposal):
        """reject() should set status to REJECTED."""
        user_id = "user-123"
        reason = "Budget cut not needed"
        sample_proposal.reject(user_id, reason)

        assert sample_proposal.status == ActionStatus.REJECTED
        assert sample_proposal.decided_by_user_id == user_id
        assert sample_proposal.decision_reason == reason
        assert sample_proposal.decided_at is not None

    def test_reject_raises_if_not_pending(self, sample_proposal):
        """reject() should raise ValueError if not in PROPOSED status."""
        sample_proposal.status = ActionStatus.REJECTED

        with pytest.raises(ValueError, match="Cannot reject proposal"):
            sample_proposal.reject("user-123")

    def test_expire_sets_expired_status(self, sample_proposal):
        """expire() should set status to EXPIRED."""
        sample_proposal.expire()

        assert sample_proposal.status == ActionStatus.EXPIRED
        assert sample_proposal.decided_at is not None

    def test_expire_raises_if_not_pending(self, sample_proposal):
        """expire() should raise ValueError if not in PROPOSED status."""
        sample_proposal.status = ActionStatus.APPROVED

        with pytest.raises(ValueError, match="Cannot expire proposal"):
            sample_proposal.expire()

    def test_cancel_sets_cancelled_status(self, sample_proposal):
        """cancel() should set status to CANCELLED with reason."""
        reason = "Campaign was deleted"
        sample_proposal.cancel(reason)

        assert sample_proposal.status == ActionStatus.CANCELLED
        assert sample_proposal.decision_reason == reason
        assert sample_proposal.decided_at is not None

    def test_cancel_raises_if_not_pending(self, sample_proposal):
        """cancel() should raise ValueError if not in PROPOSED status."""
        sample_proposal.status = ActionStatus.REJECTED

        with pytest.raises(ValueError, match="Cannot cancel proposal"):
            sample_proposal.cancel("reason")


# =============================================================================
# ActionApprovalAudit Model Tests
# =============================================================================


class TestActionApprovalAuditModel:
    """Tests for ActionApprovalAudit model."""

    def test_create_entry_factory_method(self, tenant_id):
        """create_entry should create an audit entry with all fields."""
        proposal_id = str(uuid.uuid4())

        entry = ActionApprovalAudit.create_entry(
            tenant_id=tenant_id,
            action_proposal_id=proposal_id,
            action=AuditAction.APPROVED,
            previous_status=ActionStatus.PROPOSED,
            new_status=ActionStatus.APPROVED,
            performed_by_user_id="user-123",
            performed_by_role="merchant_admin",
            reason=None,
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
        )

        assert entry.tenant_id == tenant_id
        assert entry.action_proposal_id == proposal_id
        assert entry.action == AuditAction.APPROVED
        assert entry.previous_status == ActionStatus.PROPOSED
        assert entry.new_status == ActionStatus.APPROVED
        assert entry.performed_by_user_id == "user-123"
        assert entry.performed_by_role == "merchant_admin"
        assert entry.ip_address == "192.168.1.1"
        assert entry.user_agent == "Mozilla/5.0"

    def test_create_entry_for_system_action(self, tenant_id):
        """create_entry should work for system actions (no user)."""
        proposal_id = str(uuid.uuid4())

        entry = ActionApprovalAudit.create_entry(
            tenant_id=tenant_id,
            action_proposal_id=proposal_id,
            action=AuditAction.EXPIRED,
            previous_status=ActionStatus.PROPOSED,
            new_status=ActionStatus.EXPIRED,
            reason="Proposal expired due to TTL",
        )

        assert entry.action == AuditAction.EXPIRED
        assert entry.performed_by_user_id is None
        assert entry.performed_by_role is None
        assert entry.reason == "Proposal expired due to TTL"

    def test_create_entry_for_created_action(self, tenant_id):
        """create_entry should work for CREATED action (no previous status)."""
        proposal_id = str(uuid.uuid4())

        entry = ActionApprovalAudit.create_entry(
            tenant_id=tenant_id,
            action_proposal_id=proposal_id,
            action=AuditAction.CREATED,
            previous_status=None,
            new_status=ActionStatus.PROPOSED,
        )

        assert entry.action == AuditAction.CREATED
        assert entry.previous_status is None
        assert entry.new_status == ActionStatus.PROPOSED


# =============================================================================
# Scope Rules Tests
# =============================================================================


class TestMaxScopeRules:
    """Tests for MAX_SCOPE_RULES configuration."""

    def test_all_action_types_have_scope_rules(self):
        """All action types should have defined scope rules."""
        for action_type in ActionType:
            assert action_type in MAX_SCOPE_RULES, f"Missing scope rule for {action_type}"

    def test_budget_actions_limited_to_campaign(self):
        """Budget actions should be limited to campaign scope."""
        assert MAX_SCOPE_RULES[ActionType.REDUCE_BUDGET] == TargetEntityType.CAMPAIGN
        assert MAX_SCOPE_RULES[ActionType.INCREASE_BUDGET] == TargetEntityType.CAMPAIGN

    def test_campaign_actions_limited_to_campaign(self):
        """Campaign actions should be limited to campaign scope."""
        assert MAX_SCOPE_RULES[ActionType.PAUSE_CAMPAIGN] == TargetEntityType.CAMPAIGN
        assert MAX_SCOPE_RULES[ActionType.RESUME_CAMPAIGN] == TargetEntityType.CAMPAIGN

    def test_targeting_actions_limited_to_ad_set(self):
        """Targeting/bidding actions should be limited to ad_set scope."""
        assert MAX_SCOPE_RULES[ActionType.ADJUST_TARGETING] == TargetEntityType.AD_SET
        assert MAX_SCOPE_RULES[ActionType.MODIFY_BIDDING] == TargetEntityType.AD_SET


# =============================================================================
# TTL/Expiration Tests
# =============================================================================


class TestProposalExpiration:
    """Tests for proposal expiration logic."""

    def test_default_ttl_is_7_days(self):
        """Default TTL should be 7 days."""
        assert DEFAULT_PROPOSAL_TTL_DAYS == 7

    def test_get_default_expiration_is_7_days_in_future(self):
        """get_default_expiration should return a datetime 7 days in future."""
        now = datetime.now(timezone.utc)
        expiration = get_default_expiration()

        # Should be within a few seconds of 7 days from now
        expected = now + timedelta(days=DEFAULT_PROPOSAL_TTL_DAYS)
        delta = abs((expiration - expected).total_seconds())

        assert delta < 5  # Within 5 seconds


# =============================================================================
# Enum Tests
# =============================================================================


class TestActionTypeEnum:
    """Tests for ActionType enum."""

    def test_all_action_types_have_string_values(self):
        """All action types should have snake_case string values."""
        for action_type in ActionType:
            assert isinstance(action_type.value, str)
            assert action_type.value.islower()


class TestActionStatusEnum:
    """Tests for ActionStatus enum."""

    def test_proposed_is_initial_status(self):
        """PROPOSED should be the initial status for new proposals."""
        assert ActionStatus.PROPOSED.value == "proposed"

    def test_terminal_statuses_are_defined(self):
        """All terminal statuses should be defined."""
        terminal = [
            ActionStatus.APPROVED,
            ActionStatus.REJECTED,
            ActionStatus.EXPIRED,
            ActionStatus.CANCELLED,
        ]
        for status in terminal:
            assert status in ActionStatus


class TestTargetPlatformEnum:
    """Tests for TargetPlatform enum."""

    def test_supported_platforms_are_defined(self):
        """All supported platforms should be defined."""
        assert TargetPlatform.META.value == "meta"
        assert TargetPlatform.GOOGLE.value == "google"
        assert TargetPlatform.TIKTOK.value == "tiktok"


class TestAuditActionEnum:
    """Tests for AuditAction enum."""

    def test_all_audit_actions_are_defined(self):
        """All audit action types should be defined."""
        assert AuditAction.CREATED.value == "created"
        assert AuditAction.APPROVED.value == "approved"
        assert AuditAction.REJECTED.value == "rejected"
        assert AuditAction.EXPIRED.value == "expired"
        assert AuditAction.CANCELLED.value == "cancelled"
