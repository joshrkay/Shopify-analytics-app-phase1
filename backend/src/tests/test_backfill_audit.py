"""
Tests for Story 3.4 - Backfill Audit Events.

Tests:
- All 5 audit emit functions produce correct metadata
- Emit functions never raise (graceful failure)
- Executor wires emit calls at correct lifecycle points
- audit_events.py registry contains all backfill events
- AuditAction enum has BACKFILL_PAUSED

Run with: pytest src/tests/test_backfill_audit.py -v
"""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from src.models.historical_backfill import HistoricalBackfillStatus


# =====================================================================
# Helpers
# =====================================================================


def _make_request(**overrides):
    """Build a mock HistoricalBackfillRequest with standard fields."""
    req = MagicMock()
    req.id = overrides.get("id", "req_abc")
    req.tenant_id = overrides.get("tenant_id", "tenant_1")
    req.source_system = overrides.get("source_system", "shopify")
    req.start_date = overrides.get("start_date", date(2024, 1, 1))
    req.end_date = overrides.get("end_date", date(2024, 1, 28))
    req.reason = overrides.get("reason", "Data gap after migration")
    req.requested_by = overrides.get("requested_by", "admin_user")
    req.started_at = overrides.get("started_at", None)
    req.completed_at = overrides.get("completed_at", None)
    req.error_message = overrides.get("error_message", None)
    req.status = overrides.get("status", HistoricalBackfillStatus.PENDING)
    return req


# =====================================================================
# _build_base_metadata
# =====================================================================


class TestBuildBaseMetadata:
    """Tests for the shared metadata builder."""

    def test_builds_all_common_fields(self):
        from src.services.audit_logger import _build_base_metadata

        req = _make_request()
        meta = _build_base_metadata(req)

        assert meta["backfill_id"] == "req_abc"
        assert meta["tenant_id"] == "tenant_1"
        assert meta["source_system"] == "shopify"
        assert meta["date_range"] == {"start": "2024-01-01", "end": "2024-01-28"}
        assert meta["requested_by"] == "admin_user"

    def test_handles_none_dates(self):
        from src.services.audit_logger import _build_base_metadata

        req = _make_request(start_date=None, end_date=None)
        meta = _build_base_metadata(req)

        assert meta["date_range"] == {"start": "", "end": ""}


# =====================================================================
# emit_backfill_requested
# =====================================================================


class TestEmitBackfillRequested:
    """Tests for backfill.requested audit event."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_emits_correct_action_and_metadata(self, mock_log):
        from src.services.audit_logger import emit_backfill_requested

        req = _make_request()
        db = MagicMock()
        emit_backfill_requested(db, req, correlation_id="corr_1")

        mock_log.assert_called_once()
        kwargs = mock_log.call_args[1]
        assert kwargs["action"].value == "backfill.requested"
        assert kwargs["resource_type"] == "historical_backfill_request"
        assert kwargs["resource_id"] == "req_abc"
        assert kwargs["tenant_id"] == "tenant_1"
        assert kwargs["correlation_id"] == "corr_1"
        assert kwargs["source"] == "api"
        assert kwargs["metadata"]["reason"] == "Data gap after migration"
        assert kwargs["metadata"]["backfill_id"] == "req_abc"

    @patch("src.platform.audit.log_system_audit_event_sync", side_effect=Exception("db down"))
    def test_swallows_exception(self, mock_log):
        from src.services.audit_logger import emit_backfill_requested

        req = _make_request()
        emit_backfill_requested(MagicMock(), req)  # Should not raise


# =====================================================================
# emit_backfill_started
# =====================================================================


class TestEmitBackfillStarted:
    """Tests for backfill.started audit event."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_emits_correct_action_and_metadata(self, mock_log):
        from src.services.audit_logger import emit_backfill_started

        req = _make_request(
            started_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
        )
        emit_backfill_started(MagicMock(), req, total_chunks=4)

        kwargs = mock_log.call_args[1]
        assert kwargs["action"].value == "backfill.started"
        assert kwargs["source"] == "worker"
        assert kwargs["metadata"]["total_chunks"] == 4
        assert kwargs["metadata"]["started_at"] == "2024-01-02T00:00:00+00:00"

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_uses_utcnow_if_started_at_is_none(self, mock_log):
        from src.services.audit_logger import emit_backfill_started

        req = _make_request(started_at=None)
        emit_backfill_started(MagicMock(), req, total_chunks=2)

        meta = mock_log.call_args[1]["metadata"]
        assert "started_at" in meta
        assert meta["started_at"] != ""

    @patch("src.platform.audit.log_system_audit_event_sync", side_effect=Exception("boom"))
    def test_swallows_exception(self, mock_log):
        from src.services.audit_logger import emit_backfill_started

        emit_backfill_started(MagicMock(), _make_request(), total_chunks=1)


# =====================================================================
# emit_backfill_paused
# =====================================================================


