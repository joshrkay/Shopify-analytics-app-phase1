"""
Consent service for merchant approval of data ingestion connections.

Handles the consent lifecycle: request, approve, deny, and query.
No connection activates without an APPROVED consent record.

FLOW:
1. Agency Admin or Merchant Admin calls request_consent()
2. Merchant Admin sees pending consent and calls approve() or deny()
3. Decision is immutable and auditable
4. Denied requests cannot auto-retry (must create new request)

SECURITY:
- tenant_id MUST come from JWT (org_id), never from client input
- Only MERCHANT_ADMIN (Permission.SETTINGS_MANAGE) can approve/deny
- All decisions are immutable once made
- Structured logging with no secret leakage
"""

import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from src.constants.permissions import (
    Permission,
    roles_have_permission,
    get_primary_approver_role,
)
from src.models.connection_consent import (
    ConnectionConsent,
    ConsentStatus,
)

logger = logging.getLogger(__name__)


class ConsentError(Exception):
    """Base error for consent operations."""
    pass


class ConsentNotFoundError(ConsentError):
    """Raised when a consent record is not found."""
    pass


class ConsentAlreadyExistsError(ConsentError):
    """Raised when a pending consent already exists for a connection."""
    pass


class ConsentDeniedRetryError(ConsentError):
    """Raised when attempting to re-request consent on a denied connection."""
    pass


class PermissionDeniedError(ConsentError):
    """Raised when user lacks required permission."""
    pass


