"""
Access Revocation Service for grace-period access removal.

When access is revoked, it enters a configurable grace period (default 24h).
During the grace period, UserRoleAssignment/UserTenantRole remain active
and JWTs include an access_expiring_at banner flag.

After the grace period ends, a worker calls enforce_expired_revocations()
to deactivate the role assignments.

Story 5.5.4 - Grace-Period Access Removal
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from src.models.access_revocation import AccessRevocation, RevocationStatus
from src.models.user_role_assignment import UserRoleAssignment
from src.models.user_tenant_roles import UserTenantRole

logger = logging.getLogger(__name__)

DEFAULT_GRACE_HOURS = int(os.getenv("ACCESS_REVOCATION_GRACE_HOURS", "24"))


class AccessRevocationService:
    """Service for managing grace-period access revocation."""

    def __init__(self, session: Session):
        self.session = session

    def initiate_revocation(
        self,
        user_id: str,
        tenant_id: str,
        revoked_by: Optional[str] = None,
        grace_period_hours: int = DEFAULT_GRACE_HOURS,
    ) -> dict:
        """
        Initiate grace-period revocation. Idempotent — returns existing
        if a grace_period revocation already exists for this user-tenant.

        Access remains active during grace period; the worker enforces
        actual deactivation after grace_period_ends_at.
        """
        existing = (
            self.session.query(AccessRevocation)
            .filter(
                AccessRevocation.user_id == user_id,
                AccessRevocation.tenant_id == tenant_id,
                AccessRevocation.status == RevocationStatus.GRACE_PERIOD.value,
            )
            .first()
        )
        if existing:
            return self._to_dict(existing)

        now = datetime.now(timezone.utc)
        revocation = AccessRevocation(
            user_id=user_id,
            tenant_id=tenant_id,
            revoked_by=revoked_by,
            revoked_at=now,
            grace_period_ends_at=now + timedelta(hours=grace_period_hours),
            grace_period_hours=grace_period_hours,
            status=RevocationStatus.GRACE_PERIOD.value,
        )
        self.session.add(revocation)
        self.session.flush()

        # Emit audit event
        try:
            from src.services.audit_logger import emit_agency_access_revoked

            emit_agency_access_revoked(
                db=self.session,
                tenant_id=tenant_id,
                user_id=user_id,
                revoked_by=revoked_by,
                expires_at=revocation.grace_period_ends_at,
                grace_period_hours=grace_period_hours,
            )
        except Exception:
            logger.warning(
                "access_revocation.audit_event_failed",
                extra={"user_id": user_id, "tenant_id": tenant_id},
                exc_info=True,
            )

        logger.info(
            "Access revocation initiated",
            extra={
                "user_id": user_id,
                "tenant_id": tenant_id,
                "grace_period_hours": grace_period_hours,
                "grace_period_ends_at": revocation.grace_period_ends_at.isoformat(),
            },
        )

        return self._to_dict(revocation)

    def enforce_expired_revocations(self) -> list[dict]:
        """
        Enforce all revocations whose grace period has ended.

        Deactivates UserRoleAssignment and UserTenantRole records,
        then sets revocation status to expired.

        Called by the access_revocation_job worker.
        """
        now = datetime.now(timezone.utc)
        expired = (
            self.session.query(AccessRevocation)
            .filter(
                AccessRevocation.status == RevocationStatus.GRACE_PERIOD.value,
                AccessRevocation.grace_period_ends_at <= now,
            )
            .all()
        )

        enforced = []
        for revocation in expired:
            # Deactivate UserRoleAssignment records
            self.session.query(UserRoleAssignment).filter(
                UserRoleAssignment.user_id == revocation.user_id,
                UserRoleAssignment.tenant_id == revocation.tenant_id,
                UserRoleAssignment.is_active == True,  # noqa: E712
            ).update({"is_active": False})

            # Deactivate UserTenantRole records
            self.session.query(UserTenantRole).filter(
                UserTenantRole.user_id == revocation.user_id,
                UserTenantRole.tenant_id == revocation.tenant_id,
                UserTenantRole.is_active == True,  # noqa: E712
            ).update({"is_active": False})

            revocation.enforce_expiry()

            # Emit audit event
            try:
                from src.services.audit_logger import emit_agency_access_expired

                emit_agency_access_expired(
                    db=self.session,
                    tenant_id=revocation.tenant_id,
                    user_id=revocation.user_id,
                    revocation_id=revocation.id,
                )
            except Exception:
                logger.warning(
                    "access_revocation.expired_audit_failed",
                    extra={"revocation_id": revocation.id},
                    exc_info=True,
                )

            enforced.append(self._to_dict(revocation))

        logger.info(
            "Enforced expired revocations",
            extra={"count": len(enforced)},
        )

        return enforced

    def cancel_revocation(
        self, user_id: str, tenant_id: str
    ) -> Optional[dict]:
        """Cancel a pending grace-period revocation (e.g., access re-granted)."""
        revocation = (
            self.session.query(AccessRevocation)
            .filter(
                AccessRevocation.user_id == user_id,
                AccessRevocation.tenant_id == tenant_id,
                AccessRevocation.status == RevocationStatus.GRACE_PERIOD.value,
            )
            .first()
        )
        if not revocation:
            return None

        revocation.cancel()
        self.session.flush()

        logger.info(
            "Access revocation cancelled",
            extra={"user_id": user_id, "tenant_id": tenant_id},
        )

        return self._to_dict(revocation)

    def get_active_revocation(
        self, user_id: str, tenant_id: str
    ) -> Optional[dict]:
        """Get active grace-period revocation for JWT banner flag."""
        revocation = (
            self.session.query(AccessRevocation)
            .filter(
                AccessRevocation.user_id == user_id,
                AccessRevocation.tenant_id == tenant_id,
                AccessRevocation.status == RevocationStatus.GRACE_PERIOD.value,
            )
            .first()
        )
        if not revocation:
            return None

        return self._to_dict(revocation)

    def _to_dict(self, revocation: AccessRevocation) -> dict:
        return {
            "id": revocation.id,
            "user_id": revocation.user_id,
            "tenant_id": revocation.tenant_id,
            "revoked_by": revocation.revoked_by,
            "revoked_at": revocation.revoked_at.isoformat() if revocation.revoked_at else None,
            "grace_period_ends_at": revocation.grace_period_ends_at.isoformat() if revocation.grace_period_ends_at else None,
            "grace_period_hours": revocation.grace_period_hours,
            "status": revocation.status,
            "expired_at": revocation.expired_at.isoformat() if revocation.expired_at else None,
            "is_expired": revocation.is_expired,
            "is_in_grace_period": revocation.is_in_grace_period,
        }