class TestEmitBackfillPaused:
    """Tests for backfill.paused audit event."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_emits_correct_action_and_metadata(self, mock_log):
        from src.services.audit_logger import emit_backfill_paused

        req = _make_request()
        emit_backfill_paused(MagicMock(), req, paused_chunks=3)

        kwargs = mock_log.call_args[1]
        assert kwargs["action"].value == "backfill.paused"
        assert kwargs["metadata"]["paused_chunks"] == 3
        assert "paused_at" in kwargs["metadata"]

    @patch("src.platform.audit.log_system_audit_event_sync", side_effect=Exception("fail"))
    def test_swallows_exception(self, mock_log):
        from src.services.audit_logger import emit_backfill_paused

        emit_backfill_paused(MagicMock(), _make_request(), paused_chunks=1)


# =====================================================================
# emit_backfill_failed
# =====================================================================


class TestEmitBackfillFailed:
    """Tests for backfill.failed audit event."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_emits_correct_action_and_metadata(self, mock_log):
        from src.services.audit_logger import emit_backfill_failed

        req = _make_request(
            error_message="3 chunk(s) failed permanently",
            completed_at=datetime(2024, 1, 5, tzinfo=timezone.utc),
        )
        emit_backfill_failed(MagicMock(), req)

        kwargs = mock_log.call_args[1]
        assert kwargs["action"].value == "backfill.failed"
        assert kwargs["outcome"].value == "failure"
        assert kwargs["metadata"]["reason"] == "3 chunk(s) failed permanently"
        assert kwargs["metadata"]["failed_at"] == "2024-01-05T00:00:00+00:00"

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_default_reason_when_error_message_none(self, mock_log):
        from src.services.audit_logger import emit_backfill_failed

        req = _make_request(error_message=None)
        emit_backfill_failed(MagicMock(), req)

        assert mock_log.call_args[1]["metadata"]["reason"] == "Unknown failure"

    @patch("src.platform.audit.log_system_audit_event_sync", side_effect=Exception("x"))
    def test_swallows_exception(self, mock_log):
        from src.services.audit_logger import emit_backfill_failed

        emit_backfill_failed(MagicMock(), _make_request())


# =====================================================================
# emit_backfill_completed
# =====================================================================


