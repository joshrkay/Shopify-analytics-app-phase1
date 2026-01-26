"""
Tests for retry logic and dead letter queue handling.

Validates:
- 4xx auth errors fail immediately (no retry)
- 429 rate limit errors retry with backoff
- 5xx server errors retry with exponential backoff + jitter
- After max retries (5) -> move to dead letter queue
- Backoff calculation with exponential growth and jitter

Story: Ingestion Orchestration - Retry & DLQ
"""

import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.ingestion.jobs.models import IngestionJob, JobStatus
from src.ingestion.jobs.retry import (
    RetryPolicy,
    RetryDecision,
    ErrorCategory,
    categorize_error,
    calculate_backoff,
    should_retry,
)
from src.ingestion.jobs.dispatcher import JobDispatcher
from src.ingestion.jobs.runner import JobRunner
from src.ingestion.airbyte.client import SyncJobResult


class TestErrorCategorization:
    """Tests for error classification."""

    def test_401_is_auth_error(self):
        """HTTP 401 is classified as auth error."""
        category = categorize_error(status_code=401)
        assert category == ErrorCategory.AUTH_ERROR

    def test_403_is_auth_error(self):
        """HTTP 403 is classified as auth error."""
        category = categorize_error(status_code=403)
        assert category == ErrorCategory.AUTH_ERROR

    def test_429_is_rate_limit(self):
        """HTTP 429 is classified as rate limit."""
        category = categorize_error(status_code=429)
        assert category == ErrorCategory.RATE_LIMIT

    def test_500_is_server_error(self):
        """HTTP 500 is classified as server error."""
        category = categorize_error(status_code=500)
        assert category == ErrorCategory.SERVER_ERROR

    def test_502_is_server_error(self):
        """HTTP 502 is classified as server error."""
        category = categorize_error(status_code=502)
        assert category == ErrorCategory.SERVER_ERROR

    def test_503_is_server_error(self):
        """HTTP 503 is classified as server error."""
        category = categorize_error(status_code=503)
        assert category == ErrorCategory.SERVER_ERROR

    def test_504_is_server_error(self):
        """HTTP 504 is classified as server error."""
        category = categorize_error(status_code=504)
        assert category == ErrorCategory.SERVER_ERROR

    def test_timeout_error_type(self):
        """Timeout error type is classified correctly."""
        category = categorize_error(status_code=None, error_type="timeout")
        assert category == ErrorCategory.TIMEOUT

    def test_connection_error_type(self):
        """Connection error type is classified correctly."""
        category = categorize_error(status_code=None, error_type="connection error")
        assert category == ErrorCategory.CONNECTION

    def test_unknown_error(self):
        """Unknown error defaults to UNKNOWN category."""
        category = categorize_error(status_code=None, error_type=None)
        assert category == ErrorCategory.UNKNOWN


class TestBackoffCalculation:
    """Tests for exponential backoff calculation."""

    def test_first_attempt_uses_base_delay(self):
        """First attempt (0) uses base delay."""
        policy = RetryPolicy(base_delay_seconds=60.0, jitter_factor=0)
        delay = calculate_backoff(attempt=0, policy=policy)
        assert delay == 60.0

    def test_second_attempt_doubles_delay(self):
        """Second attempt (1) doubles the delay."""
        policy = RetryPolicy(base_delay_seconds=60.0, jitter_factor=0)
        delay = calculate_backoff(attempt=1, policy=policy)
        assert delay == 120.0

    def test_third_attempt_quadruples_delay(self):
        """Third attempt (2) quadruples the delay."""
        policy = RetryPolicy(base_delay_seconds=60.0, jitter_factor=0)
        delay = calculate_backoff(attempt=2, policy=policy)
        assert delay == 240.0

    def test_delay_capped_at_max(self):
        """Delay is capped at max_delay_seconds."""
        policy = RetryPolicy(
            base_delay_seconds=60.0,
            max_delay_seconds=300.0,
            jitter_factor=0,
        )
        delay = calculate_backoff(attempt=10, policy=policy)
        assert delay == 300.0

    def test_jitter_applied(self):
        """Jitter adds randomness to delay."""
        policy = RetryPolicy(
            base_delay_seconds=100.0,
            jitter_factor=0.25,
        )
        delays = [calculate_backoff(attempt=0, policy=policy) for _ in range(10)]

        # With 25% jitter, delays should vary between 75 and 125
        assert min(delays) >= 75.0
        assert max(delays) <= 125.0
        # Some variation should exist
        assert len(set(delays)) > 1

    def test_retry_after_header_respected(self):
        """Server-specified Retry-After overrides calculation."""
        policy = RetryPolicy(base_delay_seconds=60.0)
        delay = calculate_backoff(attempt=0, policy=policy, retry_after=120)

        # Should be around 120 with small jitter (-5 to +10)
        assert 115.0 <= delay <= 130.0

    def test_minimum_delay_is_one_second(self):
        """Delay never goes below 1 second."""
        policy = RetryPolicy(
            base_delay_seconds=0.1,
            jitter_factor=0.5,
        )
        delay = calculate_backoff(attempt=0, policy=policy)
        assert delay >= 1.0


