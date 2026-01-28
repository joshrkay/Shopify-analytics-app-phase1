"""
Integration tests for Action Proposals API.

Tests cover:
- List proposals endpoint
- Get single proposal endpoint
- Approve/reject endpoints
- Audit trail endpoint
- Permission enforcement

Story 8.4 - Action Proposals (Approval Required)
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.api.routes.action_proposals import router
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


# =============================================================================
# Test Setup
# =============================================================================


@pytest.fixture
def app():
    """Create a test FastAPI application."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def tenant_id():
    """Test tenant ID."""
    return "test-tenant-123"


@pytest.fixture
def user_id():
    """Test user ID."""
    return "user-456"


@pytest.fixture
def mock_tenant_context(tenant_id, user_id):
    """Create a mock tenant context."""
    context = MagicMock()
    context.tenant_id = tenant_id
    context.user_id = user_id
    context.roles = ["merchant_admin"]
    return context


@pytest.fixture
def mock_viewer_context(tenant_id, user_id):
    """Create a mock viewer tenant context."""
    context = MagicMock()
    context.tenant_id = tenant_id
    context.user_id = user_id
    context.roles = ["merchant_viewer"]
    return context


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
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        proposal_metadata={},
    )


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    return MagicMock()


@pytest.fixture
def mock_entitlement_service():
    """Create a mock entitlement service that allows access."""
    service = MagicMock()
    result = MagicMock()
    result.is_entitled = True
    service.check_feature_entitlement.return_value = result
    return service


@pytest.fixture
def client(app, mock_tenant_context, mock_db_session, mock_entitlement_service):
    """Create a test client with mocked dependencies."""
    with patch("src.api.routes.action_proposals.get_tenant_context", return_value=mock_tenant_context):
        with patch("src.api.routes.action_proposals.get_db_session", return_value=mock_db_session):
            with patch("src.api.routes.action_proposals.BillingEntitlementsService", return_value=mock_entitlement_service):
                yield TestClient(app)


# =============================================================================
# List Proposals Tests
# =============================================================================


class TestListProposals:
    """Tests for GET /api/action-proposals endpoint."""

    def test_list_proposals_returns_200(
        self, app, mock_tenant_context, mock_db_session, mock_entitlement_service, sample_proposal
    ):
        """Should return 200 with list of proposals."""
        # Setup mock
        mock_service = MagicMock()
        mock_service.list_proposals.return_value = ([sample_proposal], 1)
        mock_service.get_pending_count.return_value = 1

        with patch("src.api.routes.action_proposals.get_tenant_context", return_value=mock_tenant_context):
            with patch("src.api.routes.action_proposals.get_db_session", return_value=mock_db_session):
                with patch("src.api.routes.action_proposals.BillingEntitlementsService", return_value=mock_entitlement_service):
                    with patch("src.api.routes.action_proposals.ActionProposalApprovalService", return_value=mock_service):
                        client = TestClient(app)
                        response = client.get("/api/action-proposals")

        assert response.status_code == 200
        data = response.json()
        assert "proposals" in data
        assert "total" in data
        assert "has_more" in data
        assert "pending_count" in data

    def test_list_proposals_filters_by_status(
        self, app, mock_tenant_context, mock_db_session, mock_entitlement_service, sample_proposal
    ):
        """Should filter proposals by status parameter."""
        mock_service = MagicMock()
        mock_service.list_proposals.return_value = ([sample_proposal], 1)
        mock_service.get_pending_count.return_value = 1

        with patch("src.api.routes.action_proposals.get_tenant_context", return_value=mock_tenant_context):
            with patch("src.api.routes.action_proposals.get_db_session", return_value=mock_db_session):
                with patch("src.api.routes.action_proposals.BillingEntitlementsService", return_value=mock_entitlement_service):
                    with patch("src.api.routes.action_proposals.ActionProposalApprovalService", return_value=mock_service):
                        client = TestClient(app)
                        response = client.get("/api/action-proposals?status=proposed")

        assert response.status_code == 200
        mock_service.list_proposals.assert_called()

    def test_list_proposals_returns_400_for_invalid_status(
        self, app, mock_tenant_context, mock_db_session, mock_entitlement_service
    ):
        """Should return 400 for invalid status filter."""
        mock_service = MagicMock()

        with patch("src.api.routes.action_proposals.get_tenant_context", return_value=mock_tenant_context):
            with patch("src.api.routes.action_proposals.get_db_session", return_value=mock_db_session):
                with patch("src.api.routes.action_proposals.BillingEntitlementsService", return_value=mock_entitlement_service):
                    with patch("src.api.routes.action_proposals.ActionProposalApprovalService", return_value=mock_service):
                        client = TestClient(app)
                        response = client.get("/api/action-proposals?status=invalid_status")

        assert response.status_code == 400