class TestEmitBackfillCompleted:
    """Tests for backfill.completed audit event."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_emits_correct_action_and_metadata(self, mock_log):
        from src.services.audit_logger import emit_backfill_completed

        req = _make_request(
            completed_at=datetime(2024, 1, 10, tzinfo=timezone.utc),
        )
        emit_backfill_completed(MagicMock(), req)

        kwargs = mock_log.call_args[1]
        assert kwargs["action"].value == "backfill.completed"
        assert kwargs["outcome"].value == "success"
        assert kwargs["metadata"]["completed_at"] == "2024-01-10T00:00:00+00:00"

    @patch("src.platform.audit.log_system_audit_event_sync", side_effect=Exception("x"))
    def test_swallows_exception(self, mock_log):
        from src.services.audit_logger import emit_backfill_completed

        emit_backfill_completed(MagicMock(), _make_request())


# =====================================================================
# AuditAction Enum & Registry
# =====================================================================


class TestAuditActionBackfillEntries:
    """Verify AuditAction enum has all 5 backfill events."""

    def test_all_backfill_actions_exist(self):
        from src.platform.audit import AuditAction

        assert AuditAction.BACKFILL_REQUESTED.value == "backfill.requested"
        assert AuditAction.BACKFILL_STARTED.value == "backfill.started"
        assert AuditAction.BACKFILL_PAUSED.value == "backfill.paused"
        assert AuditAction.BACKFILL_COMPLETED.value == "backfill.completed"
        assert AuditAction.BACKFILL_FAILED.value == "backfill.failed"


class TestAuditEventsRegistry:
    """Verify audit_events.py registry contains backfill events."""

    def test_all_events_registered(self):
        from src.platform.audit_events import AUDITABLE_EVENTS

        for event_key in [
            "backfill.requested",
            "backfill.started",
            "backfill.paused",
            "backfill.completed",
            "backfill.failed",
        ]:
            assert event_key in AUDITABLE_EVENTS, f"{event_key} missing"

    def test_required_fields_present(self):
        from src.platform.audit_events import AUDITABLE_EVENTS

        common = {"backfill_id", "tenant_id", "source_system", "date_range", "requested_by"}

        for event_key in AUDITABLE_EVENTS:
            if not event_key.startswith("backfill."):
                continue
            fields = set(AUDITABLE_EVENTS[event_key])
            missing = common - fields
            assert not missing, f"{event_key} missing common fields: {missing}"

    def test_backfill_category_exists(self):
        from src.platform.audit_events import EVENT_CATEGORIES

        assert "backfill" in EVENT_CATEGORIES
        assert len(EVENT_CATEGORIES["backfill"]) == 5

    def test_severity_assigned(self):
        from src.platform.audit_events import EVENT_SEVERITY

        assert EVENT_SEVERITY["backfill.requested"] == "high"
        assert EVENT_SEVERITY["backfill.failed"] == "high"
        assert EVENT_SEVERITY["backfill.started"] == "medium"
        assert EVENT_SEVERITY["backfill.paused"] == "medium"
        assert EVENT_SEVERITY["backfill.completed"] == "low"


class TestAuditableEventsMetadataRegistry:
    """Verify AUDITABLE_EVENTS in audit.py has correct required_fields."""

    def test_requested_required_fields(self):
        from src.platform.audit import AUDITABLE_EVENTS, AuditAction

        meta = AUDITABLE_EVENTS[AuditAction.BACKFILL_REQUESTED]
        assert "backfill_id" in meta.required_fields
        assert "reason" in meta.required_fields

    def test_paused_required_fields(self):
        from src.platform.audit import AUDITABLE_EVENTS, AuditAction

        meta = AUDITABLE_EVENTS[AuditAction.BACKFILL_PAUSED]
        assert "paused_chunks" in meta.required_fields
        assert "paused_at" in meta.required_fields

    def test_failed_required_fields(self):
        from src.platform.audit import AUDITABLE_EVENTS, AuditAction

        meta = AUDITABLE_EVENTS[AuditAction.BACKFILL_FAILED]
        assert "reason" in meta.required_fields
        assert "failed_at" in meta.required_fields


# =====================================================================
# Executor Integration — verify audit wired at lifecycle points
# =====================================================================


class TestExecutorEmitsStarted:
    """Verify executor emits backfill.started when creating jobs."""

    @patch("src.services.audit_logger.emit_backfill_started")
    def test_create_jobs_emits_started(self, mock_emit):
        from src.services.backfill_executor import BackfillExecutor

        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        req = _make_request(
            status=HistoricalBackfillStatus.APPROVED,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 14),
        )

        executor.create_jobs_for_request(req)

        mock_emit.assert_called_once()
        args = mock_emit.call_args
        assert args[0][0] is mock_db  # db session
        assert args[0][1] is req       # request
        assert args[1]["total_chunks"] == 2  # 14 days = 2 chunks


class TestExecutorEmitsPaused:
    """Verify executor emits backfill.paused when pausing."""

    @patch("src.services.audit_logger.emit_backfill_paused")
    def test_pause_request_emits_paused(self, mock_emit):
        from src.services.backfill_executor import BackfillExecutor
        from src.models.backfill_job import BackfillJobStatus

        mock_db = MagicMock()

        # Mock queued jobs that will be paused
        mock_job = MagicMock()
        mock_job.status = BackfillJobStatus.QUEUED
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_job]

        # Mock parent request lookup
        mock_request = _make_request()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_request

        executor = BackfillExecutor(mock_db)
        count = executor.pause_request("req_abc")

        assert count == 1
        mock_emit.assert_called_once()
        assert mock_emit.call_args[1]["paused_chunks"] == 1


class TestExecutorEmitsFailedAndCompleted:
    """Verify executor emits failed/completed on terminal status."""

    @patch("src.services.backfill_state_guard.BackfillStateGuard")
    @patch("src.services.audit_logger.emit_backfill_completed")
    def test_all_success_emits_completed(self, mock_emit_completed, mock_guard):
        from src.services.backfill_executor import BackfillExecutor
        from src.models.backfill_job import BackfillJobStatus

        mock_db = MagicMock()

        # All jobs succeeded
        job = MagicMock()
        job.status = BackfillJobStatus.SUCCESS
        job.is_terminal = True
        job.can_retry = False
        mock_db.query.return_value.filter.return_value.all.return_value = [job]

        # Parent request
        parent = _make_request(status=HistoricalBackfillStatus.RUNNING)
        mock_db.query.return_value.filter.return_value.first.return_value = parent

        executor = BackfillExecutor(mock_db)
        executor._update_parent_status("req_abc")

        mock_emit_completed.assert_called_once_with(mock_db, parent)

    @patch("src.services.backfill_state_guard.BackfillStateGuard")
    @patch("src.services.audit_logger.emit_backfill_failed")
    def test_terminal_failure_emits_failed(self, mock_emit_failed, mock_guard):
        from src.services.backfill_executor import BackfillExecutor
        from src.models.backfill_job import BackfillJobStatus

        mock_db = MagicMock()

        # One job failed permanently
        job_ok = MagicMock()
        job_ok.status = BackfillJobStatus.SUCCESS
        job_ok.is_terminal = True
        job_ok.can_retry = False

        job_fail = MagicMock()
        job_fail.status = BackfillJobStatus.FAILED
        job_fail.is_terminal = True
        job_fail.can_retry = False

        mock_db.query.return_value.filter.return_value.all.return_value = [
            job_ok, job_fail,
        ]

        parent = _make_request(status=HistoricalBackfillStatus.RUNNING)
        mock_db.query.return_value.filter.return_value.first.return_value = parent

        executor = BackfillExecutor(mock_db)
        executor._update_parent_status("req_abc")

        mock_emit_failed.assert_called_once_with(mock_db, parent)


# =====================================================================
# State guard no longer emits audit directly
# =====================================================================


class TestStateGuardNoDirectAudit:
    """Verify state guard delegates audit to executor via audit_logger."""

    def test_no_log_backfill_completion_method(self):
        """_log_backfill_completion should be removed from guard."""
        from src.services.backfill_state_guard import BackfillStateGuard

        assert not hasattr(BackfillStateGuard, "_log_backfill_completion")
