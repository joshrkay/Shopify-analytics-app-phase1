"""
Mock Airbyte Client for testing.

Provides deterministic responses without making real Airbyte API calls.
Supports configuring mock state for different test scenarios.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, List
from dataclasses import dataclass, field

from src.integrations.airbyte.models import (
    AirbyteHealth,
    AirbyteConnection,
    AirbyteJob,
    AirbyteJobStatus,
    AirbyteSyncResult,
    ConnectionStatus,
    AirbyteSchedule,
    ScheduleType,
    AirbyteJobAttempt,
)
from src.integrations.airbyte.exceptions import (
    AirbyteError,
    AirbyteAuthenticationError,
    AirbyteNotFoundError,
    AirbyteSyncError,
)


class MockAirbyteClient:
    """
    Mock Airbyte Client for testing.

    Features:
    - Deterministic responses (no network calls)
    - Configurable connection and job state
    - Supports all client methods
    - Can simulate errors and edge cases
    """

    def __init__(
        self,
        base_url: str = "https://api.airbyte.test/v1",
        api_token: str = "mock-token",
        workspace_id: str = "mock-workspace-id",
    ):
        """Initialize mock client with empty state."""
        self.base_url = base_url
        self.api_token = api_token
        self.workspace_id = workspace_id

        self._connections: Dict[str, AirbyteConnection] = {}
        self._jobs: Dict[str, AirbyteJob] = {}
        self._health_available = True
        self._should_fail = False
        self._fail_error: Optional[AirbyteError] = None
        self._next_job_num = 1

    def reset(self) -> None:
        """Reset all mock state."""
        self._connections.clear()
        self._jobs.clear()
        self._health_available = True
        self._should_fail = False
        self._fail_error = None
        self._next_job_num = 1

    def configure_failure(
        self,
        error: Optional[AirbyteError] = None,
        message: str = "Mock API failure",
    ) -> None:
        """Configure the mock to fail on next call."""
        self._should_fail = True
        self._fail_error = error or AirbyteError(message)

    def configure_health(self, available: bool) -> None:
        """Configure health check response."""
        self._health_available = available

    def add_connection(
        self,
        connection_id: Optional[str] = None,
        name: str = "Test Connection",
        source_id: str = "src-1",
        destination_id: str = "dest-1",
        status: ConnectionStatus = ConnectionStatus.ACTIVE,
    ) -> AirbyteConnection:
        """
        Add a connection to mock state.

        Use this to pre-populate connections for testing.
        """
        if connection_id is None:
            connection_id = f"conn-{uuid.uuid4().hex[:8]}"

        connection = AirbyteConnection(
            connection_id=connection_id,
            name=name,
            source_id=source_id,
            destination_id=destination_id,
            status=status,
            schedule=AirbyteSchedule(schedule_type=ScheduleType.MANUAL),
        )
        self._connections[connection_id] = connection
        return connection

    def add_job(
        self,
        job_id: Optional[str] = None,
        connection_id: str = "conn-1",
        status: AirbyteJobStatus = AirbyteJobStatus.SUCCEEDED,
        records_synced: int = 0,
        bytes_synced: int = 0,
    ) -> AirbyteJob:
        """
        Add a job to mock state.

        Use this to pre-populate jobs for testing.
        """
        if job_id is None:
            job_id = f"job-{self._next_job_num}"
            self._next_job_num += 1

        attempt = AirbyteJobAttempt(
            attempt_number=0,
            status=status,
            created_at=datetime.now(timezone.utc),
            records_synced=records_synced,
            bytes_synced=bytes_synced,
        )

        job = AirbyteJob(
            job_id=job_id,
            config_type="sync",
            config_id=connection_id,
            status=status,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            attempts=[attempt],
        )
        self._jobs[job_id] = job
        return job

    def set_job_status(self, job_id: str, status: AirbyteJobStatus) -> None:
        """Update the status of an existing job."""
        if job_id in self._jobs:
            job = self._jobs[job_id]
            self._jobs[job_id] = AirbyteJob(
                job_id=job.job_id,
                config_type=job.config_type,
                config_id=job.config_id,
                status=status,
                created_at=job.created_at,
                updated_at=datetime.now(timezone.utc),
                attempts=job.attempts,
            )

    def _check_failure(self) -> None:
        """Check if configured to fail and raise if so."""
        if self._should_fail:
            self._should_fail = False
            error = self._fail_error or AirbyteError("Mock failure")
            self._fail_error = None
            raise error

    async def __aenter__(self) -> "MockAirbyteClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        pass

    async def close(self) -> None:
        """Close the mock client (no-op)."""
        pass

    async def check_health(self) -> AirbyteHealth:
        """Return mock health status."""
        self._check_failure()
        return AirbyteHealth(
            available=self._health_available,
            db=True,
        )

    async def list_connections(
        self,
        workspace_id: Optional[str] = None,
        include_deleted: bool = False,
    ) -> List[AirbyteConnection]:
        """List connections from mock state."""
        self._check_failure()
        return list(self._connections.values())

    async def get_connection(self, connection_id: str) -> AirbyteConnection:
        """Get a specific connection by ID."""
        self._check_failure()

        if connection_id not in self._connections:
            raise AirbyteNotFoundError(
                message=f"Connection not found: {connection_id}",
                resource_type="connection",
                resource_id=connection_id,
            )

        return self._connections[connection_id]

    async def trigger_sync(self, connection_id: str) -> str:
        """Trigger a mock sync and return job ID."""
        self._check_failure()

        if connection_id not in self._connections:
            raise AirbyteNotFoundError(
                message=f"Connection not found: {connection_id}",
                resource_type="connection",
                resource_id=connection_id,
            )

        # Create a new job
        job = self.add_job(
            connection_id=connection_id,
            status=AirbyteJobStatus.RUNNING,
        )

        return job.job_id

    async def get_job(self, job_id: str) -> AirbyteJob:
        """Get job status from mock state."""
        self._check_failure()

        if job_id not in self._jobs:
            raise AirbyteNotFoundError(
                message=f"Job not found: {job_id}",
                resource_type="job",
                resource_id=job_id,
            )

        return self._jobs[job_id]

    async def cancel_job(self, job_id: str) -> AirbyteJob:
        """Cancel a mock job."""
        self._check_failure()

        if job_id not in self._jobs:
            raise AirbyteNotFoundError(
                message=f"Job not found: {job_id}",
                resource_type="job",
                resource_id=job_id,
            )

        self.set_job_status(job_id, AirbyteJobStatus.CANCELLED)
        return self._jobs[job_id]

    async def wait_for_sync(
        self,
        job_id: str,
        timeout_seconds: float = 3600,
        poll_interval_seconds: float = 30,
        connection_id: Optional[str] = None,
    ) -> AirbyteSyncResult:
        """
        Return sync result immediately (no actual waiting in mock).

        By default, marks job as succeeded. Use set_job_status() to
        configure different outcomes before calling.
        """
        self._check_failure()

        if job_id not in self._jobs:
            raise AirbyteNotFoundError(
                message=f"Job not found: {job_id}",
                resource_type="job",
                resource_id=job_id,
            )

        job = self._jobs[job_id]

        # If still running, mark as succeeded
        if job.is_running:
            self.set_job_status(job_id, AirbyteJobStatus.SUCCEEDED)
            job = self._jobs[job_id]

        records_synced = 0
        bytes_synced = 0
        if job.attempts:
            last_attempt = job.attempts[-1]
            records_synced = last_attempt.records_synced
            bytes_synced = last_attempt.bytes_synced

        return AirbyteSyncResult(
            job_id=job_id,
            status=job.status,
            connection_id=connection_id or job.config_id,
            records_synced=records_synced,
            bytes_synced=bytes_synced,
            duration_seconds=0.0,
        )

    async def sync_and_wait(
        self,
        connection_id: str,
        timeout_seconds: float = 3600,
        poll_interval_seconds: float = 30,
    ) -> AirbyteSyncResult:
        """Trigger sync and immediately return result."""
        job_id = await self.trigger_sync(connection_id)
        return await self.wait_for_sync(
            job_id=job_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            connection_id=connection_id,
        )
