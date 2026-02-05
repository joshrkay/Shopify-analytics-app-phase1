"""
Unit tests for credential vault service and connector credential model.

Covers:
- Model properties: is_active, is_soft_deleted, is_restorable, safe_metadata
- Store: happy path, encryption failure
- List: returns metadata only, never encrypted payload
- Get decrypted: happy path, wiped payload
- Rotate: happy path, not found
- Soft delete: sets timestamps, schedules hard delete
- Restore: within window, past window, wiped payload
- Hard delete purge: wipes payload and deletes row
- Tenant isolation: queries always scoped to tenant_id

Security:
- Verifies encrypted_payload never appears in safe_metadata()
- Verifies __repr__ never includes encrypted_payload
- Verifies list_credentials never returns encrypted payload
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.connector_credential import (
    ConnectorCredential,
    CredentialStatus,
    HARD_DELETE_AFTER_DAYS,
    SOFT_DELETE_RESTORE_WINDOW_DAYS,
)
from src.services.credential_vault import (
    CredentialVault,
    CredentialNotFoundError,
    CredentialNotRestorableError,
    CredentialVaultError,
)


# =============================================================================
# Fixtures
# =============================================================================

TENANT_ID = "tenant-test-001"
OTHER_TENANT_ID = "tenant-other-999"
USER_ID = "clerk_user_abc123"


def _make_credential(**overrides) -> ConnectorCredential:
    """Factory for ConnectorCredential instances."""
    defaults = {
        "id": str(uuid.uuid4()),
        "tenant_id": TENANT_ID,
        "credential_name": "Test Shopify Store",
        "source_type": "shopify",
        "encrypted_payload": "gAAAAABf_encrypted_blob",
        "credential_metadata": {"account_name": "My Store"},
        "status": CredentialStatus.ACTIVE,
        "created_by": USER_ID,
        "soft_deleted_at": None,
        "hard_delete_after": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    cred = ConnectorCredential()
    for key, value in defaults.items():
        setattr(cred, key, value)
    return cred


def _mock_session():
    """Create a mock SQLAlchemy session."""
    session = MagicMock()
    session.execute = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.refresh = MagicMock()
    session.flush = MagicMock()
    session.delete = MagicMock()
    return session


# =============================================================================
# Model Property Tests
# =============================================================================

class TestConnectorCredentialModel:
    """Tests for ConnectorCredential model properties."""

    def test_is_active_when_active_and_not_deleted(self):
        cred = _make_credential(
            status=CredentialStatus.ACTIVE,
            soft_deleted_at=None,
        )
        assert cred.is_active is True

    def test_is_active_false_when_expired(self):
        cred = _make_credential(status=CredentialStatus.EXPIRED)
        assert cred.is_active is False

    def test_is_active_false_when_soft_deleted(self):
        cred = _make_credential(
            status=CredentialStatus.ACTIVE,
            soft_deleted_at=datetime.now(timezone.utc),
        )
        assert cred.is_active is False

    def test_is_soft_deleted(self):
        cred = _make_credential(
            soft_deleted_at=datetime.now(timezone.utc),
        )
        assert cred.is_soft_deleted is True

    def test_is_not_soft_deleted(self):
        cred = _make_credential(soft_deleted_at=None)
        assert cred.is_soft_deleted is False

    def test_is_restorable_within_window(self):
        cred = _make_credential(
            soft_deleted_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        assert cred.is_restorable is True

    def test_is_not_restorable_past_window(self):
        cred = _make_credential(
            soft_deleted_at=datetime.now(timezone.utc)
            - timedelta(days=SOFT_DELETE_RESTORE_WINDOW_DAYS + 1),
        )
        assert cred.is_restorable is False

    def test_is_not_restorable_when_not_deleted(self):
        cred = _make_credential(soft_deleted_at=None)
        assert cred.is_restorable is False

    def test_is_payload_wiped(self):
        cred = _make_credential(encrypted_payload=None)
        assert cred.is_payload_wiped is True

    def test_is_payload_not_wiped(self):
        cred = _make_credential(encrypted_payload="gAAAAABf_encrypted")
        assert cred.is_payload_wiped is False

    def test_safe_metadata_never_includes_encrypted_payload(self):
        """SECURITY: safe_metadata must never leak encrypted_payload."""
        cred = _make_credential(
            encrypted_payload="SUPER_SECRET_ENCRYPTED_DATA",
        )
        meta = cred.safe_metadata()
        assert "encrypted_payload" not in meta
        assert "SUPER_SECRET" not in str(meta)
        assert "id" in meta
        assert "credential_name" in meta
        assert "source_type" in meta
        assert "status" in meta
        assert "metadata" in meta
        assert "is_active" in meta

    def test_repr_never_includes_encrypted_payload(self):
        """SECURITY: __repr__ must never leak encrypted_payload."""
        cred = _make_credential(
            encrypted_payload="SUPER_SECRET_ENCRYPTED_DATA",
        )
        repr_str = repr(cred)
        assert "SUPER_SECRET" not in repr_str
        assert "encrypted_payload" not in repr_str
        assert "ConnectorCredential" in repr_str


# =============================================================================
# CredentialVault.store Tests
# =============================================================================

class TestCredentialVaultStore:
    """Tests for CredentialVault.store()."""

    @pytest.mark.asyncio
    @patch("src.services.credential_vault.encrypt_secret", new_callable=AsyncMock)
    async def test_store_happy_path(self, mock_encrypt):
        """Store should encrypt, persist, and return credential ID."""
        mock_encrypt.return_value = "encrypted_blob"
        session = _mock_session()
        session.refresh = MagicMock(
            side_effect=lambda c: setattr(c, "id", "cred-uuid-123")
        )
        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)

        cred_id = await vault.store(
            credential_name="Prod Shopify",
            source_type="shopify",
            raw_credentials={"api_key": "sk-123", "api_secret": "secret"},
            created_by=USER_ID,
            metadata={"account_name": "My Store"},
        )

        mock_encrypt.assert_called_once()
        call_arg = mock_encrypt.call_args[0][0]
        parsed = json.loads(call_arg)
        assert parsed["api_key"] == "sk-123"

        session.add.assert_called_once()
        session.commit.assert_called_once()
        assert cred_id == "cred-uuid-123"

    @pytest.mark.asyncio
    @patch("src.services.credential_vault.encrypt_secret", new_callable=AsyncMock)
    async def test_store_encryption_failure_raises(self, mock_encrypt):
        """Store should raise CredentialVaultError if encryption fails."""
        mock_encrypt.side_effect = RuntimeError("KMS unavailable")
        session = _mock_session()
        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)

        with pytest.raises(CredentialVaultError, match="Encryption failed"):
            await vault.store(
                credential_name="Fail",
                source_type="meta",
                raw_credentials={"token": "abc"},
                created_by=USER_ID,
            )

        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_empty_credentials_raises(self):
        """Store should reject empty credentials."""
        session = _mock_session()
        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)

        with pytest.raises(ValueError, match="raw_credentials must not be empty"):
            await vault.store(
                credential_name="Empty",
                source_type="shopify",
                raw_credentials={},
                created_by=USER_ID,
            )


# =============================================================================
# CredentialVault.list_credentials Tests
# =============================================================================

class TestCredentialVaultList:
    """Tests for CredentialVault.list_credentials()."""

    def test_list_returns_metadata_only(self):
        """SECURITY: list must return safe_metadata, never encrypted payload."""
        cred = _make_credential(
            encrypted_payload="TOP_SECRET_ENCRYPTED_BLOB",
        )
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [cred]
        session.execute.return_value = mock_result

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)
        results = vault.list_credentials()

        assert len(results) == 1
        assert "encrypted_payload" not in results[0]
        assert "TOP_SECRET" not in str(results[0])
        assert results[0]["source_type"] == "shopify"

    def test_list_empty_tenant(self):
        """List should return empty for tenant with no credentials."""
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)
        results = vault.list_credentials()
        assert results == []


# =============================================================================
# CredentialVault.get_decrypted_payload Tests
# =============================================================================

class TestCredentialVaultDecrypt:
    """Tests for CredentialVault.get_decrypted_payload()."""

    @pytest.mark.asyncio
    @patch("src.services.credential_vault.decrypt_secret", new_callable=AsyncMock)
    async def test_decrypt_happy_path(self, mock_decrypt):
        """Should decrypt and return credential dict."""
        raw = {"api_key": "sk-123", "api_secret": "secret"}
        mock_decrypt.return_value = json.dumps(raw)

        cred = _make_credential()
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)
        result = await vault.get_decrypted_payload("cred-id")

        assert result == raw
        mock_decrypt.assert_called_once_with(cred.encrypted_payload)

    @pytest.mark.asyncio
    async def test_decrypt_wiped_payload_returns_none(self):
        """Should return None for wiped (hard-deleted) payload."""
        cred = _make_credential(encrypted_payload=None)
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)
        result = await vault.get_decrypted_payload("cred-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_decrypt_not_found_returns_none(self):
        """Should return None when credential doesn't exist."""
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)
        result = await vault.get_decrypted_payload("nonexistent")

        assert result is None