class TestRetryDecision:
    """Tests for should_retry decision logic."""

    def test_auth_error_no_retry_goes_to_dlq(self):
        """Auth errors immediately move to DLQ."""
        decision = should_retry(
            error_category=ErrorCategory.AUTH_ERROR,
            retry_count=0,
        )

        assert decision.should_retry is False
        assert decision.move_to_dlq is True
        assert "Authentication" in decision.reason

    def test_rate_limit_retries(self):
        """Rate limit errors are retried."""
        decision = should_retry(
            error_category=ErrorCategory.RATE_LIMIT,
            retry_count=0,
        )

        assert decision.should_retry is True
        assert decision.move_to_dlq is False
        assert decision.delay_seconds > 0
        assert decision.next_retry_at is not None

    def test_server_error_retries(self):
        """Server errors (5xx) are retried."""
        decision = should_retry(
            error_category=ErrorCategory.SERVER_ERROR,
            retry_count=0,
        )

        assert decision.should_retry is True
        assert decision.move_to_dlq is False

    def test_timeout_error_retries(self):
        """Timeout errors are retried."""
        decision = should_retry(
            error_category=ErrorCategory.TIMEOUT,
            retry_count=0,
        )

        assert decision.should_retry is True
        assert decision.move_to_dlq is False

    def test_connection_error_retries(self):
        """Connection errors are retried."""
        decision = should_retry(
            error_category=ErrorCategory.CONNECTION,
            retry_count=0,
        )

        assert decision.should_retry is True
        assert decision.move_to_dlq is False

    def test_max_retries_exceeded_goes_to_dlq(self):
        """After max retries, job moves to DLQ."""
        policy = RetryPolicy(max_retries=5)
        decision = should_retry(
            error_category=ErrorCategory.SERVER_ERROR,
            retry_count=5,  # Already at max
            policy=policy,
        )

        assert decision.should_retry is False
        assert decision.move_to_dlq is True
        assert "Max retries" in decision.reason

    def test_retry_count_increments_correctly(self):
        """Each failure should allow remaining retries."""
        policy = RetryPolicy(max_retries=5)

        # First 5 failures should retry
        for count in range(5):
            decision = should_retry(
                error_category=ErrorCategory.SERVER_ERROR,
                retry_count=count,
                policy=policy,
            )
            assert decision.should_retry is True, f"Failed at retry_count={count}"

        # 6th failure (count=5) should DLQ
        decision = should_retry(
            error_category=ErrorCategory.SERVER_ERROR,
            retry_count=5,
            policy=policy,
        )
        assert decision.should_retry is False
        assert decision.move_to_dlq is True


