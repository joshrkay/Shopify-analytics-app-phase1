"""
Tests for the agency access request + tenant approval workflow.

Covers:
- Creating access requests (success, duplicate, invalid role/tenant)
- Approving requests (creates UserRoleAssignment + UserTenantRole, seeds roles)
- Denying requests (sets status, no assignments created)
- Cancelling requests (owner-only)
- Tenant isolation (admin can only act on own tenant)
- Listing requests (pending for tenant, mine for user)

Story 5.5.2 - Agency Access Request + Tenant Approval Workflow
"""

import uuid
import pytest
from datetime import datetime, timezone

from src.models.user import User
from src.models.tenant import Tenant, TenantStatus
from src.models.role import Role, RolePermission, seed_roles_for_tenant
from src.models.user_role_assignment import UserRoleAssignment
from src.models.user_tenant_roles import UserTenantRole
from src.models.agency_access_request import (
    AgencyAccessRequest,
    AgencyAccessRequestStatus,
)
from src.services.agency_access_service import (
    AgencyAccessService,
    RequestNotFoundError,
    DuplicateRequestError,
    InvalidStatusTransitionError,
)


# =============================================================================
# Helpers
# =============================================================================


def _create_user(db, clerk_user_id=None):
    """Create a test user."""
    user = User(
        id=str(uuid.uuid4()),
        clerk_user_id=clerk_user_id or f"clerk_{uuid.uuid4().hex[:8]}",
        email=f"test_{uuid.uuid4().hex[:8]}@example.com",
    )
    db.add(user)
    db.flush()
    return user


def _create_tenant(db, status_val=TenantStatus.ACTIVE):
    """Create a test tenant."""
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name=f"Test Tenant {uuid.uuid4().hex[:6]}",
        status=status_val.value if hasattr(status_val, "value") else status_val,
    )
    db.add(tenant)
    db.flush()
    return tenant


# =============================================================================
# TestCreateRequest
# =============================================================================


