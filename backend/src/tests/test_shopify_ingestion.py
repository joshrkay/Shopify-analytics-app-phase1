"""
Unit tests for Shopify ingestion service.

Tests cover:
- Shopify Airbyte source creation and registration
- Encrypted credential storage
- Initial and incremental sync triggering
- Sync result logging
- Error handling for various failure scenarios
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from datetime import datetime, timezone
import uuid

from src.services.shopify_ingestion import (
    ShopifyIngestionService,
    ShopifyIngestionError,
    CredentialEncryptionError,
    SourceConfigurationError,
    SyncExecutionError,
    SyncResult,
)
from src.services.airbyte_service import (
    AirbyteService,
    ConnectionInfo,
    DuplicateConnectionError,
    ConnectionNotFoundServiceError,
)
from src.integrations.airbyte.exceptions import (
    AirbyteError,
    AirbyteSyncError,
    AirbyteConnectionError,
)
from src.integrations.airbyte.models import AirbyteSyncResult, AirbyteJobStatus
from src.models.store import ShopifyStore


# Test fixtures
@pytest.fixture
def test_tenant_id():
    """Generate a unique tenant ID for testing."""
    return f"test-tenant-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def test_shop_domain():
    """Test shop domain."""
    return "test-store.myshopify.com"


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock()
    session.query = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.close = MagicMock()
    return session


@pytest.fixture
def mock_store(test_tenant_id, test_shop_domain):
    """Create a mock ShopifyStore."""
    store = MagicMock(spec=ShopifyStore)
    store.id = str(uuid.uuid4())
    store.tenant_id = test_tenant_id
    store.shop_domain = test_shop_domain
    store.shop_name = "Test Store"
    store.access_token_encrypted = "encrypted-token-12345"
    store.status = "active"
    store.is_active = True
    store.has_valid_token = True
    return store


@pytest.fixture
def mock_connection_info():
    """Create a mock ConnectionInfo."""
    return ConnectionInfo(
        id=str(uuid.uuid4()),
        airbyte_connection_id="airbyte-conn-123",
        connection_name="Test Store - Shopify",
        connection_type="source",
        source_type="shopify",
        status="active",
        is_enabled=True,
        is_active=True,
        can_sync=True,
        last_sync_at=None,
        last_sync_status=None,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_airbyte_service(test_tenant_id, mock_db_session, mock_connection_info):
    """Create a mock AirbyteService."""
    service = MagicMock(spec=AirbyteService)
    service.tenant_id = test_tenant_id
    service.register_connection = MagicMock(return_value=mock_connection_info)
    service.get_connection = MagicMock(return_value=mock_connection_info)
    service.list_connections = MagicMock(
        return_value=MagicMock(connections=[mock_connection_info])
    )
    service.record_sync_success = MagicMock()
    service.mark_connection_failed = MagicMock()
    return service


@pytest.fixture
def ingestion_service(test_tenant_id, mock_db_session, mock_airbyte_service):
    """Create a ShopifyIngestionService instance with mocked dependencies."""
    with patch(
        "src.services.shopify_ingestion.AirbyteService",
        return_value=mock_airbyte_service,
    ):
        service = ShopifyIngestionService(mock_db_session, test_tenant_id)
        service._airbyte_service = mock_airbyte_service
        return service


class TestShopifyIngestionServiceInitialization:
    """Tests for service initialization."""

    def test_init_success(self, test_tenant_id, mock_db_session):
        """Service should initialize with valid tenant_id."""
        with patch("src.services.shopify_ingestion.AirbyteService"):
            service = ShopifyIngestionService(mock_db_session, test_tenant_id)
            assert service.tenant_id == test_tenant_id
            assert service.db == mock_db_session

    def test_init_empty_tenant_id_raises(self, mock_db_session):
        """Should raise ValueError if tenant_id is empty."""
        with pytest.raises(ValueError, match="tenant_id is required"):
            ShopifyIngestionService(mock_db_session, "")

    def test_init_none_tenant_id_raises(self, mock_db_session):
        """Should raise ValueError if tenant_id is None."""
        with pytest.raises(ValueError, match="tenant_id is required"):
            ShopifyIngestionService(mock_db_session, None)


class TestCreateShopifySource:
    """Tests for create_shopify_source method."""

    @pytest.mark.asyncio
    async def test_create_source_success(
        self, ingestion_service, mock_store, mock_connection_info
    ):
        """Should successfully register a Shopify source."""
        with patch("src.services.shopify_ingestion.decrypt_secret", new_callable=AsyncMock) as mock_decrypt:
            mock_decrypt.return_value = "decrypted-token"

            result = await ingestion_service.create_shopify_source(
                store=mock_store,
                airbyte_source_id="airbyte-source-123",
            )

            assert result == mock_connection_info.id
            ingestion_service._airbyte_service.register_connection.assert_called_once()
            mock_decrypt.assert_called_once_with(mock_store.access_token_encrypted)

    @pytest.mark.asyncio
    async def test_create_source_with_custom_name(
        self, ingestion_service, mock_store, mock_connection_info
    ):
        """Should use custom connection name when provided."""
        with patch("src.services.shopify_ingestion.decrypt_secret", new_callable=AsyncMock) as mock_decrypt:
            mock_decrypt.return_value = "decrypted-token"

            custom_name = "Custom Connection Name"
            await ingestion_service.create_shopify_source(
                store=mock_store,
                airbyte_source_id="airbyte-source-123",
                connection_name=custom_name,
            )

            call_args = ingestion_service._airbyte_service.register_connection.call_args
            assert call_args[1]["connection_name"] == custom_name

    @pytest.mark.asyncio
    async def test_create_source_invalid_token_raises(
        self, ingestion_service, mock_store
    ):
        """Should raise SourceConfigurationError if store has no valid token."""
        mock_store.has_valid_token = False

        with pytest.raises(SourceConfigurationError, match="does not have a valid access token"):
            await ingestion_service.create_shopify_source(
                store=mock_store,
                airbyte_source_id="airbyte-source-123",
            )

    @pytest.mark.asyncio
    async def test_create_source_decryption_fails_raises(
        self, ingestion_service, mock_store
    ):
        """Should raise CredentialEncryptionError if decryption fails."""
        with patch("src.services.shopify_ingestion.decrypt_secret", new_callable=AsyncMock) as mock_decrypt:
            mock_decrypt.side_effect = Exception("Decryption failed")

            with pytest.raises(CredentialEncryptionError, match="Failed to decrypt access token"):
                await ingestion_service.create_shopify_source(
                    store=mock_store,
                    airbyte_source_id="airbyte-source-123",
                )

    @pytest.mark.asyncio
    async def test_create_source_registration_fails_raises(
        self, ingestion_service, mock_store
    ):
        """Should raise SourceConfigurationError if registration fails."""
        with patch("src.services.shopify_ingestion.decrypt_secret", new_callable=AsyncMock) as mock_decrypt:
            mock_decrypt.return_value = "decrypted-token"
            ingestion_service._airbyte_service.register_connection.side_effect = Exception(
                "Registration failed"
            )

            with pytest.raises(SourceConfigurationError, match="Failed to register source"):
                await ingestion_service.create_shopify_source(
                    store=mock_store,
                    airbyte_source_id="airbyte-source-123",
                )


class TestTriggerInitialSync:
    """Tests for trigger_initial_sync method."""

    @pytest.mark.asyncio
    async def test_trigger_sync_success_wait(
        self, ingestion_service, mock_connection_info
    ):
        """Should successfully trigger sync and wait for completion."""
        mock_sync_result = AirbyteSyncResult(
            job_id="job-123",
            status=AirbyteJobStatus.SUCCEEDED,
            connection_id="airbyte-conn-123",
            records_synced=1000,
            bytes_synced=5000000,
            duration_seconds=120.0,
        )

        with patch("src.services.shopify_ingestion.get_airbyte_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.sync_and_wait = AsyncMock(return_value=mock_sync_result)
            mock_client.close = AsyncMock()
            mock_get_client.return_value = mock_client

            result = await ingestion_service.trigger_initial_sync(
                connection_id=mock_connection_info.id,
                wait_for_completion=True,
            )

            assert result.success is True
            assert result.job_id == "job-123"
            assert result.records_synced == 1000
            assert result.bytes_synced == 5000000
            ingestion_service._airbyte_service.record_sync_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_sync_success_no_wait(
        self, ingestion_service, mock_connection_info
    ):
        """Should successfully trigger sync without waiting."""
        with patch("src.services.shopify_ingestion.get_airbyte_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.trigger_sync = AsyncMock(return_value="job-123")
            mock_client.close = AsyncMock()
            mock_get_client.return_value = mock_client

            result = await ingestion_service.trigger_initial_sync(
                connection_id=mock_connection_info.id,
                wait_for_completion=False,
            )

            assert result.success is True
            assert result.job_id == "job-123"
            mock_client.trigger_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_sync_connection_not_found_raises(
        self, ingestion_service
    ):
        """Should raise SyncExecutionError if connection not found."""
        ingestion_service._airbyte_service.get_connection.return_value = None

        with pytest.raises(SyncExecutionError, match="Connection.*not found"):
            await ingestion_service.trigger_initial_sync(connection_id="invalid-id")

    @pytest.mark.asyncio
    async def test_trigger_sync_connection_not_enabled_raises(
        self, ingestion_service, mock_connection_info
    ):
        """Should raise SyncExecutionError if connection is not enabled."""
        mock_connection_info.can_sync = False
        ingestion_service._airbyte_service.get_connection.return_value = mock_connection_info

        with pytest.raises(SyncExecutionError, match="is not enabled or active"):
            await ingestion_service.trigger_initial_sync(connection_id=mock_connection_info.id)

    @pytest.mark.asyncio
    async def test_trigger_sync_failure_marks_connection_failed(
        self, ingestion_service, mock_connection_info
    ):
        """Should mark connection as failed when sync fails."""
        mock_sync_result = AirbyteSyncResult(
            job_id="job-123",
            status=AirbyteJobStatus.FAILED,
            connection_id="airbyte-conn-123",
            error_message="Sync failed",
        )

        with patch("src.services.shopify_ingestion.get_airbyte_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.sync_and_wait = AsyncMock(return_value=mock_sync_result)
            mock_client.close = AsyncMock()
            mock_get_client.return_value = mock_client

            result = await ingestion_service.trigger_initial_sync(
                connection_id=mock_connection_info.id,
                wait_for_completion=True,
            )

            assert result.success is False
            ingestion_service._airbyte_service.mark_connection_failed.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_sync_airbyte_error_raises(
        self, ingestion_service, mock_connection_info
    ):
        """Should raise SyncExecutionError when Airbyte API error occurs."""
        with patch("src.services.shopify_ingestion.get_airbyte_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.sync_and_wait = AsyncMock(
                side_effect=AirbyteSyncError("Sync timeout", job_id="job-123")
            )
            mock_client.close = AsyncMock()
            mock_get_client.return_value = mock_client

            with pytest.raises(SyncExecutionError, match="Sync failed"):
                await ingestion_service.trigger_initial_sync(
                    connection_id=mock_connection_info.id,
                    wait_for_completion=True,
                )

            ingestion_service._airbyte_service.mark_connection_failed.assert_called_once()


class TestTriggerIncrementalSync:
    """Tests for trigger_incremental_sync method."""

    @pytest.mark.asyncio
    async def test_incremental_sync_calls_initial_sync(
        self, ingestion_service, mock_connection_info
    ):
        """Should call trigger_initial_sync for incremental sync."""
        with patch.object(
            ingestion_service, "trigger_initial_sync", new_callable=AsyncMock
        ) as mock_initial_sync:
            mock_initial_sync.return_value = SyncResult(
                success=True,
                job_id="job-123",
                connection_id=mock_connection_info.id,
            )

            await ingestion_service.trigger_incremental_sync(
                connection_id=mock_connection_info.id
            )

            mock_initial_sync.assert_called_once()


class TestSyncAllActiveStores:
    """Tests for sync_all_active_stores method."""

    @pytest.mark.asyncio
    async def test_sync_all_success(
        self, ingestion_service, mock_connection_info
    ):
        """Should sync all active stores successfully."""
        with patch.object(
            ingestion_service, "trigger_incremental_sync", new_callable=AsyncMock
        ) as mock_sync:
            mock_sync.return_value = SyncResult(
                success=True,
                job_id="job-123",
                connection_id=mock_connection_info.id,
                records_synced=500,
            )

            results = await ingestion_service.sync_all_active_stores()

            assert len(results) == 1
            assert results[mock_connection_info.id].success is True
            mock_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_all_with_failures(
        self, ingestion_service, mock_connection_info
    ):
        """Should handle failures gracefully when syncing all stores."""
        with patch.object(
            ingestion_service, "trigger_incremental_sync", new_callable=AsyncMock
        ) as mock_sync:
            mock_sync.side_effect = Exception("Sync failed")

            results = await ingestion_service.sync_all_active_stores()

            assert len(results) == 1
            assert results[mock_connection_info.id].success is False
            assert results[mock_connection_info.id].error_message == "Sync failed"

    @pytest.mark.asyncio
    async def test_sync_all_empty_list(
        self, ingestion_service
    ):
        """Should handle empty connection list gracefully."""
        ingestion_service._airbyte_service.list_connections.return_value = MagicMock(
            connections=[]
        )

        results = await ingestion_service.sync_all_active_stores()

        assert len(results) == 0


class TestGetSyncStatus:
    """Tests for get_sync_status method."""

    def test_get_status_success(self, ingestion_service, mock_connection_info):
        """Should return sync status for connection."""
        status = ingestion_service.get_sync_status(mock_connection_info.id)

        assert status is not None
        assert status["connection_id"] == mock_connection_info.id
        assert status["status"] == mock_connection_info.status
        assert status["is_enabled"] == mock_connection_info.is_enabled

    def test_get_status_not_found(self, ingestion_service):
        """Should return None if connection not found."""
        ingestion_service._airbyte_service.get_connection.return_value = None

        status = ingestion_service.get_sync_status("invalid-id")

        assert status is None