class TestJobModelLifecycle:
    """Tests for IngestionJob model state transitions."""

    def test_mark_running_sets_state(self, db_session, test_tenant_id):
        """mark_running updates job state correctly."""
        job = IngestionJob(
            tenant_id=test_tenant_id,
            connector_id="connector-1",
            external_account_id="shop-1",
            status=JobStatus.QUEUED,
        )
        db_session.add(job)
        db_session.flush()

        job.mark_running(run_id="airbyte-run-123")

        assert job.status == JobStatus.RUNNING
        assert job.run_id == "airbyte-run-123"
        assert job.started_at is not None

    def test_mark_success_sets_state(self, db_session, test_tenant_id):
        """mark_success updates job state correctly."""
        job = IngestionJob(
            tenant_id=test_tenant_id,
            connector_id="connector-1",
            external_account_id="shop-1",
            status=JobStatus.RUNNING,
        )
        db_session.add(job)
        db_session.flush()

        job.mark_success(metadata={"records_synced": 1000})

        assert job.status == JobStatus.SUCCESS
        assert job.completed_at is not None
        assert job.metadata.get("records_synced") == 1000

    def test_mark_failed_increments_retry_count(self, db_session, test_tenant_id):
        """mark_failed increments retry count."""
        job = IngestionJob(
            tenant_id=test_tenant_id,
            connector_id="connector-1",
            external_account_id="shop-1",
            status=JobStatus.RUNNING,
            retry_count=2,
        )
        db_session.add(job)
        db_session.flush()

        job.mark_failed(
            error_message="Server error",
            error_code="server_error",
            next_retry_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )

        assert job.status == JobStatus.FAILED
        assert job.retry_count == 3
        assert job.error_message == "Server error"
        assert job.error_code == "server_error"
        assert job.next_retry_at is not None

    def test_mark_dead_letter_sets_terminal_state(self, db_session, test_tenant_id):
        """mark_dead_letter moves to terminal DLQ state."""
        job = IngestionJob(
            tenant_id=test_tenant_id,
            connector_id="connector-1",
            external_account_id="shop-1",
            status=JobStatus.FAILED,
            retry_count=5,
        )
        db_session.add(job)
        db_session.flush()

        job.mark_dead_letter("Max retries exceeded")

        assert job.status == JobStatus.DEAD_LETTER
        assert job.completed_at is not None
        assert job.next_retry_at is None
        assert job.is_terminal is True

    def test_can_retry_property(self, db_session, test_tenant_id):
        """can_retry property works correctly."""
        job = IngestionJob(
            tenant_id=test_tenant_id,
            connector_id="connector-1",
            external_account_id="shop-1",
            status=JobStatus.FAILED,
            retry_count=3,
        )

        assert job.can_retry is True

        job.retry_count = 5
        assert job.can_retry is False

        job.retry_count = 3
        job.status = JobStatus.SUCCESS
        assert job.can_retry is False


