"""
Mock Airbyte Cloud API server for E2E testing.

Simulates:
- Connection management
- Sync job triggering
- Job status polling
- Data injection into raw tables when sync "completes"
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class MockJob:
    """Represents a mock Airbyte sync job."""
    job_id: str
    connection_id: str
    status: JobStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    bytes_synced: int = 0
    records_synced: int = 0


@dataclass
class MockConnection:
    """Represents a mock Airbyte connection."""
    connection_id: str
    name: str
    source_type: str
    status: str = "active"
    schedule: Optional[Dict] = None


class MockAirbyteServer:
    """
    Mock Airbyte Cloud API server.

    Injects test data into raw database tables when a sync "completes",
    simulating what Airbyte does in production.

    Usage:
        mock = MockAirbyteServer()
        mock.setup_test_data(
            connection_id="conn-123",
            data={"_airbyte_raw_shopify_orders": [...]}
        )

        # In test, trigger sync via API, mock will inject data when complete
    """

    def __init__(
        self,
        db_session_factory: Optional[Callable[[], AsyncSession]] = None,
        sync_delay_seconds: float = 0.5,
        auto_complete: bool = True,
    ):
        """
        Initialize mock Airbyte server.

        Args:
            db_session_factory: Factory function to create database sessions
            sync_delay_seconds: Simulated sync duration
            auto_complete: Whether jobs auto-complete (True) or require manual completion
        """
        self.db_session_factory = db_session_factory
        self.sync_delay_seconds = sync_delay_seconds
        self.auto_complete = auto_complete

        self._connections: Dict[str, MockConnection] = {}
        self._jobs: Dict[str, MockJob] = {}
        self._test_data: Dict[str, Dict[str, List[Dict]]] = {}
        self._backfill_data: Dict[str, Dict[str, List[Dict]]] = {}

    def register_connection(
        self,
        connection_id: str,
        name: str = "Test Connection",
        source_type: str = "shopify",
        status: str = "active",
    ) -> MockConnection:
        """Register a mock Airbyte connection."""
        connection = MockConnection(
            connection_id=connection_id,
            name=name,
            source_type=source_type,
            status=status,
        )
        self._connections[connection_id] = connection
        return connection

    def setup_test_data(
        self,
        connection_id: str,
        data: Dict[str, List[Dict]],
    ) -> None:
        """
        Configure test data to inject when sync completes.

        Args:
            connection_id: Airbyte connection ID
            data: Dict mapping table names to list of records
                  e.g., {"_airbyte_raw_shopify_orders": [order1, order2, ...]}
        """
        self._test_data[connection_id] = data

    def setup_backfill_data(
        self,
        connection_id: str,
        data: Dict[str, List[Dict]],
    ) -> None:
        """Configure data for backfill operations."""
        self._backfill_data[connection_id] = data

    def configure_job_failure(
        self,
        connection_id: str,
        error_message: str = "Simulated sync failure"
    ) -> None:
        """Configure next sync job for this connection to fail."""
        self._test_data[f"{connection_id}:fail"] = {"error": error_message}

    # API Handlers

    async def handle_list_connections(self, workspace_id: str) -> Dict:
        """GET /v1/connections"""
        connections = [
            {
                "connectionId": conn.connection_id,
                "name": conn.name,
                "sourceType": conn.source_type,
                "status": conn.status,
            }
            for conn in self._connections.values()
        ]
        return {"connections": connections}

    async def handle_get_connection(self, connection_id: str) -> Dict:
        """GET /v1/connections/{connectionId}"""
        if connection_id not in self._connections:
            raise ValueError(f"Connection not found: {connection_id}")

        conn = self._connections[connection_id]
        return {
            "connectionId": conn.connection_id,
            "name": conn.name,
            "sourceType": conn.source_type,
            "status": conn.status,
        }

    async def handle_trigger_sync(self, connection_id: str) -> Dict:
        """POST /v1/jobs (trigger sync)"""
        if connection_id not in self._connections:
            # Auto-register if not exists (for simpler test setup)
            self.register_connection(connection_id)

        job_id = str(uuid.uuid4())
        job = MockJob(
            job_id=job_id,
            connection_id=connection_id,
            status=JobStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        self._jobs[job_id] = job

        # Start background task to complete the job
        if self.auto_complete:
            asyncio.create_task(self._complete_job_after_delay(job_id))

        return {
            "jobId": job_id,
            "status": job.status.value,
            "connectionId": connection_id,
        }

    async def handle_get_job(self, job_id: str) -> Dict:
        """GET /v1/jobs/{jobId}"""
        if job_id not in self._jobs:
            raise ValueError(f"Job not found: {job_id}")

        job = self._jobs[job_id]
        return {
            "jobId": job.job_id,
            "connectionId": job.connection_id,
            "status": job.status.value,
            "startedAt": job.started_at.isoformat(),
            "completedAt": job.completed_at.isoformat() if job.completed_at else None,
            "bytesEmitted": job.bytes_synced,
            "recordsEmitted": job.records_synced,
            "failureReason": job.error_message,
        }

    async def handle_cancel_job(self, job_id: str) -> Dict:
        """POST /v1/jobs/{jobId}/cancel"""
        if job_id not in self._jobs:
            raise ValueError(f"Job not found: {job_id}")

        job = self._jobs[job_id]
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(timezone.utc)

        return {"jobId": job_id, "status": "cancelled"}

    # Internal methods

    async def _complete_job_after_delay(self, job_id: str) -> None:
        """Background task to complete job after configured delay."""
        await asyncio.sleep(self.sync_delay_seconds)

        job = self._jobs.get(job_id)
        if not job or job.status != JobStatus.RUNNING:
            return

        connection_id = job.connection_id

        # Check if this job should fail
        fail_key = f"{connection_id}:fail"
        if fail_key in self._test_data:
            job.status = JobStatus.FAILED
            job.error_message = self._test_data[fail_key].get("error", "Sync failed")
            job.completed_at = datetime.now(timezone.utc)
            del self._test_data[fail_key]
            return

        # Inject test data into raw tables
        if connection_id in self._test_data and self.db_session_factory:
            await self._inject_data(connection_id, self._test_data[connection_id])
            job.records_synced = sum(
                len(records)
                for records in self._test_data[connection_id].values()
            )

        job.status = JobStatus.SUCCEEDED
        job.completed_at = datetime.now(timezone.utc)

    async def _inject_data(
        self,
        connection_id: str,
        data: Dict[str, List[Dict]]
    ) -> None:
        """Inject test data into raw Airbyte tables."""
        async with self.db_session_factory() as session:
            for table_name, records in data.items():
                for record in records:
                    # Format data as Airbyte raw format
                    await session.execute(
                        text(f"""
                            INSERT INTO {table_name}
                            (_airbyte_raw_id, _airbyte_data, _airbyte_extracted_at, _airbyte_loaded_at)
                            VALUES (:raw_id, :data, :extracted_at, :loaded_at)
                            ON CONFLICT (_airbyte_raw_id) DO UPDATE SET
                                _airbyte_data = EXCLUDED._airbyte_data,
                                _airbyte_loaded_at = EXCLUDED._airbyte_loaded_at
                        """),
                        {
                            "raw_id": str(uuid.uuid4()),
                            "data": json.dumps(record),
                            "extracted_at": datetime.now(timezone.utc),
                            "loaded_at": datetime.now(timezone.utc),
                        }
                    )
            await session.commit()

    def manually_complete_job(
        self,
        job_id: str,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> None:
        """Manually complete a job (for tests with auto_complete=False)."""
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")

        if success:
            job.status = JobStatus.SUCCEEDED
        else:
            job.status = JobStatus.FAILED
            job.error_message = error_message or "Manual failure"

        job.completed_at = datetime.now(timezone.utc)

    def get_job_status(self, job_id: str) -> JobStatus:
        """Get current job status (for test assertions)."""
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        return job.status

    def reset(self) -> None:
        """Reset all state (call between tests)."""
        self._connections.clear()
        self._jobs.clear()
        self._test_data.clear()
        self._backfill_data.clear()

    def get_mock_transport(self) -> httpx.MockTransport:
        """
        Create an httpx MockTransport for this mock server.

        Usage:
            client = httpx.AsyncClient(transport=mock.get_mock_transport())
        """
        def handle_request(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            method = request.method

            try:
                # Sync blocking wrapper for async handlers
                loop = asyncio.new_event_loop()

                if "/jobs" in path and method == "POST":
                    if "cancel" in path:
                        job_id = path.split("/jobs/")[1].split("/")[0]
                        result = loop.run_until_complete(
                            self.handle_cancel_job(job_id)
                        )
                    else:
                        data = json.loads(request.content)
                        result = loop.run_until_complete(
                            self.handle_trigger_sync(data.get("connectionId", ""))
                        )
                elif "/jobs/" in path and method == "GET":
                    job_id = path.split("/jobs/")[1].split("/")[0]
                    result = loop.run_until_complete(self.handle_get_job(job_id))
                elif "/connections" in path and method == "GET":
                    if "/connections/" in path:
                        conn_id = path.split("/connections/")[1].split("/")[0]
                        result = loop.run_until_complete(
                            self.handle_get_connection(conn_id)
                        )
                    else:
                        result = loop.run_until_complete(
                            self.handle_list_connections("")
                        )
                else:
                    return httpx.Response(404, json={"error": "Not found"})

                loop.close()
                return httpx.Response(200, json=result)

            except ValueError as e:
                return httpx.Response(404, json={"error": str(e)})
            except Exception as e:
                return httpx.Response(500, json={"error": str(e)})

        return httpx.MockTransport(handle_request)
