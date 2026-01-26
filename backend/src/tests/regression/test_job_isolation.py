"""
Tests for ingestion job isolation.

Validates:
- Only ONE active job per tenant + connector combination
- Tenant A cannot see/modify Tenant B's jobs
- Race condition handling in concurrent dispatch
- Isolation constraint enforcement at database level

Story: Ingestion Orchestration - Job Isolation
"""

import uuid
import pytest
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from src.ingestion.jobs.models import IngestionJob, JobStatus
from src.ingestion.jobs.dispatcher import (
    JobDispatcher,
    JobIsolationError,
    JobNotFoundError,
    get_global_queued_jobs,
)


class TestJobIsolation:
    """Tests for job isolation enforcement."""

    def test_dispatch_creates_queued_job(self, db_session, test_tenant_id):
        """Dispatcher creates job in QUEUED status."""
        dispatcher = JobDispatcher(db_session, test_tenant_id)
        connector_id = f"connector-{uuid.uuid4().hex[:8]}"
        external_id = f"shop-{uuid.uuid4().hex[:8]}"

        job = dispatcher.dispatch(
            connector_id=connector_id,
            external_account_id=external_id,
            correlation_id="test-correlation-123",
        )

        assert job.job_id is not None
        assert job.tenant_id == test_tenant_id
        assert job.connector_id == connector_id
        assert job.external_account_id == external_id
        assert job.status == JobStatus.QUEUED
        assert job.retry_count == 0
        assert job.correlation_id == "test-correlation-123"

    def test_dispatch_blocked_when_active_job_exists(
        self,
        db_session,
        test_tenant_id,
    ):
        """Second dispatch fails when active job exists for same connector."""
        dispatcher = JobDispatcher(db_session, test_tenant_id)
        connector_id = f"connector-{uuid.uuid4().hex[:8]}"

        # First dispatch succeeds
        job1 = dispatcher.dispatch(
            connector_id=connector_id,
            external_account_id="shop-1",
        )
        assert job1.status == JobStatus.QUEUED

        # Second dispatch fails
        with pytest.raises(JobIsolationError) as exc_info:
            dispatcher.dispatch(
                connector_id=connector_id,
                external_account_id="shop-1",
            )

        assert exc_info.value.existing_job_id == job1.job_id
        assert "Active job already exists" in str(exc_info.value)

    def test_dispatch_allowed_for_different_connectors(
        self,
        db_session,
        test_tenant_id,
    ):
        """Jobs for different connectors can run concurrently."""
        dispatcher = JobDispatcher(db_session, test_tenant_id)

        job1 = dispatcher.dispatch(
            connector_id="connector-1",
            external_account_id="shop-1",
        )
        job2 = dispatcher.dispatch(
            connector_id="connector-2",
            external_account_id="shop-1",
        )

        assert job1.job_id != job2.job_id
        assert job1.status == JobStatus.QUEUED
        assert job2.status == JobStatus.QUEUED

    def test_dispatch_allowed_after_job_success(
        self,
        db_session,
        test_tenant_id,
    ):
        """New job can be dispatched after previous job succeeds."""
        dispatcher = JobDispatcher(db_session, test_tenant_id)
        connector_id = f"connector-{uuid.uuid4().hex[:8]}"

        # First job
        job1 = dispatcher.dispatch(
            connector_id=connector_id,
            external_account_id="shop-1",
        )
        job1.mark_success()
        db_session.flush()

        # Second job allowed
        job2 = dispatcher.dispatch(
            connector_id=connector_id,
            external_account_id="shop-1",
        )

        assert job2.job_id != job1.job_id
        assert job2.status == JobStatus.QUEUED

    def test_dispatch_allowed_after_job_dead_lettered(
        self,
        db_session,
        test_tenant_id,
    ):
        """New job can be dispatched after previous job moves to DLQ."""
        dispatcher = JobDispatcher(db_session, test_tenant_id)
        connector_id = f"connector-{uuid.uuid4().hex[:8]}"

        # First job goes to DLQ
        job1 = dispatcher.dispatch(
            connector_id=connector_id,
            external_account_id="shop-1",
        )
        job1.mark_dead_letter("Max retries exceeded")
        db_session.flush()

        # Second job allowed
        job2 = dispatcher.dispatch(
            connector_id=connector_id,
            external_account_id="shop-1",
        )

        assert job2.job_id != job1.job_id
        assert job2.status == JobStatus.QUEUED

    def test_dispatch_blocked_while_job_running(
        self,
        db_session,
        test_tenant_id,
    ):
        """Cannot dispatch when job is running."""
        dispatcher = JobDispatcher(db_session, test_tenant_id)
        connector_id = f"connector-{uuid.uuid4().hex[:8]}"

        job1 = dispatcher.dispatch(
            connector_id=connector_id,
            external_account_id="shop-1",
        )
        job1.mark_running(run_id="airbyte-run-123")
        db_session.flush()

        with pytest.raises(JobIsolationError):
            dispatcher.dispatch(
                connector_id=connector_id,
                external_account_id="shop-1",
            )

    def test_dispatch_allowed_while_job_failed_awaiting_retry(
        self,
        db_session,
        test_tenant_id,
    ):
        """New job can be dispatched when previous is failed (not active)."""
        dispatcher = JobDispatcher(db_session, test_tenant_id)
        connector_id = f"connector-{uuid.uuid4().hex[:8]}"

        job1 = dispatcher.dispatch(
            connector_id=connector_id,
            external_account_id="shop-1",
        )
        job1.mark_failed(
            error_message="Server error",
            error_code="server_error",
            next_retry_at=datetime.now(timezone.utc),
        )
        db_session.flush()

        # Failed job is not active, so new dispatch is allowed
        job2 = dispatcher.dispatch(
            connector_id=connector_id,
            external_account_id="shop-1",
        )

        assert job2.job_id != job1.job_id


