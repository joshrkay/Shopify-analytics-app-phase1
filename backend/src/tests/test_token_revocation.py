"""
Tests for token refresh and revocation manager.

Covers:
- Proactive refresh: expiring credential detection, refresh execution
- Reactive refresh: on-demand refresh after auth failure
- Revocation: immediate credential invalidation
- Backoff enforcement: retry delays between refresh attempts
- Audit logging: all operations produce audit events
- Status checks: credential validity enforcement
- Edge cases: wiped payload, missing refresh_token, max attempts

Security:
- Tokens are never exposed in test assertions on log output
- All operations are tenant-scoped
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.connector_credential import (
    ConnectorCredential,
    CredentialStatus,
)
from src.services.token_manager import (
    TokenManager,
    TokenRefreshError,
    RefreshResult,
    RefreshOutcome,
    RefreshStats,
    RevocationReason,
    PROACTIVE_REFRESH_HOURS,
    MAX_REFRESH_ATTEMPTS,
    REFRESH_BACKOFF_MINUTES,
)


# =============================================================================
# Fixtures
# =============================================================================

TENANT_ID = "tenant-token-test-001"
OTHER_TENANT_ID = "tenant-other-999"
USER_ID = "clerk_user_token_abc"
CREDENTIAL_ID = "cred-uuid-001"


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


def _make_manager(session=None) -> TokenManager:
    """Create a TokenManager with a mock session."""
    return TokenManager(
        db_session=session or _mock_session(),
        tenant_id=TENANT_ID,
    )


# =============================================================================
# Constructor Tests
# =============================================================================

class TestTokenManagerInit:
    """Tests for TokenManager initialization."""

    def test_requires_tenant_id(self):
        with pytest.raises(ValueError, match="tenant_id is required"):
            TokenManager(db_session=_mock_session(), tenant_id="")

    def test_requires_non_none_tenant_id(self):
        with pytest.raises(ValueError, match="tenant_id is required"):
            TokenManager(db_session=_mock_session(), tenant_id=None)

    def test_stores_session_and_tenant(self):
        session = _mock_session()
        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        assert manager.db is session
        assert manager.tenant_id == TENANT_ID


# =============================================================================
# Revocation Tests
# =============================================================================

class TestRevocation:
    """Tests for immediate credential revocation."""

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_revoke_sets_status_to_revoked(self, mock_audit):
        cred = _make_credential(id=CREDENTIAL_ID, status=CredentialStatus.ACTIVE)
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        result = await manager.revoke_credential(
            credential_id=CREDENTIAL_ID,
            reason=RevocationReason.USER_DISCONNECT,
            revoked_by=USER_ID,
        )

        assert result is True
        assert cred.status == CredentialStatus.REVOKED
        session.flush.assert_called()

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_revoke_records_metadata(self, mock_audit):
        cred = _make_credential(
            id=CREDENTIAL_ID,
            credential_metadata={"account_name": "TestStore"},
        )
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        await manager.revoke_credential(
            credential_id=CREDENTIAL_ID,
            reason=RevocationReason.PROVIDER_REVOKED,
            revoked_by=USER_ID,
        )

        metadata = cred.credential_metadata
        assert "revoked_at" in metadata
        assert metadata["revocation_reason"] == "provider_revoked"
        assert metadata["revoked_by"] == USER_ID

    @pytest.mark.asyncio
    async def test_revoke_not_found_returns_false(self):
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        result = await manager.revoke_credential(
            credential_id="nonexistent",
            reason=RevocationReason.ADMIN_ACTION,
        )

        assert result is False

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_revoke_logs_audit_event(self, mock_audit):
        cred = _make_credential(id=CREDENTIAL_ID)
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        await manager.revoke_credential(
            credential_id=CREDENTIAL_ID,
            reason=RevocationReason.SECURITY_EVENT,
        )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args[1]
        assert call_kwargs["tenant_id"] == TENANT_ID
        assert call_kwargs["resource_type"] == "credential"
        assert call_kwargs["resource_id"] == CREDENTIAL_ID

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_revoke_all_for_connection(self, mock_audit):
        creds = [
            _make_credential(id=f"cred-{i}", source_type="meta")
            for i in range(3)
        ]
        session = _mock_session()

        # First call returns list of credentials, subsequent calls return individual creds
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = creds

        mock_single_results = []
        for c in creds:
            mr = MagicMock()
            mr.scalar_one_or_none.return_value = c
            mock_single_results.append(mr)

        session.execute.side_effect = [mock_list_result] + mock_single_results

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        count = await manager.revoke_all_for_connection(
            source_type="meta",
            reason=RevocationReason.USER_DISCONNECT,
            revoked_by=USER_ID,
        )

        assert count == 3
        for c in creds:
            assert c.status == CredentialStatus.REVOKED

    @pytest.mark.asyncio
    async def test_revoke_all_no_credentials(self):
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        count = await manager.revoke_all_for_connection(
            source_type="shopify",
            reason=RevocationReason.ADMIN_ACTION,
        )

        assert count == 0


# =============================================================================
# Status Check Tests
# =============================================================================

class TestStatusChecks:
    """Tests for credential validity checks."""

    def test_is_valid_active_credential(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        cred = _make_credential(
            id=CREDENTIAL_ID,
            credential_metadata={"token_expires_at": future},
        )
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        assert manager.is_credential_valid(CREDENTIAL_ID) is True

    def test_is_valid_expired_token(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        cred = _make_credential(
            id=CREDENTIAL_ID,
            credential_metadata={"token_expires_at": past},
        )
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        assert manager.is_credential_valid(CREDENTIAL_ID) is False

    def test_is_valid_revoked_credential(self):
        cred = _make_credential(
            id=CREDENTIAL_ID,
            status=CredentialStatus.REVOKED,
        )
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        assert manager.is_credential_valid(CREDENTIAL_ID) is False

    def test_is_valid_not_found(self):
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        assert manager.is_credential_valid("nonexistent") is False

    def test_is_valid_no_expiry_metadata(self):
        """Active credential without token_expires_at is considered valid."""
        cred = _make_credential(
            id=CREDENTIAL_ID,
            credential_metadata={},
        )
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        assert manager.is_credential_valid(CREDENTIAL_ID) is True

    def test_get_credential_status(self):
        now = datetime.now(timezone.utc)
        cred = _make_credential(
            id=CREDENTIAL_ID,
            source_type="meta",
            credential_metadata={
                "token_expires_at": (now + timedelta(days=30)).isoformat(),
                "last_refresh_at": now.isoformat(),
                "refresh_error_count": 1,
            },
        )
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        status = manager.get_credential_status(CREDENTIAL_ID)

        assert status is not None
        assert status["credential_id"] == CREDENTIAL_ID
        assert status["source_type"] == "meta"
        assert status["status"] == "active"
        assert status["is_active"] is True
        assert status["refresh_error_count"] == 1

    def test_get_credential_status_not_found(self):
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        assert manager.get_credential_status("nonexistent") is None


# =============================================================================
# Proactive Refresh Tests
# =============================================================================

class TestProactiveRefresh:
    """Tests for proactive credential refresh (background worker)."""

    @pytest.mark.asyncio
    @patch("src.services.token_manager.encrypt_secret", new_callable=AsyncMock)
    @patch("src.services.token_manager.decrypt_secret", new_callable=AsyncMock)
    async def test_refresh_expiring_credential(self, mock_decrypt, mock_encrypt):
        """Credentials expiring within threshold should be refreshed."""
        expires_soon = (
            datetime.now(timezone.utc) + timedelta(hours=6)
        ).isoformat()
        cred = _make_credential(
            id=CREDENTIAL_ID,
            source_type="shopify",
            credential_metadata={"token_expires_at": expires_soon},
        )

        mock_decrypt.return_value = json.dumps({
            "access_token": "old_token",
            "refresh_token": "refresh_abc",
        })
        mock_encrypt.return_value = "new_encrypted_blob"

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [cred]
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        stats = await manager.refresh_expiring_credentials()

        assert stats.credentials_checked == 1
        # Shopify tokens don't expire, so the refresh returns current tokens
        assert stats.refreshed == 1
        assert stats.failed == 0

    @pytest.mark.asyncio
    async def test_no_expiring_credentials(self):
        """No credentials expiring within threshold should yield empty stats."""
        far_future = (
            datetime.now(timezone.utc) + timedelta(days=60)
        ).isoformat()
        cred = _make_credential(
            credential_metadata={"token_expires_at": far_future},
        )

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [cred]
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        stats = await manager.refresh_expiring_credentials()

        assert stats.credentials_checked == 0
        assert stats.refreshed == 0

    @pytest.mark.asyncio
    async def test_credentials_without_expiry_skipped(self):
        """Credentials without token_expires_at in metadata are skipped."""
        cred = _make_credential(credential_metadata={})

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [cred]
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        stats = await manager.refresh_expiring_credentials()

        assert stats.credentials_checked == 0


# =============================================================================
# Reactive Refresh Tests
# =============================================================================

class TestReactiveRefresh:
    """Tests for reactive refresh after auth failure."""

    @pytest.mark.asyncio
    @patch("src.services.token_manager.encrypt_secret", new_callable=AsyncMock)
    @patch("src.services.token_manager.decrypt_secret", new_callable=AsyncMock)
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_reactive_refresh_success(
        self, mock_audit, mock_decrypt, mock_encrypt
    ):
        cred = _make_credential(
            id=CREDENTIAL_ID,
            source_type="shopify",
            credential_metadata={},
        )
        mock_decrypt.return_value = json.dumps({
            "access_token": "old",
            "refresh_token": "refresh_tok",
        })
        mock_encrypt.return_value = "new_encrypted"

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh(CREDENTIAL_ID)

        assert outcome.result == RefreshResult.SUCCESS
        assert cred.status == CredentialStatus.ACTIVE
        mock_audit.assert_called()

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_reactive_refresh_not_found(self, mock_audit):
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh("nonexistent")

        assert outcome.result == RefreshResult.SKIPPED_REVOKED
        assert "not found" in outcome.error

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_reactive_refresh_revoked_credential(self, mock_audit):
        cred = _make_credential(
            id=CREDENTIAL_ID,
            status=CredentialStatus.REVOKED,
        )
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh(CREDENTIAL_ID)

        assert outcome.result == RefreshResult.SKIPPED_REVOKED

    @pytest.mark.asyncio
    @patch("src.services.token_manager.decrypt_secret", new_callable=AsyncMock)
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_reactive_refresh_no_refresh_token(
        self, mock_audit, mock_decrypt
    ):
        cred = _make_credential(
            id=CREDENTIAL_ID,
            credential_metadata={},
        )
        mock_decrypt.return_value = json.dumps({
            "access_token": "token_only",
        })

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh(CREDENTIAL_ID)

        assert outcome.result == RefreshResult.NO_REFRESH_TOKEN

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_reactive_refresh_wiped_payload(self, mock_audit):
        cred = _make_credential(
            id=CREDENTIAL_ID,
            encrypted_payload=None,
            credential_metadata={},
        )

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh(CREDENTIAL_ID)

        assert outcome.result == RefreshResult.FAILED_PERMANENT
        assert "wiped" in outcome.error.lower()


# =============================================================================
# Max Attempts and Backoff Tests
# =============================================================================

class TestRefreshBackoff:
    """Tests for retry backoff and max attempt enforcement."""

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_max_attempts_marks_expired(self, mock_audit):
        """After MAX_REFRESH_ATTEMPTS failures, credential is marked EXPIRED."""
        cred = _make_credential(
            id=CREDENTIAL_ID,
            credential_metadata={
                "refresh_error_count": MAX_REFRESH_ATTEMPTS,
            },
        )

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh(CREDENTIAL_ID)

        assert outcome.result == RefreshResult.FAILED_PERMANENT
        assert cred.status == CredentialStatus.EXPIRED

    @pytest.mark.asyncio
    @patch("src.services.token_manager.decrypt_secret", new_callable=AsyncMock)
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_backoff_skips_if_too_soon(self, mock_audit, mock_decrypt):
        """Refresh should be skipped if within backoff window."""
        recent = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat()
        cred = _make_credential(
            id=CREDENTIAL_ID,
            credential_metadata={
                "refresh_error_count": 1,
                "last_refresh_attempt_at": recent,
            },
        )

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh(CREDENTIAL_ID)

        assert outcome.result == RefreshResult.SKIPPED_ACTIVE
        assert "Backoff" in outcome.error
        # decrypt_secret should NOT have been called due to backoff
        mock_decrypt.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.services.token_manager.encrypt_secret", new_callable=AsyncMock)
    @patch("src.services.token_manager.decrypt_secret", new_callable=AsyncMock)
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_backoff_allows_after_window(
        self, mock_audit, mock_decrypt, mock_encrypt
    ):
        """Refresh should proceed if backoff window has elapsed."""
        old_attempt = (
            datetime.now(timezone.utc)
            - timedelta(minutes=REFRESH_BACKOFF_MINUTES[0] + 1)
        ).isoformat()
        cred = _make_credential(
            id=CREDENTIAL_ID,
            source_type="shopify",
            credential_metadata={
                "refresh_error_count": 1,
                "last_refresh_attempt_at": old_attempt,
            },
        )
        mock_decrypt.return_value = json.dumps({
            "access_token": "old",
            "refresh_token": "refresh",
        })
        mock_encrypt.return_value = "refreshed_encrypted"

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh(CREDENTIAL_ID)

        assert outcome.result == RefreshResult.SUCCESS
        mock_decrypt.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.services.token_manager.decrypt_secret", new_callable=AsyncMock)
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_refresh_failure_increments_error_count(
        self, mock_audit, mock_decrypt
    ):
        """Failed refresh should increment refresh_error_count in metadata."""
        cred = _make_credential(
            id=CREDENTIAL_ID,
            source_type="meta",
            credential_metadata={"refresh_error_count": 0},
        )
        mock_decrypt.return_value = json.dumps({
            "access_token": "old",
            "refresh_token": "refresh",
        })

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        # Meta refresh raises TokenRefreshError (placeholder)
        outcome = await manager.reactive_refresh(CREDENTIAL_ID)

        assert outcome.result == RefreshResult.FAILED_RETRYABLE
        assert cred.credential_metadata["refresh_error_count"] == 1

    @pytest.mark.asyncio
    @patch("src.services.token_manager.decrypt_secret", new_callable=AsyncMock)
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_permanent_failure_on_unsupported_source(
        self, mock_audit, mock_decrypt
    ):
        """Unsupported source types should return permanent failure."""
        cred = _make_credential(
            id=CREDENTIAL_ID,
            source_type="tiktok",
            credential_metadata={},
        )
        mock_decrypt.return_value = json.dumps({
            "access_token": "tok",
            "refresh_token": "ref",
        })

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh(CREDENTIAL_ID)

        assert outcome.result == RefreshResult.FAILED_PERMANENT
        assert "Unsupported" in outcome.error


# =============================================================================
# Platform Refresh Tests
# =============================================================================

class TestPlatformRefresh:
    """Tests for platform-specific token refresh logic."""

    @pytest.mark.asyncio
    async def test_shopify_returns_current_tokens(self):
        """Shopify offline tokens don't expire, refresh returns as-is."""
        manager = _make_manager()
        tokens = {"access_token": "shpat_abc", "refresh_token": "ref"}
        result = await manager._refresh_shopify(tokens)
        assert result == tokens

    @pytest.mark.asyncio
    async def test_meta_raises_not_yet_implemented(self):
        """Meta refresh raises error (placeholder for Graph API)."""
        manager = _make_manager()
        with pytest.raises(TokenRefreshError):
            await manager._refresh_meta({"refresh_token": "tok"})

    @pytest.mark.asyncio
    async def test_google_raises_not_yet_implemented(self):
        """Google refresh raises error (placeholder for OAuth2)."""
        manager = _make_manager()
        with pytest.raises(TokenRefreshError):
            await manager._refresh_google({"refresh_token": "tok"})