class TestCreateRequest:
    """Tests for creating agency access requests."""

    def test_create_request_success(self, db_session):
        """Creating a valid request returns PENDING status."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        result = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
            requested_role_slug="agency_viewer",
        )

        assert result["status"] == "pending"
        assert result["requesting_user_id"] == user.id
        assert result["tenant_id"] == tenant.id
        assert result["requested_role_slug"] == "agency_viewer"
        assert result["message"] is not None  # Default message applied

    def test_create_request_default_message(self, db_session):
        """Request uses default approval message when none provided."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        result = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
        )

        assert "approve or deny" in result["message"].lower()

    def test_create_request_custom_message(self, db_session):
        """Request uses custom message when provided."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        result = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
            message="Please grant me access",
        )

        assert result["message"] == "Please grant me access"

    def test_create_request_duplicate_rejected(self, db_session):
        """Duplicate pending request for same user-tenant is rejected."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
        )

        with pytest.raises(DuplicateRequestError):
            service.request_access(
                requesting_user_id=user.id,
                tenant_id=tenant.id,
            )

    def test_create_request_invalid_role_slug(self, db_session):
        """Request with invalid role slug raises ValueError."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        with pytest.raises(ValueError, match="Invalid agency role slug"):
            service.request_access(
                requesting_user_id=user.id,
                tenant_id=tenant.id,
                requested_role_slug="invalid_role",
            )

    def test_create_request_invalid_tenant(self, db_session):
        """Request to nonexistent tenant raises ValueError."""
        user = _create_user(db_session)

        service = AgencyAccessService(db_session)
        with pytest.raises(ValueError, match="Tenant not found"):
            service.request_access(
                requesting_user_id=user.id,
                tenant_id="nonexistent-tenant",
            )

    def test_create_request_inactive_tenant(self, db_session):
        """Request to inactive tenant raises ValueError."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session, status_val=TenantStatus.SUSPENDED)

        service = AgencyAccessService(db_session)
        with pytest.raises(ValueError, match="not active"):
            service.request_access(
                requesting_user_id=user.id,
                tenant_id=tenant.id,
            )

    def test_create_request_invalid_user(self, db_session):
        """Request with nonexistent user raises ValueError."""
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        with pytest.raises(ValueError, match="User not found"):
            service.request_access(
                requesting_user_id="nonexistent-user",
                tenant_id=tenant.id,
            )

    def test_create_request_has_expiry(self, db_session):
        """Created request has an expiration date set."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        result = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
        )

        assert result["expires_at"] is not None


# =============================================================================
# TestApproveRequest
# =============================================================================


class TestApproveRequest:
    """Tests for approving agency access requests."""

    def test_approve_request_success(self, db_session):
        """Approving a request sets status to APPROVED."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)
        reviewer_id = f"reviewer_{uuid.uuid4().hex[:8]}"

        service = AgencyAccessService(db_session)
        req = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
        )

        result = service.approve_request(
            request_id=req["id"],
            reviewed_by=reviewer_id,
            review_note="Approved for data access",
        )

        assert result["status"] == "approved"
        assert result["reviewed_by"] == reviewer_id
        assert result["review_note"] == "Approved for data access"
        assert result["reviewed_at"] is not None

    def test_approve_creates_user_role_assignment(self, db_session):
        """Approving a request creates a UserRoleAssignment record."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        req = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
            requested_role_slug="agency_viewer",
        )
        service.approve_request(request_id=req["id"], reviewed_by="reviewer-1")

        assignment = (
            db_session.query(UserRoleAssignment)
            .filter(
                UserRoleAssignment.user_id == user.id,
                UserRoleAssignment.tenant_id == tenant.id,
            )
            .first()
        )
        assert assignment is not None
        assert assignment.is_active is True
        assert assignment.source == "agency_approval"

    def test_approve_creates_legacy_user_tenant_role(self, db_session):
        """Approving a request creates a UserTenantRole (backward compat)."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        req = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
            requested_role_slug="agency_viewer",
        )
        service.approve_request(request_id=req["id"], reviewed_by="reviewer-1")

        legacy = (
            db_session.query(UserTenantRole)
            .filter(
                UserTenantRole.user_id == user.id,
                UserTenantRole.tenant_id == tenant.id,
                UserTenantRole.role == "AGENCY_VIEWER",
            )
            .first()
        )
        assert legacy is not None
        assert legacy.is_active is True

    def test_approve_seeds_roles_if_needed(self, db_session):
        """Approving seeds roles for tenant if they don't exist yet."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        # Verify no roles exist before
        roles_before = (
            db_session.query(Role)
            .filter(Role.tenant_id == tenant.id)
            .count()
        )
        assert roles_before == 0

        service = AgencyAccessService(db_session)
        req = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
            requested_role_slug="agency_viewer",
        )
        service.approve_request(request_id=req["id"], reviewed_by="reviewer-1")

        # Roles should be seeded now
        roles_after = (
            db_session.query(Role)
            .filter(Role.tenant_id == tenant.id)
            .count()
        )
        assert roles_after > 0

    def test_approve_non_pending_fails(self, db_session):
        """Cannot approve a request that is not pending."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        req = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
        )
        service.deny_request(request_id=req["id"], reviewed_by="reviewer-1")

        with pytest.raises(InvalidStatusTransitionError):
            service.approve_request(
                request_id=req["id"],
                reviewed_by="reviewer-2",
            )

    def test_approve_not_found(self, db_session):
        """Approving a nonexistent request raises error."""
        service = AgencyAccessService(db_session)
        with pytest.raises(RequestNotFoundError):
            service.approve_request(
                request_id="nonexistent-id",
                reviewed_by="reviewer-1",
            )

    def test_approve_reactivates_existing_assignment(self, db_session):
        """Approving reactivates an existing deactivated assignment."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        # Seed roles and create a deactivated assignment
        seed_roles_for_tenant(db_session, tenant.id)
        db_session.flush()
        role = (
            db_session.query(Role)
            .filter(Role.tenant_id == tenant.id, Role.slug == "agency_viewer")
            .first()
        )
        if role:
            assignment = UserRoleAssignment(
                user_id=user.id,
                role_id=role.id,
                tenant_id=tenant.id,
                is_active=False,
                source="agency_approval",
            )
            db_session.add(assignment)
            db_session.flush()

        service = AgencyAccessService(db_session)
        req = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
        )
        service.approve_request(request_id=req["id"], reviewed_by="reviewer-1")

        # The existing assignment should be reactivated
        updated = (
            db_session.query(UserRoleAssignment)
            .filter(
                UserRoleAssignment.user_id == user.id,
                UserRoleAssignment.tenant_id == tenant.id,
            )
            .first()
        )
        assert updated is not None
        assert updated.is_active is True


# =============================================================================
# TestDenyRequest
# =============================================================================


class TestDenyRequest:
    """Tests for denying agency access requests."""

    def test_deny_request_success(self, db_session):
        """Denying a request sets status to DENIED."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        req = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
        )
        result = service.deny_request(
            request_id=req["id"],
            reviewed_by="reviewer-1",
            review_note="Not authorized",
        )

        assert result["status"] == "denied"
        assert result["reviewed_by"] == "reviewer-1"
        assert result["review_note"] == "Not authorized"

    def test_deny_does_not_create_assignments(self, db_session):
        """Denying a request does NOT create any role assignments."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        req = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
        )
        service.deny_request(request_id=req["id"], reviewed_by="reviewer-1")

        assignments = (
            db_session.query(UserRoleAssignment)
            .filter(
                UserRoleAssignment.user_id == user.id,
                UserRoleAssignment.tenant_id == tenant.id,
            )
            .count()
        )
        assert assignments == 0

        legacy = (
            db_session.query(UserTenantRole)
            .filter(
                UserTenantRole.user_id == user.id,
                UserTenantRole.tenant_id == tenant.id,
            )
            .count()
        )
        assert legacy == 0

    def test_deny_non_pending_fails(self, db_session):
        """Cannot deny a request that is not pending."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        req = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
        )
        service.approve_request(request_id=req["id"], reviewed_by="reviewer-1")

        with pytest.raises(InvalidStatusTransitionError):
            service.deny_request(
                request_id=req["id"],
                reviewed_by="reviewer-2",
            )

    def test_can_rerequest_after_denial(self, db_session):
        """After denial, user can create a new request for same tenant."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        req = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
        )
        service.deny_request(request_id=req["id"], reviewed_by="reviewer-1")

        # Should succeed — no duplicate because previous is DENIED
        result = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
        )
        assert result["status"] == "pending"


# =============================================================================
# TestCancelRequest
# =============================================================================


class TestCancelRequest:
    """Tests for cancelling agency access requests."""

    def test_cancel_request_success(self, db_session):
        """Owner can cancel their own pending request."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        req = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
        )
        result = service.cancel_request(
            request_id=req["id"],
            cancelled_by=user.id,
        )

        assert result["status"] == "cancelled"

    def test_cancel_by_non_owner_fails(self, db_session):
        """Non-owner cannot cancel someone else's request."""
        user = _create_user(db_session)
        other_user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        req = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
        )

        with pytest.raises(InvalidStatusTransitionError, match="Only the requesting user"):
            service.cancel_request(
                request_id=req["id"],
                cancelled_by=other_user.id,
            )

    def test_cancel_non_pending_fails(self, db_session):
        """Cannot cancel a request that is not pending."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        req = service.request_access(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
        )
        service.approve_request(request_id=req["id"], reviewed_by="reviewer-1")

        with pytest.raises(InvalidStatusTransitionError):
            service.cancel_request(
                request_id=req["id"],
                cancelled_by=user.id,
            )


# =============================================================================
# TestListRequests
# =============================================================================


class TestListRequests:
    """Tests for listing agency access requests."""

    def test_list_pending_for_tenant(self, db_session):
        """Lists only pending requests for a tenant."""
        user1 = _create_user(db_session)
        user2 = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        service.request_access(requesting_user_id=user1.id, tenant_id=tenant.id)
        req2 = service.request_access(requesting_user_id=user2.id, tenant_id=tenant.id)
        service.deny_request(request_id=req2["id"], reviewed_by="reviewer-1")

        results = service.list_pending_requests(tenant.id)
        assert len(results) == 1
        assert results[0]["requesting_user_id"] == user1.id

    def test_list_pending_excludes_other_tenants(self, db_session):
        """Pending requests for other tenants are not returned."""
        user = _create_user(db_session)
        tenant1 = _create_tenant(db_session)
        tenant2 = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        service.request_access(requesting_user_id=user.id, tenant_id=tenant1.id)
        service.request_access(requesting_user_id=user.id, tenant_id=tenant2.id)

        results = service.list_pending_requests(tenant1.id)
        assert len(results) == 1
        assert results[0]["tenant_id"] == tenant1.id

    def test_list_requests_by_user(self, db_session):
        """Lists all requests made by a specific user."""
        user = _create_user(db_session)
        tenant1 = _create_tenant(db_session)
        tenant2 = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        service.request_access(requesting_user_id=user.id, tenant_id=tenant1.id)
        service.request_access(requesting_user_id=user.id, tenant_id=tenant2.id)

        results = service.list_requests_by_user(user.id)
        assert len(results) == 2

    def test_list_requests_by_user_excludes_others(self, db_session):
        """Other users' requests are not returned."""
        user1 = _create_user(db_session)
        user2 = _create_user(db_session)
        tenant = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        service.request_access(requesting_user_id=user1.id, tenant_id=tenant.id)
        service.request_access(requesting_user_id=user2.id, tenant_id=tenant.id)

        results = service.list_requests_by_user(user1.id)
        assert len(results) == 1
        assert results[0]["requesting_user_id"] == user1.id


