"""
AgencyAccessRequest model for agency-to-tenant access approval workflow.

Flow:
1. Agency user creates a PENDING request to access a tenant
2. Tenant admin reviews and approves or denies
3. On approval, UserRoleAssignment + UserTenantRole records are created
4. On denial, request is closed with audit event

SECURITY:
- Agency access requires explicit tenant approval
- One active (pending) request per user-tenant pair
- All state transitions emit audit events

Story 5.5.2 - Agency Access Request + Tenant Approval Workflow
"""

import uuid
import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
)
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin

if TYPE_CHECKING:
    from src.models.user import User
    from src.models.tenant import Tenant
    from src.models.organization import Organization


class AgencyAccessRequestStatus(str, enum.Enum):
    """Lifecycle status of an agency access request."""
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class AgencyAccessRequest(Base, TimestampMixin):
    """
    Tracks agency access requests through the approval workflow.

    - requesting_user_id: the agency user requesting access
    - tenant_id: the tenant being requested
    - requested_role_slug: which role template to assign on approval
    - status: PENDING -> APPROVED|DENIED|EXPIRED|CANCELLED
    """

    __tablename__ = "agency_access_requests"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Internal UUID primary key",
    )

    # Who is requesting access
    requesting_user_id = Column(
        String(255),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User ID of the agency user requesting access",
    )

    requesting_org_id = Column(
        String(255),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Organization ID of the requesting agency (optional)",
    )

    # Which tenant is being requested
    tenant_id = Column(
        String(255),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID being requested for access",
    )

    # What role is requested
    requested_role_slug = Column(
        String(100),
        nullable=False,
        default="agency_viewer",
        comment="Role template slug to assign on approval (e.g. agency_viewer, agency_admin)",
    )

    # Approval message shown to tenant admin
    message = Column(
        Text,
        nullable=False,
        default="[AppName] is testing for bringing in your reporting data. Please approve or deny.",
        comment="Message displayed to tenant admin for review",
    )

    # Status tracking
    status = Column(
        String(20),
        nullable=False,
        default=AgencyAccessRequestStatus.PENDING.value,
        index=True,
        comment="Request lifecycle status: pending, approved, denied, expired, cancelled",
    )

    # Approval/denial tracking
    reviewed_by = Column(
        String(255),
        nullable=True,
        comment="clerk_user_id of the tenant admin who reviewed this request",
    )

    reviewed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the request was reviewed",
    )

    review_note = Column(
        Text,
        nullable=True,
        comment="Optional note from the reviewer",
    )

    # Expiration
    expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When this request expires if not reviewed",
    )

    # Relationships
    requesting_user = relationship("User", lazy="joined")
    requesting_org = relationship("Organization", lazy="joined")
    tenant = relationship("Tenant", lazy="joined")

    __table_args__ = (
        # Only one pending request per user-tenant pair
        # (handled via partial unique index in SQL migration)
        Index("ix_agency_access_requests_tenant_status", "tenant_id", "status"),
        Index("ix_agency_access_requests_user_status", "requesting_user_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<AgencyAccessRequest(id={self.id}, user={self.requesting_user_id}, "
            f"tenant={self.tenant_id}, status={self.status})>"
        )

    @property
    def is_pending(self) -> bool:
        return self.status == AgencyAccessRequestStatus.PENDING.value

    @property
    def is_reviewable(self) -> bool:
        """Check if this request can still be reviewed."""
        if not self.is_pending:
            return False
        if self.expires_at:
            expires = self.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > expires:
                return False
        return True

    def approve(self, reviewed_by: str, review_note: Optional[str] = None) -> None:
        """Mark this request as approved."""
        self.status = AgencyAccessRequestStatus.APPROVED.value
        self.reviewed_by = reviewed_by
        self.reviewed_at = datetime.now(timezone.utc)
        self.review_note = review_note

    def deny(self, reviewed_by: str, review_note: Optional[str] = None) -> None:
        """Mark this request as denied."""
        self.status = AgencyAccessRequestStatus.DENIED.value
        self.reviewed_by = reviewed_by
        self.reviewed_at = datetime.now(timezone.utc)
        self.review_note = review_note

    def cancel(self) -> None:
        """Mark this request as cancelled by the requester."""
        self.status = AgencyAccessRequestStatus.CANCELLED.value

    def expire(self) -> None:
        """Mark this request as expired."""
        self.status = AgencyAccessRequestStatus.EXPIRED.value