# =============================================================================
# Token Expiry Update Tests
# =============================================================================

class TestTokenExpiryUpdate:
    """Tests for updating token expiry after refresh."""

    @pytest.mark.asyncio
    @patch("src.services.token_manager.encrypt_secret", new_callable=AsyncMock)
    @patch("src.services.token_manager.decrypt_secret", new_callable=AsyncMock)
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_refresh_resets_error_count(
        self, mock_audit, mock_decrypt, mock_encrypt
    ):
        """Successful refresh should reset refresh_error_count to 0."""
        cred = _make_credential(
            id=CREDENTIAL_ID,
            source_type="shopify",
            credential_metadata={"refresh_error_count": 2},
        )
        mock_decrypt.return_value = json.dumps({
            "access_token": "old",
            "refresh_token": "ref",
        })
        mock_encrypt.return_value = "new_enc"

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh(CREDENTIAL_ID)

        assert outcome.result == RefreshResult.SUCCESS
        assert cred.credential_metadata["refresh_error_count"] == 0
        assert "last_refresh_at" in cred.credential_metadata

    @pytest.mark.asyncio
    @patch("src.services.token_manager.encrypt_secret", new_callable=AsyncMock)
    @patch("src.services.token_manager.decrypt_secret", new_callable=AsyncMock)
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_refresh_clears_last_error(
        self, mock_audit, mock_decrypt, mock_encrypt
    ):
        """Successful refresh should remove last_refresh_error from metadata."""
        cred = _make_credential(
            id=CREDENTIAL_ID,
            source_type="shopify",
            credential_metadata={
                "refresh_error_count": 1,
                "last_refresh_error": "Previous failure",
            },
        )
        mock_decrypt.return_value = json.dumps({
            "access_token": "old",
            "refresh_token": "ref",
        })
        mock_encrypt.return_value = "new_enc"

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh(CREDENTIAL_ID)

        assert outcome.result == RefreshResult.SUCCESS
        assert "last_refresh_error" not in cred.credential_metadata


