"""
Tests for sync orchestration and retry logic.

CRITICAL: These tests verify that:
1. Syncs can be triggered via API
2. Automatic retries occur on failure
3. Failure status is persisted
4. Alerts are logged on failures
5. Tenant isolation is enforced

Story 3.5 - Sync Orchestration & Retry Logic
"""

import os
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set test environment
os.environ["ENV"] = "test"
os.environ["ENCRYPTION_KEY"] = "test-encryption-key-for-sync-retries"

from src.db_base import Base
from src.models.airbyte_connection import (
    TenantAirbyteConnection,
    ConnectionStatus,
    ConnectionType,
)
from src.integrations.airbyte.models import (
    AirbyteJobStatus,
    AirbyteSyncResult,
)
from src.integrations.airbyte.exceptions import (
    AirbyteError,
    AirbyteSyncError,
    AirbyteRateLimitError,
)
from src.services.sync_orchestrator import (
    SyncOrchestrator,
    SyncResult,
    SyncOrchestratorError,
    ConnectionNotFoundError,
    SyncFailedError,
    DEFAULT_MAX_RETRIES,
)


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
def successful_sync_result():
    """Create a successful sync result."""
    return AirbyteSyncResult(
        job_id="job-success-123",
        status=AirbyteJobStatus.SUCCEEDED,
        connection_id="airbyte-conn-123",
        records_synced=1000,
        bytes_synced=50000,
        duration_seconds=120.5,
    )


@pytest.fixture
def failed_sync_result():
    """Create a failed sync result."""
    return AirbyteSyncResult(
        job_id="job-fail-456",
        status=AirbyteJobStatus.FAILED,
        connection_id="airbyte-conn-123",
        records_synced=0,
        bytes_synced=0,
        duration_seconds=10.0,
        error_message="Connection timeout",
    )


# =============================================================================
# Connection Setup Fixtures
# =============================================================================

@pytest.fixture
def create_connection(db_session, tenant_id):
    """Factory to create test connections."""
    def _create(
        status: ConnectionStatus = ConnectionStatus.ACTIVE,
        is_enabled: bool = True,
        last_sync_status: str = None,
    ) -> TenantAirbyteConnection:
        connection = TenantAirbyteConnection(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            airbyte_connection_id=f"airbyte-{uuid.uuid4().hex[:8]}",
            connection_name="Test Connection",
            connection_type=ConnectionType.SOURCE,
            source_type="test-source",
            status=status,
            is_enabled=is_enabled,
            last_sync_status=last_sync_status,
        )
        db_session.add(connection)
        db_session.commit()
        return connection

    return _create


@pytest.fixture
def orchestrator(db_session, tenant_id, mock_airbyte_client):
    """Create SyncOrchestrator for testing."""
    return SyncOrchestrator(
        db_session=db_session,
        tenant_id=tenant_id,
        airbyte_client=mock_airbyte_client,
        max_retries=2,  # Use fewer retries for faster tests
        base_delay_seconds=0.01,  # Minimal delay for tests
        max_delay_seconds=0.1,
    )


# =============================================================================
# Test: Service Initialization
# =============================================================================

class TestServiceInitialization:
    """Tests for SyncOrchestrator initialization."""

    def test_requires_tenant_id(self, db_session):
        """Service requires tenant_id."""
        with pytest.raises(ValueError, match="tenant_id is required"):
            SyncOrchestrator(db_session, "")

        with pytest.raises(ValueError, match="tenant_id is required"):
            SyncOrchestrator(db_session, None)

    def test_initializes_with_valid_tenant_id(self, db_session, tenant_id):
        """Service initializes with valid tenant_id."""
        orchestrator = SyncOrchestrator(db_session, tenant_id)
        assert orchestrator.tenant_id == tenant_id

    def test_configurable_retry_settings(self, db_session, tenant_id):
        """Retry settings can be configured."""
        orchestrator = SyncOrchestrator(
            db_session,
            tenant_id,
            max_retries=5,
            base_delay_seconds=1.0,
            max_delay_seconds=30.0,
        )
        assert orchestrator.max_retries == 5
        assert orchestrator.base_delay_seconds == 1.0
        assert orchestrator.max_delay_seconds == 30.0


# =============================================================================
# Test: Sync Success on First Attempt
# =============================================================================

class TestSyncSuccess:
    """Tests for successful sync operations."""

    @pytest.mark.asyncio
    async def test_sync_succeeds_first_attempt(
        self, orchestrator, create_connection, mock_airbyte_client, successful_sync_result
    ):
        """Sync succeeds on first attempt."""
        connection = create_connection()
        mock_airbyte_client.sync_and_wait.return_value = successful_sync_result

        result = await orchestrator.trigger_sync_with_retry(connection.id)

        assert result.is_successful is True
        assert result.status == "succeeded"
        assert result.attempt_count == 1
        assert result.records_synced == 1000
        assert result.error_message is None
        mock_airbyte_client.sync_and_wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_updates_connection_status_on_success(
        self, orchestrator, create_connection, mock_airbyte_client, successful_sync_result, db_session
    ):
        """Sync updates connection status to success."""
        connection = create_connection()
        mock_airbyte_client.sync_and_wait.return_value = successful_sync_result

        await orchestrator.trigger_sync_with_retry(connection.id)

        db_session.refresh(connection)
        assert connection.status == ConnectionStatus.ACTIVE
        assert connection.last_sync_status == "success"


# =============================================================================
# Test: Retry Logic
# =============================================================================

class TestRetryLogic:
    """Tests for retry logic on failures."""

    @pytest.mark.asyncio
    async def test_retries_on_failure(
        self, orchestrator, create_connection, mock_airbyte_client, successful_sync_result
    ):
        """Sync retries on failure and eventually succeeds."""
        connection = create_connection()

        # Fail twice, then succeed
        mock_airbyte_client.sync_and_wait.side_effect = [
            AirbyteSyncError("First failure", job_id="job-1"),
            AirbyteSyncError("Second failure", job_id="job-2"),
            successful_sync_result,
        ]

        result = await orchestrator.trigger_sync_with_retry(connection.id)

        assert result.is_successful is True
        assert result.attempt_count == 3
        assert mock_airbyte_client.sync_and_wait.call_count == 3

    @pytest.mark.asyncio
    async def test_fails_after_max_retries(
        self, orchestrator, create_connection, mock_airbyte_client
    ):
        """Sync fails after exhausting all retries."""
        connection = create_connection()

        # Always fail
        mock_airbyte_client.sync_and_wait.side_effect = AirbyteSyncError(
            "Persistent failure", job_id="job-fail"
        )

        result = await orchestrator.trigger_sync_with_retry(connection.id)

        # With max_retries=2, we get 3 total attempts (initial + 2 retries)
        assert result.is_successful is False
        assert result.status == "failed"
        assert result.attempt_count == 3  # Initial + 2 retries
        assert result.error_message == "Persistent failure"
        assert mock_airbyte_client.sync_and_wait.call_count == 3

    @pytest.mark.asyncio
    async def test_handles_rate_limiting(
        self, orchestrator, create_connection, mock_airbyte_client, successful_sync_result
    ):
        """Sync handles rate limit errors with appropriate delay."""
        connection = create_connection()

        # Rate limit then succeed
        mock_airbyte_client.sync_and_wait.side_effect = [
            AirbyteRateLimitError(retry_after=1),
            successful_sync_result,
        ]

        result = await orchestrator.trigger_sync_with_retry(connection.id)

        assert result.is_successful is True
        assert result.attempt_count == 2

    @pytest.mark.asyncio
    async def test_exponential_backoff_calculation(self, db_session, tenant_id):
        """Backoff delay increases exponentially."""
        orchestrator = SyncOrchestrator(
            db_session,
            tenant_id,
            base_delay_seconds=2.0,
            max_delay_seconds=60.0,
        )

        assert orchestrator._calculate_backoff_delay(0) == 2.0   # 2 * 2^0 = 2
        assert orchestrator._calculate_backoff_delay(1) == 4.0   # 2 * 2^1 = 4
        assert orchestrator._calculate_backoff_delay(2) == 8.0   # 2 * 2^2 = 8
        assert orchestrator._calculate_backoff_delay(3) == 16.0  # 2 * 2^3 = 16
        assert orchestrator._calculate_backoff_delay(10) == 60.0  # Capped at max

    @pytest.mark.asyncio
    async def test_backoff_capped_at_max_delay(self, db_session, tenant_id):
        """Backoff delay is capped at max_delay_seconds."""
        orchestrator = SyncOrchestrator(
            db_session,
            tenant_id,
            base_delay_seconds=10.0,
            max_delay_seconds=30.0,
        )

        # 10 * 2^3 = 80, but should be capped at 30
        assert orchestrator._calculate_backoff_delay(3) == 30.0


# =============================================================================
# Test: Failure Status Persistence
# =============================================================================

class TestFailureStatusPersistence:
    """Tests for persisting failure status."""

    @pytest.mark.asyncio
    async def test_persists_failure_status_after_retries(
        self, orchestrator, create_connection, mock_airbyte_client, db_session
    ):
        """Failure status is persisted after all retries exhausted."""
        connection = create_connection()

        mock_airbyte_client.sync_and_wait.side_effect = AirbyteSyncError(
            "Persistent failure", job_id="job-fail"
        )

        await orchestrator.trigger_sync_with_retry(connection.id)

        db_session.refresh(connection)
        assert connection.status == ConnectionStatus.FAILED
        assert connection.last_sync_status == "failed"

    @pytest.mark.asyncio
    async def test_get_sync_state_shows_failure(
        self, orchestrator, create_connection, mock_airbyte_client
    ):
        """Sync state reflects failure after retries exhausted."""
        connection = create_connection()

        mock_airbyte_client.sync_and_wait.side_effect = AirbyteSyncError(
            "Failure", job_id="job-fail"
        )

        await orchestrator.trigger_sync_with_retry(connection.id)

        state = orchestrator.get_sync_state(connection.id)

        assert state["status"] == "failed"
        assert state["last_sync_status"] == "failed"

    @pytest.mark.asyncio
    async def test_get_failed_connections_includes_failed(
        self, orchestrator, create_connection, mock_airbyte_client
    ):
        """Failed connections appear in failed connections list."""
        connection = create_connection()

        mock_airbyte_client.sync_and_wait.side_effect = AirbyteSyncError(
            "Failure", job_id="job-fail"
        )

        await orchestrator.trigger_sync_with_retry(connection.id)

        failed = orchestrator.get_failed_connections()

        assert len(failed) == 1
        assert failed[0]["connection_id"] == connection.id


# =============================================================================
# Test: Alert Logging
# =============================================================================

class TestAlertLogging:
    """Tests for alert logging on failures."""

    @pytest.mark.asyncio
    async def test_logs_failure_alert(
        self, orchestrator, create_connection, mock_airbyte_client, caplog
    ):
        """Failure alert is logged after retries exhausted."""
        connection = create_connection()

        mock_airbyte_client.sync_and_wait.side_effect = AirbyteSyncError(
            "Critical failure", job_id="job-fail"
        )

        with caplog.at_level("ERROR"):
            await orchestrator.trigger_sync_with_retry(connection.id)

        # Check that failure alert was logged
        assert any(
            "SYNC_FAILURE_ALERT" in record.message
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_logs_retry_attempts(
        self, orchestrator, create_connection, mock_airbyte_client, successful_sync_result, caplog
    ):
        """Retry attempts are logged."""
        connection = create_connection()

        mock_airbyte_client.sync_and_wait.side_effect = [
            AirbyteSyncError("Failure", job_id="job-1"),
            successful_sync_result,
        ]

        with caplog.at_level("INFO"):
            await orchestrator.trigger_sync_with_retry(connection.id)

        # Check that retry was logged
        assert any(
            "Retrying sync after delay" in record.message
            for record in caplog.records
        )


# =============================================================================
# Test: Connection State Validation
# =============================================================================

class TestConnectionStateValidation:
    """Tests for connection state validation before sync."""

    @pytest.mark.asyncio
    async def test_cannot_sync_disabled_connection(
        self, orchestrator, create_connection
    ):
        """Cannot sync a disabled connection."""
        connection = create_connection(is_enabled=False)

        with pytest.raises(SyncOrchestratorError, match="cannot sync"):
            await orchestrator.trigger_sync_with_retry(connection.id)

    @pytest.mark.asyncio
    async def test_cannot_sync_deleted_connection(
        self, orchestrator, create_connection
    ):
        """Cannot sync a deleted connection."""
        connection = create_connection(status=ConnectionStatus.DELETED)

        with pytest.raises(SyncOrchestratorError, match="cannot sync"):
            await orchestrator.trigger_sync_with_retry(connection.id)

    @pytest.mark.asyncio
    async def test_can_sync_pending_connection(
        self, orchestrator, create_connection, mock_airbyte_client, successful_sync_result
    ):
        """Can sync a pending connection."""
        connection = create_connection(status=ConnectionStatus.PENDING)
        mock_airbyte_client.sync_and_wait.return_value = successful_sync_result

        result = await orchestrator.trigger_sync_with_retry(connection.id)

        assert result.is_successful is True


# =============================================================================
# Test: Connection Not Found
# =============================================================================

class TestConnectionNotFound:
    """Tests for handling missing connections."""

    @pytest.mark.asyncio
    async def test_sync_nonexistent_connection_raises_error(self, orchestrator):
        """Sync raises error for nonexistent connection."""
        with pytest.raises(ConnectionNotFoundError):
            await orchestrator.trigger_sync_with_retry("nonexistent-id")

    def test_get_sync_state_nonexistent_raises_error(self, orchestrator):
        """Get sync state raises error for nonexistent connection."""
        with pytest.raises(ConnectionNotFoundError):
            orchestrator.get_sync_state("nonexistent-id")


# =============================================================================
# Test: Tenant Isolation
# =============================================================================

class TestTenantIsolation:
    """Tests for tenant isolation."""

    @pytest.mark.asyncio
    async def test_cannot_sync_other_tenant_connection(
        self, db_session, tenant_id, other_tenant_id, mock_airbyte_client
    ):
        """Cannot sync connection belonging to another tenant."""
        # Create connection for tenant A
        connection = TenantAirbyteConnection(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            airbyte_connection_id=f"airbyte-{uuid.uuid4().hex[:8]}",
            connection_name="Tenant A Connection",
            connection_type=ConnectionType.SOURCE,
            source_type="test-source",
            status=ConnectionStatus.ACTIVE,
            is_enabled=True,
        )
        db_session.add(connection)
        db_session.commit()

        # Try to sync as tenant B
        orchestrator_b = SyncOrchestrator(
            db_session, other_tenant_id, mock_airbyte_client
        )

        with pytest.raises(ConnectionNotFoundError):
            await orchestrator_b.trigger_sync_with_retry(connection.id)

    def test_get_sync_state_tenant_isolation(
        self, db_session, tenant_id, other_tenant_id, mock_airbyte_client
    ):
        """Get sync state enforces tenant isolation."""
        # Create connection for tenant A
        connection = TenantAirbyteConnection(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            airbyte_connection_id=f"airbyte-{uuid.uuid4().hex[:8]}",
            connection_name="Tenant A Connection",
            connection_type=ConnectionType.SOURCE,
            source_type="test-source",
            status=ConnectionStatus.ACTIVE,
            is_enabled=True,
        )
        db_session.add(connection)
        db_session.commit()

        # Try to get state as tenant B
        orchestrator_b = SyncOrchestrator(
            db_session, other_tenant_id, mock_airbyte_client
        )

        with pytest.raises(ConnectionNotFoundError):
            orchestrator_b.get_sync_state(connection.id)

    @pytest.mark.asyncio
    async def test_failed_connections_only_shows_own_tenant(
        self, db_session, tenant_id, other_tenant_id, mock_airbyte_client
    ):
        """Failed connections list only shows connections for current tenant."""
        # Create failed connection for tenant A
        conn_a = TenantAirbyteConnection(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            airbyte_connection_id=f"airbyte-a-{uuid.uuid4().hex[:8]}",
            connection_name="Tenant A Failed Connection",
            connection_type=ConnectionType.SOURCE,
            source_type="test-source",
            status=ConnectionStatus.FAILED,
            is_enabled=True,
            last_sync_status="failed",
        )
        db_session.add(conn_a)

        # Create failed connection for tenant B
        conn_b = TenantAirbyteConnection(
            id=str(uuid.uuid4()),
            tenant_id=other_tenant_id,
            airbyte_connection_id=f"airbyte-b-{uuid.uuid4().hex[:8]}",
            connection_name="Tenant B Failed Connection",
            connection_type=ConnectionType.SOURCE,
            source_type="test-source",
            status=ConnectionStatus.FAILED,
            is_enabled=True,
            last_sync_status="failed",
        )
        db_session.add(conn_b)
        db_session.commit()

        # Check tenant A sees only their connection
        orchestrator_a = SyncOrchestrator(
            db_session, tenant_id, mock_airbyte_client
        )
        failed_a = orchestrator_a.get_failed_connections()
        assert len(failed_a) == 1
        assert failed_a[0]["connection_id"] == conn_a.id

        # Check tenant B sees only their connection
        orchestrator_b = SyncOrchestrator(
            db_session, other_tenant_id, mock_airbyte_client
        )
        failed_b = orchestrator_b.get_failed_connections()
        assert len(failed_b) == 1
        assert failed_b[0]["connection_id"] == conn_b.id


# =============================================================================
# Test: Sync Result Data
# =============================================================================

class TestSyncResultData:
    """Tests for sync result data accuracy."""

    @pytest.mark.asyncio
    async def test_result_contains_all_fields(
        self, orchestrator, create_connection, mock_airbyte_client, successful_sync_result
    ):
        """Sync result contains all expected fields."""
        connection = create_connection()
        mock_airbyte_client.sync_and_wait.return_value = successful_sync_result

        result = await orchestrator.trigger_sync_with_retry(connection.id)

        assert result.connection_id == connection.id
        assert result.job_id == "job-success-123"
        assert result.status == "succeeded"
        assert result.is_successful is True
        assert result.records_synced == 1000
        assert result.bytes_synced == 50000
        assert result.duration_seconds == 120.5
        assert result.attempt_count == 1
        assert result.max_retries == 3  # initial + 2 retries
        assert result.error_message is None
        assert isinstance(result.completed_at, datetime)

    @pytest.mark.asyncio
    async def test_failed_result_contains_error(
        self, orchestrator, create_connection, mock_airbyte_client
    ):
        """Failed sync result contains error message."""
        connection = create_connection()
        mock_airbyte_client.sync_and_wait.side_effect = AirbyteSyncError(
            "Connection timeout", job_id="job-fail"
        )

        result = await orchestrator.trigger_sync_with_retry(connection.id)

        assert result.is_successful is False
        assert result.error_message == "Connection timeout"
        assert result.records_synced == 0


# =============================================================================
# Test: Various Airbyte Error Types
# =============================================================================

class TestAirbyteErrorHandling:
    """Tests for handling various Airbyte error types."""

    @pytest.mark.asyncio
    async def test_handles_generic_airbyte_error(
        self, orchestrator, create_connection, mock_airbyte_client
    ):
        """Handles generic Airbyte errors."""
        connection = create_connection()
        mock_airbyte_client.sync_and_wait.side_effect = AirbyteError(
            "API Error", status_code=500
        )

        result = await orchestrator.trigger_sync_with_retry(connection.id)

        assert result.is_successful is False
        assert "API Error" in result.error_message

    @pytest.mark.asyncio
    async def test_handles_sync_error_with_job_id(
        self, orchestrator, create_connection, mock_airbyte_client
    ):
        """Handles sync errors that include job ID."""
        connection = create_connection()
        mock_airbyte_client.sync_and_wait.side_effect = AirbyteSyncError(
            "Sync failed", job_id="job-xyz-789"
        )

        result = await orchestrator.trigger_sync_with_retry(connection.id)

        assert result.is_successful is False
        assert result.job_id == "job-xyz-789"
