"""
Explore guardrail bypass exception model.

Defines time-boxed, approval-based exceptions that allow limited guardrail
relaxation for a specific user and dataset scope.

SECURITY:
- Tenant isolation enforced via TenantScopedMixin.
- request/approval roles are stored for auditability.
- RLS/tenant isolation is never disabled by this model.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import Column, DateTime, Enum, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin


JSONType = JSON().with_variant(JSONB(), "postgresql")


class GuardrailExceptionStatus(str, enum.Enum):
    """Lifecycle status for guardrail bypass exceptions."""

    REQUESTED = "requested"
    APPROVED = "approved"
    REVOKED = "revoked"
    EXPIRED = "expired"


class ExploreGuardrailException(Base, TimestampMixin, TenantScopedMixin):
    """
    Time-boxed guardrail bypass exception.

    Scoped to a user + dataset(s). Exceptions auto-expire at expires_at.
    """

    __tablename__ = "explore_guardrail_exceptions"

    id = Column(String(255), primary_key=True, default=lambda: str(uuid.uuid4()))

    user_id = Column(String(255), nullable=False, index=True)
    requested_by = Column(String(255), nullable=False)
    requested_by_role = Column(String(100), nullable=False)
    approved_by = Column(String(255), nullable=True)
    approved_by_role = Column(String(100), nullable=True)

    dataset_names = Column(JSONType, nullable=False, default=list)
    reason = Column(Text, nullable=False)

    status = Column(
        Enum(GuardrailExceptionStatus),
        nullable=False,
        default=GuardrailExceptionStatus.REQUESTED,
        index=True,
    )

    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_guardrail_exceptions_tenant_user", "tenant_id", "user_id"),
        Index("ix_guardrail_exceptions_status_expires", "status", "expires_at"),
    )

    @classmethod
    def create_request(
        cls,
        *,
        tenant_id: str,
        user_id: str,
        requested_by: str,
        requested_by_role: str,
        dataset_names: Iterable[str],
        reason: str,
        expires_at: datetime,
    ) -> "ExploreGuardrailException":
        """Create a new guardrail bypass request."""
        if not dataset_names:
            raise ValueError("dataset_names must be provided")
        if expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")

        return cls(
            tenant_id=tenant_id,
            user_id=user_id,
            requested_by=requested_by,
            requested_by_role=requested_by_role,
            dataset_names=list(dataset_names),
            reason=reason,
            expires_at=expires_at,
            status=GuardrailExceptionStatus.REQUESTED,
        )

    def approve(self, approved_by: str, approved_by_role: str) -> None:
        """Approve the exception request."""
        self.approved_by = approved_by
        self.approved_by_role = approved_by_role
        self.approved_at = datetime.now(timezone.utc)
        self.status = GuardrailExceptionStatus.APPROVED

    def revoke(self) -> None:
        """Revoke the exception early."""
        self.revoked_at = datetime.now(timezone.utc)
        self.status = GuardrailExceptionStatus.REVOKED

    def mark_expired(self) -> None:
        """Mark the exception as expired."""
        self.status = GuardrailExceptionStatus.EXPIRED

    def is_active(self, now: Optional[datetime] = None) -> bool:
        """Check if the exception is currently active."""
        now = now or datetime.now(timezone.utc)
        return (
            self.status == GuardrailExceptionStatus.APPROVED
            and self.expires_at > now
            and self.revoked_at is None
        )

    def has_dataset(self, dataset: str) -> bool:
        """Check if the exception applies to a dataset."""
        return dataset in (self.dataset_names or [])