# =============================================================================
# CredentialVault.soft_delete Tests
# =============================================================================

class TestCredentialVaultSoftDelete:
    """Tests for CredentialVault.soft_delete()."""

    def test_soft_delete_sets_timestamps(self):
        """Soft delete should set soft_deleted_at and hard_delete_after."""
        cred = _make_credential()
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)
        vault.soft_delete("cred-id", deleted_by=USER_ID)

        assert cred.soft_deleted_at is not None
        assert cred.hard_delete_after is not None
        assert cred.status == CredentialStatus.REVOKED

        expected_hard_delete = cred.soft_deleted_at + timedelta(
            days=HARD_DELETE_AFTER_DAYS
        )
        delta = abs(
            (cred.hard_delete_after - expected_hard_delete).total_seconds()
        )
        assert delta < 1  # Within 1 second tolerance

        session.commit.assert_called_once()

    def test_soft_delete_not_found_raises(self):
        """Soft delete should raise CredentialNotFoundError if not found."""
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)

        with pytest.raises(CredentialNotFoundError):
            vault.soft_delete("nonexistent", deleted_by=USER_ID)


# =============================================================================
# CredentialVault.restore Tests
# =============================================================================

class TestCredentialVaultRestore:
    """Tests for CredentialVault.restore()."""

    def test_restore_within_window(self):
        """Restore should clear soft_deleted_at and set status to ACTIVE."""
        cred = _make_credential(
            soft_deleted_at=datetime.now(timezone.utc) - timedelta(days=1),
            hard_delete_after=datetime.now(timezone.utc) + timedelta(days=19),
            status=CredentialStatus.REVOKED,
        )
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)
        vault.restore("cred-id", restored_by=USER_ID)

        assert cred.soft_deleted_at is None
        assert cred.hard_delete_after is None
        assert cred.status == CredentialStatus.ACTIVE
        session.commit.assert_called_once()

    def test_restore_past_window_raises(self):
        """Restore should raise if past the 5-day restore window."""
        cred = _make_credential(
            soft_deleted_at=datetime.now(timezone.utc)
            - timedelta(days=SOFT_DELETE_RESTORE_WINDOW_DAYS + 1),
            hard_delete_after=datetime.now(timezone.utc) + timedelta(days=14),
            status=CredentialStatus.REVOKED,
        )
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)

        with pytest.raises(CredentialNotRestorableError, match="restore window"):
            vault.restore("cred-id", restored_by=USER_ID)

    def test_restore_wiped_payload_raises(self):
        """Restore should raise if payload has been permanently wiped."""
        cred = _make_credential(
            soft_deleted_at=datetime.now(timezone.utc) - timedelta(days=1),
            hard_delete_after=datetime.now(timezone.utc) + timedelta(days=19),
            encrypted_payload=None,
            status=CredentialStatus.REVOKED,
        )
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)

        with pytest.raises(
            CredentialNotRestorableError, match="permanently wiped"
        ):
            vault.restore("cred-id", restored_by=USER_ID)

    def test_restore_not_found_raises(self):
        """Restore should raise if credential not found."""
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)

        with pytest.raises(CredentialNotFoundError):
            vault.restore("nonexistent", restored_by=USER_ID)


