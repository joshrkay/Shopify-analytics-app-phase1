"""
Credential vault service for secure connector credential management.

Handles encryption, storage, retrieval, and lifecycle management of
connector credentials (OAuth tokens, API keys) with tenant isolation.

SECURITY:
- All credentials are Fernet-encrypted at rest via src.platform.secrets
- Tokens are NEVER logged, returned in list responses, or exposed in errors
- tenant_id MUST come from JWT (org_id), never from client input
- Metadata access gated by Permission.SETTINGS_MANAGE (Merchant Admin+)
- Soft delete (5-day restore window) + hard delete (20-day permanent wipe)

Usage:
    from src.services.credential_vault import CredentialVault

    vault = CredentialVault(db_session=session, tenant_id=tenant_id)
    cred_id = await vault.store(
        credential_name="Production Shopify",
        source_type="shopify",
        raw_credentials={"api_key": "...", "api_secret": "..."},
        metadata={"account_name": "My Store"},
        created_by="clerk_user_abc123",
    )
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.connector_credential import (
    ConnectorCredential,
    CredentialStatus,
    HARD_DELETE_AFTER_DAYS,
    SOFT_DELETE_RESTORE_WINDOW_DAYS,
)
from src.platform.secrets import encrypt_secret, decrypt_secret

logger = logging.getLogger(__name__)


class CredentialVaultError(Exception):
    """Base error for credential vault operations."""
    pass


class CredentialNotFoundError(CredentialVaultError):
    """Raised when a credential is not found or not accessible."""
    pass


class CredentialNotRestorableError(CredentialVaultError):
    """Raised when a soft-deleted credential is past the restore window."""
    pass


class CredentialVault:
    """
    Secure credential vault for connector credentials.

    All operations are tenant-scoped. The tenant_id MUST come from
    the JWT (org_id claim), never from client input.

    SECURITY:
    - Encrypted payloads are never logged or returned in list operations
    - Decryption only occurs in get_decrypted_payload()
    - Soft delete preserves data for 5-day restore window
    - Hard delete permanently wipes encrypted_payload after 20 days
    """

    def __init__(self, db_session: Session, tenant_id: str):
        """
        Initialize the credential vault.

        Args:
            db_session: SQLAlchemy database session
            tenant_id: Tenant identifier from JWT org_id (NEVER client input)
        """
        self.db = db_session
        self.tenant_id = tenant_id

    # =========================================================================
    # Store
    # =========================================================================

    async def store(
        self,
        credential_name: str,
        source_type: str,
        raw_credentials: dict,
        created_by: str,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        Encrypt and store a new connector credential.

        Args:
            credential_name: Human-readable label
            source_type: Connector type (shopify, meta, google_ads, etc.)
            raw_credentials: Sensitive credential dict to encrypt
            created_by: clerk_user_id of the creating user
            metadata: Optional non-sensitive metadata (account_name, labels)

        Returns:
            The credential ID (UUID string)

        Raises:
            CredentialVaultError: If encryption fails
        """
        if not raw_credentials:
            raise ValueError("raw_credentials must not be empty")

        try:
            encrypted = await encrypt_secret(json.dumps(raw_credentials))
        except Exception as exc:
            logger.error(
                "Failed to encrypt credential payload",
                extra={
                    "tenant_id": self.tenant_id,
                    "source_type": source_type,
                    "error_type": type(exc).__name__,
                },
            )
            raise CredentialVaultError("Encryption failed") from exc

        credential = ConnectorCredential(
            tenant_id=self.tenant_id,
            credential_name=credential_name,
            source_type=source_type,
            encrypted_payload=encrypted,
            credential_metadata=metadata or {},
            status=CredentialStatus.ACTIVE,
            created_by=created_by,
        )

        self.db.add(credential)
        self.db.commit()
        self.db.refresh(credential)

        logger.info(
            "Credential stored",
            extra={
                "tenant_id": self.tenant_id,
                "credential_id": credential.id,
                "source_type": source_type,
                "created_by": created_by,
            },
        )

        return credential.id

    # =========================================================================
    # Retrieve (metadata only - safe for API responses)
    # =========================================================================

    def get_metadata(self, credential_id: str) -> Optional[dict]:
        """
        Get credential metadata without decrypting the payload.

        Safe for API responses. Returns None if not found or soft-deleted.

        Args:
            credential_id: The credential UUID

        Returns:
            Dict of non-sensitive metadata, or None if not found
        """
        credential = self._get_active_credential(credential_id)
        if credential is None:
            return None
        return credential.safe_metadata()

    def list_credentials(self) -> list[dict]:
        """
        List all active credential metadata for the current tenant.

        Returns metadata only - NEVER includes encrypted payloads.

        Returns:
            List of credential metadata dicts
        """
        stmt = (
            select(ConnectorCredential)
            .where(ConnectorCredential.tenant_id == self.tenant_id)
            .where(ConnectorCredential.soft_deleted_at.is_(None))
            .order_by(ConnectorCredential.created_at.desc())
        )
        results = self.db.execute(stmt).scalars().all()
        return [cred.safe_metadata() for cred in results]

    # =========================================================================
    # Retrieve (decrypted - internal use only)
    # =========================================================================

    async def get_decrypted_payload(
        self, credential_id: str
    ) -> Optional[dict]:
        """
        Decrypt and return the credential payload.

        SECURITY: Only call this when credentials are needed for an API call.
        NEVER log, cache, or return the result to an end user.

        Args:
            credential_id: The credential UUID

        Returns:
            Decrypted credential dict, or None if not found

        Raises:
            CredentialVaultError: If decryption fails
        """
        credential = self._get_active_credential(credential_id)
        if credential is None:
            return None

        if credential.is_payload_wiped:
            logger.warning(
                "Attempted to decrypt wiped credential",
                extra={
                    "tenant_id": self.tenant_id,
                    "credential_id": credential_id,
                },
            )
            return None

        try:
            plaintext = await decrypt_secret(credential.encrypted_payload)
            decrypted = json.loads(plaintext)
        except Exception as exc:
            logger.error(
                "Failed to decrypt credential payload",
                extra={
                    "tenant_id": self.tenant_id,
                    "credential_id": credential_id,
                    "error_type": type(exc).__name__,
                },
            )
            raise CredentialVaultError("Decryption failed") from exc

        logger.info(
            "Credential payload decrypted",
            extra={
                "tenant_id": self.tenant_id,
                "credential_id": credential_id,
                "source_type": credential.source_type,
            },
        )

        return decrypted

    # =========================================================================
    # Update
    # =========================================================================

    async def rotate(
        self,
        credential_id: str,
        new_credentials: dict,
        rotated_by: str,
    ) -> None:
        """
        Rotate (replace) the encrypted payload for a credential.

        Args:
            credential_id: The credential UUID
            new_credentials: New sensitive credential dict to encrypt
            rotated_by: clerk_user_id performing the rotation

        Raises:
            CredentialNotFoundError: If credential not found or soft-deleted
            CredentialVaultError: If encryption fails
        """
        credential = self._get_active_credential(
            credential_id, for_update=True
        )
        if credential is None:
            raise CredentialNotFoundError(
                f"Credential {credential_id} not found"
            )

        if not new_credentials:
            raise ValueError("new_credentials must not be empty")

        try:
            encrypted = await encrypt_secret(json.dumps(new_credentials))
        except Exception as exc:
            logger.error(
                "Failed to encrypt rotated credential payload",
                extra={
                    "tenant_id": self.tenant_id,
                    "credential_id": credential_id,
                    "error_type": type(exc).__name__,
                },
            )
            raise CredentialVaultError("Encryption failed") from exc

        credential.encrypted_payload = encrypted
        credential.status = CredentialStatus.ACTIVE
        self.db.commit()

        logger.info(
            "Credential rotated",
            extra={
                "tenant_id": self.tenant_id,
                "credential_id": credential_id,
                "rotated_by": rotated_by,
            },
        )

    def update_status(
        self,
        credential_id: str,
        new_status: CredentialStatus,
    ) -> None:
        """
        Update the status of a credential (e.g., mark as expired).

        Args:
            credential_id: The credential UUID
            new_status: New status value

        Raises:
            CredentialNotFoundError: If credential not found
        """
        credential = self._get_active_credential(
            credential_id, for_update=True
        )
        if credential is None:
            raise CredentialNotFoundError(
                f"Credential {credential_id} not found"
            )

        credential.status = new_status
        self.db.commit()

        logger.info(
            "Credential status updated",
            extra={
                "tenant_id": self.tenant_id,
                "credential_id": credential_id,
                "new_status": new_status.value,
            },
        )

    # =========================================================================
    # Soft Delete & Restore
    # =========================================================================

    def soft_delete(self, credential_id: str, deleted_by: str) -> None:
        """
        Soft-delete a credential. Restorable within 5 days.

        Sets soft_deleted_at to now and schedules hard delete after 20 days.

        Args:
            credential_id: The credential UUID
            deleted_by: clerk_user_id performing the deletion

        Raises:
            CredentialNotFoundError: If credential not found or already deleted
        """
        credential = self._get_active_credential(
            credential_id, for_update=True
        )
        if credential is None:
            raise CredentialNotFoundError(
                f"Credential {credential_id} not found"
            )

        now = datetime.now(timezone.utc)
        credential.soft_deleted_at = now
        credential.hard_delete_after = now + timedelta(
            days=HARD_DELETE_AFTER_DAYS
        )
        credential.status = CredentialStatus.REVOKED
        self.db.commit()

        logger.info(
            "Credential soft-deleted",
            extra={
                "tenant_id": self.tenant_id,
                "credential_id": credential_id,
                "deleted_by": deleted_by,
                "restore_window_days": SOFT_DELETE_RESTORE_WINDOW_DAYS,
                "hard_delete_after": credential.hard_delete_after.isoformat(),
            },
        )

    def restore(self, credential_id: str, restored_by: str) -> None:
        """
        Restore a soft-deleted credential within the 5-day restore window.

        Args:
            credential_id: The credential UUID
            restored_by: clerk_user_id performing the restoration

        Raises:
            CredentialNotFoundError: If credential not found
            CredentialNotRestorableError: If restore window has passed
        """
        stmt = (
            select(ConnectorCredential)
            .where(ConnectorCredential.id == credential_id)
            .where(ConnectorCredential.tenant_id == self.tenant_id)
            .where(ConnectorCredential.soft_deleted_at.isnot(None))
        )
        credential = self.db.execute(stmt).scalar_one_or_none()

        if credential is None:
            raise CredentialNotFoundError(
                f"Soft-deleted credential {credential_id} not found"
            )

        if not credential.is_restorable:
            raise CredentialNotRestorableError(
                f"Credential {credential_id} is past the "
                f"{SOFT_DELETE_RESTORE_WINDOW_DAYS}-day restore window"
            )

        if credential.is_payload_wiped:
            raise CredentialNotRestorableError(
                f"Credential {credential_id} payload has been permanently wiped"
            )

        credential.soft_deleted_at = None
        credential.hard_delete_after = None
        credential.status = CredentialStatus.ACTIVE
        self.db.commit()

        logger.info(
            "Credential restored",
            extra={
                "tenant_id": self.tenant_id,
                "credential_id": credential_id,
                "restored_by": restored_by,
            },
        )

    # =========================================================================
    # Hard Delete (background job entry point)
    # =========================================================================

    @staticmethod
    def purge_expired(db_session: Session) -> int:
        """
        Permanently wipe encrypted payloads past their hard_delete_after deadline.

        This is a background job entry point. It operates across ALL tenants
        and permanently destroys encrypted data that is past the 20-day window.

        After wiping the payload, the row is deleted from the database.

        Args:
            db_session: Database session (not tenant-scoped)

        Returns:
            Number of credentials permanently wiped
        """
        now = datetime.now(timezone.utc)

        # Find all credentials past their hard delete deadline
        stmt = (
            select(ConnectorCredential)
            .where(ConnectorCredential.hard_delete_after.isnot(None))
            .where(ConnectorCredential.hard_delete_after <= now)
            .where(ConnectorCredential.soft_deleted_at.isnot(None))
        )
        expired = db_session.execute(stmt).scalars().all()

        if not expired:
            return 0

        purged_count = 0
        for credential in expired:
            # Step 1: Wipe encrypted payload to NULL (defense in depth)
            credential.encrypted_payload = None
            db_session.flush()

            # Step 2: Delete the row entirely
            db_session.delete(credential)
            purged_count += 1

            logger.info(
                "Credential hard-deleted",
                extra={
                    "tenant_id": credential.tenant_id,
                    "credential_id": credential.id,
                    "source_type": credential.source_type,
                },
            )

        db_session.commit()

        logger.info(
            "Credential purge completed",
            extra={"purged_count": purged_count},
        )

        return purged_count

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _get_active_credential(
        self, credential_id: str, for_update: bool = False
    ) -> Optional[ConnectorCredential]:
        """
        Fetch an active (non-soft-deleted) credential for the current tenant.

        Args:
            credential_id: The credential UUID
            for_update: If True, acquires a row-level lock (SELECT FOR UPDATE)
                to prevent race conditions on concurrent mutations.

        Returns:
            ConnectorCredential or None if not found / soft-deleted
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
