"""
Unit tests for Airbyte client.

Tests cover:
- Client initialization and validation
- Health check requests
- Connection listing and retrieval
- Sync triggering and monitoring
- Error handling for various HTTP status codes
- Timeout and connection error handling
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

import httpx

from src.integrations.airbyte.client import (
    AirbyteClient,
    get_airbyte_client,
    DEFAULT_BASE_URL,
)
from src.integrations.airbyte.exceptions import (
    AirbyteError,
    AirbyteAuthenticationError,
    AirbyteRateLimitError,
    AirbyteConnectionError,
    AirbyteSyncError,
    AirbyteNotFoundError,
)
from src.integrations.airbyte.models import (
    AirbyteHealth,
    AirbyteConnection,
    AirbyteJob,
    AirbyteJobStatus,
    AirbyteSyncResult,
    ConnectionStatus,
)


# Test fixtures
@pytest.fixture
def mock_env(monkeypatch):
    """Set up mock environment variables."""
    monkeypatch.setenv("AIRBYTE_API_TOKEN", "test-token-12345")
    monkeypatch.setenv("AIRBYTE_WORKSPACE_ID", "test-workspace-id")
    monkeypatch.setenv("AIRBYTE_BASE_URL", "https://api.airbyte.test/v1")


@pytest.fixture
def client(mock_env):
    """Create a test client instance."""
    return AirbyteClient()


class TestAirbyteClientInitialization:
    """Tests for client initialization."""

    def test_init_with_env_vars(self, mock_env):
        """Client should initialize from environment variables."""
        client = AirbyteClient()
        assert client.api_token == "test-token-12345"
        assert client.workspace_id == "test-workspace-id"
        assert client.base_url == "https://api.airbyte.test/v1"

    def test_init_with_explicit_params(self, mock_env):
        """Client should prefer explicit parameters over env vars."""
        client = AirbyteClient(
            base_url="https://custom.api.com/v1",
            api_token="custom-token",
            workspace_id="custom-workspace",
        )
        assert client.api_token == "custom-token"
        assert client.workspace_id == "custom-workspace"
        assert client.base_url == "https://custom.api.com/v1"

    def test_init_strips_trailing_slash(self, mock_env):
        """Base URL should not have trailing slash."""
        client = AirbyteClient(base_url="https://api.airbyte.test/v1/")
        assert client.base_url == "https://api.airbyte.test/v1"

    def test_init_missing_token_raises(self, monkeypatch):
        """Should raise ValueError if API token is missing."""
        monkeypatch.delenv("AIRBYTE_API_TOKEN", raising=False)
        monkeypatch.setenv("AIRBYTE_WORKSPACE_ID", "test-workspace")

        with pytest.raises(ValueError, match="API token is required"):
            AirbyteClient()

    def test_init_missing_workspace_raises(self, monkeypatch):
        """Should raise ValueError if workspace ID is missing."""
        monkeypatch.setenv("AIRBYTE_API_TOKEN", "test-token")
        monkeypatch.delenv("AIRBYTE_WORKSPACE_ID", raising=False)

        with pytest.raises(ValueError, match="workspace ID is required"):
            AirbyteClient()

    def test_factory_function(self, mock_env):
        """Factory function should create client correctly."""
        client = get_airbyte_client()
        assert client.api_token == "test-token-12345"
        assert client.workspace_id == "test-workspace-id"


class TestAirbyteClientHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_success(self, client):
        """Should return health status on success."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"available": True, "db": True}

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            health = await client.check_health()

            assert health.available is True
            assert health.db is True
            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_unavailable(self, client):
        """Should return unavailable status when API is down."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"available": False, "db": False}

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            health = await client.check_health()

            assert health.available is False

    @pytest.mark.asyncio
    async def test_health_check_auth_failure(self, client):
        """Should raise AirbyteAuthenticationError on 401."""
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            with pytest.raises(AirbyteAuthenticationError):
                await client.check_health()


class TestAirbyteClientConnections:
    """Tests for connection management."""

    @pytest.mark.asyncio
    async def test_list_connections_success(self, client):
        """Should list connections successfully."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "connectionId": "conn-1",
                    "name": "Test Connection",
                    "sourceId": "src-1",
                    "destinationId": "dest-1",
                    "status": "active",
                },
                {
                    "connectionId": "conn-2",
                    "name": "Another Connection",
                    "sourceId": "src-2",
                    "destinationId": "dest-2",
                    "status": "inactive",
                },
            ]
        }

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            connections = await client.list_connections()

            assert len(connections) == 2
            assert connections[0].connection_id == "conn-1"
            assert connections[0].name == "Test Connection"
            assert connections[0].status == ConnectionStatus.ACTIVE
            assert connections[1].status == ConnectionStatus.INACTIVE

    @pytest.mark.asyncio
    async def test_list_connections_empty(self, client):
        """Should return empty list when no connections exist."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            connections = await client.list_connections()

            assert len(connections) == 0

    @pytest.mark.asyncio
    async def test_get_connection_success(self, client):
        """Should get a specific connection by ID."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "connectionId": "conn-1",
            "name": "Test Connection",
            "sourceId": "src-1",
            "destinationId": "dest-1",
            "status": "active",
        }

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            connection = await client.get_connection("conn-1")

            assert connection.connection_id == "conn-1"
            assert connection.name == "Test Connection"

    @pytest.mark.asyncio
    async def test_get_connection_not_found(self, client):
        """Should raise AirbyteNotFoundError when connection not found."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            with pytest.raises(AirbyteNotFoundError):
                await client.get_connection("nonexistent")


class TestAirbyteClientSync:
    """Tests for sync operations."""

    @pytest.mark.asyncio
    async def test_trigger_sync_success(self, client):
        """Should trigger sync and return job ID."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"jobId": "job-12345"}

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            job_id = await client.trigger_sync("conn-1")

            assert job_id == "job-12345"
            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_job_success(self, client):
        """Should get job status successfully."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "job": {
                "id": "job-12345",
                "configType": "sync",
                "configId": "conn-1",
                "status": "succeeded",
                "createdAt": 1704067200,
                "updatedAt": 1704070800,
                "attempts": [
                    {
                        "attemptNumber": 0,
                        "status": "succeeded",
                        "recordsSynced": 1000,
                        "bytesSynced": 50000,
                    }
                ],
            }
        }

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            job = await client.get_job("job-12345")

            assert job.job_id == "job-12345"
            assert job.status == AirbyteJobStatus.SUCCEEDED
            assert job.is_successful is True
            assert job.is_complete is True
            assert len(job.attempts) == 1

    @pytest.mark.asyncio
    async def test_get_job_running(self, client):
        """Should identify running job correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "job": {
                "id": "job-12345",
                "configType": "sync",
                "configId": "conn-1",
                "status": "running",
                "attempts": [],
            }
        }

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            job = await client.get_job("job-12345")

            assert job.status == AirbyteJobStatus.RUNNING
            assert job.is_running is True
            assert job.is_complete is False

    @pytest.mark.asyncio
    async def test_cancel_job_success(self, client):
        """Should cancel a running job."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "job": {
                "id": "job-12345",
                "status": "cancelled",
                "configType": "sync",
                "configId": "conn-1",
            }
        }

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            job = await client.cancel_job("job-12345")

            assert job.status == AirbyteJobStatus.CANCELLED


class TestAirbyteClientWaitForSync:
    """Tests for wait_for_sync functionality."""

    @pytest.mark.asyncio
    async def test_wait_for_sync_immediate_success(self, client):
        """Should return immediately when job is already complete."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "job": {
                "id": "job-12345",
                "configType": "sync",
                "configId": "conn-1",
                "status": "succeeded",
                "attempts": [
                    {
                        "attemptNumber": 0,
                        "status": "succeeded",
                        "recordsSynced": 500,
                        "bytesSynced": 25000,
                    }
                ],
            }
        }

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await client.wait_for_sync(
                "job-12345",
                timeout_seconds=10,
                poll_interval_seconds=1,
            )

            assert result.is_successful is True
            assert result.records_synced == 500
            assert result.bytes_synced == 25000

    @pytest.mark.asyncio
    async def test_wait_for_sync_polls_until_complete(self, client):
        """Should poll until job completes."""
        running_response = MagicMock()
        running_response.status_code = 200
        running_response.json.return_value = {
            "job": {
                "id": "job-12345",
                "configType": "sync",
                "configId": "conn-1",
                "status": "running",
                "attempts": [],
            }
        }

        completed_response = MagicMock()
        completed_response.status_code = 200
        completed_response.json.return_value = {
            "job": {
                "id": "job-12345",
                "configType": "sync",
                "configId": "conn-1",
                "status": "succeeded",
                "attempts": [
                    {
                        "attemptNumber": 0,
                        "status": "succeeded",
                        "recordsSynced": 100,
                        "bytesSynced": 5000,
                    }
                ],
            }
        }

        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return running_response
            return completed_response

        with patch.object(client._client, "request", side_effect=mock_request):
            result = await client.wait_for_sync(
                "job-12345",
                timeout_seconds=60,
                poll_interval_seconds=0.1,
            )

            assert result.is_successful is True
            assert call_count == 3

    @pytest.mark.asyncio
    async def test_wait_for_sync_timeout(self, client):
        """Should raise AirbyteSyncError on timeout."""
        running_response = MagicMock()
        running_response.status_code = 200
        running_response.json.return_value = {
            "job": {
                "id": "job-12345",
                "configType": "sync",
                "configId": "conn-1",
                "status": "running",
                "attempts": [],
            }
        }

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = running_response

            with pytest.raises(AirbyteSyncError, match="timed out"):
                await client.wait_for_sync(
                    "job-12345",
                    timeout_seconds=0.2,
                    poll_interval_seconds=0.1,
                )


class TestAirbyteClientErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, client):
        """Should raise AirbyteRateLimitError on 429."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            with pytest.raises(AirbyteRateLimitError) as exc_info:
                await client.check_health()

            assert exc_info.value.retry_after == 60

    @pytest.mark.asyncio
    async def test_forbidden_error(self, client):
        """Should raise AirbyteAuthenticationError on 403."""
        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            with pytest.raises(AirbyteAuthenticationError) as exc_info:
                await client.check_health()

            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_generic_server_error(self, client):
        """Should raise AirbyteError on 5xx errors."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "Internal Server Error"}

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            with pytest.raises(AirbyteError) as exc_info:
                await client.check_health()

            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_timeout_error(self, client):
        """Should raise AirbyteConnectionError on timeout."""
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = httpx.TimeoutException("Connection timed out")

            with pytest.raises(AirbyteConnectionError, match="timeout"):
                await client.check_health()

    @pytest.mark.asyncio
    async def test_connection_error(self, client):
        """Should raise AirbyteConnectionError on network failure."""
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = httpx.ConnectError("Connection refused")

            with pytest.raises(AirbyteConnectionError, match="Connection error"):
                await client.check_health()


class TestAirbyteClientContextManager:
    """Tests for async context manager behavior."""

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self, mock_env):
        """Context manager should close client on exit."""
        async with AirbyteClient() as client:
            assert client._client is not None

        # After exiting context, client should be closed
        assert client._client.is_closed

    @pytest.mark.asyncio
    async def test_manual_close(self, mock_env):
        """Manual close should work correctly."""
        client = AirbyteClient()
        await client.close()
        assert client._client.is_closed


class TestAirbyteModels:
    """Tests for data model parsing."""

    def test_health_from_dict(self):
        """Should parse health response correctly."""
        data = {"available": True, "db": True}
        health = AirbyteHealth.from_dict(data)
        assert health.available is True
        assert health.db is True

    def test_health_from_dict_defaults(self):
        """Should use defaults for missing fields."""
        data = {}
        health = AirbyteHealth.from_dict(data)
        assert health.available is False
        assert health.db is True

    def test_connection_from_dict(self):
        """Should parse connection response correctly."""
        data = {
            "connectionId": "conn-123",
            "name": "Test Connection",
            "sourceId": "src-456",
            "destinationId": "dest-789",
            "status": "active",
            "schedule": {
                "scheduleType": "basic",
            },
        }
        connection = AirbyteConnection.from_dict(data)
        assert connection.connection_id == "conn-123"
        assert connection.name == "Test Connection"
        assert connection.status == ConnectionStatus.ACTIVE

    def test_job_from_dict(self):
        """Should parse job response correctly."""
        data = {
            "job": {
                "id": "job-123",
                "configType": "sync",
                "configId": "conn-456",
                "status": "succeeded",
                "createdAt": 1704067200,
                "updatedAt": 1704070800,
                "attempts": [
                    {
                        "attemptNumber": 0,
                        "status": "succeeded",
                        "recordsSynced": 1000,
                        "bytesSynced": 50000,
                    }
                ],
            }
        }
        job = AirbyteJob.from_dict(data)
        assert job.job_id == "job-123"
        assert job.status == AirbyteJobStatus.SUCCEEDED
        assert job.is_successful is True
        assert len(job.attempts) == 1
        assert job.attempts[0].records_synced == 1000

    def test_sync_result_properties(self):
        """Should have correct computed properties."""
        result = AirbyteSyncResult(
            job_id="job-123",
            status=AirbyteJobStatus.SUCCEEDED,
            connection_id="conn-456",
            records_synced=1000,
            bytes_synced=50000,
            duration_seconds=120.5,
        )
        assert result.is_successful is True

        failed_result = AirbyteSyncResult(
            job_id="job-124",
            status=AirbyteJobStatus.FAILED,
            connection_id="conn-456",
            error_message="Sync failed",
        )
        assert failed_result.is_successful is False
