"""
Airbyte Cloud API client for data synchronization management.

This client handles:
- Health checks for Airbyte Cloud availability
- Connection management (list, get)
- Sync job orchestration (trigger, status, wait)

Documentation: https://reference.airbyte.com/
"""

import asyncio
import logging
import os
import time
from typing import Optional, List, Dict, Any

import httpx

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
    AirbyteSource,
    AirbyteDestination,
    SourceCreationRequest,
    ConnectionCreationRequest,
)

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_BASE_URL = "https://api.airbyte.com/v1"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_SYNC_TIMEOUT_SECONDS = 3600
DEFAULT_POLL_INTERVAL_SECONDS = 30


class AirbyteClient:
    """
    Async client for Airbyte Cloud API.

    This client is designed to work with Airbyte Cloud's REST API.
    All methods are async and should be used with async/await.

    SECURITY: API token must be stored securely and never logged.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_token: Optional[str] = None,
        workspace_id: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    ):
        """
        Initialize Airbyte client.

        Args:
            base_url: Airbyte Cloud API base URL (default: from env or cloud URL)
            api_token: API token for authentication (default: from env)
            workspace_id: Airbyte workspace ID (default: from env)
            timeout: Request timeout in seconds
            connect_timeout: Connection timeout in seconds
        """
        self.base_url = (
            base_url or os.getenv("AIRBYTE_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_token = api_token or os.getenv("AIRBYTE_API_TOKEN")
        self.workspace_id = workspace_id or os.getenv("AIRBYTE_WORKSPACE_ID")

        if not self.api_token:
            raise ValueError(
                "Airbyte API token is required. Set AIRBYTE_API_TOKEN environment variable "
                "or pass api_token parameter."
            )

        if not self.workspace_id:
            raise ValueError(
                "Airbyte workspace ID is required. Set AIRBYTE_WORKSPACE_ID environment variable "
                "or pass workspace_id parameter."
            )

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_token}",
            },
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "AirbyteClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the Airbyte API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            json: Request body as JSON
            params: Query parameters

        Returns:
            Response data as dictionary

        Raises:
            AirbyteError: On API errors
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            response = await self._client.request(
                method=method,
                url=url,
                json=json,
                params=params,
            )

            if response.status_code == 401:
                logger.error(
                    "Airbyte API authentication failed",
                    extra={"status_code": 401, "endpoint": endpoint},
                )
                raise AirbyteAuthenticationError()

            if response.status_code == 403:
                logger.error(
                    "Airbyte API authorization failed",
                    extra={"status_code": 403, "endpoint": endpoint},
                )
                raise AirbyteAuthenticationError(
                    message="Authorization failed - token may lack required permissions",
                    status_code=403,
                )

            if response.status_code == 404:
                raise AirbyteNotFoundError(
                    message=f"Resource not found: {endpoint}",
                )

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                logger.warning(
                    "Airbyte API rate limited",
                    extra={
                        "endpoint": endpoint,
                        "retry_after": retry_after,
                    },
                )
                raise AirbyteRateLimitError(
                    retry_after=int(retry_after) if retry_after else None
                )

            if response.status_code >= 400:
                error_body = {}
                try:
                    error_body = response.json()
                except Exception:
                    pass

                logger.error(
                    "Airbyte API error",
                    extra={
                        "status_code": response.status_code,
                        "endpoint": endpoint,
                        "response": str(error_body)[:500],
                    },
                )
                raise AirbyteError(
                    message=f"Airbyte API error: {response.status_code}",
                    status_code=response.status_code,
                    response=error_body,
                )

            if response.status_code == 204:
                return {}

            return response.json()

        except httpx.TimeoutException as e:
            logger.error(
                "Airbyte API timeout",
                extra={"endpoint": endpoint, "error": str(e)},
            )
            raise AirbyteConnectionError(f"Request timeout: {e}")
        except httpx.RequestError as e:
            logger.error(
                "Airbyte API connection error",
                extra={"endpoint": endpoint, "error": str(e)},
            )
            raise AirbyteConnectionError(f"Connection error: {e}")

    async def check_health(self) -> AirbyteHealth:
        """
        Check Airbyte API health status.

        Returns:
            AirbyteHealth with availability status

        Raises:
            AirbyteError: On API errors
        """
        data = await self._request("GET", "/health")
        return AirbyteHealth.from_dict(data)

    async def list_connections(
        self,
        workspace_id: Optional[str] = None,
        include_deleted: bool = False,
    ) -> List[AirbyteConnection]:
        """
        List all connections in the workspace.

        Args:
            workspace_id: Override workspace ID (uses default if not provided)
            include_deleted: Include deleted connections

        Returns:
            List of AirbyteConnection objects

        Raises:
            AirbyteError: On API errors
        """
        ws_id = workspace_id or self.workspace_id

        params = {"workspaceIds": ws_id}
        if include_deleted:
            params["includeDeleted"] = "true"

        data = await self._request("GET", "/connections", params=params)

        connections = []
        for conn_data in data.get("data", []):
            connections.append(AirbyteConnection.from_dict(conn_data))

        logger.debug(
            "Listed Airbyte connections",
            extra={
                "workspace_id": ws_id,
                "connection_count": len(connections),
            },
        )

        return connections

    async def get_connection(self, connection_id: str) -> AirbyteConnection:
        """
        Get a specific connection by ID.

        Args:
            connection_id: Connection UUID

        Returns:
            AirbyteConnection object

        Raises:
            AirbyteNotFoundError: If connection not found
            AirbyteError: On other API errors
        """
        data = await self._request("GET", f"/connections/{connection_id}")
        return AirbyteConnection.from_dict(data)

    async def trigger_sync(self, connection_id: str) -> str:
        """
        Trigger a manual sync for a connection.

        Args:
            connection_id: Connection UUID

        Returns:
            Job ID for the triggered sync

        Raises:
            AirbyteError: On API errors
        """
        data = await self._request(
            "POST",
            f"/connections/{connection_id}/sync",
        )

        job_id = data.get("jobId", "")

        logger.info(
            "Airbyte sync triggered",
            extra={
                "connection_id": connection_id,
                "job_id": job_id,
            },
        )

        return job_id

    async def get_job(self, job_id: str) -> AirbyteJob:
        """
        Get job status and details.

        Args:
            job_id: Job ID

        Returns:
            AirbyteJob object

        Raises:
            AirbyteError: On API errors
        """
        data = await self._request("GET", f"/jobs/{job_id}")
        return AirbyteJob.from_dict(data)

    async def cancel_job(self, job_id: str) -> AirbyteJob:
        """
        Cancel a running job.

        Args:
            job_id: Job ID to cancel

        Returns:
            Updated AirbyteJob object

        Raises:
            AirbyteError: On API errors
        """
        data = await self._request("DELETE", f"/jobs/{job_id}")

        logger.info(
            "Airbyte job cancelled",
            extra={"job_id": job_id},
        )

        return AirbyteJob.from_dict(data)

    async def wait_for_sync(
        self,
        job_id: str,
        timeout_seconds: float = DEFAULT_SYNC_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        connection_id: Optional[str] = None,
    ) -> AirbyteSyncResult:
        """
        Wait for a sync job to complete.

        Args:
            job_id: Job ID to monitor
            timeout_seconds: Maximum wait time
            poll_interval_seconds: Interval between status checks
            connection_id: Optional connection ID for logging

        Returns:
            AirbyteSyncResult with final status

        Raises:
            AirbyteSyncError: On timeout or job failure
            AirbyteError: On API errors
        """
        start_time = time.time()

        logger.info(
            "Waiting for Airbyte sync",
            extra={
                "job_id": job_id,
                "timeout_seconds": timeout_seconds,
                "poll_interval_seconds": poll_interval_seconds,
            },
        )

        while True:
            elapsed = time.time() - start_time

            if elapsed >= timeout_seconds:
                raise AirbyteSyncError(
                    message=f"Sync timed out after {timeout_seconds} seconds",
                    job_id=job_id,
                    connection_id=connection_id,
                )

            job = await self.get_job(job_id)

            if job.is_complete:
                duration = time.time() - start_time

                records_synced = 0
                bytes_synced = 0
                if job.attempts:
                    last_attempt = job.attempts[-1]
                    records_synced = last_attempt.records_synced
                    bytes_synced = last_attempt.bytes_synced

                result = AirbyteSyncResult(
                    job_id=job_id,
                    status=job.status,
                    connection_id=connection_id or job.config_id,
                    records_synced=records_synced,
                    bytes_synced=bytes_synced,
                    duration_seconds=duration,
                )

                if job.is_successful:
                    logger.info(
                        "Airbyte sync completed successfully",
                        extra={
                            "job_id": job_id,
                            "connection_id": connection_id,
                            "records_synced": records_synced,
                            "bytes_synced": bytes_synced,
                            "duration_seconds": duration,
                        },
                    )
                else:
                    logger.warning(
                        "Airbyte sync completed with status",
                        extra={
                            "job_id": job_id,
                            "connection_id": connection_id,
                            "status": job.status.value,
                            "duration_seconds": duration,
                        },
                    )

                return result

            logger.debug(
                "Airbyte sync still running",
                extra={
                    "job_id": job_id,
                    "status": job.status.value,
                    "elapsed_seconds": elapsed,
                },
            )

            await asyncio.sleep(poll_interval_seconds)

    async def sync_and_wait(
        self,
        connection_id: str,
        timeout_seconds: float = DEFAULT_SYNC_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> AirbyteSyncResult:
        """
        Trigger a sync and wait for completion.

        Convenience method that combines trigger_sync and wait_for_sync.

        Args:
            connection_id: Connection to sync
            timeout_seconds: Maximum wait time
            poll_interval_seconds: Interval between status checks

        Returns:
            AirbyteSyncResult with final status

        Raises:
            AirbyteSyncError: On timeout or job failure
            AirbyteError: On API errors
        """
        job_id = await self.trigger_sync(connection_id)
        return await self.wait_for_sync(
            job_id=job_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            connection_id=connection_id,
        )

    # =========================================================================
    # Source Management Methods
    # =========================================================================

    async def create_source(
        self,
        request: SourceCreationRequest,
        workspace_id: Optional[str] = None,
    ) -> AirbyteSource:
        """
        Create a new source in Airbyte.

        Args:
            request: Source creation request with configuration
            workspace_id: Override workspace ID (uses default if not provided)

        Returns:
            Created AirbyteSource object

        Raises:
            AirbyteError: On API errors
        """
        ws_id = workspace_id or self.workspace_id

        data = await self._request(
            "POST",
            "/sources",
            json=request.to_dict(ws_id),
        )

        source = AirbyteSource.from_dict(data)

        logger.info(
            "Airbyte source created",
            extra={
                "source_id": source.source_id,
                "source_type": source.source_type,
                "name": source.name,
            },
        )

        return source

    async def get_source(self, source_id: str) -> AirbyteSource:
        """
        Get a specific source by ID.

        Args:
            source_id: Source UUID

        Returns:
            AirbyteSource object

        Raises:
            AirbyteNotFoundError: If source not found
            AirbyteError: On other API errors
        """
        data = await self._request("GET", f"/sources/{source_id}")
        return AirbyteSource.from_dict(data)

    async def list_sources(
        self,
        workspace_id: Optional[str] = None,
    ) -> List[AirbyteSource]:
        """
        List all sources in the workspace.

        Args:
            workspace_id: Override workspace ID (uses default if not provided)

        Returns:
            List of AirbyteSource objects

        Raises:
            AirbyteError: On API errors
        """
        ws_id = workspace_id or self.workspace_id

        data = await self._request(
            "GET",
            "/sources",
            params={"workspaceIds": ws_id},
        )

        sources = []
        for source_data in data.get("data", []):
            sources.append(AirbyteSource.from_dict(source_data))

        return sources

    async def delete_source(self, source_id: str) -> None:
        """
        Delete a source.

        Args:
            source_id: Source UUID to delete

        Raises:
            AirbyteError: On API errors
        """
        await self._request("DELETE", f"/sources/{source_id}")

        logger.info(
            "Airbyte source deleted",
            extra={"source_id": source_id},
        )

    # =========================================================================
    # Destination Management Methods
    # =========================================================================

    async def get_destination(self, destination_id: str) -> AirbyteDestination:
        """
        Get a specific destination by ID.

        Args:
            destination_id: Destination UUID

        Returns:
            AirbyteDestination object

        Raises:
            AirbyteNotFoundError: If destination not found
            AirbyteError: On other API errors
        """
        data = await self._request("GET", f"/destinations/{destination_id}")
        return AirbyteDestination.from_dict(data)

    async def list_destinations(
        self,
        workspace_id: Optional[str] = None,
    ) -> List[AirbyteDestination]:
        """
        List all destinations in the workspace.

        Args:
            workspace_id: Override workspace ID (uses default if not provided)

        Returns:
            List of AirbyteDestination objects

        Raises:
            AirbyteError: On API errors
        """
        ws_id = workspace_id or self.workspace_id

        data = await self._request(
            "GET",
            "/destinations",
            params={"workspaceIds": ws_id},
        )

        destinations = []
        for dest_data in data.get("data", []):
            destinations.append(AirbyteDestination.from_dict(dest_data))

        return destinations

    # =========================================================================
    # Connection Creation Methods
    # =========================================================================

    async def create_connection(
        self,
        request: ConnectionCreationRequest,
    ) -> AirbyteConnection:
        """
        Create a new connection between source and destination.

        Args:
            request: Connection creation request

        Returns:
            Created AirbyteConnection object

        Raises:
            AirbyteError: On API errors
        """
        data = await self._request(
            "POST",
            "/connections",
            json=request.to_dict(),
        )

        connection = AirbyteConnection.from_dict(data)

        logger.info(
            "Airbyte connection created",
            extra={
                "connection_id": connection.connection_id,
                "source_id": connection.source_id,
                "destination_id": connection.destination_id,
                "name": connection.name,
            },
        )

        return connection

    async def delete_connection(self, connection_id: str) -> None:
        """
        Delete a connection.

        Args:
            connection_id: Connection UUID to delete

        Raises:
            AirbyteError: On API errors
        """
        await self._request("DELETE", f"/connections/{connection_id}")

        logger.info(
            "Airbyte connection deleted",
            extra={"connection_id": connection_id},
        )


def get_airbyte_client(
    base_url: Optional[str] = None,
    api_token: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> AirbyteClient:
    """
    Factory function to create an AirbyteClient.

    Args:
        base_url: Override API base URL
        api_token: Override API token
        workspace_id: Override workspace ID

    Returns:
        Configured AirbyteClient instance
    """
    return AirbyteClient(
        base_url=base_url,
        api_token=api_token,
        workspace_id=workspace_id,
    )
