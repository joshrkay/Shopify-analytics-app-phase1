"""
Unit tests for Action Proposal Approval Service.

Tests cover:
- Approve/reject workflow
- Permission validation
- Audit trail creation
- Proposal expiration

Story 8.4 - Action Proposals (Approval Required)
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from src.models.action_proposal import (
    ActionProposal,
    ActionType,
    ActionStatus,
    TargetPlatform,
    TargetEntityType,
    get_default_expiration,
)
from src.models.action_approval_audit import ActionApprovalAudit, AuditAction
from src.models.ai_recommendation import RiskLevel
from src.services.action_proposal_approval_service import (
    ActionProposalApprovalService,
    ApprovalError,
    NotFoundError,
    PermissionDeniedError,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock(spec=Session)
    return session


@pytest.fixture
def tenant_id():
    """Test tenant ID."""
    return "test-tenant-123"


@pytest.fixture
def user_id():
    """Test user ID."""
    return "user-456"


@pytest.fixture
def admin_roles():
    """Admin roles that can approve."""
    return ["merchant_admin"]


@pytest.fixture
def viewer_roles():
    """Viewer roles that cannot approve."""
    return ["merchant_viewer"]


@pytest.fixture
def sample_proposal(tenant_id):
    """Create a sample action proposal in PROPOSED status."""
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


@pytest.fixture
def expired_proposal(tenant_id):
    """Create an expired action proposal."""
    proposal = ActionProposal(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        source_recommendation_id=str(uuid.uuid4()),
        action_type=ActionType.REDUCE_BUDGET,
        status=ActionStatus.PROPOSED,
        target_platform=TargetPlatform.META,
        target_entity_type=TargetEntityType.CAMPAIGN,
        target_entity_id="campaign_123",
        proposed_change={"type": "percentage", "value": -15},
        expected_effect="Budget will decrease by 15%",
        risk_disclaimer="Reducing budget may decrease impressions.",
        risk_level=RiskLevel.MEDIUM,
        confidence_score=0.85,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # Expired
        content_hash="abc123def456",
        generated_at=datetime.now(timezone.utc) - timedelta(days=8),
        proposal_metadata={},
    )
    return proposal


# =============================================================================
# Service Initialization Tests
# =============================================================================


class TestServiceInitialization:
    """Tests for service initialization."""

    def test_requires_tenant_id(self, mock_db_session):
        """Should raise ValueError if tenant_id is not provided."""
        with pytest.raises(ValueError, match="tenant_id is required"):
            ActionProposalApprovalService(mock_db_session, "")

    def test_creates_service_with_valid_params(self, mock_db_session, tenant_id):
        """Should create service with valid parameters."""
        service = ActionProposalApprovalService(mock_db_session, tenant_id)
        assert service.tenant_id == tenant_id


# =============================================================================
# Approve Proposal Tests
# =============================================================================


class TestApproveProposal:
    """Tests for approve_proposal method."""

    def test_approve_sets_approved_status(
        self, mock_db_session, tenant_id, user_id, admin_roles, sample_proposal
    ):
        """Should set status to APPROVED and create audit entry."""
        # Setup mock
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = sample_proposal
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        result = service.approve_proposal(
            proposal_id=sample_proposal.id,
            user_id=user_id,
            user_roles=admin_roles,
        )

        assert result.status == ActionStatus.APPROVED
        assert result.decided_by_user_id == user_id
        assert result.decided_at is not None

        # Should have added audit entry
        mock_db_session.add.assert_called()

    def test_approve_raises_not_found(
        self, mock_db_session, tenant_id, user_id, admin_roles
    ):
        """Should raise NotFoundError if proposal not found."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        with pytest.raises(NotFoundError):
            service.approve_proposal(
                proposal_id="non-existent",
                user_id=user_id,
                user_roles=admin_roles,
            )

    def test_approve_raises_permission_denied_for_viewer(
        self, mock_db_session, tenant_id, user_id, viewer_roles, sample_proposal
    ):
        """Should raise PermissionDeniedError for viewer roles."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = sample_proposal
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        with pytest.raises(PermissionDeniedError):
            service.approve_proposal(
                proposal_id=sample_proposal.id,
                user_id=user_id,
                user_roles=viewer_roles,
            )

    def test_approve_raises_error_for_expired_proposal(
        self, mock_db_session, tenant_id, user_id, admin_roles, expired_proposal
    ):
        """Should raise ApprovalError for expired proposals."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = expired_proposal
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        with pytest.raises(ApprovalError, match="expired"):
            service.approve_proposal(
                proposal_id=expired_proposal.id,
                user_id=user_id,
                user_roles=admin_roles,
            )

    def test_approve_raises_error_for_already_approved(
        self, mock_db_session, tenant_id, user_id, admin_roles, sample_proposal
    ):
        """Should raise ApprovalError for already approved proposals."""
        sample_proposal.status = ActionStatus.APPROVED

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = sample_proposal
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        with pytest.raises(ApprovalError, match="Only proposals in 'proposed' status"):
            service.approve_proposal(
                proposal_id=sample_proposal.id,
                user_id=user_id,
                user_roles=admin_roles,
            )


