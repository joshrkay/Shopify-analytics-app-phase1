"""
Agency Access Service for managing agency-to-tenant access requests.

Flow:
1. Agency user calls request_access() -> creates PENDING request
2. Tenant admin sees pending requests via list_pending_requests()
3. Tenant admin calls approve_request() or deny_request()
4. On approval: UserRoleAssignment + UserTenantRole records are created
5. On denial: request closed, audit event emitted

LOCKED BUSINESS RULES:
- Agency access requires explicit tenant approval
- Agency access is scoped to specific tenant(s)
- No cross-tenant rollups: one active tenant context at a time

Story 5.5.2 - Agency Access Request + Tenant Approval Workflow
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from src.models.agency_access_request import (
    AgencyAccessRequest,
    AgencyAccessRequestStatus,
)
from src.models.role import Role, ROLE_TEMPLATES, seed_roles_for_tenant
from src.models.user_role_assignment import UserRoleAssignment
from src.models.user_tenant_roles import UserTenantRole
from src.models.user import User
from src.models.tenant import Tenant, TenantStatus

logger = logging.getLogger(__name__)


class AgencyAccessServiceError(Exception):
    """Base exception for agency access service."""
    pass


class RequestNotFoundError(AgencyAccessServiceError):
    """Raised when request is not found."""
    pass


class DuplicateRequestError(AgencyAccessServiceError):
    """Raised when a pending request already exists for user-tenant pair."""
    pass


class InvalidStatusTransitionError(AgencyAccessServiceError):
    """Raised when attempting an invalid status transition."""
    pass


class AgencyAccessService:
    """
    Service for managing agency access requests and approvals.

    Handles the full lifecycle: request -> review -> assign/deny.
    """

    DEFAULT_EXPIRY_DAYS = 30
    DEFAULT_MESSAGE = (
        "[AppName] is testing for bringing in your reporting data. "
        "Please approve or deny."
    )
    VALID_AGENCY_ROLE_SLUGS = {"agency_admin", "agency_viewer"}

    def __init__(self, session: Session):
        self.session = session

    def request_access(
        self,
        requesting_user_id: str,
        tenant_id: str,
        requested_role_slug: str = "agency_viewer",
        requesting_org_id: Optional[str] = None,
        message: Optional[str] = None,
    ) -> dict:
        """
        Create an agency access request.

        Args:
            requesting_user_id: Internal user.id of the requesting agency user
            tenant_id: Target tenant ID
            requested_role_slug: Role template slug (agency_admin or agency_viewer)
            requesting_org_id: Optional organization ID
            message: Optional custom message (defaults to standard approval message)

        Returns:
            Dict representation of the created request

        Raises:
            DuplicateRequestError: If a pending request already exists
            ValueError: If tenant or role_slug is invalid
        """
        # Validate tenant exists and is active
        tenant = self.session.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            raise ValueError(f"Tenant not found: {tenant_id}")
        if tenant.status != TenantStatus.ACTIVE:
            raise ValueError(f"Tenant is not active: {tenant_id}")

        # Validate requesting user exists
        user = self.session.query(User).filter(User.id == requesting_user_id).first()
        if not user:
            raise ValueError(f"User not found: {requesting_user_id}")

        # Validate role slug
        if requested_role_slug not in self.VALID_AGENCY_ROLE_SLUGS:
            raise ValueError(
                f"Invalid agency role slug: {requested_role_slug}. "
                f"Must be one of: {', '.join(self.VALID_AGENCY_ROLE_SLUGS)}"
            )

        # Check for existing pending request
        existing = (
            self.session.query(AgencyAccessRequest)
            .filter(
                AgencyAccessRequest.requesting_user_id == requesting_user_id,
                AgencyAccessRequest.tenant_id == tenant_id,
                AgencyAccessRequest.status == AgencyAccessRequestStatus.PENDING.value,
            )
            .first()
        )
        if existing:
            raise DuplicateRequestError(
                f"A pending request already exists for user {requesting_user_id} "
                f"and tenant {tenant_id}"
            )

        # Create request
        request = AgencyAccessRequest(
            requesting_user_id=requesting_user_id,
            requesting_org_id=requesting_org_id,
            tenant_id=tenant_id,
            requested_role_slug=requested_role_slug,
            message=message or self.DEFAULT_MESSAGE,
            status=AgencyAccessRequestStatus.PENDING.value,
            expires_at=datetime.now(timezone.utc) + timedelta(days=self.DEFAULT_EXPIRY_DAYS),
        )
        self.session.add(request)
        self.session.flush()

        # Emit audit event
        try:
            from src.services.audit_logger import emit_agency_access_requested
            emit_agency_access_requested(
                db=self.session,
                tenant_id=tenant_id,
                requesting_user_id=requesting_user_id,
                request_id=request.id,
                requested_role_slug=requested_role_slug,
                requesting_org_id=requesting_org_id,
            )
        except Exception:
            logger.warning(
                "agency_access.audit_event_failed",
                extra={"request_id": request.id, "event": "requested"},
                exc_info=True,
            )

        logger.info(
            "Agency access requested",
            extra={
                "request_id": request.id,
                "requesting_user_id": requesting_user_id,
                "tenant_id": tenant_id,
                "requested_role_slug": requested_role_slug,
            },
        )

        return self._request_to_dict(request)

    def approve_request(
        self,
        request_id: str,
        reviewed_by: str,
        review_note: Optional[str] = None,
    ) -> dict:
        """
        Approve an agency access request.

        On approval:
        1. Updates request status to APPROVED
        2. Finds/seeds the matching Role for the tenant
        3. Creates UserRoleAssignment linking agency user to that Role
        4. Creates UserTenantRole for backward compatibility

        Args:
            request_id: The request ID to approve
            reviewed_by: clerk_user_id of the approving tenant admin
            review_note: Optional note from the reviewer

        Returns:
            Dict representation of the approved request

        Raises:
            RequestNotFoundError: If request not found
            InvalidStatusTransitionError: If request is not pending
        """
        request = self._get_request(request_id)

        if not request.is_reviewable:
            raise InvalidStatusTransitionError(
                f"Request {request_id} cannot be approved (status={request.status})"
            )

        # Update status
        request.approve(reviewed_by=reviewed_by, review_note=review_note)

        # Find or seed the matching role for this tenant
        role = (
            self.session.query(Role)
            .filter(
                Role.tenant_id == request.tenant_id,
                Role.slug == request.requested_role_slug,
                Role.is_active == True,  # noqa: E712
            )
            .first()
        )

        if not role:
            # Seed roles for this tenant if they don't exist yet
            seed_roles_for_tenant(self.session, request.tenant_id)
            self.session.flush()
            role = (
                self.session.query(Role)
                .filter(
                    Role.tenant_id == request.tenant_id,
                    Role.slug == request.requested_role_slug,
                    Role.is_active == True,  # noqa: E712
                )
                .first()
            )

        # Create UserRoleAssignment (data-driven RBAC)
        if role:
            # Check if assignment already exists
            existing_assignment = (
                self.session.query(UserRoleAssignment)
                .filter(
                    UserRoleAssignment.user_id == request.requesting_user_id,
                    UserRoleAssignment.role_id == role.id,
                    UserRoleAssignment.tenant_id == request.tenant_id,
                )
                .first()
            )
            if existing_assignment:
                existing_assignment.is_active = True
                existing_assignment.assigned_by = reviewed_by
            else:
                assignment = UserRoleAssignment.create_from_approval(
                    user_id=request.requesting_user_id,
                    role_id=role.id,
                    tenant_id=request.tenant_id,
                    assigned_by=reviewed_by,
                )
                self.session.add(assignment)

        # Create UserTenantRole for backward compatibility
        legacy_role_name = request.requested_role_slug.upper()
        existing_legacy = (
            self.session.query(UserTenantRole)
            .filter(
                UserTenantRole.user_id == request.requesting_user_id,
                UserTenantRole.tenant_id == request.tenant_id,
                UserTenantRole.role == legacy_role_name,
            )
            .first()
        )
        if existing_legacy:
            existing_legacy.is_active = True
            existing_legacy.assigned_by = reviewed_by
        else:
            legacy = UserTenantRole.create_from_grant(
                user_id=request.requesting_user_id,
                tenant_id=request.tenant_id,
                role=legacy_role_name,
                granted_by=reviewed_by,
            )
            self.session.add(legacy)

        self.session.flush()

        # Emit audit event
        try:
            from src.services.audit_logger import emit_agency_access_approved
            emit_agency_access_approved(
                db=self.session,
                tenant_id=request.tenant_id,
                request_id=request.id,
                requesting_user_id=request.requesting_user_id,
                reviewed_by=reviewed_by,
                role_slug=request.requested_role_slug,
            )
        except Exception:
            logger.warning(
                "agency_access.audit_event_failed",
                extra={"request_id": request.id, "event": "approved"},
                exc_info=True,
            )

        logger.info(
            "Agency access approved",
            extra={
                "request_id": request.id,
                "tenant_id": request.tenant_id,
                "reviewed_by": reviewed_by,
                "role_slug": request.requested_role_slug,
            },
        )

        return self._request_to_dict(request)

    def deny_request(
        self,
        request_id: str,
        reviewed_by: str,
        review_note: Optional[str] = None,
    ) -> dict:
        """
        Deny an agency access request.

        Args:
            request_id: The request ID to deny
            reviewed_by: clerk_user_id of the denying tenant admin
            review_note: Optional reason for denial

        Returns:
            Dict representation of the denied request

        Raises:
            RequestNotFoundError: If request not found
            InvalidStatusTransitionError: If request is not pending
        """
        request = self._get_request(request_id)

        if not request.is_reviewable:
            raise InvalidStatusTransitionError(
                f"Request {request_id} cannot be denied (status={request.status})"
            )

        request.deny(reviewed_by=reviewed_by, review_note=review_note)
        self.session.flush()

        # Emit audit event
        try:
            from src.services.audit_logger import emit_agency_access_denied
            emit_agency_access_denied(
                db=self.session,
                tenant_id=request.tenant_id,
                request_id=request.id,
                requesting_user_id=request.requesting_user_id,
                reviewed_by=reviewed_by,
                review_note=review_note,
            )
        except Exception:
            logger.warning(
                "agency_access.audit_event_failed",
                extra={"request_id": request.id, "event": "denied"},
                exc_info=True,
            )

        logger.info(
            "Agency access denied",
            extra={
                "request_id": request.id,
                "tenant_id": request.tenant_id,
                "reviewed_by": reviewed_by,
            },
        )

        return self._request_to_dict(request)

    def list_pending_requests(self, tenant_id: str) -> list[dict]:
        """
        List all pending requests for a tenant.

        Used by tenant admin to see incoming agency access requests.

        Args:
            tenant_id: Tenant ID

        Returns:
            List of pending request dicts
        """
        requests = (
            self.session.query(AgencyAccessRequest)
            .filter(
                AgencyAccessRequest.tenant_id == tenant_id,
                AgencyAccessRequest.status == AgencyAccessRequestStatus.PENDING.value,
            )
            .order_by(AgencyAccessRequest.created_at.desc())
            .all()
        )
        return [self._request_to_dict(r) for r in requests]

    def list_requests_by_user(self, user_id: str) -> list[dict]:
        """
        List all requests made by a user.

        Used by agency users to track their requests.

        Args:
            user_id: Internal user ID

        Returns:
            List of request dicts
        """
        requests = (
            self.session.query(AgencyAccessRequest)
            .filter(AgencyAccessRequest.requesting_user_id == user_id)
            .order_by(AgencyAccessRequest.created_at.desc())
            .all()
        )
        return [self._request_to_dict(r) for r in requests]

    def cancel_request(
        self,
        request_id: str,
        cancelled_by: str,
    ) -> dict:
        """
        Cancel a pending request.

        Only the requesting user can cancel their own request.

        Args:
            request_id: The request ID to cancel
            cancelled_by: Internal user ID of the person cancelling

        Returns:
            Dict representation of the cancelled request

        Raises:
            RequestNotFoundError: If request not found
            InvalidStatusTransitionError: If request is not pending or not owned
        """
        request = self._get_request(request_id)

        if request.requesting_user_id != cancelled_by:
            raise InvalidStatusTransitionError(
                "Only the requesting user can cancel their own request"
            )

        if not request.is_pending:
            raise InvalidStatusTransitionError(
                f"Request {request_id} cannot be cancelled (status={request.status})"
            )

        request.cancel()
        self.session.flush()

        logger.info(
            "Agency access request cancelled",
            extra={"request_id": request.id, "cancelled_by": cancelled_by},
        )

        return self._request_to_dict(request)

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _get_request(self, request_id: str) -> AgencyAccessRequest:
        """Get request by ID or raise error."""
        request = (
            self.session.query(AgencyAccessRequest)
            .filter(AgencyAccessRequest.id == request_id)
            .first()
        )
        if not request:
            raise RequestNotFoundError(f"Request not found: {request_id}")
        return request

    def _request_to_dict(self, request: AgencyAccessRequest) -> dict:
        """Convert AgencyAccessRequest to dict."""
        return {
            "id": request.id,
            "requesting_user_id": request.requesting_user_id,
            "requesting_org_id": request.requesting_org_id,
            "tenant_id": request.tenant_id,
            "requested_role_slug": request.requested_role_slug,
            "message": request.message,
            "status": request.status,
            "reviewed_by": request.reviewed_by,
            "reviewed_at": request.reviewed_at.isoformat() if request.reviewed_at else None,
            "review_note": request.review_note,
            "expires_at": request.expires_at.isoformat() if request.expires_at else None,
            "created_at": request.created_at.isoformat() if request.created_at else None,
        }