class TestJobRunnerRetryHandling:
    """Tests for JobRunner retry behavior."""

    @pytest.fixture
    def mock_airbyte_client(self):
        """Create mock Airbyte client."""
        client = MagicMock()
        client.trigger_sync = AsyncMock()
        client.wait_for_sync = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_auth_error_moves_to_dlq_immediately(
        self,
        db_session,
        test_tenant_id,
        mock_airbyte_client,
    ):
        """Auth error skips retries and moves to DLQ."""
        from src.ingestion.airbyte.client import IngestionAirbyteClient

        dispatcher = JobDispatcher(db_session, test_tenant_id)
        connector_id = f"connector-{uuid.uuid4().hex[:8]}"

        # Create a job
        job = dispatcher.dispatch(
            connector_id=connector_id,
            external_account_id="shop-1",
        )

        # Mock auth error response
        mock_airbyte_client.trigger_sync.return_value = SyncJobResult(
            run_id=None,
            connection_id="conn-123",
            started_at=datetime.now(timezone.utc),
            error_category=ErrorCategory.AUTH_ERROR,
            error_message="Invalid API token",
        )

        # Create mock ingestion client
        ingestion_client = MagicMock(spec=IngestionAirbyteClient)
        ingestion_client.trigger_sync = mock_airbyte_client.trigger_sync

        runner = JobRunner(
            db_session=db_session,
            airbyte_client=ingestion_client,
        )

        # Mock the Airbyte service connection lookup
        with patch.object(runner, '_get_airbyte_connection_id', return_value="conn-123"):
            with patch.object(runner, '_check_entitlement', return_value=True):
                await runner.execute_job(job)

        db_session.refresh(job)
        assert job.status == JobStatus.DEAD_LETTER
        assert job.retry_count == 1

    @pytest.mark.asyncio
    async def test_server_error_schedules_retry(
        self,
        db_session,
        test_tenant_id,
        mock_airbyte_client,
    ):
        """Server error schedules job for retry."""
        from src.ingestion.airbyte.client import IngestionAirbyteClient

        dispatcher = JobDispatcher(db_session, test_tenant_id)
        connector_id = f"connector-{uuid.uuid4().hex[:8]}"

        job = dispatcher.dispatch(
            connector_id=connector_id,
            external_account_id="shop-1",
        )

        # Mock server error response
        mock_airbyte_client.trigger_sync.return_value = SyncJobResult(
            run_id=None,
            connection_id="conn-123",
            started_at=datetime.now(timezone.utc),
            error_category=ErrorCategory.SERVER_ERROR,
            error_message="Internal server error",
        )

        ingestion_client = MagicMock(spec=IngestionAirbyteClient)
        ingestion_client.trigger_sync = mock_airbyte_client.trigger_sync

        runner = JobRunner(
            db_session=db_session,
            airbyte_client=ingestion_client,
        )

        with patch.object(runner, '_get_airbyte_connection_id', return_value="conn-123"):
            with patch.object(runner, '_check_entitlement', return_value=True):
                await runner.execute_job(job)

        db_session.refresh(job)
        assert job.status == JobStatus.FAILED
        assert job.retry_count == 1
        assert job.next_retry_at is not None
        assert job.error_code == ErrorCategory.SERVER_ERROR.value


class TestDeadLetterQueueQueries:
    """Tests for DLQ query functionality."""

    def test_get_dead_letter_jobs(self, db_session, test_tenant_id):
        """get_dead_letter_jobs returns only DLQ jobs for tenant."""
        dispatcher = JobDispatcher(db_session, test_tenant_id)

        # Create jobs in various states
        job_queued = dispatcher.dispatch(
            connector_id="connector-1",
            external_account_id="shop-1",
        )

        job_success = dispatcher.dispatch(
            connector_id="connector-2",
            external_account_id="shop-1",
        )
        job_success.mark_success()

        job_dlq = dispatcher.dispatch(
            connector_id="connector-3",
            external_account_id="shop-1",
        )
        job_dlq.mark_dead_letter("Error after retries")

        db_session.flush()

        dlq_jobs = dispatcher.get_dead_letter_jobs()

        assert len(dlq_jobs) == 1
        assert dlq_jobs[0].job_id == job_dlq.job_id

    def test_get_failed_jobs_for_retry(self, db_session, test_tenant_id):
        """get_failed_jobs_for_retry returns jobs due for retry."""
        dispatcher = JobDispatcher(db_session, test_tenant_id)

        # Job not due for retry (future next_retry_at)
        job_future = dispatcher.dispatch(
            connector_id="connector-1",
            external_account_id="shop-1",
        )
        job_future.mark_failed(
            error_message="Error",
            next_retry_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        # Job due for retry (past next_retry_at)
        job_ready = dispatcher.dispatch(
            connector_id="connector-2",
            external_account_id="shop-1",
        )
        job_ready.mark_failed(
            error_message="Error",
            next_retry_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        # Job already at max retries
        job_maxed = dispatcher.dispatch(
            connector_id="connector-3",
            external_account_id="shop-1",
        )
        job_maxed.retry_count = 5
        job_maxed.status = JobStatus.FAILED
        job_maxed.next_retry_at = datetime.now(timezone.utc) - timedelta(minutes=1)

        db_session.flush()

        retry_jobs = dispatcher.get_failed_jobs_for_retry()

        job_ids = [j.job_id for j in retry_jobs]
        assert job_ready.job_id in job_ids
        assert job_future.job_id not in job_ids
        assert job_maxed.job_id not in job_ids