# =============================================================================
# Reject Proposal Tests
# =============================================================================


class TestRejectProposal:
    """Tests for reject_proposal method."""

    def test_reject_sets_rejected_status(
        self, mock_db_session, tenant_id, user_id, admin_roles, sample_proposal
    ):
        """Should set status to REJECTED and create audit entry."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = sample_proposal
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        result = service.reject_proposal(
            proposal_id=sample_proposal.id,
            user_id=user_id,
            user_roles=admin_roles,
            reason="Not needed at this time",
        )

        assert result.status == ActionStatus.REJECTED
        assert result.decided_by_user_id == user_id
        assert result.decision_reason == "Not needed at this time"

    def test_reject_raises_permission_denied_for_viewer(
        self, mock_db_session, tenant_id, user_id, viewer_roles, sample_proposal
    ):
        """Should raise PermissionDeniedError for viewer roles."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = sample_proposal
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        with pytest.raises(PermissionDeniedError):
            service.reject_proposal(
                proposal_id=sample_proposal.id,
                user_id=user_id,
                user_roles=viewer_roles,
            )

    def test_reject_without_reason(
        self, mock_db_session, tenant_id, user_id, admin_roles, sample_proposal
    ):
        """Should allow rejection without a reason."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = sample_proposal
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        result = service.reject_proposal(
            proposal_id=sample_proposal.id,
            user_id=user_id,
            user_roles=admin_roles,
            reason=None,
        )

        assert result.status == ActionStatus.REJECTED
        assert result.decision_reason is None


# =============================================================================
# Cancel Proposal Tests
# =============================================================================


class TestCancelProposal:
    """Tests for cancel_proposal method."""

    def test_cancel_sets_cancelled_status(
        self, mock_db_session, tenant_id, sample_proposal
    ):
        """Should set status to CANCELLED with reason."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = sample_proposal
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        result = service.cancel_proposal(
            proposal_id=sample_proposal.id,
            reason="Campaign was deleted",
        )

        assert result.status == ActionStatus.CANCELLED
        assert result.decision_reason == "Campaign was deleted"

    def test_cancel_raises_error_for_terminal_status(
        self, mock_db_session, tenant_id, sample_proposal
    ):
        """Should raise ApprovalError for proposals in terminal status."""
        sample_proposal.status = ActionStatus.APPROVED

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = sample_proposal
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        with pytest.raises(ApprovalError):
            service.cancel_proposal(
                proposal_id=sample_proposal.id,
                reason="Campaign was deleted",
            )


# =============================================================================
# Expire Stale Proposals Tests
# =============================================================================


class TestExpireStaleProposals:
    """Tests for expire_stale_proposals method."""

    def test_expires_stale_proposals(
        self, mock_db_session, tenant_id, expired_proposal
    ):
        """Should expire proposals past their TTL."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [expired_proposal]
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        count = service.expire_stale_proposals()

        assert count == 1
        assert expired_proposal.status == ActionStatus.EXPIRED

    def test_returns_zero_when_no_stale_proposals(
        self, mock_db_session, tenant_id
    ):
        """Should return 0 when no stale proposals exist."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        count = service.expire_stale_proposals()

        assert count == 0


# =============================================================================
# Audit Trail Tests
# =============================================================================


class TestAuditTrail:
    """Tests for audit trail functionality."""

    def test_get_audit_trail_returns_entries(
        self, mock_db_session, tenant_id, sample_proposal
    ):
        """Should return audit entries for a proposal."""
        # Create mock audit entries
        audit_entry = ActionApprovalAudit.create_entry(
            tenant_id=tenant_id,
            action_proposal_id=sample_proposal.id,
            action=AuditAction.CREATED,
            new_status=ActionStatus.PROPOSED,
        )

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = [audit_entry]
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        entries = service.get_audit_trail(sample_proposal.id)

        assert len(entries) == 1
        assert entries[0].action == AuditAction.CREATED


# =============================================================================
# List Proposals Tests
# =============================================================================


class TestListProposals:
    """Tests for list_proposals method."""

    def test_list_returns_proposals_and_count(
        self, mock_db_session, tenant_id, sample_proposal
    ):
        """Should return list of proposals and total count."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [sample_proposal]
        mock_query.count.return_value = 1
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        proposals, total = service.list_proposals()

        assert len(proposals) == 1
        assert total == 1

    def test_list_filters_by_status(
        self, mock_db_session, tenant_id, sample_proposal
    ):
        """Should filter proposals by status."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [sample_proposal]
        mock_query.count.return_value = 1
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        proposals, total = service.list_proposals(status=ActionStatus.PROPOSED)

        # Verify filter was called
        assert mock_query.filter.called


# =============================================================================
# Pending Count Tests
# =============================================================================


class TestPendingCount:
    """Tests for get_pending_count method."""

    def test_returns_pending_count(self, mock_db_session, tenant_id):
        """Should return count of pending proposals."""
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 5
        mock_db_session.query.return_value = mock_query

        service = ActionProposalApprovalService(mock_db_session, tenant_id)

        count = service.get_pending_count()

        assert count == 5
