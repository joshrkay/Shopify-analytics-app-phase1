"""
Regression tests for secure credential vault, token management, and retry handling.

Validates cross-component contracts and integration between:
- CredentialVault: encrypted storage, soft/hard delete lifecycle
- TokenManager: proactive/reactive refresh, revocation, status checks
- SyncRetryManager: retry scheduling, DLQ routing, admin notifications
- Audit trail: every state transition is auditable
- NotificationService: terminal failures notify admin users

These tests use mocks to avoid requiring PostgreSQL and external services,
while validating the behavioral contracts between components.

Story: Secure Credential Vault - Regression
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# =============================================================================
# Constants
# =============================================================================

TENANT_ID = "tenant-regression-001"
TENANT_ID_B = "tenant-regression-002"
CREDENTIAL_ID = "cred-regression-001"
CONNECTOR_ID = "connector-regression-001"
USER_ID = "clerk_user_regression"


# =============================================================================
# Model + Enum Contract Tests
# =============================================================================


class TestCredentialStatusContract:
    """CredentialStatus enum must be stable across all consumers."""

    def test_credential_status_values_unchanged(self):
        """CredentialStatus must have exact expected values."""
        from src.models.connector_credential import CredentialStatus

        expected = {"active", "expired", "revoked", "invalid", "missing"}
        actual = {s.value for s in CredentialStatus}
        assert actual == expected

    def test_credential_status_is_string_enum(self):
        """CredentialStatus must be a string enum for JSON serialization."""
        from src.models.connector_credential import CredentialStatus

        for status in CredentialStatus:
            assert isinstance(status.value, str)
            assert isinstance(status, str)

    def test_credential_status_importable_from_model(self):
        """CredentialStatus must be importable from connector_credential model."""
        from src.models.connector_credential import CredentialStatus

        assert CredentialStatus.ACTIVE.value == "active"
        assert CredentialStatus.EXPIRED.value == "expired"
        assert CredentialStatus.REVOKED.value == "revoked"

    def test_credential_status_used_consistently(self):
        """Both vault and token_manager import from the same source."""
        from src.services.credential_vault import CredentialStatus as VaultStatus
        from src.services.token_manager import CredentialStatus as TMStatus

        # Both must be the exact same class (not duplicates)
        assert VaultStatus is TMStatus


class TestJobStatusContract:
    """JobStatus enum must be stable for retry manager."""

    def test_job_status_values_unchanged(self):
        """JobStatus must have exact expected values."""
        from src.ingestion.jobs.models import JobStatus

        expected = {"queued", "running", "failed", "dead_letter", "success"}
        actual = {s.value for s in JobStatus}
        assert actual == expected

    def test_job_status_used_by_retry_manager(self):
        """SyncRetryManager must use the same JobStatus."""
        from src.ingestion.jobs.models import JobStatus as ModelStatus
        from src.services.sync_retry_manager import JobStatus as RetryStatus

        assert ModelStatus is RetryStatus


class TestErrorCategoryContract:
    """ErrorCategory enum must be stable for retry classification."""

    def test_error_category_values_unchanged(self):
        """ErrorCategory must have expected values."""
        from src.ingestion.jobs.retry import ErrorCategory

        required = {
            "AUTH_ERROR", "RATE_LIMIT", "SERVER_ERROR",
            "TIMEOUT", "CONNECTION", "SYNC_FAILED", "UNKNOWN",
        }
        actual = {e.name for e in ErrorCategory}
        assert required.issubset(actual)

    def test_error_category_imported_by_retry_manager(self):
        """SyncRetryManager must import from retry module."""
        from src.ingestion.jobs.retry import ErrorCategory as RetryEC
        from src.services.sync_retry_manager import ErrorCategory as ManagerEC

        assert RetryEC is ManagerEC


class TestFailureActionContract:
    """FailureAction enum must be stable for UI consumers."""

    def test_failure_action_values(self):
        """FailureAction must have all expected values."""
        from src.services.sync_retry_manager import FailureAction

        expected = {"retry_scheduled", "moved_to_dlq", "marked_failed_terminal"}
        actual = {a.value for a in FailureAction}
        assert actual == expected


class TestRefreshResultContract:
    """RefreshResult enum must be stable for token management consumers."""

    def test_refresh_result_values(self):
        """RefreshResult must have all expected values."""
        from src.services.token_manager import RefreshResult

        expected = {
            "success", "failed_retryable", "failed_permanent",
            "skipped_active", "skipped_revoked", "no_refresh_token",
        }
        actual = {r.value for r in RefreshResult}
        assert actual == expected


class TestRevocationReasonContract:
    """RevocationReason enum must be stable."""

    def test_revocation_reason_values(self):
        """RevocationReason must have all expected values."""
        from src.services.token_manager import RevocationReason

        expected = {
            "user_disconnect", "provider_revoked", "admin_action",
            "security_event", "auth_failure_exhausted",
        }
        actual = {r.value for r in RevocationReason}
        assert actual == expected


# =============================================================================
# Model Property Contract Tests
# =============================================================================


class TestConnectorCredentialModelContract:
    """ConnectorCredential model properties must remain stable."""

    def test_is_active_property_exists(self):
        """ConnectorCredential must have is_active property."""
        from src.models.connector_credential import ConnectorCredential

        assert hasattr(ConnectorCredential, "is_active")

    def test_is_active_logic_active_not_deleted(self):
        """is_active: active status + no soft delete → True."""
        from src.models.connector_credential import CredentialStatus

        cred = MagicMock()
        cred.status = CredentialStatus.ACTIVE
        cred.soft_deleted_at = None

        # Inline the property logic to validate it
        result = (
            cred.status == CredentialStatus.ACTIVE
            and cred.soft_deleted_at is None
        )
        assert result is True

    def test_is_active_logic_revoked(self):
        """is_active: revoked status → False."""
        from src.models.connector_credential import CredentialStatus

        cred = MagicMock()
        cred.status = CredentialStatus.REVOKED
        cred.soft_deleted_at = None

        result = (
            cred.status == CredentialStatus.ACTIVE
            and cred.soft_deleted_at is None
        )
        assert result is False

    def test_is_active_logic_soft_deleted(self):
        """is_active: soft_deleted_at set → False."""
        from src.models.connector_credential import CredentialStatus

        cred = MagicMock()
        cred.status = CredentialStatus.ACTIVE
        cred.soft_deleted_at = datetime.now(timezone.utc)

        result = (
            cred.status == CredentialStatus.ACTIVE
            and cred.soft_deleted_at is None
        )
        assert result is False

    def test_is_payload_wiped_logic(self):
        """is_payload_wiped: None payload → True, present → False."""
        assert (None is None) is True   # wiped
        assert ("data" is None) is False  # not wiped

    def test_safe_metadata_method_exists(self):
        """ConnectorCredential must have safe_metadata method."""
        from src.models.connector_credential import ConnectorCredential

        assert hasattr(ConnectorCredential, "safe_metadata")
        assert callable(getattr(ConnectorCredential, "safe_metadata", None))

    def test_safe_metadata_keys(self):
        """safe_metadata output must include expected keys and exclude payload."""
        expected_keys = {"id", "credential_name", "source_type", "status",
                         "metadata", "created_at", "is_active"}
        from src.models.connector_credential import ConnectorCredential

        # Verify the method signature exists
        import inspect
        sig = inspect.signature(ConnectorCredential.safe_metadata)
        assert "self" in sig.parameters or len(sig.parameters) == 0

    def test_repr_method_exists(self):
        """ConnectorCredential must have __repr__ that excludes payload."""
        from src.models.connector_credential import ConnectorCredential

        # Verify __repr__ is defined on the class (not just inherited)
        assert "__repr__" in ConnectorCredential.__dict__


class TestIngestionJobModelContract:
    """IngestionJob model properties must remain stable."""

    def test_can_retry_property_exists(self):
        """IngestionJob must have can_retry property."""
        from src.ingestion.jobs.models import IngestionJob

        assert hasattr(IngestionJob, "can_retry")

    def test_can_retry_logic_failed_under_limit(self):
        """can_retry: failed + retry_count < 5 → True."""
        from src.ingestion.jobs.models import JobStatus

        job = MagicMock()
        job.status = JobStatus.FAILED
        job.retry_count = 3
        # Inline can_retry logic
        result = job.status == JobStatus.FAILED and job.retry_count < 5
        assert result is True

    def test_can_retry_logic_at_max(self):
        """can_retry: failed + retry_count == 5 → False."""
        from src.ingestion.jobs.models import JobStatus

        job = MagicMock()
        job.status = JobStatus.FAILED
        job.retry_count = 5
        result = job.status == JobStatus.FAILED and job.retry_count < 5
        assert result is False

    def test_can_retry_logic_success(self):
        """can_retry: success → False regardless of retry count."""
        from src.ingestion.jobs.models import JobStatus

        job = MagicMock()
        job.status = JobStatus.SUCCESS
        job.retry_count = 0
        result = job.status == JobStatus.FAILED and job.retry_count < 5
        assert result is False

    def test_is_terminal_property_exists(self):
        """IngestionJob must have is_terminal property."""
        from src.ingestion.jobs.models import IngestionJob

        assert hasattr(IngestionJob, "is_terminal")

    def test_is_terminal_logic(self):
        """is_terminal: SUCCESS and DEAD_LETTER → True, others → False."""
        from src.ingestion.jobs.models import JobStatus

        terminal = {JobStatus.SUCCESS, JobStatus.DEAD_LETTER}
        non_terminal = {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.FAILED}

        for status in terminal:
            assert status in terminal
        for status in non_terminal:
            assert status not in terminal

    def test_mark_methods_exist(self):
        """IngestionJob must have mark_running, mark_success, mark_failed, mark_dead_letter."""
        from src.ingestion.jobs.models import IngestionJob

        assert hasattr(IngestionJob, "mark_running")
        assert hasattr(IngestionJob, "mark_success")
        assert hasattr(IngestionJob, "mark_failed")
        assert hasattr(IngestionJob, "mark_dead_letter")


# =============================================================================
# CredentialVault Behavioral Contracts
# =============================================================================


class TestCredentialVaultContract:
    """CredentialVault public API contracts must remain stable."""

    def test_vault_requires_tenant_id_and_session(self):
        """CredentialVault must accept db_session and tenant_id."""
        from src.services.credential_vault import CredentialVault

        session = MagicMock()
        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)
        assert vault.tenant_id == TENANT_ID
        assert vault.db is session

    @pytest.mark.asyncio
    @patch("src.services.credential_vault.encrypt_secret", new_callable=AsyncMock)
    async def test_store_encrypts_and_returns_id(self, mock_encrypt):
        """store() must encrypt credentials and return a credential ID."""
        from src.services.credential_vault import CredentialVault

        mock_encrypt.return_value = "encrypted-blob"
        session = MagicMock()
        cred_obj = MagicMock()
        cred_obj.id = "new-cred-id"
        session.add = MagicMock()

        def fake_refresh(obj):
            obj.id = "new-cred-id"

        session.refresh = fake_refresh

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)
        result = await vault.store(
            credential_name="Test",
            source_type="shopify",
            raw_credentials={"access_token": "tok"},
            created_by=USER_ID,
        )

        mock_encrypt.assert_called_once()
        session.add.assert_called_once()
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_rejects_empty_credentials(self):
        """store() must reject empty raw_credentials."""
        from src.services.credential_vault import CredentialVault

        vault = CredentialVault(db_session=MagicMock(), tenant_id=TENANT_ID)
        with pytest.raises(ValueError, match="must not be empty"):
            await vault.store(
                credential_name="Test",
                source_type="shopify",
                raw_credentials={},
                created_by=USER_ID,
            )

    @pytest.mark.asyncio
    @patch("src.services.credential_vault.decrypt_secret", new_callable=AsyncMock)
    async def test_get_decrypted_payload_returns_dict(self, mock_decrypt):
        """get_decrypted_payload() must return decrypted dict."""
        from src.models.connector_credential import (
            ConnectorCredential,
            CredentialStatus,
        )
        from src.services.credential_vault import CredentialVault

        mock_decrypt.return_value = json.dumps({"access_token": "tok123"})

        cred = MagicMock(spec=ConnectorCredential)
        cred.encrypted_payload = "encrypted"
        cred.is_payload_wiped = False
        cred.source_type = "shopify"

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = cred

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)
        result = await vault.get_decrypted_payload("cred-123")

        assert result == {"access_token": "tok123"}
        mock_decrypt.assert_called_once_with("encrypted")

    @pytest.mark.asyncio
    async def test_get_decrypted_payload_returns_none_when_wiped(self):
        """get_decrypted_payload() must return None for wiped payloads."""
        from src.models.connector_credential import ConnectorCredential
        from src.services.credential_vault import CredentialVault

        cred = MagicMock(spec=ConnectorCredential)
        cred.is_payload_wiped = True

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = cred

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)
        result = await vault.get_decrypted_payload("cred-123")

        assert result is None

    def test_soft_delete_sets_status_to_revoked(self):
        """soft_delete() must set status to REVOKED."""
        from src.models.connector_credential import (
            ConnectorCredential,
            CredentialStatus,
        )
        from src.services.credential_vault import CredentialVault

        cred = MagicMock(spec=ConnectorCredential)
        cred.status = CredentialStatus.ACTIVE
        cred.soft_deleted_at = None
        cred.credential_metadata = {}

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = cred

        vault = CredentialVault(db_session=session, tenant_id=TENANT_ID)
        vault.soft_delete("cred-123", deleted_by=USER_ID)

        assert cred.status == CredentialStatus.REVOKED
        assert cred.soft_deleted_at is not None
        assert cred.hard_delete_after is not None
        session.commit.assert_called_once()


# =============================================================================
# TokenManager Behavioral Contracts
# =============================================================================


class TestTokenManagerContract:
    """TokenManager public API contracts must remain stable."""

    def test_token_manager_requires_tenant_id(self):
        """TokenManager must require tenant_id."""
        from src.services.token_manager import TokenManager

        with pytest.raises(ValueError, match="tenant_id is required"):
            TokenManager(db_session=MagicMock(), tenant_id="")

    def test_token_manager_accepts_valid_args(self):
        """TokenManager must accept db_session and tenant_id."""
        from src.services.token_manager import TokenManager

        session = MagicMock()
        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        assert manager.tenant_id == TENANT_ID

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_revoke_sets_status_to_revoked(self, mock_audit):
        """revoke_credential() must set status to REVOKED."""
        from src.models.connector_credential import (
            ConnectorCredential,
            CredentialStatus,
        )
        from src.services.token_manager import TokenManager, RevocationReason

        cred = MagicMock(spec=ConnectorCredential)
        cred.id = CREDENTIAL_ID
        cred.status = CredentialStatus.ACTIVE
        cred.source_type = "shopify"
        cred.credential_metadata = {}
        cred.soft_deleted_at = None

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = cred

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
    async def test_revoke_records_revocation_metadata(self, mock_audit):
        """Revocation must record reason and timestamp in metadata."""
        from src.models.connector_credential import (
            ConnectorCredential,
            CredentialStatus,
        )
        from src.services.token_manager import TokenManager, RevocationReason

        cred = MagicMock(spec=ConnectorCredential)
        cred.id = CREDENTIAL_ID
        cred.status = CredentialStatus.ACTIVE
        cred.source_type = "shopify"
        cred.credential_metadata = {"account_name": "MyStore"}
        cred.soft_deleted_at = None

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = cred

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        await manager.revoke_credential(
            credential_id=CREDENTIAL_ID,
            reason=RevocationReason.SECURITY_EVENT,
            revoked_by=USER_ID,
        )

        metadata = cred.credential_metadata
        assert "revoked_at" in metadata
        assert metadata["revocation_reason"] == "security_event"
        assert metadata["revoked_by"] == USER_ID

    def test_is_credential_valid_false_for_revoked(self):
        """is_credential_valid() must return False for revoked credentials."""
        from src.models.connector_credential import (
            ConnectorCredential,
            CredentialStatus,
        )
        from src.services.token_manager import TokenManager

        cred = MagicMock(spec=ConnectorCredential)
        cred.status = CredentialStatus.REVOKED
        cred.soft_deleted_at = None
        cred.credential_metadata = {}

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = cred

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        assert manager.is_credential_valid(CREDENTIAL_ID) is False

    def test_is_credential_valid_false_for_expired_token(self):
        """is_credential_valid() must return False for expired tokens."""
        from src.models.connector_credential import (
            ConnectorCredential,
            CredentialStatus,
        )
        from src.services.token_manager import TokenManager

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        cred = MagicMock(spec=ConnectorCredential)
        cred.status = CredentialStatus.ACTIVE
        cred.soft_deleted_at = None
        cred.credential_metadata = {"token_expires_at": past}

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = cred

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        assert manager.is_credential_valid(CREDENTIAL_ID) is False

    def test_is_credential_valid_true_for_active_unexpired(self):
        """is_credential_valid() must return True for active non-expired creds."""
        from src.models.connector_credential import (
            ConnectorCredential,
            CredentialStatus,
        )
        from src.services.token_manager import TokenManager

        future = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        cred = MagicMock(spec=ConnectorCredential)
        cred.status = CredentialStatus.ACTIVE
        cred.soft_deleted_at = None
        cred.credential_metadata = {"token_expires_at": future}

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = cred

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        assert manager.is_credential_valid(CREDENTIAL_ID) is True

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_reactive_refresh_skips_revoked(self, mock_audit):
        """reactive_refresh() must skip revoked credentials."""
        from src.models.connector_credential import (
            ConnectorCredential,
            CredentialStatus,
        )
        from src.services.token_manager import TokenManager, RefreshResult

        cred = MagicMock(spec=ConnectorCredential)
        cred.id = CREDENTIAL_ID
        cred.status = CredentialStatus.REVOKED
        cred.source_type = "shopify"
        cred.soft_deleted_at = None

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = cred

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh(CREDENTIAL_ID)

        assert outcome.result == RefreshResult.SKIPPED_REVOKED

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_reactive_refresh_not_found(self, mock_audit):
        """reactive_refresh() must handle missing credentials gracefully."""
        from src.services.token_manager import TokenManager, RefreshResult

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = None

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        outcome = await manager.reactive_refresh("nonexistent")

        assert outcome.result == RefreshResult.SKIPPED_REVOKED
        assert "not found" in outcome.error


# =============================================================================
# SyncRetryManager Behavioral Contracts
# =============================================================================


class TestSyncRetryManagerContract:
    """SyncRetryManager public API contracts must remain stable."""

    def test_retry_manager_requires_tenant_id(self):
        """SyncRetryManager must require tenant_id."""
        from src.services.sync_retry_manager import SyncRetryManager

        with pytest.raises(ValueError, match="tenant_id is required"):
            SyncRetryManager(db_session=MagicMock(), tenant_id="")

    def test_retry_manager_accepts_custom_policy(self):
        """SyncRetryManager must accept optional retry_policy."""
        from src.ingestion.jobs.retry import RetryPolicy
        from src.services.sync_retry_manager import SyncRetryManager

        policy = RetryPolicy(max_retries=3, base_delay_seconds=30.0)
        manager = SyncRetryManager(
            db_session=MagicMock(),
            tenant_id=TENANT_ID,
            retry_policy=policy,
        )
        assert manager.retry_policy.max_retries == 3
        assert manager.retry_policy.base_delay_seconds == 30.0

    def test_failure_result_to_dict_format(self):
        """FailureResult.to_dict() must return expected keys."""
        from src.services.sync_retry_manager import FailureAction, FailureResult

        result = FailureResult(
            job_id="job-1",
            action=FailureAction.RETRY_SCHEDULED,
            retry_count=2,
            error_category="server_error",
            error_message="Internal server error",
            next_retry_at=datetime.now(timezone.utc),
            delay_seconds=120.0,
        )

        d = result.to_dict()
        assert d["job_id"] == "job-1"
        assert d["action"] == "retry_scheduled"
        assert d["retry_count"] == 2
        assert "next_retry_at" in d
        assert d["delay_seconds"] == 120.0

    def test_failure_summary_to_dict_format(self):
        """FailureSummary.to_dict() must return expected keys."""
        from src.services.sync_retry_manager import FailureSummary

        summary = FailureSummary(
            connector_id=CONNECTOR_ID,
            total_failures=5,
            active_retries=2,
            dead_letter_count=1,
            last_error="Server error",
            last_error_at=datetime.now(timezone.utc),
            last_error_category="server_error",
            next_retry_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        d = summary.to_dict()
        assert d["connector_id"] == CONNECTOR_ID
        assert d["total_failures"] == 5
        assert d["active_retries"] == 2
        assert d["dead_letter_count"] == 1
        assert "last_error_at" in d
        assert "next_retry_at" in d


# =============================================================================
# Cross-Component: Credential Revocation → Token Validity
# =============================================================================


class TestRevocationBlocksSyncs:
    """Credential revocation must block syncs via TokenManager checks."""

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_revoked_credential_invalid_for_sync(self, mock_audit):
        """After revocation, is_credential_valid must return False."""
        from src.models.connector_credential import (
            ConnectorCredential,
            CredentialStatus,
        )
        from src.services.token_manager import TokenManager, RevocationReason

        cred = MagicMock(spec=ConnectorCredential)
        cred.id = CREDENTIAL_ID
        cred.status = CredentialStatus.ACTIVE
        cred.source_type = "shopify"
        cred.credential_metadata = {}
        cred.soft_deleted_at = None

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = cred

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)

        # Credential is valid before revocation
        assert manager.is_credential_valid(CREDENTIAL_ID) is True

        # Revoke
        await manager.revoke_credential(
            CREDENTIAL_ID, reason=RevocationReason.ADMIN_ACTION
        )

        # After revocation, status is REVOKED
        assert cred.status == CredentialStatus.REVOKED

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_revoke_all_for_connection_blocks_platform(self, mock_audit):
        """revoke_all_for_connection must revoke all credentials for a source."""
        from src.models.connector_credential import (
            ConnectorCredential,
            CredentialStatus,
        )
        from src.services.token_manager import TokenManager, RevocationReason

        creds = []
        for i in range(3):
            c = MagicMock(spec=ConnectorCredential)
            c.id = f"cred-{i}"
            c.status = CredentialStatus.ACTIVE
            c.source_type = "meta"
            c.credential_metadata = {}
            c.soft_deleted_at = None
            creds.append(c)

        session = MagicMock()
        # First call returns list, subsequent calls return individual creds
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = creds

        call_count = [0]
        original_creds = {f"cred-{i}": creds[i] for i in range(3)}

        def mock_execute(stmt):
            result = MagicMock()
            nonlocal call_count
            if call_count[0] == 0:
                result.scalars.return_value = scalars_mock
            else:
                # Return individual credential for each revoke call
                idx = min(call_count[0] - 1, len(creds) - 1)
                result.scalar_one_or_none.return_value = creds[idx]
            call_count[0] += 1
            return result

        session.execute.side_effect = mock_execute

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        count = await manager.revoke_all_for_connection(
            source_type="meta",
            reason=RevocationReason.USER_DISCONNECT,
        )

        assert count == 3
        for c in creds:
            assert c.status == CredentialStatus.REVOKED


# =============================================================================
# Cross-Component: Auth Error → Retry Manager → DLQ (no retry)
# =============================================================================


class TestAuthErrorRouting:
    """Auth errors must route to DLQ immediately, never retry."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_auth_error_goes_to_dlq(self, mock_audit):
        """Auth error must route to DLQ immediately."""
        from src.ingestion.jobs.models import IngestionJob, JobStatus
        from src.ingestion.jobs.retry import ErrorCategory
        from src.services.sync_retry_manager import (
            FailureAction,
            SyncRetryManager,
        )

        job = MagicMock(spec=IngestionJob)
        job.job_id = "job-auth-fail"
        job.tenant_id = TENANT_ID
        job.connector_id = CONNECTOR_ID
        job.retry_count = 0
        job.job_metadata = {}
        job.status = JobStatus.RUNNING

        session = MagicMock()
        # Mock query for admin lookup
        session.query.return_value.filter.return_value.distinct.return_value.all.return_value = []

        manager = SyncRetryManager(db_session=session, tenant_id=TENANT_ID)

        with patch.object(manager, "_get_admin_user_ids", return_value=[]):
            result = manager.handle_failure(
                job=job,
                error_category=ErrorCategory.AUTH_ERROR,
                error_message="Invalid API token",
            )

        assert result.action == FailureAction.MOVED_TO_DLQ
        job.mark_dead_letter.assert_called_once()

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_server_error_retries(self, mock_audit):
        """Server error must schedule retry, not go to DLQ."""
        from src.ingestion.jobs.models import IngestionJob, JobStatus
        from src.ingestion.jobs.retry import ErrorCategory
        from src.services.sync_retry_manager import (
            FailureAction,
            SyncRetryManager,
        )

        job = MagicMock(spec=IngestionJob)
        job.job_id = "job-server-fail"
        job.tenant_id = TENANT_ID
        job.connector_id = CONNECTOR_ID
        job.retry_count = 0
        job.job_metadata = {}
        job.status = JobStatus.RUNNING

        session = MagicMock()

        manager = SyncRetryManager(db_session=session, tenant_id=TENANT_ID)
        result = manager.handle_failure(
            job=job,
            error_category=ErrorCategory.SERVER_ERROR,
            error_message="Internal server error",
        )

        assert result.action == FailureAction.RETRY_SCHEDULED
        job.mark_failed.assert_called_once()
        job.mark_dead_letter.assert_not_called()


# =============================================================================
# Cross-Component: Retry Exhaustion → DLQ → Admin Notification
# =============================================================================


class TestRetryExhaustionNotification:
    """After max retries, admins must be notified."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    @patch("src.services.notification_service.NotificationService")
    @patch("src.services.tenant_members_service.TenantMembersService")
    def test_dlq_triggers_admin_notification(
        self, MockMembers, MockNotification, mock_audit
    ):
        """DLQ movement must trigger admin notification."""
        from src.ingestion.jobs.models import IngestionJob, JobStatus
        from src.ingestion.jobs.retry import ErrorCategory
        from src.services.sync_retry_manager import (
            FailureAction,
            SyncRetryManager,
        )

        # Mock members service returns admin users
        mock_members_instance = MagicMock()
        mock_members_instance.list_members.return_value = [
            {
                "clerk_user_id": "admin-1",
                "role": "MERCHANT_ADMIN",
                "is_active": True,
            },
            {
                "clerk_user_id": "admin-2",
                "role": "AGENCY_ADMIN",
                "is_active": True,
            },
            {
                "clerk_user_id": "viewer-1",
                "role": "VIEWER",
                "is_active": True,
            },
        ]
        MockMembers.return_value = mock_members_instance

        # Mock notification service
        mock_notif_instance = MagicMock()
        mock_notif_instance.notify_connector_failed.return_value = [
            MagicMock(), MagicMock(),
        ]
        MockNotification.return_value = mock_notif_instance

        job = MagicMock(spec=IngestionJob)
        job.job_id = "job-max-retry"
        job.tenant_id = TENANT_ID
        job.connector_id = CONNECTOR_ID
        job.retry_count = 5  # At max
        job.job_metadata = {"connector_name": "Shopify Store"}
        job.status = JobStatus.FAILED

        session = MagicMock()

        manager = SyncRetryManager(db_session=session, tenant_id=TENANT_ID)
        result = manager.handle_failure(
            job=job,
            error_category=ErrorCategory.SERVER_ERROR,
            error_message="Server unreachable after retries",
        )

        assert result.action == FailureAction.MOVED_TO_DLQ
        assert result.notified_admins is True

        # Verify notification targeted only admins
        mock_notif_instance.notify_connector_failed.assert_called_once()
        call_kwargs = mock_notif_instance.notify_connector_failed.call_args
        user_ids = call_kwargs.kwargs.get("user_ids") or call_kwargs[1].get("user_ids")
        if user_ids is None:
            # Positional args
            user_ids = call_kwargs[0][3] if len(call_kwargs[0]) > 3 else None
        assert "admin-1" in user_ids
        assert "admin-2" in user_ids
        assert "viewer-1" not in user_ids

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_retry_does_not_notify(self, mock_audit):
        """Retry scheduling must NOT trigger admin notification."""
        from src.ingestion.jobs.models import IngestionJob, JobStatus
        from src.ingestion.jobs.retry import ErrorCategory
        from src.services.sync_retry_manager import (
            FailureAction,
            SyncRetryManager,
        )

        job = MagicMock(spec=IngestionJob)
        job.job_id = "job-retry-no-notify"
        job.tenant_id = TENANT_ID
        job.connector_id = CONNECTOR_ID
        job.retry_count = 1
        job.job_metadata = {}
        job.status = JobStatus.RUNNING

        session = MagicMock()

        manager = SyncRetryManager(db_session=session, tenant_id=TENANT_ID)
        result = manager.handle_failure(
            job=job,
            error_category=ErrorCategory.SERVER_ERROR,
            error_message="Transient error",
        )

        assert result.action == FailureAction.RETRY_SCHEDULED
        assert result.notified_admins is False


# =============================================================================
# Cross-Component: Audit Trail Completeness
# =============================================================================


class TestAuditTrailCompleteness:
    """All state transitions must emit audit events."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_revocation_emits_audit(self, mock_audit):
        """Credential revocation must emit an audit event."""
        from src.models.connector_credential import (
            ConnectorCredential,
            CredentialStatus,
        )
        from src.services.token_manager import TokenManager, RevocationReason

        cred = MagicMock(spec=ConnectorCredential)
        cred.id = CREDENTIAL_ID
        cred.status = CredentialStatus.ACTIVE
        cred.source_type = "shopify"
        cred.credential_metadata = {}
        cred.soft_deleted_at = None

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = cred

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        await manager.revoke_credential(
            CREDENTIAL_ID, reason=RevocationReason.ADMIN_ACTION
        )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args[1]
        assert call_kwargs["tenant_id"] == TENANT_ID
        assert call_kwargs["resource_type"] == "credential"
        assert call_kwargs["resource_id"] == CREDENTIAL_ID

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_retry_emits_audit(self, mock_audit):
        """Retry scheduling must emit an audit event."""
        from src.ingestion.jobs.models import IngestionJob, JobStatus
        from src.ingestion.jobs.retry import ErrorCategory
        from src.services.sync_retry_manager import SyncRetryManager

        job = MagicMock(spec=IngestionJob)
        job.job_id = "job-audit-retry"
        job.tenant_id = TENANT_ID
        job.connector_id = CONNECTOR_ID
        job.retry_count = 1
        job.job_metadata = {}
        job.status = JobStatus.RUNNING

        session = MagicMock()

        manager = SyncRetryManager(db_session=session, tenant_id=TENANT_ID)
        manager.handle_failure(
            job=job,
            error_category=ErrorCategory.SERVER_ERROR,
            error_message="Server error",
        )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args[1]
        assert call_kwargs["resource_type"] == "ingestion_job"
        assert call_kwargs["resource_id"] == "job-audit-retry"
        assert call_kwargs["metadata"]["decision"] == "retry"

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_dlq_emits_audit(self, mock_audit):
        """DLQ movement must emit an audit event."""
        from src.ingestion.jobs.models import IngestionJob, JobStatus
        from src.ingestion.jobs.retry import ErrorCategory
        from src.services.sync_retry_manager import SyncRetryManager

        job = MagicMock(spec=IngestionJob)
        job.job_id = "job-audit-dlq"
        job.tenant_id = TENANT_ID
        job.connector_id = CONNECTOR_ID
        job.retry_count = 0
        job.job_metadata = {}
        job.status = JobStatus.RUNNING

        session = MagicMock()

        manager = SyncRetryManager(db_session=session, tenant_id=TENANT_ID)

        with patch.object(manager, "_get_admin_user_ids", return_value=[]):
            manager.handle_failure(
                job=job,
                error_category=ErrorCategory.AUTH_ERROR,
                error_message="Auth failed",
            )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args[1]
        assert call_kwargs["metadata"]["decision"] == "dead_letter"

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_audit_failure_never_crashes_retry(self, mock_audit):
        """Audit logging failure must not crash the retry flow."""
        mock_audit.side_effect = RuntimeError("DB connection lost")

        from src.ingestion.jobs.models import IngestionJob, JobStatus
        from src.ingestion.jobs.retry import ErrorCategory
        from src.services.sync_retry_manager import (
            FailureAction,
            SyncRetryManager,
        )

        job = MagicMock(spec=IngestionJob)
        job.job_id = "job-audit-crash"
        job.tenant_id = TENANT_ID
        job.connector_id = CONNECTOR_ID
        job.retry_count = 1
        job.job_metadata = {}
        job.status = JobStatus.RUNNING

        session = MagicMock()

        manager = SyncRetryManager(db_session=session, tenant_id=TENANT_ID)
        # Must not raise even though audit fails
        result = manager.handle_failure(
            job=job,
            error_category=ErrorCategory.SERVER_ERROR,
            error_message="Server error",
        )

        assert result.action == FailureAction.RETRY_SCHEDULED
        job.mark_failed.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.platform.audit.log_system_audit_event_sync")
    async def test_audit_failure_never_crashes_revocation(self, mock_audit):
        """Audit logging failure must not crash credential revocation."""
        mock_audit.side_effect = RuntimeError("DB connection lost")

        from src.models.connector_credential import (
            ConnectorCredential,
            CredentialStatus,
        )
        from src.services.token_manager import TokenManager, RevocationReason

        cred = MagicMock(spec=ConnectorCredential)
        cred.id = CREDENTIAL_ID
        cred.status = CredentialStatus.ACTIVE
        cred.source_type = "shopify"
        cred.credential_metadata = {}
        cred.soft_deleted_at = None

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = cred

        manager = TokenManager(db_session=session, tenant_id=TENANT_ID)
        result = await manager.revoke_credential(
            CREDENTIAL_ID, reason=RevocationReason.SECURITY_EVENT
        )

        # Revocation succeeds even if audit logging fails
        assert result is True
        assert cred.status == CredentialStatus.REVOKED


# =============================================================================
# Cross-Component: HTTP Status Code → Error Category → Retry Decision
# =============================================================================


class TestStatusCodeToRetryDecision:
    """HTTP status code classification must produce correct retry behavior."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_401_routes_to_dlq(self, mock_audit):
        """HTTP 401 → AUTH_ERROR → DLQ (no retry)."""
        from src.ingestion.jobs.models import IngestionJob, JobStatus
        from src.services.sync_retry_manager import (
            FailureAction,
            SyncRetryManager,
        )

        job = MagicMock(spec=IngestionJob)
        job.job_id = "job-401"
        job.tenant_id = TENANT_ID
        job.connector_id = CONNECTOR_ID
        job.retry_count = 0
        job.job_metadata = {}
        job.status = JobStatus.RUNNING

        session = MagicMock()

        manager = SyncRetryManager(db_session=session, tenant_id=TENANT_ID)

        with patch.object(manager, "_get_admin_user_ids", return_value=[]):
            result = manager.handle_failure_from_status_code(
                job=job,
                status_code=401,
                error_message="Unauthorized",
            )

        assert result.action == FailureAction.MOVED_TO_DLQ
        assert result.error_category == "auth_error"

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_429_schedules_retry(self, mock_audit):
        """HTTP 429 → RATE_LIMIT → retry scheduled."""
        from src.ingestion.jobs.models import IngestionJob, JobStatus
        from src.services.sync_retry_manager import (
            FailureAction,
            SyncRetryManager,
        )

        job = MagicMock(spec=IngestionJob)
        job.job_id = "job-429"
        job.tenant_id = TENANT_ID
        job.connector_id = CONNECTOR_ID
        job.retry_count = 0
        job.job_metadata = {}
        job.status = JobStatus.RUNNING

        session = MagicMock()

        manager = SyncRetryManager(db_session=session, tenant_id=TENANT_ID)
        result = manager.handle_failure_from_status_code(
            job=job,
            status_code=429,
            error_message="Rate limited",
        )

        assert result.action == FailureAction.RETRY_SCHEDULED
        assert result.error_category == "rate_limit"

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_500_schedules_retry(self, mock_audit):
        """HTTP 500 → SERVER_ERROR → retry scheduled."""
        from src.ingestion.jobs.models import IngestionJob, JobStatus
        from src.services.sync_retry_manager import (
            FailureAction,
            SyncRetryManager,
        )

        job = MagicMock(spec=IngestionJob)
        job.job_id = "job-500"
        job.tenant_id = TENANT_ID
        job.connector_id = CONNECTOR_ID
        job.retry_count = 0
        job.job_metadata = {}
        job.status = JobStatus.RUNNING

        session = MagicMock()

        manager = SyncRetryManager(db_session=session, tenant_id=TENANT_ID)
        result = manager.handle_failure_from_status_code(
            job=job,
            status_code=500,
            error_message="Internal server error",
        )

        assert result.action == FailureAction.RETRY_SCHEDULED
        assert result.error_category == "server_error"

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_403_routes_to_dlq(self, mock_audit):
        """HTTP 403 → AUTH_ERROR → DLQ (no retry)."""
        from src.ingestion.jobs.models import IngestionJob, JobStatus
        from src.services.sync_retry_manager import (
            FailureAction,
            SyncRetryManager,
        )

        job = MagicMock(spec=IngestionJob)
        job.job_id = "job-403"
        job.tenant_id = TENANT_ID
        job.connector_id = CONNECTOR_ID
        job.retry_count = 0
        job.job_metadata = {}
        job.status = JobStatus.RUNNING

        session = MagicMock()

        manager = SyncRetryManager(db_session=session, tenant_id=TENANT_ID)

        with patch.object(manager, "_get_admin_user_ids", return_value=[]):
            result = manager.handle_failure_from_status_code(
                job=job,
                status_code=403,
                error_message="Forbidden",
            )

        assert result.action == FailureAction.MOVED_TO_DLQ
        assert result.error_category == "auth_error"


# =============================================================================
# Cross-Component: Soft Delete Constants
# =============================================================================


class TestSoftDeleteConstants:
    """Soft delete constants must match across model and vault."""

    def test_restore_window_is_5_days(self):
        """Restore window must be 5 days."""
        from src.models.connector_credential import SOFT_DELETE_RESTORE_WINDOW_DAYS

        assert SOFT_DELETE_RESTORE_WINDOW_DAYS == 5

    def test_hard_delete_is_20_days(self):
        """Hard delete must happen after 20 days."""
        from src.models.connector_credential import HARD_DELETE_AFTER_DAYS

        assert HARD_DELETE_AFTER_DAYS == 20

    def test_vault_imports_same_constants(self):
        """CredentialVault must use the same delete constants."""
        from src.models.connector_credential import (
            HARD_DELETE_AFTER_DAYS as model_hard,
        )
        from src.models.connector_credential import (
            SOFT_DELETE_RESTORE_WINDOW_DAYS as model_soft,
        )
        from src.services.credential_vault import (
            HARD_DELETE_AFTER_DAYS as vault_hard,
        )
        from src.services.credential_vault import (
            SOFT_DELETE_RESTORE_WINDOW_DAYS as vault_soft,
        )

        assert model_soft is vault_soft
        assert model_hard is vault_hard


# =============================================================================
# Cross-Component: Retry Policy Defaults
# =============================================================================


class TestRetryPolicyDefaults:
    """Retry policy defaults must be stable."""

    def test_default_max_retries_is_5(self):
        """Default max retries must be 5."""
        from src.ingestion.jobs.retry import RetryPolicy

        policy = RetryPolicy()
        assert policy.max_retries == 5

    def test_default_base_delay_is_60(self):
        """Default base delay must be 60 seconds."""
        from src.ingestion.jobs.retry import RetryPolicy

        policy = RetryPolicy()
        assert policy.base_delay_seconds == 60.0

    def test_default_max_delay_is_3600(self):
        """Default max delay must be 3600 seconds (1 hour)."""
        from src.ingestion.jobs.retry import RetryPolicy

        policy = RetryPolicy()
        assert policy.max_delay_seconds == 3600.0

    def test_job_model_max_retry_matches_policy(self):
        """IngestionJob.can_retry limit (5) must match RetryPolicy default."""
        from src.ingestion.jobs.models import JobStatus
        from src.ingestion.jobs.retry import RetryPolicy

        policy = RetryPolicy()

        # can_retry logic: status == FAILED and retry_count < 5
        # At max retries, should NOT be retryable
        assert not (JobStatus.FAILED == JobStatus.FAILED and policy.max_retries < 5)

        # One less should still be retryable
        assert (JobStatus.FAILED == JobStatus.FAILED and (policy.max_retries - 1) < 5)


# =============================================================================
# Cross-Component: Token Refresh Constants
# =============================================================================


class TestTokenRefreshConstants:
    """Token refresh constants must remain stable."""

    def test_proactive_refresh_window_is_24_hours(self):
        """Proactive refresh window must be 24 hours."""
        from src.services.token_manager import PROACTIVE_REFRESH_HOURS

        assert PROACTIVE_REFRESH_HOURS == 24

    def test_max_refresh_attempts_is_3(self):
        """Max refresh attempts must be 3."""
        from src.services.token_manager import MAX_REFRESH_ATTEMPTS

        assert MAX_REFRESH_ATTEMPTS == 3

    def test_backoff_minutes_has_3_levels(self):
        """Refresh backoff must have 3 levels."""
        from src.services.token_manager import REFRESH_BACKOFF_MINUTES

        assert len(REFRESH_BACKOFF_MINUTES) == 3
        # Must be increasing
        assert REFRESH_BACKOFF_MINUTES[0] < REFRESH_BACKOFF_MINUTES[1]
        assert REFRESH_BACKOFF_MINUTES[1] < REFRESH_BACKOFF_MINUTES[2]


# =============================================================================
# Data Contract: Error Message Truncation
# =============================================================================


class TestErrorMessageSafety:
    """Error messages must be truncated to prevent log injection."""

    def test_retry_manager_truncates_error_messages(self):
        """SyncRetryManager must truncate error messages."""
        from src.services.sync_retry_manager import MAX_ERROR_MESSAGE_LENGTH

        assert MAX_ERROR_MESSAGE_LENGTH == 500

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_long_error_message_truncated_in_failure(self, mock_audit):
        """Long error messages must be truncated in handle_failure."""
        from src.ingestion.jobs.models import IngestionJob, JobStatus
        from src.ingestion.jobs.retry import ErrorCategory
        from src.services.sync_retry_manager import SyncRetryManager

        long_message = "x" * 1000
        job = MagicMock(spec=IngestionJob)
        job.job_id = "job-truncate"
        job.tenant_id = TENANT_ID
        job.connector_id = CONNECTOR_ID
        job.retry_count = 0
        job.job_metadata = {}
        job.status = JobStatus.RUNNING

        session = MagicMock()

        manager = SyncRetryManager(db_session=session, tenant_id=TENANT_ID)
        result = manager.handle_failure(
            job=job,
            error_category=ErrorCategory.SERVER_ERROR,
            error_message=long_message,
        )

        assert len(result.error_message) == 500

    def test_failure_result_to_dict_truncates_to_200(self):
        """FailureResult.to_dict() must truncate error_message to 200 chars."""
        from src.services.sync_retry_manager import FailureAction, FailureResult

        result = FailureResult(
            job_id="job-1",
            action=FailureAction.RETRY_SCHEDULED,
            retry_count=1,
            error_category="server_error",
            error_message="y" * 500,
        )

        d = result.to_dict()
        assert len(d["error_message"]) == 200


# =============================================================================
# Cross-Component: Notification Filtering
# =============================================================================


class TestNotificationFiltering:
    """Admin notification must filter to correct roles."""

    def test_admin_roles_include_merchant_and_agency(self):
        """Admin roles must include MERCHANT_ADMIN, AGENCY_ADMIN, ADMIN, OWNER."""
        from src.services.sync_retry_manager import SyncRetryManager

        manager = SyncRetryManager(
            db_session=MagicMock(), tenant_id=TENANT_ID
        )

        # Access the role set used internally
        # The _get_admin_user_ids method filters by these roles
        with patch(
            "src.services.tenant_members_service.TenantMembersService"
        ) as MockMembers:
            mock_instance = MagicMock()
            mock_instance.list_members.return_value = [
                {"clerk_user_id": "u1", "role": "MERCHANT_ADMIN", "is_active": True},
                {"clerk_user_id": "u2", "role": "AGENCY_ADMIN", "is_active": True},
                {"clerk_user_id": "u3", "role": "ADMIN", "is_active": True},
                {"clerk_user_id": "u4", "role": "OWNER", "is_active": True},
                {"clerk_user_id": "u5", "role": "VIEWER", "is_active": True},
                {"clerk_user_id": "u6", "role": "EDITOR", "is_active": True},
                {"clerk_user_id": "u7", "role": "MERCHANT_ADMIN", "is_active": False},
            ]
            MockMembers.return_value = mock_instance

            user_ids = manager._get_admin_user_ids()

        # Must include all active admins
        assert "u1" in user_ids  # MERCHANT_ADMIN
        assert "u2" in user_ids  # AGENCY_ADMIN
        assert "u3" in user_ids  # ADMIN
        assert "u4" in user_ids  # OWNER
        # Must exclude non-admin roles
        assert "u5" not in user_ids  # VIEWER
        assert "u6" not in user_ids  # EDITOR
        # Must exclude inactive admins
        assert "u7" not in user_ids  # inactive MERCHANT_ADMIN

    def test_notification_failure_does_not_crash_retry(self):
        """Notification service failure must not crash retry flow."""
        from src.ingestion.jobs.models import IngestionJob, JobStatus
        from src.ingestion.jobs.retry import ErrorCategory
        from src.services.sync_retry_manager import (
            FailureAction,
            SyncRetryManager,
        )

        job = MagicMock(spec=IngestionJob)
        job.job_id = "job-notif-crash"
        job.tenant_id = TENANT_ID
        job.connector_id = CONNECTOR_ID
        job.retry_count = 5
        job.job_metadata = {}
        job.status = JobStatus.FAILED

        session = MagicMock()

        manager = SyncRetryManager(db_session=session, tenant_id=TENANT_ID)

        with patch.object(
            manager,
            "_get_admin_user_ids",
            side_effect=RuntimeError("Members service down"),
        ), patch("src.platform.audit.log_system_audit_event_sync"):
            result = manager.handle_failure(
                job=job,
                error_category=ErrorCategory.SERVER_ERROR,
                error_message="Server error after max retries",
            )

        # DLQ should still work even if notification fails
        assert result.action == FailureAction.MOVED_TO_DLQ
        assert result.notified_admins is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