# =============================================================================
# CredentialVault.purge_expired Tests
# =============================================================================

class TestCredentialVaultPurge:
    """Tests for CredentialVault.purge_expired()."""

    def test_purge_wipes_payload_and_deletes_row(self):
        """Hard delete should NULL payload then delete the row."""
        cred = _make_credential(
            soft_deleted_at=datetime.now(timezone.utc) - timedelta(days=21),
            hard_delete_after=datetime.now(timezone.utc) - timedelta(days=1),
            encrypted_payload="MUST_BE_DESTROYED",
            status=CredentialStatus.REVOKED,
        )
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [cred]
        session.execute.return_value = mock_result

        count = CredentialVault.purge_expired(session)

        assert count == 1
        assert cred.encrypted_payload is None
        session.flush.assert_called()
        session.delete.assert_called_once_with(cred)
        session.commit.assert_called_once()

    def test_purge_nothing_to_delete(self):
        """Purge should return 0 when no credentials are past deadline."""
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        count = CredentialVault.purge_expired(session)

        assert count == 0
        session.commit.assert_not_called()

    def test_purge_multiple_credentials(self):
        """Purge should handle multiple expired credentials."""
        now = datetime.now(timezone.utc)
        creds = [
            _make_credential(
                id=f"cred-{i}",
                soft_deleted_at=now - timedelta(days=25),
                hard_delete_after=now - timedelta(days=5),
                encrypted_payload=f"secret-{i}",
                status=CredentialStatus.REVOKED,
            )
            for i in range(3)
        ]
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = creds
        session.execute.return_value = mock_result

        count = CredentialVault.purge_expired(session)

        assert count == 3
        for cred in creds:
            assert cred.encrypted_payload is None
        assert session.delete.call_count == 3
        session.commit.assert_called_once()