# =============================================================================
# RefreshStats Tests
# =============================================================================

class TestRefreshStats:
    """Tests for RefreshStats dataclass."""

    def test_to_dict(self):
        stats = RefreshStats(
            credentials_checked=10,
            refreshed=5,
            failed=2,
            skipped=3,
            expired_marked=1,
            errors=["err1", "err2"],
        )
        d = stats.to_dict()
        assert d["credentials_checked"] == 10
        assert d["refreshed"] == 5
        assert d["failed"] == 2
        assert d["skipped"] == 3
        assert d["expired_marked"] == 1
        assert d["error_count"] == 2

    def test_default_stats(self):
        stats = RefreshStats()
        assert stats.credentials_checked == 0
        assert stats.refreshed == 0
        assert stats.errors == []


# =============================================================================
# RefreshOutcome Tests
# =============================================================================

class TestRefreshOutcome:
    """Tests for RefreshOutcome dataclass."""

    def test_success_outcome(self):
        now = datetime.now(timezone.utc)
        outcome = RefreshOutcome(
            credential_id="cred-1",
            source_type="shopify",
            result=RefreshResult.SUCCESS,
            new_expires_at=now,
        )
        assert outcome.result == RefreshResult.SUCCESS
        assert outcome.error is None
        assert outcome.new_expires_at == now

    def test_failure_outcome(self):
        outcome = RefreshOutcome(
            credential_id="cred-1",
            source_type="meta",
            result=RefreshResult.FAILED_RETRYABLE,
            error="Network timeout",
            attempt_number=2,
        )
        assert outcome.result == RefreshResult.FAILED_RETRYABLE
        assert outcome.attempt_number == 2


