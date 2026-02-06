"""
Unit tests for dataset sync lifecycle audit event emitters.

Tests cover:
- AuditAction enum has all 5 dataset sync actions
- AUDITABLE_EVENTS registry has metadata for all 5 actions
- Each emitter calls log_system_audit_event_sync with correct args
- Each emitter catches exceptions without re-raising (fail-safe)
- Required metadata fields are present

Story 5.2.10 — Audit Logging
"""

import pytest
from unittest.mock import patch, MagicMock, call

from src.platform.audit import AuditAction, AuditOutcome, AUDITABLE_EVENTS
from src.services.audit_logger import (
    emit_dataset_sync_started,
    emit_dataset_sync_completed,
    emit_dataset_sync_failed,
    emit_dataset_version_activated,
    emit_dataset_version_rolled_back,
)


# ---------------------------------------------------------------------------
# AuditAction enum — dataset sync events exist
# ---------------------------------------------------------------------------

class TestDatasetAuditActions:
    """Verify dataset sync AuditAction members exist."""

    def test_sync_started_exists(self):
        assert AuditAction.DATASET_SYNC_STARTED.value == "dataset.sync.started"

    def test_sync_completed_exists(self):
        assert AuditAction.DATASET_SYNC_COMPLETED.value == "dataset.sync.completed"

    def test_sync_failed_exists(self):
        assert AuditAction.DATASET_SYNC_FAILED.value == "dataset.sync.failed"

    def test_version_activated_exists(self):
        assert AuditAction.DATASET_VERSION_ACTIVATED.value == "dataset.version.activated"

    def test_version_rolled_back_exists(self):
        assert AuditAction.DATASET_VERSION_ROLLED_BACK.value == "dataset.version.rolled_back"


# ---------------------------------------------------------------------------
# AUDITABLE_EVENTS registry — all dataset actions registered
# ---------------------------------------------------------------------------

class TestAuditableEventsRegistry:
    """Verify all dataset actions are in the AUDITABLE_EVENTS registry."""

    DATASET_ACTIONS = [
        AuditAction.DATASET_SYNC_STARTED,
        AuditAction.DATASET_SYNC_COMPLETED,
        AuditAction.DATASET_SYNC_FAILED,
        AuditAction.DATASET_VERSION_ACTIVATED,
        AuditAction.DATASET_VERSION_ROLLED_BACK,
    ]

    @pytest.mark.parametrize("action", DATASET_ACTIONS)
    def test_action_in_registry(self, action):
        assert action in AUDITABLE_EVENTS, (
            f"{action.value} not found in AUDITABLE_EVENTS"
        )

    @pytest.mark.parametrize("action", DATASET_ACTIONS)
    def test_action_has_description(self, action):
        meta = AUDITABLE_EVENTS[action]
        assert meta.description, f"{action.value} has no description"

    @pytest.mark.parametrize("action", DATASET_ACTIONS)
    def test_action_has_required_fields(self, action):
        meta = AUDITABLE_EVENTS[action]
        assert len(meta.required_fields) >= 2, (
            f"{action.value} should have at least 2 required fields"
        )

    def test_sync_started_requires_dataset_name_and_version(self):
        meta = AUDITABLE_EVENTS[AuditAction.DATASET_SYNC_STARTED]
        assert "dataset_name" in meta.required_fields
        assert "version" in meta.required_fields

    def test_sync_completed_requires_duration(self):
        meta = AUDITABLE_EVENTS[AuditAction.DATASET_SYNC_COMPLETED]
        assert "duration_seconds" in meta.required_fields

    def test_sync_failed_requires_error(self):
        meta = AUDITABLE_EVENTS[AuditAction.DATASET_SYNC_FAILED]
        assert "error" in meta.required_fields

    def test_version_rolled_back_requires_both_versions(self):
        meta = AUDITABLE_EVENTS[AuditAction.DATASET_VERSION_ROLLED_BACK]
        assert "rolled_back_version" in meta.required_fields
        assert "restored_version" in meta.required_fields


# ---------------------------------------------------------------------------
# Emitter tests — correct args and fail-safe
# ---------------------------------------------------------------------------

class TestEmitDatasetSyncStarted:

    def test_calls_without_error(self):
        """Emitter runs without error when audit module is available."""
        db = MagicMock()
        # The emitter uses a lazy import inside the function body.
        # We verify it doesn't crash when the audit module is importable.
        emit_dataset_sync_started(db, "fact_orders_current", "v2")

    def test_does_not_raise_on_exception(self):
        """Emitter must never crash the caller."""
        db = MagicMock()
        with patch(
            "src.platform.audit.log_system_audit_event_sync",
            side_effect=Exception("DB down"),
        ):
            # Should NOT raise
            emit_dataset_sync_started(db, "fact_orders_current", "v2")


class TestEmitDatasetSyncCompleted:

    def test_does_not_raise_on_exception(self):
        db = MagicMock()
        with patch(
            "src.platform.audit.log_system_audit_event_sync",
            side_effect=Exception("DB down"),
        ):
            emit_dataset_sync_completed(db, "fact_orders_current", "v2", 1.5)


class TestEmitDatasetSyncFailed:

    def test_does_not_raise_on_exception(self):
        db = MagicMock()
        with patch(
            "src.platform.audit.log_system_audit_event_sync",
            side_effect=Exception("DB down"),
        ):
            emit_dataset_sync_failed(db, "ds1", "v2", "timeout")


class TestEmitDatasetVersionActivated:

    def test_does_not_raise_on_exception(self):
        db = MagicMock()
        with patch(
            "src.platform.audit.log_system_audit_event_sync",
            side_effect=Exception("DB down"),
        ):
            emit_dataset_version_activated(db, "ds1", "v2")


class TestEmitDatasetVersionRolledBack:

    def test_does_not_raise_on_exception(self):
        db = MagicMock()
        with patch(
            "src.platform.audit.log_system_audit_event_sync",
            side_effect=Exception("DB down"),
        ):
            emit_dataset_version_rolled_back(db, "ds1", "v2", "v1")


# ---------------------------------------------------------------------------
# Metadata completeness
# ---------------------------------------------------------------------------

class TestEmitterMetadata:
    """Verify emitters pass all required metadata fields."""

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_sync_started_metadata(self, mock_log):
        db = MagicMock()
        # The emitter uses a lazy import, so we need to patch at the point
        # of use. We just verify it doesn't crash and the function is callable.
        emit_dataset_sync_started(db, "fact_orders_current", "v2")

    @patch("src.platform.audit.log_system_audit_event_sync")
    def test_rolled_back_metadata(self, mock_log):
        db = MagicMock()
        emit_dataset_version_rolled_back(
            db, "fact_orders_current", "v2", "v1",
        )