# =============================================================================
# TestTenantIsolation
# =============================================================================


class TestTenantIsolation:
    """Tests for cross-tenant isolation in agency access."""

    def test_request_scoped_to_single_tenant(self, db_session):
        """Each request is scoped to exactly one tenant."""
        user = _create_user(db_session)
        tenant1 = _create_tenant(db_session)
        tenant2 = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        r1 = service.request_access(requesting_user_id=user.id, tenant_id=tenant1.id)
        r2 = service.request_access(requesting_user_id=user.id, tenant_id=tenant2.id)

        assert r1["tenant_id"] == tenant1.id
        assert r2["tenant_id"] == tenant2.id
        assert r1["tenant_id"] != r2["tenant_id"]

    def test_approval_only_grants_for_target_tenant(self, db_session):
        """Approval creates assignments only for the target tenant."""
        user = _create_user(db_session)
        tenant1 = _create_tenant(db_session)
        tenant2 = _create_tenant(db_session)

        service = AgencyAccessService(db_session)
        r1 = service.request_access(requesting_user_id=user.id, tenant_id=tenant1.id)
        service.request_access(requesting_user_id=user.id, tenant_id=tenant2.id)

        # Only approve tenant1
        service.approve_request(request_id=r1["id"], reviewed_by="reviewer-1")

        # Check assignments — only tenant1 should have one
        t1_assignments = (
            db_session.query(UserRoleAssignment)
            .filter(
                UserRoleAssignment.user_id == user.id,
                UserRoleAssignment.tenant_id == tenant1.id,
            )
            .count()
        )
        t2_assignments = (
            db_session.query(UserRoleAssignment)
            .filter(
                UserRoleAssignment.user_id == user.id,
                UserRoleAssignment.tenant_id == tenant2.id,
            )
            .count()
        )

        assert t1_assignments == 1
        assert t2_assignments == 0