# =============================================================================
# RevocationReason Tests
# =============================================================================

class TestRevocationReason:
    """Tests for RevocationReason enum values."""

    def test_all_reasons_exist(self):
        assert RevocationReason.USER_DISCONNECT.value == "user_disconnect"
        assert RevocationReason.PROVIDER_REVOKED.value == "provider_revoked"
        assert RevocationReason.ADMIN_ACTION.value == "admin_action"
        assert RevocationReason.SECURITY_EVENT.value == "security_event"
        assert RevocationReason.AUTH_FAILURE_EXHAUSTED.value == "auth_failure_exhausted"

    def test_is_string_enum(self):
        assert isinstance(RevocationReason.USER_DISCONNECT, str)


# =============================================================================
# TokenRefreshError Tests
# =============================================================================

class TestTokenRefreshError:
    """Tests for TokenRefreshError exception."""

    def test_permanent_flag(self):
        err = TokenRefreshError("Token revoked by provider", permanent=True)
        assert err.permanent is True
        assert str(err) == "Token revoked by provider"

    def test_retryable_flag(self):
        err = TokenRefreshError("Network timeout", permanent=False)
        assert err.permanent is False

    def test_default_not_permanent(self):
        err = TokenRefreshError("Some error")
        assert err.permanent is False


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestEdgeCases:
    """Edge case and security tests."""

    @pytest.mark.asyncio
    @patch("src.services.token_manager.decrypt_secret", new_callable=AsyncMock)
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_decrypt_failure_returns_permanent(
        self, mock_audit, mock_decrypt
    ):
        """Decryption failure should return permanent failure."""
        mock_decrypt.side_effect = RuntimeError("Bad ciphertext")
        cred = _make_credential(
            id=CREDENTIAL_ID,
            credential_metadata={},
        )

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh(CREDENTIAL_ID)

        assert outcome.result == RefreshResult.FAILED_PERMANENT
        assert "Decryption failed" in outcome.error

    @pytest.mark.asyncio
    @patch("src.services.token_manager.encrypt_secret", new_callable=AsyncMock)
    @patch("src.services.token_manager.decrypt_secret", new_callable=AsyncMock)
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_encrypt_failure_returns_retryable(
        self, mock_audit, mock_decrypt, mock_encrypt
    ):
        """Encryption failure after refresh should return retryable failure."""
        mock_decrypt.return_value = json.dumps({
            "access_token": "old",
            "refresh_token": "ref",
        })
        mock_encrypt.side_effect = RuntimeError("Encryption service down")

        cred = _make_credential(
            id=CREDENTIAL_ID,
            source_type="shopify",
            credential_metadata={},
        )

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh(CREDENTIAL_ID)

        assert outcome.result == RefreshResult.FAILED_RETRYABLE
        assert "Encryption" in outcome.error

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_revoke_already_revoked_credential(self, mock_audit):
        """Revoking an already-revoked credential should still succeed."""
        cred = _make_credential(
            id=CREDENTIAL_ID,
            status=CredentialStatus.REVOKED,
        )
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        result = await manager.revoke_credential(
            credential_id=CREDENTIAL_ID,
            reason=RevocationReason.ADMIN_ACTION,
        )

        assert result is True
        assert cred.status == CredentialStatus.REVOKED

    def test_invalid_expires_at_metadata_treated_as_valid(self):
        """Invalid token_expires_at format should not crash validity check."""
        cred = _make_credential(
            id=CREDENTIAL_ID,
            credential_metadata={"token_expires_at": "not-a-date"},
        )
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        # Should not raise, treats invalid date as no expiry
        assert manager.is_credential_valid(CREDENTIAL_ID) is True

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_audit_failure_does_not_crash_revocation(self, mock_audit):
        """Audit log failure should not prevent revocation from succeeding."""
        mock_audit.side_effect = RuntimeError("DB connection lost")
        cred = _make_credential(id=CREDENTIAL_ID)

        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        session.execute.return_value = mock_result

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        result = await manager.revoke_credential(
            credential_id=CREDENTIAL_ID,
            reason=RevocationReason.SECURITY_EVENT,
        )

        # Revocation should succeed even if audit logging fails
        assert result is True
        assert cred.status == CredentialStatus.REVOKED
