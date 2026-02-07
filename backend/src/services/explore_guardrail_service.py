"""
Explore guardrail bypass service.

Provides creation, approval, listing, and revocation of guardrail bypass
exceptions with audit logging.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from src.models.explore_guardrail_exception import (
    ExploreGuardrailException,
    GuardrailExceptionStatus,
)
from src.platform.audit import AuditAction, AuditOutcome, log_system_audit_event_sync


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GuardrailBypassContext:
    """Context for guardrail bypass decisions."""

    user_id: str
    dataset: str
    query_hash: Optional[str] = None


class ExploreGuardrailService:
    """
    Service for guardrail bypass exceptions.

    SECURITY:
    - request requires super admin
    - approval requires analytics tech lead or security engineer role
    """

    MAX_DURATION_MINUTES = 60
    REQUESTOR_ROLE = "super_admin"
    APPROVER_ROLES = {"analytics_tech_lead", "security_engineer"}

    def __init__(self, db_session: Session, tenant_id: str):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.db = db_session
        self.tenant_id = tenant_id

    def request_exception(
        self,
        *,
        requestor_id: str,
        requestor_roles: Iterable[str],
        user_id: str,
        dataset_names: Iterable[str],
        reason: str,
        duration_minutes: int,
    ) -> ExploreGuardrailException:
        """Create a bypass exception request (super admin only)."""
        if self.REQUESTOR_ROLE not in {r.lower() for r in requestor_roles}:
            raise PermissionError("Super admin access required to request bypass")
        if duration_minutes <= 0 or duration_minutes > self.MAX_DURATION_MINUTES:
            raise ValueError("duration_minutes must be between 1 and 60")
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)

        exception = ExploreGuardrailException.create_request(
            tenant_id=self.tenant_id,
            user_id=user_id,
            requested_by=requestor_id,
            requested_by_role=self.REQUESTOR_ROLE,
            dataset_names=list(dataset_names),
            reason=reason,
            expires_at=expires_at,
        )

        self.db.add(exception)
        self.db.flush()

        self._audit_event(
            action=AuditAction.EXPLORE_GUARDRAIL_BYPASS_REQUESTED,
            metadata={
                "user_id": user_id,
                "dataset": list(dataset_names),
                "reason": reason,
            },
        )
        return exception

    def approve_exception(
        self,
        *,
        approver_id: str,
        approver_roles: Iterable[str],
        exception_id: str,
    ) -> ExploreGuardrailException:
        """Approve a pending guardrail bypass exception."""
        if not self._is_valid_approver(approver_roles):
            raise PermissionError("Approver role not permitted")

        exception = self._get_exception(exception_id)
        if exception.status != GuardrailExceptionStatus.REQUESTED:
            raise ValueError("Exception is not in requested status")

        remaining = exception.expires_at - datetime.now(timezone.utc)
        if remaining > timedelta(minutes=self.MAX_DURATION_MINUTES):
            raise ValueError("Exception duration exceeds 60 minutes")

        exception.approve(approved_by=approver_id, approved_by_role=self._role_label(approver_roles))
        self.db.flush()

        duration_minutes = int((exception.expires_at - exception.created_at).total_seconds() // 60)
        self._audit_event(
            action=AuditAction.EXPLORE_GUARDRAIL_BYPASS_APPROVED,
            metadata={
                "user_id": exception.user_id,
                "approved_by": approver_id,
                "duration_minutes": duration_minutes,
            },
        )
        return exception

    def list_active_exceptions(self, user_id: Optional[str] = None) -> List[ExploreGuardrailException]:
        """Return active guardrail exceptions, marking expired ones."""
        now = datetime.now(timezone.utc)
        query = (
            self.db.query(ExploreGuardrailException)
            .filter(ExploreGuardrailException.tenant_id == self.tenant_id)
        )
        if user_id:
            query = query.filter(ExploreGuardrailException.user_id == user_id)

        exceptions = query.all()
        active: List[ExploreGuardrailException] = []
        for exception in exceptions:
            if exception.status == GuardrailExceptionStatus.APPROVED and exception.expires_at <= now:
                exception.mark_expired()
                self._audit_event(
                    action=AuditAction.EXPLORE_GUARDRAIL_BYPASS_EXPIRED,
                    metadata={
                        "user_id": exception.user_id,
                        "expired_at": exception.expires_at.isoformat(),
                    },
                )
            elif exception.is_active(now=now):
                active.append(exception)

        self.db.flush()
        return active

    def revoke_exception(
        self,
        *,
        actor_id: str,
        actor_roles: Iterable[str],
        exception_id: str,
    ) -> ExploreGuardrailException:
        """Revoke an exception early."""
        if not (self._is_valid_approver(actor_roles) or self.REQUESTOR_ROLE in {r.lower() for r in actor_roles}):
            raise PermissionError("Not authorized to revoke exception")

        exception = self._get_exception(exception_id)
        exception.revoke()
        self.db.flush()

        self._audit_event(
            action=AuditAction.EXPLORE_GUARDRAIL_BYPASS_REVOKED,
            metadata={
                "user_id": exception.user_id,
                "revoked_by": actor_id,
            },
        )
        return exception

    def get_active_exception_for_dataset(
        self,
        *,
        user_id: str,
        dataset_name: str,
    ) -> Optional[ExploreGuardrailException]:
        """Return active exception for a user + dataset, if any."""
        active = self.list_active_exceptions(user_id=user_id)
        for exception in active:
            if exception.has_dataset(dataset_name):
                return exception
        return None

    def record_usage(self, context: GuardrailBypassContext) -> None:
        """Audit a bypass usage event."""
        self._audit_event(
            action=AuditAction.EXPLORE_GUARDRAIL_BYPASS_USED,
            metadata={
                "user_id": context.user_id,
                "dataset": context.dataset,
                "query_hash": context.query_hash,
            },
        )

    @staticmethod
    def hash_query_params(query_params: dict) -> str:
        """Compute deterministic hash for query params."""
        payload = json.dumps(query_params, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _get_exception(self, exception_id: str) -> ExploreGuardrailException:
        exception = (
            self.db.query(ExploreGuardrailException)
            .filter(
                ExploreGuardrailException.tenant_id == self.tenant_id,
                ExploreGuardrailException.id == exception_id,
            )
            .first()
        )
        if not exception:
            raise ValueError("Guardrail exception not found")
        return exception

    def _audit_event(self, *, action: AuditAction, metadata: dict) -> None:
        try:
            log_system_audit_event_sync(
                db=self.db,
                tenant_id=self.tenant_id,
                action=action,
                resource_type="explore_guardrail_exception",
                metadata=metadata,
                outcome=AuditOutcome.SUCCESS,
            )
        except Exception:
            logger.warning(
                "guardrail_audit_failed",
                extra={"tenant_id": self.tenant_id, "action": action.value},
                exc_info=True,
            )

    @classmethod
    def _is_valid_approver(cls, roles: Iterable[str]) -> bool:
        role_set = {r.lower() for r in roles}
        return bool(cls.APPROVER_ROLES & role_set)

    @classmethod
    def _role_label(cls, roles: Iterable[str]) -> str:
        role_set = {r.lower() for r in roles}
        for role in cls.APPROVER_ROLES:
            if role in role_set:
                return role
        return "unknown"
