"""
ConnectionConsent model for merchant consent on data ingestion connections.

Stores explicit merchant approval/denial for data ingestion connections.
No connection activates without an APPROVED consent record.

KEY PRINCIPLES:
- NO connection activates without explicit merchant approval
- Consent decisions are immutable once made (approve/deny)
- Denied requests cannot auto-retry (must create new request)
- Full audit context captured at decision time

SECURITY:
- Tenant isolation via TenantScopedMixin (tenant_id from JWT only)
- Only MERCHANT_ADMIN can approve or deny
- Decision records are immutable (status transitions enforced)
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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import JSON

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin

# Use JSONB for PostgreSQL, JSON for other databases (testing)
JSONType = JSON().with_variant(JSONB(), "postgresql")


class ConsentStatus(str, enum.Enum):
    """Consent lifecycle status. Terminal states are immutable."""
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class ConnectionConsent(Base, TimestampMixin, TenantScopedMixin):
    """
    Merchant consent record for a data ingestion connection.

    Lifecycle:
    - PENDING: Request created, awaiting merchant decision
    - APPROVED: Merchant approved, connection may activate
    - DENIED: Merchant denied, connection must NOT activate.
      Denied requests cannot auto-retry; a new request is required.

    IMMUTABILITY: Once status transitions to APPROVED or DENIED, no
    further changes are permitted. The decision timestamp, approver,
    and context are captured at decision time and cannot be altered.

    Attributes:
        id: Primary key (UUID)
        tenant_id: Tenant from JWT org_id (NEVER client input)
        connection_id: ID of the connection this consent covers
        connection_name: Human-readable connection label
        source_type: Connector type (shopify, meta, google_ads, etc.)
        app_name: Display name of the app requesting data access
        requested_by: clerk_user_id of the user who initiated the request
        status: Consent lifecycle (pending, approved, denied)
        decided_by: clerk_user_id of the merchant admin who decided
        decided_at: Immutable timestamp of the decision
        decision_reason: Optional reason provided with the decision
        ip_address: Client IP at decision time (compliance)
        user_agent: Client user agent at decision time (compliance)
    """

    __tablename__ = "connection_consents"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)",
    )

    connection_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="ID of the Airbyte/ingestion connection this consent covers",
    )

    connection_name = Column(
        String(255),
        nullable=False,
        comment="Human-readable connection label shown to merchant",
    )

    source_type = Column(
        String(100),
        nullable=False,
        comment="Connector source type (shopify, meta, google_ads, etc.)",
    )

    app_name = Column(
        String(255),
        nullable=False,
        comment="Display name of the app requesting data access",
    )

    requested_by = Column(
        String(255),
        nullable=False,
        comment="clerk_user_id of the user who initiated the consent request",
    )

    status = Column(
        Enum(ConsentStatus),
        nullable=False,
        default=ConsentStatus.PENDING,
        comment="Consent lifecycle: pending, approved, denied",
    )

    # Decision context (populated when merchant decides)
    decided_by = Column(
        String(255),
        nullable=True,
        comment="clerk_user_id of the merchant admin who approved/denied",
    )

    decided_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Immutable timestamp when the decision was made",
    )

    decision_reason = Column(
        Text,
        nullable=True,
        comment="Optional reason provided with approval or denial",
    )

    # Compliance context captured at decision time
    ip_address = Column(
        String(45),
        nullable=True,
        comment="Client IP at decision time (IPv6 compatible)",
    )

    user_agent = Column(
        String(500),
        nullable=True,
        comment="Client user agent at decision time",
    )

    __table_args__ = (
        # One pending consent per connection per tenant
        UniqueConstraint(
            "tenant_id",
            "connection_id",
            name="uq_connection_consents_tenant_connection",
        ),
        # Pending consents per tenant (dashboard query)
        Index(
            "ix_connection_consents_tenant_status",
            "tenant_id",
            "status",
        ),
        # Lookup by connection
        Index(
            "ix_connection_consents_connection",
            "connection_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ConnectionConsent("
            f"id={self.id}, "
            f"connection_id={self.connection_id}, "
            f"status={self.status}"
            f")>"
        )

    @property
    def is_pending(self) -> bool:
        return self.status == ConsentStatus.PENDING

    @property
    def is_approved(self) -> bool:
        return self.status == ConsentStatus.APPROVED

    @property
    def is_denied(self) -> bool:
        return self.status == ConsentStatus.DENIED

    @property
    def is_decided(self) -> bool:
        return self.status in (ConsentStatus.APPROVED, ConsentStatus.DENIED)

    def approve(
        self,
        user_id: str,
        reason: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """
        Approve this consent request. Immutable once set.

        Raises:
            ValueError: If consent is not in PENDING status
        """
        if self.status != ConsentStatus.PENDING:
            raise ValueError(
                f"Cannot approve consent in {self.status.value} status"
            )
        self.status = ConsentStatus.APPROVED
        self.decided_by = user_id
        self.decided_at = datetime.now(timezone.utc)
        self.decision_reason = reason
        self.ip_address = ip_address
        self.user_agent = user_agent

    def deny(
        self,
        user_id: str,
        reason: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """
        Deny this consent request. Immutable once set.
        Denied requests cannot auto-retry.

        Raises:
            ValueError: If consent is not in PENDING status
        """
        if self.status != ConsentStatus.PENDING:
            raise ValueError(
                f"Cannot deny consent in {self.status.value} status"
            )
        self.status = ConsentStatus.DENIED
        self.decided_by = user_id
        self.decided_at = datetime.now(timezone.utc)
        self.decision_reason = reason
        self.ip_address = ip_address
        self.user_agent = user_agent

    def to_summary(self) -> dict:
        """Return a safe summary dict for API responses."""
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "connection_name": self.connection_name,
            "source_type": self.source_type,
            "app_name": self.app_name,
            "status": self.status.value if self.status else None,
            "requested_by": self.requested_by,
            "decided_by": self.decided_by,
            "decided_at": (
                self.decided_at.isoformat() if self.decided_at else None
            ),
            "decision_reason": self.decision_reason,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }
