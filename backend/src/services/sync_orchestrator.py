"""
Sync orchestration service with automatic retry logic.

This service orchestrates:
- Manual sync triggering via API
- Automatic retries with exponential backoff
- Failure status persistence
- Alert logging for sync failures

SECURITY: All operations are tenant-scoped via tenant_id from JWT.

Story 3.5 - Sync Orchestration & Retry Logic
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.integrations.airbyte.client import AirbyteClient, get_airbyte_client
from src.integrations.airbyte.exceptions import (
    AirbyteError,
    AirbyteRateLimitError,
    AirbyteSyncError,
)
from src.integrations.airbyte.models import AirbyteJobStatus
from src.services.airbyte_service import (
    AirbyteService,
    ConnectionNotFoundServiceError,
)

logger = logging.getLogger(__name__)

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY_SECONDS = 2.0
DEFAULT_MAX_DELAY_SECONDS = 60.0
DEFAULT_SYNC_TIMEOUT_SECONDS = 3600


@dataclass
class SyncResult:
    """Result of a sync operation with retry information."""
    connection_id: str
    job_id: Optional[str]
    status: str
    is_successful: bool
    records_synced: int
    bytes_synced: int
    duration_seconds: Optional[float]
    attempt_count: int
    max_retries: int
    error_message: Optional[str]
    completed_at: datetime


class SyncOrchestratorError(Exception):
    """Base exception for sync orchestrator errors."""
    pass


class ConnectionNotFoundError(SyncOrchestratorError):
    """Connection not found within tenant scope."""
    pass


class SyncFailedError(SyncOrchestratorError):
    """Sync failed after all retry attempts."""

    def __init__(
        self,
        message: str,
        connection_id: str,
        attempt_count: int,
        last_error: Optional[str] = None,
    ):
        super().__init__(message)
        self.connection_id = connection_id
        self.attempt_count = attempt_count
        self.last_error = last_error


class SyncOrchestrator:
    """
    Orchestrates sync operations with automatic retry logic.

    Provides:
    - Manual sync triggering with retries
    - Exponential backoff on failures
    - Status persistence after each attempt
    - Structured alert logging for failures

    SECURITY: All methods require tenant_id from JWT context.
    """

    def __init__(
        self,
        db_session: Session,
        tenant_id: str,
        airbyte_client: Optional[AirbyteClient] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
        max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS,
    ):
        """
        Initialize sync orchestrator.

        Args:
            db_session: Database session
            tenant_id: Tenant ID from JWT (org_id)
            airbyte_client: Optional Airbyte client (creates default if not provided)
            max_retries: Maximum retry attempts (default: 3)
            base_delay_seconds: Initial backoff delay (default: 2s)
            max_delay_seconds: Maximum backoff delay (default: 60s)

        Raises:
            ValueError: If tenant_id is empty or None
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id
        self._airbyte_service = AirbyteService(db_session, tenant_id)
        self._airbyte_client = airbyte_client
        self.max_retries = max_retries
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds

    def _get_airbyte_client(self) -> AirbyteClient:
        """Get or create Airbyte client."""
        if self._airbyte_client is None:
            self._airbyte_client = get_airbyte_client()
        return self._airbyte_client

    def _calculate_backoff_delay(self, attempt: int) -> float:
        """
        Calculate exponential backoff delay.

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        delay = self.base_delay_seconds * (2 ** attempt)
        return min(delay, self.max_delay_seconds)

    async def trigger_sync_with_retry(
        self,
        connection_id: str,
        timeout_seconds: float = DEFAULT_SYNC_TIMEOUT_SECONDS,
    ) -> SyncResult:
        """
        Trigger a sync with automatic retry on failure.

        Implements exponential backoff retry logic. On final failure,
        persists failed status and logs alert.

        Args:
            connection_id: Internal connection ID
            timeout_seconds: Maximum wait time per sync attempt

        Returns:
            SyncResult with final status and retry information

        Raises:
            ConnectionNotFoundError: If connection not found
            SyncFailedError: If sync fails after all retries
        """
        connection = self._airbyte_service.get_connection(connection_id)
        if not connection:
            raise ConnectionNotFoundError(f"Connection {connection_id} not found")

        if not connection.can_sync:
            raise SyncOrchestratorError(
                f"Connection {connection_id} cannot sync: "
                f"status={connection.status}, enabled={connection.is_enabled}"
            )

        last_error: Optional[str] = None
        last_job_id: Optional[str] = None
        attempt = 0

        while attempt <= self.max_retries:
            try:
                logger.info(
                    "Sync attempt starting",
                    extra={
                        "tenant_id": self.tenant_id,
                        "connection_id": connection_id,
                        "attempt": attempt + 1,
                        "max_retries": self.max_retries + 1,
                    },
                )

                result = await self._execute_sync(
                    connection_id=connection_id,
                    airbyte_connection_id=connection.airbyte_connection_id,
                    timeout_seconds=timeout_seconds,
                )

                # Sync succeeded - persist success status
                self._airbyte_service.record_sync_success(connection_id)

                logger.info(
                    "Sync completed successfully",
                    extra={
                        "tenant_id": self.tenant_id,
                        "connection_id": connection_id,
                        "job_id": result.job_id,
                        "records_synced": result.records_synced,
                        "attempt": attempt + 1,
                    },
                )

                return SyncResult(
                    connection_id=connection_id,
                    job_id=result.job_id,
                    status="succeeded",
                    is_successful=True,
                    records_synced=result.records_synced,
                    bytes_synced=result.bytes_synced,
                    duration_seconds=result.duration_seconds,
                    attempt_count=attempt + 1,
                    max_retries=self.max_retries + 1,
                    error_message=None,
                    completed_at=datetime.now(timezone.utc),
                )

            except (AirbyteSyncError, AirbyteError) as e:
                last_error = str(e)
                last_job_id = getattr(e, "job_id", None)

                logger.warning(
                    "Sync attempt failed",
                    extra={
                        "tenant_id": self.tenant_id,
                        "connection_id": connection_id,
                        "attempt": attempt + 1,
                        "max_retries": self.max_retries + 1,
                        "error": last_error,
                        "job_id": last_job_id,
                    },
                )

                if attempt < self.max_retries:
                    delay = self._calculate_backoff_delay(attempt)

                    # Handle rate limiting with retry-after header
                    if isinstance(e, AirbyteRateLimitError) and e.retry_after:
                        delay = max(delay, float(e.retry_after))

                    logger.info(
                        "Retrying sync after delay",
                        extra={
                            "tenant_id": self.tenant_id,
                            "connection_id": connection_id,
                            "delay_seconds": delay,
                            "next_attempt": attempt + 2,
                        },
                    )
                    await asyncio.sleep(delay)

                attempt += 1

        # All retries exhausted - persist failure and log alert
        self._airbyte_service.mark_connection_failed(connection_id, last_error)

        logger.error(
            "SYNC_FAILURE_ALERT: Sync failed after all retries",
            extra={
                "tenant_id": self.tenant_id,
                "connection_id": connection_id,
                "airbyte_connection_id": connection.airbyte_connection_id,
                "total_attempts": self.max_retries + 1,
                "last_error": last_error,
                "last_job_id": last_job_id,
            },
        )

        return SyncResult(
            connection_id=connection_id,
            job_id=last_job_id,
            status="failed",
            is_successful=False,
            records_synced=0,
            bytes_synced=0,
            duration_seconds=None,
            attempt_count=self.max_retries + 1,
            max_retries=self.max_retries + 1,
            error_message=last_error,
            completed_at=datetime.now(timezone.utc),
        )

    async def _execute_sync(
        self,
        connection_id: str,
        airbyte_connection_id: str,
        timeout_seconds: float,
    ):
        """
        Execute a single sync attempt.

        Args:
            connection_id: Internal connection ID
            airbyte_connection_id: Airbyte's connection ID
            timeout_seconds: Maximum wait time

        Returns:
            AirbyteSyncResult from the client

        Raises:
            AirbyteSyncError: On sync failure
            AirbyteError: On API errors
        """
        client = self._get_airbyte_client()
        result = await client.sync_and_wait(
            connection_id=airbyte_connection_id,
            timeout_seconds=timeout_seconds,
        )

        if result.status != AirbyteJobStatus.SUCCEEDED:
            raise AirbyteSyncError(
                message=f"Sync completed with status: {result.status.value}",
                job_id=result.job_id,
                connection_id=airbyte_connection_id,
            )

        return result

    def get_sync_state(self, connection_id: str) -> dict:
        """
        Get current sync state for a connection.

        Returns status, last sync time, and whether sync is possible.

        Args:
            connection_id: Internal connection ID

        Returns:
            Dictionary with sync state information

        Raises:
            ConnectionNotFoundError: If connection not found
        """
        connection = self._airbyte_service.get_connection(connection_id)
        if not connection:
            raise ConnectionNotFoundError(f"Connection {connection_id} not found")

        return {
            "connection_id": connection_id,
            "status": connection.status,
            "last_sync_at": (
                connection.last_sync_at.isoformat() if connection.last_sync_at else None
            ),
            "last_sync_status": connection.last_sync_status,
            "is_enabled": connection.is_enabled,
            "can_sync": connection.can_sync,
        }

    def get_failed_connections(self) -> list:
        """
        Get all failed connections for the tenant.

        Useful for building admin dashboards and alerting.

        Returns:
            List of connection info for failed connections
        """
        result = self._airbyte_service.list_connections(status="failed")
        return [
            {
                "connection_id": conn.id,
                "connection_name": conn.connection_name,
                "last_sync_at": (
                    conn.last_sync_at.isoformat() if conn.last_sync_at else None
                ),
                "last_sync_status": conn.last_sync_status,
            }
            for conn in result.connections
        ]