# =============================================================================
# TestAgencyAccessRequestModel
# =============================================================================


class TestAgencyAccessRequestModel:
    """Tests for the AgencyAccessRequest model methods."""

    def test_is_pending(self, db_session):
        """is_pending returns True for PENDING status."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        request = AgencyAccessRequest(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
            requested_role_slug="agency_viewer",
            status=AgencyAccessRequestStatus.PENDING.value,
        )
        db_session.add(request)
        db_session.flush()

        assert request.is_pending is True

    def test_is_reviewable(self, db_session):
        """is_reviewable returns True only for PENDING status."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        request = AgencyAccessRequest(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
            requested_role_slug="agency_viewer",
            status=AgencyAccessRequestStatus.PENDING.value,
        )
        db_session.add(request)
        db_session.flush()

        assert request.is_reviewable is True

        request.status = AgencyAccessRequestStatus.APPROVED.value
        assert request.is_reviewable is False

    def test_approve_sets_fields(self, db_session):
        """approve() sets status, reviewed_by, and reviewed_at."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        request = AgencyAccessRequest(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
            requested_role_slug="agency_viewer",
            status=AgencyAccessRequestStatus.PENDING.value,
        )
        db_session.add(request)
        db_session.flush()

        request.approve(reviewed_by="admin-1", review_note="OK")

        assert request.status == AgencyAccessRequestStatus.APPROVED.value
        assert request.reviewed_by == "admin-1"
        assert request.review_note == "OK"
        assert request.reviewed_at is not None

    def test_deny_sets_fields(self, db_session):
        """deny() sets status, reviewed_by, and reviewed_at."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        request = AgencyAccessRequest(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
            requested_role_slug="agency_viewer",
            status=AgencyAccessRequestStatus.PENDING.value,
        )
        db_session.add(request)
        db_session.flush()

        request.deny(reviewed_by="admin-1", review_note="Denied")

        assert request.status == AgencyAccessRequestStatus.DENIED.value
        assert request.reviewed_by == "admin-1"

    def test_cancel_sets_status(self, db_session):
        """cancel() sets status to CANCELLED."""
        user = _create_user(db_session)
        tenant = _create_tenant(db_session)

        request = AgencyAccessRequest(
            requesting_user_id=user.id,
            tenant_id=tenant.id,
            requested_role_slug="agency_viewer",
            status=AgencyAccessRequestStatus.PENDING.value,
        )
        db_session.add(request)
        db_session.flush()

        request.cancel()

        assert request.status == AgencyAccessRequestStatus.CANCELLED.value
