"""
AccessRevocation model for grace-period access removal.

When agency access is revoked, access enters a configurable grace period
(default 24h). During the grace period, the user retains access but JWT
tokens include an access_expiring_at banner flag. After the grace period
ends, a worker job enforces the actual deactivation.

Story 5.5.4 - Grace-Period Access Removal
"""

import uuid
import enum
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin


class RevocationStatus(enum.Enum):
    GRACE_PERIOD = "grace_period"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class AccessRevocation(Base, TimestampMixin):
    """
    Tracks grace-period access revocation for agency users.

    Lifecycle:
    1. Revocation initiated -> status=grace_period, grace_period_ends_at set
    2. Worker enforces after grace_period_ends_at -> status=expired
    3. OR access re-granted before expiry -> status=cancelled
    """

    __tablename__ = "access_revocations"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    user_id = Column(
        String(255),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    tenant_id = Column(
        String(255),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    revoked_by = Column(
        String(255),
        nullable=True,
        comment="clerk_user_id of the user who initiated revocation",
    )

    revoked_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    grace_period_ends_at = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="When access actually expires",
    )

    grace_period_hours = Column(
        Integer,
        nullable=False,
        default=24,
    )

    status = Column(
        String(50),
        nullable=False,
        default=RevocationStatus.GRACE_PERIOD.value,
        index=True,
    )

    expired_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When expiry was enforced by the worker",
    )

    # Relationships
    user = relationship("User", lazy="joined")
    tenant = relationship("Tenant", lazy="joined")

    __table_args__ = (
        Index(
            "ix_access_revocations_user_tenant_active",
            "user_id",
            "tenant_id",
            unique=True,
            postgresql_where=(
                Column("status") == RevocationStatus.GRACE_PERIOD.value
            ),
        ),
        Index("ix_access_revocations_status_ends", "status", "grace_period_ends_at"),
    )

    def _ensure_tz_aware(self, dt: datetime) -> datetime:
        """Ensure datetime is timezone-aware (SQLite returns naive datetimes)."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @property
    def is_in_grace_period(self) -> bool:
        return (
            self.status == RevocationStatus.GRACE_PERIOD.value
            and datetime.now(timezone.utc) < self._ensure_tz_aware(self.grace_period_ends_at)
        )

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self._ensure_tz_aware(self.grace_period_ends_at)

    def enforce_expiry(self) -> None:
        self.status = RevocationStatus.EXPIRED.value
        self.expired_at = datetime.now(timezone.utc)

    def cancel(self) -> None:
        self.status = RevocationStatus.CANCELLED.value

    def __repr__(self) -> str:
        return (
            f"<AccessRevocation(id={self.id}, user_id={self.user_id}, "
            f"tenant_id={self.tenant_id}, status={self.status})>"
        )