# =============================================================================
# Get Single Proposal Tests
# =============================================================================


class TestGetProposal:
    """Tests for GET /api/action-proposals/{proposal_id} endpoint."""

    def test_get_proposal_returns_200(
        self, app, mock_tenant_context, mock_db_session, mock_entitlement_service, sample_proposal
    ):
        """Should return 200 with proposal details."""
        mock_service = MagicMock()
        mock_service.get_proposal.return_value = sample_proposal

        with patch("src.api.routes.action_proposals.get_tenant_context", return_value=mock_tenant_context):
            with patch("src.api.routes.action_proposals.get_db_session", return_value=mock_db_session):
                with patch("src.api.routes.action_proposals.BillingEntitlementsService", return_value=mock_entitlement_service):
                    with patch("src.api.routes.action_proposals.ActionProposalApprovalService", return_value=mock_service):
                        client = TestClient(app)
                        response = client.get(f"/api/action-proposals/{sample_proposal.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["proposal_id"] == sample_proposal.id
        assert data["action_type"] == "reduce_budget"
        assert data["status"] == "proposed"
        assert data["requires_approval"] is True

    def test_get_proposal_returns_404_when_not_found(
        self, app, mock_tenant_context, mock_db_session, mock_entitlement_service
    ):
        """Should return 404 when proposal not found."""
        mock_service = MagicMock()
        mock_service.get_proposal.return_value = None

        with patch("src.api.routes.action_proposals.get_tenant_context", return_value=mock_tenant_context):
            with patch("src.api.routes.action_proposals.get_db_session", return_value=mock_db_session):
                with patch("src.api.routes.action_proposals.BillingEntitlementsService", return_value=mock_entitlement_service):
                    with patch("src.api.routes.action_proposals.ActionProposalApprovalService", return_value=mock_service):
                        client = TestClient(app)
                        response = client.get("/api/action-proposals/non-existent-id")

        assert response.status_code == 404


# =============================================================================
# Approve Proposal Tests
# =============================================================================


class TestApproveProposal:
    """Tests for POST /api/action-proposals/{proposal_id}/approve endpoint."""

    def test_approve_returns_200_for_admin(
        self, app, mock_tenant_context, mock_db_session, mock_entitlement_service, sample_proposal
    ):
        """Should return 200 when admin approves proposal."""
        # Mark proposal as approved after method call
        approved_proposal = sample_proposal
        approved_proposal.status = ActionStatus.APPROVED

        mock_service = MagicMock()
        mock_service.approve_proposal.return_value = approved_proposal

        with patch("src.api.routes.action_proposals.get_tenant_context", return_value=mock_tenant_context):
            with patch("src.api.routes.action_proposals.get_db_session", return_value=mock_db_session):
                with patch("src.api.routes.action_proposals.BillingEntitlementsService", return_value=mock_entitlement_service):
                    with patch("src.api.routes.action_proposals.ActionProposalApprovalService", return_value=mock_service):
                        client = TestClient(app)
                        response = client.post(f"/api/action-proposals/{sample_proposal.id}/approve")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["new_status"] == "approved"

    def test_approve_returns_403_for_viewer(
        self, app, mock_viewer_context, mock_db_session, mock_entitlement_service, sample_proposal
    ):
        """Should return 403 when viewer tries to approve."""
        with patch("src.api.routes.action_proposals.get_tenant_context", return_value=mock_viewer_context):
            with patch("src.api.routes.action_proposals.get_db_session", return_value=mock_db_session):
                with patch("src.api.routes.action_proposals.BillingEntitlementsService", return_value=mock_entitlement_service):
                    client = TestClient(app)
                    response = client.post(f"/api/action-proposals/{sample_proposal.id}/approve")

        assert response.status_code == 403


# =============================================================================
# Reject Proposal Tests
# =============================================================================


class TestRejectProposal:
    """Tests for POST /api/action-proposals/{proposal_id}/reject endpoint."""

    def test_reject_returns_200_for_admin(
        self, app, mock_tenant_context, mock_db_session, mock_entitlement_service, sample_proposal
    ):
        """Should return 200 when admin rejects proposal."""
        rejected_proposal = sample_proposal
        rejected_proposal.status = ActionStatus.REJECTED

        mock_service = MagicMock()
        mock_service.reject_proposal.return_value = rejected_proposal

        with patch("src.api.routes.action_proposals.get_tenant_context", return_value=mock_tenant_context):
            with patch("src.api.routes.action_proposals.get_db_session", return_value=mock_db_session):
                with patch("src.api.routes.action_proposals.BillingEntitlementsService", return_value=mock_entitlement_service):
                    with patch("src.api.routes.action_proposals.ActionProposalApprovalService", return_value=mock_service):
                        client = TestClient(app)
                        response = client.post(
                            f"/api/action-proposals/{sample_proposal.id}/reject",
                            json={"reason": "Not needed"},
                        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["new_status"] == "rejected"

    def test_reject_returns_403_for_viewer(
        self, app, mock_viewer_context, mock_db_session, mock_entitlement_service, sample_proposal
    ):
        """Should return 403 when viewer tries to reject."""
        with patch("src.api.routes.action_proposals.get_tenant_context", return_value=mock_viewer_context):
            with patch("src.api.routes.action_proposals.get_db_session", return_value=mock_db_session):
                with patch("src.api.routes.action_proposals.BillingEntitlementsService", return_value=mock_entitlement_service):
                    client = TestClient(app)
                    response = client.post(f"/api/action-proposals/{sample_proposal.id}/reject")

        assert response.status_code == 403


# =============================================================================
# Audit Trail Tests
# =============================================================================


class TestAuditTrail:
    """Tests for GET /api/action-proposals/{proposal_id}/audit endpoint."""

    def test_audit_trail_returns_200_for_admin(
        self, app, mock_tenant_context, mock_db_session, mock_entitlement_service, sample_proposal, tenant_id
    ):
        """Should return 200 with audit trail for admin."""
        audit_entry = ActionApprovalAudit.create_entry(
            tenant_id=tenant_id,
            action_proposal_id=sample_proposal.id,
            action=AuditAction.CREATED,
            new_status=ActionStatus.PROPOSED,
        )
        audit_entry.performed_at = datetime.now(timezone.utc)

        mock_service = MagicMock()
        mock_service.get_proposal.return_value = sample_proposal
        mock_service.get_audit_trail.return_value = [audit_entry]

        with patch("src.api.routes.action_proposals.get_tenant_context", return_value=mock_tenant_context):
            with patch("src.api.routes.action_proposals.get_db_session", return_value=mock_db_session):
                with patch("src.api.routes.action_proposals.BillingEntitlementsService", return_value=mock_entitlement_service):
                    with patch("src.api.routes.action_proposals.ActionProposalApprovalService", return_value=mock_service):
                        client = TestClient(app)
                        response = client.get(f"/api/action-proposals/{sample_proposal.id}/audit")

        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        assert data["proposal_id"] == sample_proposal.id

    def test_audit_trail_returns_403_for_viewer(
        self, app, mock_viewer_context, mock_db_session, mock_entitlement_service, sample_proposal
    ):
        """Should return 403 when viewer tries to view audit trail."""
        with patch("src.api.routes.action_proposals.get_tenant_context", return_value=mock_viewer_context):
            with patch("src.api.routes.action_proposals.get_db_session", return_value=mock_db_session):
                with patch("src.api.routes.action_proposals.BillingEntitlementsService", return_value=mock_entitlement_service):
                    client = TestClient(app)
                    response = client.get(f"/api/action-proposals/{sample_proposal.id}/audit")

        assert response.status_code == 403


# =============================================================================
# Entitlement Tests
# =============================================================================


class TestEntitlementEnforcement:
    """Tests for billing entitlement enforcement."""

    def test_returns_402_when_not_entitled(
        self, app, mock_tenant_context, mock_db_session
    ):
        """Should return 402 when tenant is not entitled to AI Actions."""
        mock_entitlement_service = MagicMock()
        result = MagicMock()
        result.is_entitled = False
        result.required_tier = "Growth"
        result.current_tier = "Free"
        mock_entitlement_service.check_feature_entitlement.return_value = result

        with patch("src.api.routes.action_proposals.get_tenant_context", return_value=mock_tenant_context):
            with patch("src.api.routes.action_proposals.get_db_session", return_value=mock_db_session):
                with patch("src.api.routes.action_proposals.BillingEntitlementsService", return_value=mock_entitlement_service):
                    client = TestClient(app)
                    response = client.get("/api/action-proposals")

        assert response.status_code == 402
        assert "Growth" in response.json()["detail"]


# =============================================================================
# Pending Count Tests
# =============================================================================


class TestPendingCount:
    """Tests for GET /api/action-proposals/stats/pending endpoint."""

    def test_pending_count_returns_200(
        self, app, mock_tenant_context, mock_db_session, mock_entitlement_service
    ):
        """Should return 200 with pending count."""
        mock_service = MagicMock()
        mock_service.get_pending_count.return_value = 5

        with patch("src.api.routes.action_proposals.get_tenant_context", return_value=mock_tenant_context):
            with patch("src.api.routes.action_proposals.get_db_session", return_value=mock_db_session):
                with patch("src.api.routes.action_proposals.BillingEntitlementsService", return_value=mock_entitlement_service):
                    with patch("src.api.routes.action_proposals.ActionProposalApprovalService", return_value=mock_service):
                        client = TestClient(app)
                        response = client.get("/api/action-proposals/stats/pending")

        assert response.status_code == 200
        data = response.json()
        assert data["pending_count"] == 5