# =============================================================================
# CredentialVault.rotate Tests
# =============================================================================

class TestCredentialVaultRotate:
    """Tests for CredentialVault.rotate()."""

    @pytest.mark.asyncio
    @patch("src.services.credential_vault.encrypt_secret", new_callable=AsyncMock)
    async def test_rotate_happy_path(self, mock_encrypt):
        """Rotate should re-encrypt and set status to ACTIVE."""
        mock_encrypt.return_value = "new_encrypted_blob"
        cred = _make_credential(status=CredentialStatus.EXPIRED)
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)
        await vault.rotate(
            credential_id="cred-id",
            new_credentials={"api_key": "new-key"},
            rotated_by=USER_ID,
        )

        assert cred.encrypted_payload == "new_encrypted_blob"
        assert cred.status == CredentialStatus.ACTIVE
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rotate_not_found_raises(self):
        """Rotate should raise if credential not found."""
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)

        with pytest.raises(CredentialNotFoundError):
            await vault.rotate(
                credential_id="nonexistent",
                new_credentials={"key": "val"},
                rotated_by=USER_ID,
            )


# =============================================================================
# CredentialStatus Enum Tests
# =============================================================================

class TestCredentialStatus:
    """Tests for canonical CredentialStatus enum."""

    def test_all_expected_values_exist(self):
        assert CredentialStatus.ACTIVE.value == "active"
        assert CredentialStatus.EXPIRED.value == "expired"
        assert CredentialStatus.REVOKED.value == "revoked"
        assert CredentialStatus.INVALID.value == "invalid"
        assert CredentialStatus.MISSING.value == "missing"

    def test_is_string_enum(self):
        """CredentialStatus should be usable as a string."""
        assert CredentialStatus.ACTIVE == "active"
        assert isinstance(CredentialStatus.ACTIVE, str)