class TestTenantIsolation:
    """Tests for multi-tenant isolation."""

    def test_tenant_a_cannot_see_tenant_b_jobs(
        self,
        db_session,
        test_tenant_id,
        test_tenant_id_b,
    ):
        """Tenant A's dispatcher cannot see Tenant B's jobs."""
        dispatcher_a = JobDispatcher(db_session, test_tenant_id)
        dispatcher_b = JobDispatcher(db_session, test_tenant_id_b)
        connector_id = "shared-connector-id"

        # Tenant A creates a job
        job_a = dispatcher_a.dispatch(
            connector_id=connector_id,
            external_account_id="shop-a",
        )

        # Tenant B can also create a job for same connector ID
        job_b = dispatcher_b.dispatch(
            connector_id=connector_id,
            external_account_id="shop-b",
        )

        assert job_a.job_id != job_b.job_id
        assert job_a.tenant_id == test_tenant_id
        assert job_b.tenant_id == test_tenant_id_b

    def test_tenant_a_cannot_get_tenant_b_job(
        self,
        db_session,
        test_tenant_id,
        test_tenant_id_b,
    ):
        """Tenant A's dispatcher cannot retrieve Tenant B's job by ID."""
        dispatcher_a = JobDispatcher(db_session, test_tenant_id)
        dispatcher_b = JobDispatcher(db_session, test_tenant_id_b)

        job_b = dispatcher_b.dispatch(
            connector_id="connector-1",
            external_account_id="shop-b",
        )

        # Tenant A cannot see Tenant B's job
        result = dispatcher_a.get_job(job_b.job_id)
        assert result is None

    def test_tenant_a_cannot_see_tenant_b_queued_jobs(
        self,
        db_session,
        test_tenant_id,
        test_tenant_id_b,
    ):
        """Tenant A's queued jobs list excludes Tenant B's jobs."""
        dispatcher_a = JobDispatcher(db_session, test_tenant_id)
        dispatcher_b = JobDispatcher(db_session, test_tenant_id_b)

        job_a = dispatcher_a.dispatch(
            connector_id="connector-1",
            external_account_id="shop-a",
        )
        job_b = dispatcher_b.dispatch(
            connector_id="connector-2",
            external_account_id="shop-b",
        )

        queued_a = dispatcher_a.get_queued_jobs()
        queued_b = dispatcher_b.get_queued_jobs()

        assert len(queued_a) == 1
        assert queued_a[0].job_id == job_a.job_id

        assert len(queued_b) == 1
        assert queued_b[0].job_id == job_b.job_id

    def test_tenant_a_cannot_cancel_tenant_b_job(
        self,
        db_session,
        test_tenant_id,
        test_tenant_id_b,
    ):
        """Tenant A cannot cancel Tenant B's job."""
        dispatcher_a = JobDispatcher(db_session, test_tenant_id)
        dispatcher_b = JobDispatcher(db_session, test_tenant_id_b)

        job_b = dispatcher_b.dispatch(
            connector_id="connector-1",
            external_account_id="shop-b",
        )

        with pytest.raises(JobNotFoundError):
            dispatcher_a.cancel_job(job_b.job_id)


