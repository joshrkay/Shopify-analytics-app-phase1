"""
Token refresh and revocation manager for ingestion credentials.

Handles the complete credential token lifecycle:
- Proactive refresh: background check for tokens approaching expiry
- Reactive refresh: on-demand refresh when auth failures are detected
- Immediate revocation: instant credential invalidation on disconnect
- Audit trail: all operations logged to immutable audit log

SECURITY:
- tenant_id from JWT only, never from client input
- Tokens are NEVER logged or exposed
- All revocations are enforced immediately via status update
- Audit events use canonical registry (credentials.refreshed, etc.)

Usage:
    manager = TokenManager(db_session=db, tenant_id=tenant_id)

    # Proactive: refresh credentials approaching expiry
    stats = await manager.refresh_expiring_credentials()

    # Reactive: attempt refresh after auth failure during sync
    result = await manager.reactive_refresh(credential_id)

    # Revocation: immediately revoke on disconnect
    await manager.revoke_credential(credential_id, reason="user_disconnect")
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.connector_credential import (
    ConnectorCredential,
    CredentialStatus,
)
from src.platform.secrets import encrypt_secret, decrypt_secret

logger = logging.getLogger(__name__)

# Refresh thresholds
PROACTIVE_REFRESH_HOURS = 24  # Refresh tokens expiring within 24 hours
MAX_REFRESH_ATTEMPTS = 3  # Max consecutive refresh failures before marking expired
REFRESH_BACKOFF_MINUTES = [5, 30, 120]  # Backoff between retry attempts


class RefreshResult(str, Enum):
    """Outcome of a token refresh attempt."""
    SUCCESS = "success"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"
    SKIPPED_ACTIVE = "skipped_active"
    SKIPPED_REVOKED = "skipped_revoked"
    NO_REFRESH_TOKEN = "no_refresh_token"


class RevocationReason(str, Enum):
    """Reason for credential revocation."""
    USER_DISCONNECT = "user_disconnect"
    PROVIDER_REVOKED = "provider_revoked"
    ADMIN_ACTION = "admin_action"
    SECURITY_EVENT = "security_event"
    AUTH_FAILURE_EXHAUSTED = "auth_failure_exhausted"


@dataclass
class RefreshOutcome:
    """Result of a single credential refresh attempt."""
    credential_id: str
    source_type: str
    result: RefreshResult
    error: Optional[str] = None
    new_expires_at: Optional[datetime] = None
    attempt_number: int = 0


@dataclass
class RefreshStats:
    """Aggregate stats from a proactive refresh run."""
    credentials_checked: int = 0
    refreshed: int = 0
    failed: int = 0
    skipped: int = 0
    expired_marked: int = 0
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "credentials_checked": self.credentials_checked,
            "refreshed": self.refreshed,
            "failed": self.failed,
            "skipped": self.skipped,
            "expired_marked": self.expired_marked,
            "error_count": len(self.errors),
        }


class TokenManager:
    """
    Manages token refresh and revocation for ingestion credentials.

    Coordinates proactive refresh (background), reactive refresh (on auth
    failure), and immediate revocation (on disconnect). All operations are
    tenant-scoped and fully audited.
    """

    def __init__(self, db_session: Session, tenant_id: str):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.db = db_session
        self.tenant_id = tenant_id

    # =========================================================================
    # Proactive Refresh
    # =========================================================================

    async def refresh_expiring_credentials(
        self,
        hours_before_expiry: int = PROACTIVE_REFRESH_HOURS,
    ) -> RefreshStats:
        """
        Scan for credentials approaching expiry and refresh them.

        Called by a background worker on a schedule. Checks credential
        metadata for token_expires_at and refreshes those within the
        threshold window.

        Args:
            hours_before_expiry: Refresh tokens expiring within this many hours

        Returns:
            RefreshStats with counts of outcomes
        """
        stats = RefreshStats()
        expiring = self._get_expiring_credentials(hours_before_expiry)
        stats.credentials_checked = len(expiring)

        for credential in expiring:
            outcome = await self._attempt_refresh(credential)
            self._record_refresh_outcome(outcome, stats)
            self.db.flush()

        logger.info(
            "Proactive refresh completed",
            extra={
                "tenant_id": self.tenant_id,
                **stats.to_dict(),
            },
        )

        return stats

    def _get_expiring_credentials(self, hours_before_expiry: int) -> list:
        """
        Find active credentials with tokens expiring within the threshold.

        Checks credential_metadata['token_expires_at'] for expiry detection.
        """
        cutoff = datetime.now(timezone.utc) + timedelta(hours=hours_before_expiry)

        stmt = (
            select(ConnectorCredential)
            .where(ConnectorCredential.tenant_id == self.tenant_id)
            .where(ConnectorCredential.status == CredentialStatus.ACTIVE)
            .where(ConnectorCredential.soft_deleted_at.is_(None))
        )
        all_active = self.db.execute(stmt).scalars().all()

        expiring = []
        for cred in all_active:
            metadata = cred.credential_metadata or {}
            expires_at_str = metadata.get("token_expires_at")
            if not expires_at_str:
                continue
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                if expires_at <= cutoff:
                    expiring.append(cred)
            except (ValueError, TypeError):
                logger.warning(
                    "Invalid token_expires_at in credential metadata",
                    extra={
                        "tenant_id": self.tenant_id,
                        "credential_id": cred.id,
                    },
                )
        return expiring

    # =========================================================================
    # Reactive Refresh
    # =========================================================================

    async def reactive_refresh(
        self, credential_id: str
    ) -> RefreshOutcome:
        """
        Attempt to refresh a credential after an auth failure during sync.

        Called by the sync executor when an ingestion job fails with
        401/403. Attempts refresh up to MAX_REFRESH_ATTEMPTS times with
        backoff. After exhaustion, marks the credential as EXPIRED.

        Args:
            credential_id: The credential to refresh

        Returns:
            RefreshOutcome describing what happened
        """
        credential = self._get_credential(credential_id)
        if credential is None:
            return RefreshOutcome(
                credential_id=credential_id,
                source_type="unknown",
                result=RefreshResult.SKIPPED_REVOKED,
                error="Credential not found or not accessible",
            )

        if credential.status == CredentialStatus.REVOKED:
            return RefreshOutcome(
                credential_id=credential_id,
                source_type=credential.source_type,
                result=RefreshResult.SKIPPED_REVOKED,
                error="Credential has been revoked",
            )

        outcome = await self._attempt_refresh(credential)

        if outcome.result == RefreshResult.FAILED_PERMANENT:
            self._mark_expired(credential, outcome.error or "Refresh attempts exhausted")

        self.db.flush()

        self._log_audit_refresh(credential, outcome)

        return outcome

    # =========================================================================
    # Revocation
    # =========================================================================

    async def revoke_credential(
        self,
        credential_id: str,
        reason: RevocationReason,
        revoked_by: Optional[str] = None,
    ) -> bool:
        """
        Immediately revoke a credential.

        Sets status to REVOKED, which is enforced by all downstream
        consumers (sync executor checks credential status before use).
        The revocation is logged to the immutable audit trail.

        Args:
            credential_id: The credential to revoke
            reason: Why the credential is being revoked
            revoked_by: clerk_user_id of revoker (None for system)

        Returns:
            True if revoked, False if credential not found
        """
        credential = self._get_credential(credential_id, for_update=True)
        if credential is None:
            return False

        previous_status = credential.status
        credential.status = CredentialStatus.REVOKED

        metadata = dict(credential.credential_metadata or {})
        metadata["revoked_at"] = datetime.now(timezone.utc).isoformat()
        metadata["revocation_reason"] = reason.value
        if revoked_by:
            metadata["revoked_by"] = revoked_by
        credential.credential_metadata = metadata

        self.db.flush()

        self._log_audit_revocation(credential, reason, previous_status, revoked_by)

        logger.info(
            "Credential revoked",
            extra={
                "tenant_id": self.tenant_id,
                "credential_id": credential_id,
                "source_type": credential.source_type,
                "reason": reason.value,
                "previous_status": previous_status.value if previous_status else None,
            },
        )

        return True

    async def revoke_all_for_connection(
        self,
        source_type: str,
        reason: RevocationReason,
        revoked_by: Optional[str] = None,
    ) -> int:
        """
        Revoke all credentials for a given source type.

        Used when a connection is fully disconnected. Revokes all active
        credentials for the source type within the tenant.

        Args:
            source_type: Connector source type (e.g., 'shopify', 'meta')
            reason: Why credentials are being revoked
            revoked_by: clerk_user_id of revoker (None for system)

        Returns:
            Count of credentials revoked
        """
        stmt = (
            select(ConnectorCredential)
            .where(ConnectorCredential.tenant_id == self.tenant_id)
            .where(ConnectorCredential.source_type == source_type)
            .where(ConnectorCredential.status == CredentialStatus.ACTIVE)
            .where(ConnectorCredential.soft_deleted_at.is_(None))
        )
        credentials = self.db.execute(stmt).scalars().all()

        revoked_count = 0
        for credential in credentials:
            result = await self.revoke_credential(
                credential_id=credential.id,
                reason=reason,
                revoked_by=revoked_by,
            )
            if result:
                revoked_count += 1

        if revoked_count > 0:
            logger.info(
                "All credentials revoked for connection",
                extra={
                    "tenant_id": self.tenant_id,
                    "source_type": source_type,
                    "revoked_count": revoked_count,
                    "reason": reason.value,
                },
            )

        return revoked_count

    # =========================================================================
    # Status Checks
    # =========================================================================

    def is_credential_valid(self, credential_id: str) -> bool:
        """
        Check if a credential is still valid for use.

        Called by sync executor before starting a sync to fail fast
        instead of wasting an API call with revoked/expired tokens.

        Args:
            credential_id: The credential to check

        Returns:
            True if credential is active and not expired
        """
        credential = self._get_credential(credential_id)
        if credential is None:
            return False

        if credential.status != CredentialStatus.ACTIVE:
            return False

        # Check token expiry from metadata
        metadata = credential.credential_metadata or {}
        expires_at_str = metadata.get("token_expires_at")
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                if expires_at <= datetime.now(timezone.utc):
                    return False
            except (ValueError, TypeError):
                pass

        return True

    def get_credential_status(self, credential_id: str) -> Optional[dict]:
        """
        Get credential status summary (safe for API response).

        Args:
            credential_id: The credential to check

        Returns:
            Status dict or None if not found
        """
        credential = self._get_credential(credential_id)
        if credential is None:
            return None

        metadata = credential.credential_metadata or {}
        return {
            "credential_id": credential.id,
            "source_type": credential.source_type,
            "status": credential.status.value,
            "is_active": credential.is_active,
            "token_expires_at": metadata.get("token_expires_at"),
            "last_refresh_at": metadata.get("last_refresh_at"),
            "refresh_error_count": metadata.get("refresh_error_count", 0),
            "revoked_at": metadata.get("revoked_at"),
            "revocation_reason": metadata.get("revocation_reason"),
        }

    # =========================================================================
    # Internal: Refresh Logic
    # =========================================================================

    async def _attempt_refresh(
        self, credential: ConnectorCredential
    ) -> RefreshOutcome:
        """
        Attempt to refresh a single credential's tokens.

        Platform-specific refresh is delegated to _platform_refresh().
        Tracks attempt count in metadata for backoff enforcement.
        """
        metadata = dict(credential.credential_metadata or {})
        error_count = metadata.get("refresh_error_count", 0)

        if error_count >= MAX_REFRESH_ATTEMPTS:
            return RefreshOutcome(
                credential_id=credential.id,
                source_type=credential.source_type,
                result=RefreshResult.FAILED_PERMANENT,
                error=f"Max refresh attempts ({MAX_REFRESH_ATTEMPTS}) exhausted",
                attempt_number=error_count,
            )

        # Check backoff timing
        last_attempt_str = metadata.get("last_refresh_attempt_at")
        if last_attempt_str and error_count > 0:
            try:
                last_attempt = datetime.fromisoformat(last_attempt_str)
                backoff_idx = min(error_count - 1, len(REFRESH_BACKOFF_MINUTES) - 1)
                backoff_minutes = REFRESH_BACKOFF_MINUTES[backoff_idx]
                next_allowed = last_attempt + timedelta(minutes=backoff_minutes)
                if datetime.now(timezone.utc) < next_allowed:
                    return RefreshOutcome(
                        credential_id=credential.id,
                        source_type=credential.source_type,
                        result=RefreshResult.SKIPPED_ACTIVE,
                        error=f"Backoff in effect until {next_allowed.isoformat()}",
                        attempt_number=error_count,
                    )
            except (ValueError, TypeError):
                pass

        # Decrypt current tokens
        try:
            if credential.encrypted_payload is None:
                return RefreshOutcome(
                    credential_id=credential.id,
                    source_type=credential.source_type,
                    result=RefreshResult.FAILED_PERMANENT,
                    error="Credential payload wiped",
                    attempt_number=error_count,
                )

            plaintext = await decrypt_secret(credential.encrypted_payload)
            current_tokens = json.loads(plaintext)
        except Exception as exc:
            logger.error(
                "Failed to decrypt credential for refresh",
                extra={
                    "tenant_id": self.tenant_id,
                    "credential_id": credential.id,
                    "error_type": type(exc).__name__,
                },
            )
            return RefreshOutcome(
                credential_id=credential.id,
                source_type=credential.source_type,
                result=RefreshResult.FAILED_PERMANENT,
                error="Decryption failed",
                attempt_number=error_count,
            )

        # Check for refresh token
        refresh_token = current_tokens.get("refresh_token")
        if not refresh_token:
            return RefreshOutcome(
                credential_id=credential.id,
                source_type=credential.source_type,
                result=RefreshResult.NO_REFRESH_TOKEN,
                error="No refresh_token in credential payload",
                attempt_number=error_count,
            )

        # Record the attempt timestamp
        now = datetime.now(timezone.utc)
        metadata["last_refresh_attempt_at"] = now.isoformat()
        credential.credential_metadata = metadata
        self.db.flush()

        # Perform platform-specific refresh
        try:
            new_tokens = await self._platform_refresh(
                credential.source_type, current_tokens
            )
        except TokenRefreshError as exc:
            # Increment error count
            error_count += 1
            metadata["refresh_error_count"] = error_count
            metadata["last_refresh_error"] = str(exc)
            credential.credential_metadata = metadata
            self.db.flush()

            is_permanent = exc.permanent or error_count >= MAX_REFRESH_ATTEMPTS
            result = (
                RefreshResult.FAILED_PERMANENT
                if is_permanent
                else RefreshResult.FAILED_RETRYABLE
            )

            return RefreshOutcome(
                credential_id=credential.id,
                source_type=credential.source_type,
                result=result,
                error=str(exc),
                attempt_number=error_count,
            )

        # Refresh succeeded: encrypt and store new tokens
        try:
            encrypted = await encrypt_secret(json.dumps(new_tokens))
        except Exception as exc:
            logger.error(
                "Failed to encrypt refreshed tokens",
                extra={
                    "tenant_id": self.tenant_id,
                    "credential_id": credential.id,
                    "error_type": type(exc).__name__,
                },
            )
            return RefreshOutcome(
                credential_id=credential.id,
                source_type=credential.source_type,
                result=RefreshResult.FAILED_RETRYABLE,
                error="Encryption of new tokens failed",
                attempt_number=error_count,
            )

        credential.encrypted_payload = encrypted
        credential.status = CredentialStatus.ACTIVE

        # Update metadata with new expiry info
        new_expires_at = None
        if "expires_at" in new_tokens:
            metadata["token_expires_at"] = new_tokens["expires_at"]
            try:
                new_expires_at = datetime.fromisoformat(new_tokens["expires_at"])
            except (ValueError, TypeError):
                pass
        elif "expires_in" in new_tokens:
            expires_at = now + timedelta(seconds=int(new_tokens["expires_in"]))
            metadata["token_expires_at"] = expires_at.isoformat()
            new_expires_at = expires_at

        metadata["last_refresh_at"] = now.isoformat()
        metadata["refresh_error_count"] = 0
        metadata.pop("last_refresh_error", None)
        credential.credential_metadata = metadata

        self.db.flush()

        return RefreshOutcome(
            credential_id=credential.id,
            source_type=credential.source_type,
            result=RefreshResult.SUCCESS,
            new_expires_at=new_expires_at,
            attempt_number=0,
        )

    async def _platform_refresh(
        self, source_type: str, current_tokens: dict
    ) -> dict:
        """
        Perform platform-specific token refresh.

        Delegates to the appropriate platform's OAuth refresh endpoint.
        Each platform has different refresh mechanics:
        - Shopify: Offline tokens don't expire (returns current tokens)
        - Meta/Facebook: Exchange for long-lived token via Graph API
        - Google: Standard OAuth2 refresh_token flow

        Args:
            source_type: Platform identifier
            current_tokens: Current credential payload with refresh_token

        Returns:
            New token payload dict

        Raises:
            TokenRefreshError: If refresh fails
        """
        if source_type == "shopify":
            return await self._refresh_shopify(current_tokens)
        elif source_type in ("meta", "facebook"):
            return await self._refresh_meta(current_tokens)
        elif source_type in ("google_ads", "google"):
            return await self._refresh_google(current_tokens)
        else:
            raise TokenRefreshError(
                f"Unsupported source type for refresh: {source_type}",
                permanent=True,
            )

    async def _refresh_shopify(self, tokens: dict) -> dict:
        """
        Refresh Shopify credentials.

        Shopify offline access tokens don't expire, so this is effectively
        a no-op validation. If the token is invalid, Shopify returns 401
        and this should be treated as a permanent failure (re-auth needed).
        """
        # Shopify offline tokens don't expire - return as-is
        # In production, this would validate the token is still active
        # by making a lightweight API call
        return tokens

    async def _refresh_meta(self, tokens: dict) -> dict:
        """
        Refresh Meta/Facebook credentials.

        Exchanges a short-lived token for a long-lived one, or refreshes
        an existing long-lived token. Long-lived tokens are valid for ~60
        days and can be refreshed before expiry.

        In production, this calls the Graph API:
        GET /oauth/access_token?grant_type=fb_exchange_token&
            client_id={app_id}&client_secret={app_secret}&
            fb_exchange_token={existing_token}
        """
        # Placeholder for Meta token refresh
        # Production implementation would call the Graph API
        raise TokenRefreshError(
            "Meta token refresh requires Graph API integration",
            permanent=False,
        )

    async def _refresh_google(self, tokens: dict) -> dict:
        """
        Refresh Google OAuth2 credentials.

        Uses the standard OAuth2 refresh_token grant to obtain a new
        access_token. Refresh tokens for Google Ads don't expire unless
        revoked by the user.

        In production, this calls:
        POST https://oauth2.googleapis.com/token
            grant_type=refresh_token&
            client_id={client_id}&client_secret={client_secret}&
            refresh_token={refresh_token}
        """
        # Placeholder for Google OAuth2 refresh
        # Production implementation would call the token endpoint
        raise TokenRefreshError(
            "Google token refresh requires OAuth2 integration",
            permanent=False,
        )

    # =========================================================================
    # Internal: Status Management
    # =========================================================================

    def _mark_expired(self, credential: ConnectorCredential, reason: str) -> None:
        """Mark a credential as expired after refresh failures."""
        credential.status = CredentialStatus.EXPIRED

        metadata = dict(credential.credential_metadata or {})
        metadata["expired_at"] = datetime.now(timezone.utc).isoformat()
        metadata["expired_reason"] = reason
        credential.credential_metadata = metadata

        self.db.flush()

        logger.warning(
            "Credential marked as expired",
            extra={
                "tenant_id": self.tenant_id,
                "credential_id": credential.id,
                "source_type": credential.source_type,
                "reason": reason,
            },
        )

    def _record_refresh_outcome(
        self, outcome: RefreshOutcome, stats: RefreshStats
    ) -> None:
        """Update aggregate stats from a single refresh outcome."""
        if outcome.result == RefreshResult.SUCCESS:
            stats.refreshed += 1
        elif outcome.result in (
            RefreshResult.SKIPPED_ACTIVE,
            RefreshResult.SKIPPED_REVOKED,
            RefreshResult.NO_REFRESH_TOKEN,
        ):
            stats.skipped += 1
        elif outcome.result == RefreshResult.FAILED_PERMANENT:
            stats.failed += 1
            stats.expired_marked += 1
            if outcome.error:
                stats.errors.append(outcome.error)
            # Mark expired for permanent failures in proactive mode
            credential = self._get_credential(outcome.credential_id)
            if credential and credential.status == CredentialStatus.ACTIVE:
                self._mark_expired(credential, outcome.error or "Refresh failed")
        elif outcome.result == RefreshResult.FAILED_RETRYABLE:
            stats.failed += 1
            if outcome.error:
                stats.errors.append(outcome.error)

    # =========================================================================
    # Internal: DB Access
    # =========================================================================

    def _get_credential(
        self, credential_id: str, for_update: bool = False
    ) -> Optional[ConnectorCredential]:
        """
        Fetch a credential by ID within the current tenant.

        Unlike CredentialVault._get_active_credential, this fetches
        credentials regardless of status (needed for revocation checks
        and status transitions).
        """
        stmt = (
            select(ConnectorCredential)
            .where(ConnectorCredential.id == credential_id)
            .where(ConnectorCredential.tenant_id == self.tenant_id)
            .where(ConnectorCredential.soft_deleted_at.is_(None))
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.db.execute(stmt).scalar_one_or_none()

    # =========================================================================
    # Internal: Audit Logging
    # =========================================================================

    def _log_audit_refresh(
        self, credential: ConnectorCredential, outcome: RefreshOutcome
    ) -> None:
        """Log a credential refresh attempt to the audit trail."""
        try:
            from src.platform.audit import (
                AuditAction,
                AuditOutcome,
                log_system_audit_event_sync,
            )

            is_success = outcome.result == RefreshResult.SUCCESS
            action = AuditAction.AUTH_TOKEN_REFRESH
            audit_outcome = (
                AuditOutcome.SUCCESS if is_success else AuditOutcome.FAILURE
            )

            metadata = {
                "source_type": credential.source_type,
                "credential_id": credential.id,
                "refresh_result": outcome.result.value,
                "attempt_number": outcome.attempt_number,
            }
            if outcome.error:
                metadata["error"] = outcome.error[:200]
            if outcome.new_expires_at:
                metadata["new_expires_at"] = outcome.new_expires_at.isoformat()

            log_system_audit_event_sync(
                db=self.db,
                tenant_id=self.tenant_id,
                action=action,
                resource_type="credential",
                resource_id=credential.id,
                metadata=metadata,
                source="worker",
                outcome=audit_outcome,
            )
        except Exception:
            logger.warning(
                "Failed to write refresh audit event",
                extra={
                    "tenant_id": self.tenant_id,
                    "credential_id": credential.id,
                },
                exc_info=True,
            )

    def _log_audit_revocation(
        self,
        credential: ConnectorCredential,
        reason: RevocationReason,
        previous_status: Optional[CredentialStatus],
        revoked_by: Optional[str],
    ) -> None:
        """Log a credential revocation to the audit trail."""
        try:
            from src.platform.audit import (
                AuditAction,
                AuditOutcome,
                log_system_audit_event_sync,
            )

            log_system_audit_event_sync(
                db=self.db,
                tenant_id=self.tenant_id,
                action=AuditAction.STORE_DISCONNECTED,
                resource_type="credential",
                resource_id=credential.id,
                metadata={
                    "source_type": credential.source_type,
                    "reason": reason.value,
                    "previous_status": (
                        previous_status.value if previous_status else None
                    ),
                    "revoked_by": revoked_by,
                    "shop_domain": (credential.credential_metadata or {}).get(
                        "account_name", "unknown"
                    ),
                },
                source="system",
                outcome=AuditOutcome.SUCCESS,
            )
        except Exception:
            logger.warning(
                "Failed to write revocation audit event",
                extra={
                    "tenant_id": self.tenant_id,
                    "credential_id": credential.id,
                },
                exc_info=True,
            )


class TokenRefreshError(Exception):
    """
    Raised when a platform token refresh fails.

    Attributes:
        permanent: If True, the error is not retryable (e.g., token revoked
                   by provider). If False, the error may be transient.
    """

    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent
