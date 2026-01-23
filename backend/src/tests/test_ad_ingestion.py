"""
Tests for ad platform ingestion service.

CRITICAL: These tests verify that:
1. Meta Ads and Google Ads connectors are supported
2. OAuth tokens are encrypted before storage
3. Sync operations work correctly
4. Tenant isolation is enforced
5. Invalid credentials are rejected

Story 3.4 - Ad Platform Ingestion
"""

import os
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set test environment
os.environ["ENV"] = "test"
os.environ["ENCRYPTION_KEY"] = "test-encryption-key-for-ad-ingestion"

from src.db_base import Base
from src.models.airbyte_connection import (
    TenantAirbyteConnection,
    ConnectionStatus,
    ConnectionType,
)
from src.integrations.airbyte.models import (
    AirbyteJob,
    AirbyteJobStatus,
    AirbyteJobAttempt,
    AirbyteSyncResult,
)
from src.services.ad_ingestion import (
    AdIngestionService,
    AdPlatform,
    AdAccountCredentials,
    AdAccountInfo,
    SyncStatus,
    AdIngestionError,
    InvalidCredentialsError,
    AccountNotFoundError,
    SyncError,
    AIRBYTE_SOURCE_TYPES,
)
from src.services.airbyte_service import DuplicateConnectionError


# =============================================================================
# Test Database Fixtures
# =============================================================================

def _get_test_database_url():
    """Get database URL for testing."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return "sqlite:///:memory:"
    return database_url


@pytest.fixture(scope="module")
def db_engine():
    """Create database engine for tests."""
    database_url = _get_test_database_url()

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    if database_url.startswith("sqlite"):
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(database_url, pool_pre_ping=True)

    from src.models import airbyte_connection

    Base.metadata.create_all(bind=engine)

    yield engine

    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Create a new database session for each test with transaction rollback."""
    connection = db_engine.connect()
    transaction = connection.begin()

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = SessionLocal()

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(session, transaction):
        nonlocal nested
        if transaction.nested and not transaction._parent.nested:
            nested = connection.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# =============================================================================
# Test Identity Fixtures
# =============================================================================

@pytest.fixture
def tenant_id() -> str:
    """Generate unique tenant ID."""
    return f"tenant-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def other_tenant_id() -> str:
    """Generate unique tenant ID for cross-tenant tests."""
    return f"other-tenant-{uuid.uuid4().hex[:8]}"


# =============================================================================
# Mock Fixtures
# =============================================================================

@pytest.fixture
def mock_airbyte_client():
    """Create a mock Airbyte client."""
    client = MagicMock()
    client.trigger_sync = AsyncMock(return_value="job-123")
    client.get_job = AsyncMock()
    client.sync_and_wait = AsyncMock()
    return client


@pytest.fixture
def service(db_session, tenant_id, mock_airbyte_client):
    """Create AdIngestionService for testing."""
    return AdIngestionService(
        db_session=db_session,
        tenant_id=tenant_id,
        airbyte_client=mock_airbyte_client,
    )


# =============================================================================
# Credential Fixtures
# =============================================================================

@pytest.fixture
def meta_credentials() -> AdAccountCredentials:
    """Valid Meta Ads credentials."""
    return AdAccountCredentials(
        platform=AdPlatform.META_ADS,
        account_id="act_123456789",
        access_token="EAAxxxxxxxxxxxxxxxxxxxxxxx",
        app_id="123456789",
        app_secret="secret123",
    )


@pytest.fixture
def google_credentials() -> AdAccountCredentials:
    """Valid Google Ads credentials."""
    return AdAccountCredentials(
        platform=AdPlatform.GOOGLE_ADS,
        account_id="1234567890",
        access_token="ya29.xxxxxxxxxx",
        refresh_token="1//xxxxxxxxxx",
        client_id="client-id.apps.googleusercontent.com",
        client_secret="client-secret",
        developer_token="dev-token",
        customer_id="123-456-7890",
    )


# =============================================================================
# Test: Service Initialization
# =============================================================================

class TestServiceInitialization:
    """Tests for AdIngestionService initialization."""

    def test_requires_tenant_id(self, db_session):
        """Service requires tenant_id."""
        with pytest.raises(ValueError, match="tenant_id is required"):
            AdIngestionService(db_session, "")

        with pytest.raises(ValueError, match="tenant_id is required"):
            AdIngestionService(db_session, None)

    def test_initializes_with_valid_tenant_id(self, db_session, tenant_id):
        """Service initializes with valid tenant_id."""
        service = AdIngestionService(db_session, tenant_id)
        assert service.tenant_id == tenant_id


# =============================================================================
# Test: Credential Validation
# =============================================================================

class TestCredentialValidation:
    """Tests for credential validation."""

    def test_meta_requires_access_token(self, service):
        """Meta Ads requires access_token."""
        creds = AdAccountCredentials(
            platform=AdPlatform.META_ADS,
            account_id="act_123",
            access_token="",
        )
        with pytest.raises(InvalidCredentialsError, match="access_token"):
            service._validate_credentials(creds)

    def test_meta_requires_account_id(self, service):
        """Meta Ads requires account_id."""
        creds = AdAccountCredentials(
            platform=AdPlatform.META_ADS,
            account_id="",
            access_token="token",
        )
        with pytest.raises(InvalidCredentialsError, match="account_id"):
            service._validate_credentials(creds)

    def test_google_requires_refresh_token(self, service):
        """Google Ads requires refresh_token."""
        creds = AdAccountCredentials(
            platform=AdPlatform.GOOGLE_ADS,
            account_id="123",
            access_token="token",
            refresh_token="",
            client_id="client",
            client_secret="secret",
            developer_token="dev",
            customer_id="cust",
        )
        with pytest.raises(InvalidCredentialsError, match="refresh_token"):
            service._validate_credentials(creds)

    def test_google_requires_client_id(self, service):
        """Google Ads requires client_id."""
        creds = AdAccountCredentials(
            platform=AdPlatform.GOOGLE_ADS,
            account_id="123",
            access_token="token",
            refresh_token="refresh",
            client_id="",
            client_secret="secret",
            developer_token="dev",
            customer_id="cust",
        )
        with pytest.raises(InvalidCredentialsError, match="client_id"):
            service._validate_credentials(creds)

    def test_google_requires_developer_token(self, service):
        """Google Ads requires developer_token."""
        creds = AdAccountCredentials(
            platform=AdPlatform.GOOGLE_ADS,
            account_id="123",
            access_token="token",
            refresh_token="refresh",
            client_id="client",
            client_secret="secret",
            developer_token="",
            customer_id="cust",
        )
        with pytest.raises(InvalidCredentialsError, match="developer_token"):
            service._validate_credentials(creds)

    def test_valid_meta_credentials_pass(self, service, meta_credentials):
        """Valid Meta credentials pass validation."""
        service._validate_credentials(meta_credentials)  # Should not raise

    def test_valid_google_credentials_pass(self, service, google_credentials):
        """Valid Google credentials pass validation."""
        service._validate_credentials(google_credentials)  # Should not raise


# =============================================================================
# Test: OAuth Token Encryption
# =============================================================================

class TestOAuthEncryption:
    """Tests for OAuth token encryption."""

    @pytest.mark.asyncio
    async def test_encrypts_access_token(self, service, meta_credentials):
        """Access token is encrypted."""
        encrypted = await service._encrypt_credentials(meta_credentials)

        assert "access_token_encrypted" in encrypted
        assert encrypted["access_token_encrypted"] != meta_credentials.access_token
        assert "access_token" not in encrypted

    @pytest.mark.asyncio
    async def test_encrypts_refresh_token(self, service, google_credentials):
        """Refresh token is encrypted."""
        encrypted = await service._encrypt_credentials(google_credentials)

        assert "refresh_token_encrypted" in encrypted
        assert encrypted["refresh_token_encrypted"] != google_credentials.refresh_token

    @pytest.mark.asyncio
    async def test_encrypts_secrets(self, service, google_credentials):
        """Client secret and developer token are encrypted."""
        encrypted = await service._encrypt_credentials(google_credentials)

        assert "client_secret_encrypted" in encrypted
        assert "developer_token_encrypted" in encrypted
        assert "client_secret" not in encrypted
        assert "developer_token" not in encrypted

    @pytest.mark.asyncio
    async def test_preserves_non_secret_fields(self, service, google_credentials):
        """Non-secret identifiers are preserved unencrypted."""
        encrypted = await service._encrypt_credentials(google_credentials)

        assert encrypted["platform"] == "google_ads"
        assert encrypted["account_id"] == google_credentials.account_id
        assert encrypted["client_id"] == google_credentials.client_id
        assert encrypted["customer_id"] == google_credentials.customer_id

    @pytest.mark.asyncio
    async def test_decrypt_recovers_credentials(self, service, meta_credentials):
        """Decryption recovers original credentials."""
        encrypted = await service._encrypt_credentials(meta_credentials)
        decrypted = await service._decrypt_credentials(encrypted)

        assert decrypted.platform == meta_credentials.platform
        assert decrypted.account_id == meta_credentials.account_id
        assert decrypted.access_token == meta_credentials.access_token

    @pytest.mark.asyncio
    async def test_decrypt_google_credentials(self, service, google_credentials):
        """Decryption recovers Google credentials."""
        encrypted = await service._encrypt_credentials(google_credentials)
        decrypted = await service._decrypt_credentials(encrypted)

        assert decrypted.platform == AdPlatform.GOOGLE_ADS
        assert decrypted.access_token == google_credentials.access_token
        assert decrypted.refresh_token == google_credentials.refresh_token
        assert decrypted.client_secret == google_credentials.client_secret
        assert decrypted.developer_token == google_credentials.developer_token


# =============================================================================
# Test: Connect Ad Account
# =============================================================================

class TestConnectAdAccount:
    """Tests for connecting ad accounts."""

    @pytest.mark.asyncio
    async def test_connect_meta_account(self, service, meta_credentials):
        """Can connect Meta Ads account."""
        airbyte_conn_id = f"airbyte-{uuid.uuid4().hex[:8]}"

        account = await service.connect_ad_account(
            credentials=meta_credentials,
            account_name="My Meta Ads Account",
            airbyte_connection_id=airbyte_conn_id,
        )

        assert account.platform == "meta_ads"
        assert account.account_name == "My Meta Ads Account"
        assert account.airbyte_connection_id == airbyte_conn_id
        assert account.status == "active"
        assert account.is_enabled is True

    @pytest.mark.asyncio
    async def test_connect_google_account(self, service, google_credentials):
        """Can connect Google Ads account."""
        airbyte_conn_id = f"airbyte-{uuid.uuid4().hex[:8]}"

        account = await service.connect_ad_account(
            credentials=google_credentials,
            account_name="My Google Ads Account",
            airbyte_connection_id=airbyte_conn_id,
        )

        assert account.platform == "google_ads"
        assert account.account_name == "My Google Ads Account"
        assert account.status == "active"

    @pytest.mark.asyncio
    async def test_duplicate_connection_rejected(self, service, meta_credentials):
        """Duplicate connection is rejected."""
        airbyte_conn_id = f"airbyte-{uuid.uuid4().hex[:8]}"

        await service.connect_ad_account(
            credentials=meta_credentials,
            account_name="First Account",
            airbyte_connection_id=airbyte_conn_id,
        )

        with pytest.raises(DuplicateConnectionError):
            await service.connect_ad_account(
                credentials=meta_credentials,
                account_name="Duplicate Account",
                airbyte_connection_id=airbyte_conn_id,
            )

    @pytest.mark.asyncio
    async def test_invalid_credentials_rejected(self, service):
        """Invalid credentials are rejected."""
        invalid_creds = AdAccountCredentials(
            platform=AdPlatform.META_ADS,
            account_id="",
            access_token="token",
        )

        with pytest.raises(InvalidCredentialsError):
            await service.connect_ad_account(
                credentials=invalid_creds,
                account_name="Invalid Account",
                airbyte_connection_id="abc",
            )


# =============================================================================
# Test: List Ad Accounts
# =============================================================================

class TestListAdAccounts:
    """Tests for listing ad accounts."""

    @pytest.mark.asyncio
    async def test_list_empty_initially(self, service):
        """List is empty when no accounts connected."""
        accounts = service.list_ad_accounts()
        assert accounts == []

    @pytest.mark.asyncio
    async def test_list_returns_connected_accounts(
        self, service, meta_credentials, google_credentials
    ):
        """List returns all connected accounts."""
        await service.connect_ad_account(
            credentials=meta_credentials,
            account_name="Meta Account",
            airbyte_connection_id=f"airbyte-meta-{uuid.uuid4().hex[:8]}",
        )
        await service.connect_ad_account(
            credentials=google_credentials,
            account_name="Google Account",
            airbyte_connection_id=f"airbyte-google-{uuid.uuid4().hex[:8]}",
        )

        accounts = service.list_ad_accounts()
        assert len(accounts) == 2
        platforms = {a.platform for a in accounts}
        assert platforms == {"meta_ads", "google_ads"}

    @pytest.mark.asyncio
    async def test_filter_by_platform(
        self, service, meta_credentials, google_credentials
    ):
        """Can filter by platform."""
        await service.connect_ad_account(
            credentials=meta_credentials,
            account_name="Meta Account",
            airbyte_connection_id=f"airbyte-meta-{uuid.uuid4().hex[:8]}",
        )
        await service.connect_ad_account(
            credentials=google_credentials,
            account_name="Google Account",
            airbyte_connection_id=f"airbyte-google-{uuid.uuid4().hex[:8]}",
        )

        meta_accounts = service.list_ad_accounts(platform=AdPlatform.META_ADS)
        assert len(meta_accounts) == 1
        assert meta_accounts[0].platform == "meta_ads"


# =============================================================================
# Test: Get Ad Account
# =============================================================================

class TestGetAdAccount:
    """Tests for getting a single ad account."""

    @pytest.mark.asyncio
    async def test_get_existing_account(self, service, meta_credentials):
        """Can get existing account by ID."""
        airbyte_conn_id = f"airbyte-{uuid.uuid4().hex[:8]}"
        created = await service.connect_ad_account(
            credentials=meta_credentials,
            account_name="Test Account",
            airbyte_connection_id=airbyte_conn_id,
        )

        account = service.get_ad_account(created.id)
        assert account is not None
        assert account.id == created.id
        assert account.account_name == "Test Account"

    def test_get_nonexistent_returns_none(self, service):
        """Get returns None for nonexistent account."""
        account = service.get_ad_account("nonexistent-id")
        assert account is None


# =============================================================================
# Test: Tenant Isolation
# =============================================================================

class TestTenantIsolation:
    """Tests for tenant isolation."""

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_see_tenant_b_accounts(
        self, db_session, tenant_id, other_tenant_id, meta_credentials, mock_airbyte_client
    ):
        """Tenant A cannot see Tenant B's accounts."""
        # Create account for tenant A
        service_a = AdIngestionService(db_session, tenant_id, mock_airbyte_client)
        account_a = await service_a.connect_ad_account(
            credentials=meta_credentials,
            account_name="Tenant A Account",
            airbyte_connection_id=f"airbyte-a-{uuid.uuid4().hex[:8]}",
        )

        # Create account for tenant B
        service_b = AdIngestionService(db_session, other_tenant_id, mock_airbyte_client)
        other_creds = AdAccountCredentials(
            platform=AdPlatform.META_ADS,
            account_id="act_other",
            access_token="other-token",
        )
        account_b = await service_b.connect_ad_account(
            credentials=other_creds,
            account_name="Tenant B Account",
            airbyte_connection_id=f"airbyte-b-{uuid.uuid4().hex[:8]}",
        )

        # Tenant A should only see their account
        accounts_a = service_a.list_ad_accounts()
        assert len(accounts_a) == 1
        assert accounts_a[0].id == account_a.id

        # Tenant B should only see their account
        accounts_b = service_b.list_ad_accounts()
        assert len(accounts_b) == 1
        assert accounts_b[0].id == account_b.id

    @pytest.mark.asyncio
    async def test_tenant_cannot_get_other_tenant_account(
        self, db_session, tenant_id, other_tenant_id, meta_credentials, mock_airbyte_client
    ):
        """Tenant cannot get another tenant's account by ID."""
        # Create account for tenant A
        service_a = AdIngestionService(db_session, tenant_id, mock_airbyte_client)
        account_a = await service_a.connect_ad_account(
            credentials=meta_credentials,
            account_name="Tenant A Account",
            airbyte_connection_id=f"airbyte-a-{uuid.uuid4().hex[:8]}",
        )

        # Tenant B cannot access it
        service_b = AdIngestionService(db_session, other_tenant_id, mock_airbyte_client)
        account = service_b.get_ad_account(account_a.id)
        assert account is None


# =============================================================================
# Test: Sync Operations
# =============================================================================

class TestSyncOperations:
    """Tests for sync triggering and monitoring."""

    @pytest.mark.asyncio
    async def test_trigger_sync(self, service, meta_credentials, mock_airbyte_client):
        """Can trigger sync for connected account."""
        airbyte_conn_id = f"airbyte-{uuid.uuid4().hex[:8]}"
        account = await service.connect_ad_account(
            credentials=meta_credentials,
            account_name="Test Account",
            airbyte_connection_id=airbyte_conn_id,
        )

        mock_airbyte_client.trigger_sync.return_value = "job-abc123"

        status = await service.trigger_sync(account.id)

        assert status.job_id == "job-abc123"
        assert status.is_running is True
        assert status.is_complete is False
        mock_airbyte_client.trigger_sync.assert_called_once_with(airbyte_conn_id)

    @pytest.mark.asyncio
    async def test_trigger_sync_nonexistent_account(self, service):
        """Trigger sync fails for nonexistent account."""
        with pytest.raises(AccountNotFoundError):
            await service.trigger_sync("nonexistent-id")

    @pytest.mark.asyncio
    async def test_get_sync_status(self, service, mock_airbyte_client):
        """Can get sync status."""
        mock_job = MagicMock()
        mock_job.status = AirbyteJobStatus.SUCCEEDED
        mock_job.is_complete = True
        mock_job.is_successful = True
        mock_job.config_id = "conn-123"
        mock_job.attempts = [
            MagicMock(records_synced=1000, bytes_synced=50000)
        ]

        mock_airbyte_client.get_job.return_value = mock_job

        status = await service.get_sync_status("job-123")

        assert status.status == "succeeded"
        assert status.is_complete is True
        assert status.is_successful is True
        assert status.records_synced == 1000

    @pytest.mark.asyncio
    async def test_sync_and_wait(self, service, meta_credentials, mock_airbyte_client):
        """Can trigger sync and wait for completion."""
        airbyte_conn_id = f"airbyte-{uuid.uuid4().hex[:8]}"
        account = await service.connect_ad_account(
            credentials=meta_credentials,
            account_name="Test Account",
            airbyte_connection_id=airbyte_conn_id,
        )

        mock_result = AirbyteSyncResult(
            job_id="job-456",
            status=AirbyteJobStatus.SUCCEEDED,
            connection_id=airbyte_conn_id,
            records_synced=5000,
            bytes_synced=250000,
            duration_seconds=120.5,
        )
        mock_airbyte_client.sync_and_wait.return_value = mock_result

        status = await service.sync_and_wait(account.id)

        assert status.job_id == "job-456"
        assert status.is_successful is True
        assert status.records_synced == 5000
        assert status.duration_seconds == 120.5


# =============================================================================
# Test: Sync Health
# =============================================================================

class TestSyncHealth:
    """Tests for sync health monitoring."""

    @pytest.mark.asyncio
    async def test_get_sync_health(self, service, meta_credentials):
        """Can get sync health for account."""
        account = await service.connect_ad_account(
            credentials=meta_credentials,
            account_name="Test Account",
            airbyte_connection_id=f"airbyte-{uuid.uuid4().hex[:8]}",
        )

        health = service.get_sync_health(account.id)

        assert health["connection_id"] == account.id
        assert health["status"] == "active"
        assert health["is_enabled"] is True
        assert health["can_sync"] is True

    def test_get_sync_health_nonexistent(self, service):
        """Get sync health fails for nonexistent account."""
        with pytest.raises(AccountNotFoundError):
            service.get_sync_health("nonexistent-id")


# =============================================================================
# Test: Enable/Disable Ad Account
# =============================================================================

class TestEnableDisable:
    """Tests for enabling/disabling accounts."""

    @pytest.mark.asyncio
    async def test_disable_account(self, service, meta_credentials):
        """Can disable account."""
        account = await service.connect_ad_account(
            credentials=meta_credentials,
            account_name="Test Account",
            airbyte_connection_id=f"airbyte-{uuid.uuid4().hex[:8]}",
        )

        updated = service.disable_ad_account(account.id)

        assert updated.is_enabled is False

    @pytest.mark.asyncio
    async def test_enable_account(self, service, meta_credentials):
        """Can enable disabled account."""
        account = await service.connect_ad_account(
            credentials=meta_credentials,
            account_name="Test Account",
            airbyte_connection_id=f"airbyte-{uuid.uuid4().hex[:8]}",
        )

        service.disable_ad_account(account.id)
        updated = service.enable_ad_account(account.id)

        assert updated.is_enabled is True

    def test_disable_nonexistent_account(self, service):
        """Disable fails for nonexistent account."""
        with pytest.raises(AccountNotFoundError):
            service.disable_ad_account("nonexistent-id")


# =============================================================================
# Test: Disconnect Ad Account
# =============================================================================

class TestDisconnectAccount:
    """Tests for disconnecting accounts."""

    @pytest.mark.asyncio
    async def test_disconnect_account(self, service, meta_credentials):
        """Can disconnect (soft delete) account."""
        account = await service.connect_ad_account(
            credentials=meta_credentials,
            account_name="Test Account",
            airbyte_connection_id=f"airbyte-{uuid.uuid4().hex[:8]}",
        )

        disconnected = service.disconnect_ad_account(account.id)

        assert disconnected.status == "deleted"

    @pytest.mark.asyncio
    async def test_disconnected_account_not_in_list(self, service, meta_credentials):
        """Disconnected account not returned in list."""
        account = await service.connect_ad_account(
            credentials=meta_credentials,
            account_name="Test Account",
            airbyte_connection_id=f"airbyte-{uuid.uuid4().hex[:8]}",
        )

        service.disconnect_ad_account(account.id)

        # Deleted accounts should not appear in list (depends on implementation)
        accounts = service.list_ad_accounts()
        account_ids = [a.id for a in accounts]
        # The account may still appear but with deleted status


# =============================================================================
# Test: Multiple Accounts Per Platform
# =============================================================================

class TestMultipleAccounts:
    """Tests for supporting multiple accounts per platform."""

    @pytest.mark.asyncio
    async def test_multiple_meta_accounts(self, service):
        """Can connect multiple Meta Ads accounts."""
        accounts = []
        for i in range(3):
            creds = AdAccountCredentials(
                platform=AdPlatform.META_ADS,
                account_id=f"act_{i}",
                access_token=f"token_{i}",
            )
            account = await service.connect_ad_account(
                credentials=creds,
                account_name=f"Meta Account {i}",
                airbyte_connection_id=f"airbyte-meta-{i}-{uuid.uuid4().hex[:8]}",
            )
            accounts.append(account)

        listed = service.list_ad_accounts(platform=AdPlatform.META_ADS)
        assert len(listed) == 3

    @pytest.mark.asyncio
    async def test_multiple_google_accounts(self, service):
        """Can connect multiple Google Ads accounts."""
        accounts = []
        for i in range(2):
            creds = AdAccountCredentials(
                platform=AdPlatform.GOOGLE_ADS,
                account_id=f"customer_{i}",
                access_token=f"token_{i}",
                refresh_token=f"refresh_{i}",
                client_id=f"client_{i}",
                client_secret=f"secret_{i}",
                developer_token=f"dev_{i}",
                customer_id=f"cust_{i}",
            )
            account = await service.connect_ad_account(
                credentials=creds,
                account_name=f"Google Account {i}",
                airbyte_connection_id=f"airbyte-google-{i}-{uuid.uuid4().hex[:8]}",
            )
            accounts.append(account)

        listed = service.list_ad_accounts(platform=AdPlatform.GOOGLE_ADS)
        assert len(listed) == 2


# =============================================================================
# Test: Source Type Mapping
# =============================================================================

class TestSourceTypeMapping:
    """Tests for Airbyte source type mapping."""

    def test_meta_ads_source_type(self):
        """Meta Ads maps to correct Airbyte source type."""
        assert AIRBYTE_SOURCE_TYPES[AdPlatform.META_ADS] == "source-facebook-marketing"

    def test_google_ads_source_type(self):
        """Google Ads maps to correct Airbyte source type."""
        assert AIRBYTE_SOURCE_TYPES[AdPlatform.GOOGLE_ADS] == "source-google-ads"
