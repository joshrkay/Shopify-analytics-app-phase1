"""
Airbyte client extension for ingestion job orchestration.

Extends the base Airbyte client with:
- Per-connector rate limiting
- Per-external-account rate limiting
- Enhanced error classification for retry decisions
- Sync result extraction for job metadata

SECURITY: API token must be stored securely and never logged.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.integrations.airbyte.client import AirbyteClient, get_airbyte_client
from src.integrations.airbyte.exceptions import (
    AirbyteError,
    AirbyteAuthenticationError,
    AirbyteRateLimitError,
    AirbyteConnectionError,
    AirbyteSyncError,
    AirbyteNotFoundError,
)
from src.integrations.airbyte.models import AirbyteJobStatus
from src.ingestion.jobs.retry import ErrorCategory

logger = logging.getLogger(__name__)

# Rate limit configuration per connector/account
DEFAULT_MIN_INTERVAL_SECONDS = 60  # Minimum 1 minute between syncs
RATE_LIMIT_WINDOW_SECONDS = 3600  # 1 hour sliding window


@dataclass
class RateLimitState:
    """
    Tracks rate limit state for a connector or account.

    Attributes:
        key: Unique identifier (connector_id or external_account_id)
        last_request_at: Timestamp of last request
        request_count: Number of requests in current window
        window_start: Start of rate limit window
        blocked_until: If rate limited, when limit expires
    """
    key: str
    last_request_at: Optional[datetime] = None
    request_count: int = 0
    window_start: Optional[datetime] = None
    blocked_until: Optional[datetime] = None


@dataclass
class SyncJobResult:
    """
    Result of triggering an Airbyte sync job.

    Attributes:
        run_id: Airbyte job ID
        connection_id: Airbyte connection ID
        started_at: When the sync was triggered
        error_category: If failed, the error classification
        error_message: Human-readable error message
        retry_after: Server-specified retry delay (for rate limits)
    """
    run_id: Optional[str]
    connection_id: str
    started_at: datetime
    error_category: Optional[ErrorCategory] = None
    error_message: Optional[str] = None
    retry_after: Optional[int] = None
    status: Optional[AirbyteJobStatus] = None
    records_synced: int = 0
    bytes_synced: int = 0
    duration_seconds: Optional[float] = None


class IngestionAirbyteClient:
    """
    Airbyte client for ingestion job orchestration.

    Wraps the base AirbyteClient with:
    - Rate limiting per connector and external account
    - Error classification for retry decisions
    - Enhanced observability

    SECURITY: All operations should be tenant-scoped at the caller level.
    """

    def __init__(
        self,
        airbyte_client: Optional[AirbyteClient] = None,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    ):
        """
        Initialize ingestion Airbyte client.

        Args:
            airbyte_client: Optional base client (creates default if not provided)
            min_interval_seconds: Minimum interval between requests per key
        """
        self._client = airbyte_client
        self._min_interval_seconds = min_interval_seconds
        # In-memory rate limit state (consider Redis for distributed deployments)
        self._rate_limits: dict[str, RateLimitState] = {}

    def _get_client(self) -> AirbyteClient:
        """Get or create the base Airbyte client."""
        if self._client is None:
            self._client = get_airbyte_client()
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.close()

    async def __aenter__(self) -> "IngestionAirbyteClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def _get_rate_limit_key(
        self,
        connector_id: str,
        external_account_id: Optional[str] = None,
    ) -> str:
        """
        Generate rate limit key for connector/account combination.

        Rate limiting is applied per connector and optionally per external account.
        """
        if external_account_id:
            return f"{connector_id}:{external_account_id}"
        return connector_id

    def _check_rate_limit(self, key: str) -> Optional[float]:
        """
        Check if request is rate limited.

        Args:
            key: Rate limit key

        Returns:
            Seconds to wait if rate limited, None if allowed
        """
        now = datetime.now(timezone.utc)
        state = self._rate_limits.get(key)

        if state is None:
            return None

        # Check if blocked by previous rate limit response
        if state.blocked_until and state.blocked_until > now:
            return (state.blocked_until - now).total_seconds()

        # Check minimum interval between requests
        if state.last_request_at:
            elapsed = (now - state.last_request_at).total_seconds()
            if elapsed < self._min_interval_seconds:
                return self._min_interval_seconds - elapsed

        return None

    def _record_request(self, key: str) -> None:
        """Record a request for rate limiting."""
        now = datetime.now(timezone.utc)

        if key not in self._rate_limits:
            self._rate_limits[key] = RateLimitState(key=key)

        state = self._rate_limits[key]
        state.last_request_at = now
        state.request_count += 1

        # Reset window if expired
        if state.window_start is None or (now - state.window_start).total_seconds() > RATE_LIMIT_WINDOW_SECONDS:
            state.window_start = now
            state.request_count = 1

    def _record_rate_limit_response(
        self,
        key: str,
        retry_after: Optional[int],
    ) -> None:
        """Record a rate limit response from the API."""
        if key not in self._rate_limits:
            self._rate_limits[key] = RateLimitState(key=key)

        state = self._rate_limits[key]

        if retry_after:
            state.blocked_until = datetime.now(timezone.utc) + \
                __import__("datetime").timedelta(seconds=retry_after)
        else:
            # Default block for 60 seconds if no Retry-After header
            state.blocked_until = datetime.now(timezone.utc) + \
                __import__("datetime").timedelta(seconds=60)

    def _classify_error(self, error: Exception) -> tuple[ErrorCategory, Optional[int]]:
        """
        Classify an exception for retry decisions.

        Returns:
            Tuple of (ErrorCategory, retry_after_seconds)
        """
        if isinstance(error, AirbyteAuthenticationError):
            return ErrorCategory.AUTH_ERROR, None

        if isinstance(error, AirbyteRateLimitError):
            return ErrorCategory.RATE_LIMIT, error.retry_after

        if isinstance(error, AirbyteConnectionError):
            if "timeout" in str(error).lower():
                return ErrorCategory.TIMEOUT, None
            return ErrorCategory.CONNECTION, None

        if isinstance(error, AirbyteSyncError):
            return ErrorCategory.SYNC_FAILED, None

        if isinstance(error, AirbyteNotFoundError):
            # Not found is not retryable
            return ErrorCategory.AUTH_ERROR, None

        if isinstance(error, AirbyteError):
            status = getattr(error, "status_code", None)
            if status and 500 <= status < 600:
                return ErrorCategory.SERVER_ERROR, None
            if status == 429:
                return ErrorCategory.RATE_LIMIT, None
            if status and 400 <= status < 500:
                return ErrorCategory.AUTH_ERROR, None

        return ErrorCategory.UNKNOWN, None

    async def trigger_sync(
        self,
        airbyte_connection_id: str,
        connector_id: str,
        external_account_id: Optional[str] = None,
    ) -> SyncJobResult:
        """
        Trigger an Airbyte sync with rate limiting.

        Args:
            airbyte_connection_id: Airbyte's connection UUID
            connector_id: Internal connector ID for rate limiting
            external_account_id: External account ID for rate limiting

        Returns:
            SyncJobResult with job ID or error details
        """
        rate_key = self._get_rate_limit_key(connector_id, external_account_id)
        started_at = datetime.now(timezone.utc)

        # Check rate limit
        wait_time = self._check_rate_limit(rate_key)
        if wait_time is not None:
            logger.warning(
                "Rate limited before request",
                extra={
                    "connector_id": connector_id,
                    "external_account_id": external_account_id,
                    "wait_seconds": wait_time,
                },
            )
            return SyncJobResult(
                run_id=None,
                connection_id=airbyte_connection_id,
                started_at=started_at,
                error_category=ErrorCategory.RATE_LIMIT,
                error_message=f"Rate limited - wait {wait_time:.0f}s",
                retry_after=int(wait_time),
            )

        # Record request
        self._record_request(rate_key)

        try:
            client = self._get_client()
            run_id = await client.trigger_sync(airbyte_connection_id)

            logger.info(
                "Airbyte sync triggered",
                extra={
                    "airbyte_connection_id": airbyte_connection_id,
                    "connector_id": connector_id,
                    "external_account_id": external_account_id,
                    "run_id": run_id,
                },
            )

            return SyncJobResult(
                run_id=run_id,
                connection_id=airbyte_connection_id,
                started_at=started_at,
            )

        except Exception as e:
            error_category, retry_after = self._classify_error(e)

            if error_category == ErrorCategory.RATE_LIMIT:
                self._record_rate_limit_response(rate_key, retry_after)

            logger.error(
                "Failed to trigger Airbyte sync",
                extra={
                    "airbyte_connection_id": airbyte_connection_id,
                    "connector_id": connector_id,
                    "external_account_id": external_account_id,
                    "error": str(e),
                    "error_category": error_category.value,
                },
            )

            return SyncJobResult(
                run_id=None,
                connection_id=airbyte_connection_id,
                started_at=started_at,
                error_category=error_category,
                error_message=str(e),
                retry_after=retry_after,
            )

    async def wait_for_sync(
        self,
        run_id: str,
        connection_id: str,
        timeout_seconds: float = 3600,
        poll_interval_seconds: float = 30,
    ) -> SyncJobResult:
        """
        Wait for an Airbyte sync to complete.

        Args:
            run_id: Airbyte job ID
            connection_id: Airbyte connection ID
            timeout_seconds: Maximum wait time
            poll_interval_seconds: Interval between status checks

        Returns:
            SyncJobResult with final status and metrics
        """
        client = self._get_client()
        start_time = time.time()
        started_at = datetime.now(timezone.utc)

        try:
            result = await client.wait_for_sync(
                job_id=run_id,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                connection_id=connection_id,
            )

            return SyncJobResult(
                run_id=run_id,
                connection_id=connection_id,
                started_at=started_at,
                status=result.status,
                records_synced=result.records_synced,
                bytes_synced=result.bytes_synced,
                duration_seconds=result.duration_seconds,
            )

        except Exception as e:
            error_category, retry_after = self._classify_error(e)

            logger.error(
                "Airbyte sync wait failed",
                extra={
                    "run_id": run_id,
                    "connection_id": connection_id,
                    "error": str(e),
                    "error_category": error_category.value,
                    "elapsed_seconds": time.time() - start_time,
                },
            )

            return SyncJobResult(
                run_id=run_id,
                connection_id=connection_id,
                started_at=started_at,
                error_category=error_category,
                error_message=str(e),
                retry_after=retry_after,
            )

    async def trigger_and_wait(
        self,
        airbyte_connection_id: str,
        connector_id: str,
        external_account_id: Optional[str] = None,
        timeout_seconds: float = 3600,
        poll_interval_seconds: float = 30,
    ) -> SyncJobResult:
        """
        Trigger a sync and wait for completion.

        Convenience method combining trigger_sync and wait_for_sync.

        Args:
            airbyte_connection_id: Airbyte's connection UUID
            connector_id: Internal connector ID
            external_account_id: External account ID
            timeout_seconds: Maximum wait time
            poll_interval_seconds: Status check interval

        Returns:
            SyncJobResult with final status and metrics
        """
        # Trigger the sync
        trigger_result = await self.trigger_sync(
            airbyte_connection_id=airbyte_connection_id,
            connector_id=connector_id,
            external_account_id=external_account_id,
        )

        if trigger_result.error_category is not None:
            return trigger_result

        if trigger_result.run_id is None:
            return SyncJobResult(
                run_id=None,
                connection_id=airbyte_connection_id,
                started_at=trigger_result.started_at,
                error_category=ErrorCategory.UNKNOWN,
                error_message="No run_id returned from trigger",
            )

        # Wait for completion
        return await self.wait_for_sync(
            run_id=trigger_result.run_id,
            connection_id=airbyte_connection_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