class ConsentService:
    """
    Service for managing merchant consent on data ingestion connections.

    All operations are tenant-scoped. The tenant_id MUST come from
    the JWT (org_id claim), never from client input.
    """

    def __init__(self, db_session: Session, tenant_id: str):
        self.db = db_session
        self.tenant_id = tenant_id

    # =========================================================================
    # Request Consent
    # =========================================================================

    def request_consent(
        self,
        connection_id: str,
        connection_name: str,
        source_type: str,
        app_name: str,
        requested_by: str,
    ) -> ConnectionConsent:
        """
        Create a new consent request for a data ingestion connection.

        Args:
            connection_id: ID of the connection requiring consent
            connection_name: Human-readable connection label
            source_type: Connector type (shopify, meta, google_ads, etc.)
            app_name: Display name of the app requesting data access
            requested_by: clerk_user_id of the requesting user

        Returns:
            The created ConnectionConsent record

        Raises:
            ConsentAlreadyExistsError: If a pending consent already exists
            ConsentDeniedRetryError: If a denied consent exists (no auto-retry)
        """
        existing = self._get_consent_for_connection(connection_id)

        if existing is not None:
            if existing.is_pending:
                raise ConsentAlreadyExistsError(
                    f"Pending consent already exists for connection "
                    f"{connection_id}"
                )
            if existing.is_denied:
                raise ConsentDeniedRetryError(
                    f"Consent was denied for connection {connection_id}. "
                    f"Denied requests cannot auto-retry."
                )
            if existing.is_approved:
                raise ConsentAlreadyExistsError(
                    f"Connection {connection_id} is already approved"
                )

        consent = ConnectionConsent(
            tenant_id=self.tenant_id,
            connection_id=connection_id,
            connection_name=connection_name,
            source_type=source_type,
            app_name=app_name,
            requested_by=requested_by,
            status=ConsentStatus.PENDING,
        )
        self.db.add(consent)
        self.db.commit()
        self.db.refresh(consent)

        logger.info(
            "Consent requested",
            extra={
                "tenant_id": self.tenant_id,
                "consent_id": consent.id,
                "connection_id": connection_id,
                "source_type": source_type,
                "requested_by": requested_by,
            },
        )

        return consent

    # =========================================================================
    # Approve / Deny
    # =========================================================================

    def approve(
        self,
        consent_id: str,
        user_id: str,
        user_roles: list[str],
        reason: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ConnectionConsent:
        """
        Approve a pending consent request.

        Args:
            consent_id: ID of the consent to approve
            user_id: clerk_user_id of the approving merchant admin
            user_roles: Roles from JWT for permission check
            reason: Optional approval reason
            ip_address: Client IP for audit compliance
            user_agent: Client user agent for audit compliance

        Returns:
            The approved ConnectionConsent record

        Raises:
            PermissionDeniedError: If user lacks SETTINGS_MANAGE permission
            ConsentNotFoundError: If consent not found for this tenant
            ConsentError: If consent is not in PENDING status
        """
        self._require_permission(user_roles)

        consent = self._get_consent(consent_id)
        if consent is None:
            raise ConsentNotFoundError(
                f"Consent {consent_id} not found"
            )

        try:
            consent.approve(
                user_id=user_id,
                reason=reason,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        except ValueError as exc:
            raise ConsentError(str(exc)) from exc

        self.db.commit()

        approver_role = get_primary_approver_role(user_roles)
        logger.info(
            "Consent approved",
            extra={
                "tenant_id": self.tenant_id,
                "consent_id": consent_id,
                "connection_id": consent.connection_id,
                "decided_by": user_id,
                "approver_role": approver_role,
            },
        )

        return consent

    def deny(
        self,
        consent_id: str,
        user_id: str,
        user_roles: list[str],
        reason: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ConnectionConsent:
        """
        Deny a pending consent request. Denied requests cannot auto-retry.

        Args:
            consent_id: ID of the consent to deny
            user_id: clerk_user_id of the denying merchant admin
            user_roles: Roles from JWT for permission check
            reason: Optional denial reason
            ip_address: Client IP for audit compliance
            user_agent: Client user agent for audit compliance

        Returns:
            The denied ConnectionConsent record

        Raises:
            PermissionDeniedError: If user lacks SETTINGS_MANAGE permission
            ConsentNotFoundError: If consent not found for this tenant
            ConsentError: If consent is not in PENDING status
        """
        self._require_permission(user_roles)

        consent = self._get_consent(consent_id)
        if consent is None:
            raise ConsentNotFoundError(
                f"Consent {consent_id} not found"
            )

        try:
            consent.deny(
                user_id=user_id,
                reason=reason,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        except ValueError as exc:
            raise ConsentError(str(exc)) from exc

        self.db.commit()

        approver_role = get_primary_approver_role(user_roles)
        logger.info(
            "Consent denied",
            extra={
                "tenant_id": self.tenant_id,
                "consent_id": consent_id,
                "connection_id": consent.connection_id,
                "decided_by": user_id,
                "approver_role": approver_role,
            },
        )

        return consent

    # =========================================================================
    # Query
    # =========================================================================

    def get_consent(self, consent_id: str) -> Optional[dict]:
        """Get a consent record summary by ID."""
        consent = self._get_consent(consent_id)
        if consent is None:
            return None
        return consent.to_summary()

    def list_pending(self) -> list[dict]:
        """List all pending consent requests for the tenant."""
        stmt = (
            select(ConnectionConsent)
            .where(ConnectionConsent.tenant_id == self.tenant_id)
            .where(ConnectionConsent.status == ConsentStatus.PENDING)
            .order_by(ConnectionConsent.created_at.desc())
        )
        results = self.db.execute(stmt).scalars().all()
        return [c.to_summary() for c in results]

    def list_all(self) -> list[dict]:
        """List all consent records for the tenant (all statuses)."""
        stmt = (
            select(ConnectionConsent)
            .where(ConnectionConsent.tenant_id == self.tenant_id)
            .order_by(ConnectionConsent.created_at.desc())
        )
        results = self.db.execute(stmt).scalars().all()
        return [c.to_summary() for c in results]

    def get_pending_count(self) -> int:
        """Get count of pending consent requests for badge display."""
        stmt = (
            select(func.count())
            .select_from(ConnectionConsent)
            .where(ConnectionConsent.tenant_id == self.tenant_id)
            .where(ConnectionConsent.status == ConsentStatus.PENDING)
        )
        return self.db.execute(stmt).scalar() or 0

    def is_connection_approved(self, connection_id: str) -> bool:
        """Check if a connection has an approved consent record."""
        consent = self._get_consent_for_connection(connection_id)
        return consent is not None and consent.is_approved

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _get_consent(self, consent_id: str) -> Optional[ConnectionConsent]:
        """Fetch a consent record by ID, scoped to tenant."""
        stmt = (
            select(ConnectionConsent)
            .where(ConnectionConsent.id == consent_id)
            .where(ConnectionConsent.tenant_id == self.tenant_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def _get_consent_for_connection(
        self, connection_id: str
    ) -> Optional[ConnectionConsent]:
        """Fetch the consent record for a connection, scoped to tenant."""
        stmt = (
            select(ConnectionConsent)
            .where(ConnectionConsent.connection_id == connection_id)
            .where(ConnectionConsent.tenant_id == self.tenant_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def _require_permission(user_roles: list[str]) -> None:
        """
        Verify user has SETTINGS_MANAGE permission (Merchant Admin+).

        Raises:
            PermissionDeniedError: If user lacks the required permission
        """
        if not roles_have_permission(
            user_roles, Permission.SETTINGS_MANAGE
        ):
            raise PermissionDeniedError(
                "Only Merchant Admin or higher can approve/deny "
                "connection consent"
            )