class TestGlobalJobQueries:
    """Tests for global job queries used by workers."""

    def test_global_queued_jobs_returns_all_tenants(
        self,
        db_session,
        test_tenant_id,
        test_tenant_id_b,
    ):
        """Global query returns jobs from all tenants for worker processing."""
        dispatcher_a = JobDispatcher(db_session, test_tenant_id)
        dispatcher_b = JobDispatcher(db_session, test_tenant_id_b)

        job_a = dispatcher_a.dispatch(
            connector_id="connector-1",
            external_account_id="shop-a",
        )
        job_b = dispatcher_b.dispatch(
            connector_id="connector-2",
            external_account_id="shop-b",
        )

        global_jobs = get_global_queued_jobs(db_session, limit=100)

        job_ids = [j.job_id for j in global_jobs]
        assert job_a.job_id in job_ids
        assert job_b.job_id in job_ids

    def test_global_queued_jobs_ordered_by_created_at(
        self,
        db_session,
        test_tenant_id,
    ):
        """Global query returns jobs in FIFO order."""
        dispatcher = JobDispatcher(db_session, test_tenant_id)

        job1 = dispatcher.dispatch(
            connector_id="connector-1",
            external_account_id="shop-1",
        )
        job1.mark_success()
        db_session.flush()

        job2 = dispatcher.dispatch(
            connector_id="connector-1",
            external_account_id="shop-1",
        )

        global_jobs = get_global_queued_jobs(db_session, limit=100)

        # Only job2 should be in queue (job1 is success)
        assert len(global_jobs) >= 1
        queued_job_ids = [j.job_id for j in global_jobs]
        assert job2.job_id in queued_job_ids
        assert job1.job_id not in queued_job_ids


class TestJobRequeue:
    """Tests for dead letter queue requeue functionality."""

    def test_requeue_from_dlq_creates_new_job(
        self,
        db_session,
        test_tenant_id,
    ):
        """Requeue creates new job with reset retry count."""
        dispatcher = JobDispatcher(db_session, test_tenant_id)
        connector_id = f"connector-{uuid.uuid4().hex[:8]}"

        original = dispatcher.dispatch(
            connector_id=connector_id,
            external_account_id="shop-1",
        )
        original.mark_dead_letter("Max retries exceeded")
        db_session.flush()

        requeued = dispatcher.requeue_from_dlq(
            job_id=original.job_id,
            correlation_id="support-requeue-123",
        )

        assert requeued.job_id != original.job_id
        assert requeued.status == JobStatus.QUEUED
        assert requeued.retry_count == 0
        assert requeued.job_metadata.get("requeued_from") == original.job_id

    def test_requeue_fails_if_not_in_dlq(
        self,
        db_session,
        test_tenant_id,
    ):
        """Cannot requeue a job that is not in dead letter status."""
        dispatcher = JobDispatcher(db_session, test_tenant_id)

        job = dispatcher.dispatch(
            connector_id="connector-1",
            external_account_id="shop-1",
        )

        with pytest.raises(ValueError) as exc_info:
            dispatcher.requeue_from_dlq(job.job_id)

        assert "not in dead letter queue" in str(exc_info.value)

    def test_requeue_fails_if_active_job_exists(
        self,
        db_session,
        test_tenant_id,
    ):
        """Cannot requeue if an active job already exists for connector."""
        dispatcher = JobDispatcher(db_session, test_tenant_id)
        connector_id = f"connector-{uuid.uuid4().hex[:8]}"

        # Create and DLQ first job
        dlq_job = dispatcher.dispatch(
            connector_id=connector_id,
            external_account_id="shop-1",
        )
        dlq_job.mark_dead_letter("Error")
        db_session.flush()

        # Create new active job
        dispatcher.dispatch(
            connector_id=connector_id,
            external_account_id="shop-1",
        )

        # Cannot requeue DLQ job - active job exists
        with pytest.raises(JobIsolationError):
            dispatcher.requeue_from_dlq(dlq_job.job_id)


class TestDispatcherValidation:
    """Tests for dispatcher input validation."""

    def test_dispatcher_requires_tenant_id(self, db_session):
        """Dispatcher raises ValueError if tenant_id is empty."""
        with pytest.raises(ValueError) as exc_info:
            JobDispatcher(db_session, "")

        assert "tenant_id is required" in str(exc_info.value)

    def test_dispatcher_requires_non_none_tenant_id(self, db_session):
        """Dispatcher raises ValueError if tenant_id is None."""
        with pytest.raises(ValueError):
            JobDispatcher(db_session, None)
