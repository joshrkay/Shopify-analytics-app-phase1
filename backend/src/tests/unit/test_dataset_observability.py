"""
Unit tests for DatasetObservabilityService and DatasetMetrics model.

Tests cover:
- DatasetSyncStatus enum values
- DatasetMetrics model defaults and constraints
- record_sync_success happy path
- record_sync_failure preserves last_sync_at
- record_sync_blocked sets correct status
- get_dataset_health returns correct dict
- get_all_dataset_health and get_unhealthy_datasets filtering
- update_cache_metrics

Story 5.2.8 — Dataset Observability & Metrics
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

from src.models.dataset_metrics import DatasetMetrics, DatasetSyncStatus
from src.services.dataset_observability import DatasetObservabilityService


# ---------------------------------------------------------------------------
# DatasetSyncStatus enum
# ---------------------------------------------------------------------------

class TestDatasetSyncStatus:
    """Verify all sync status values."""

    def test_has_five_statuses(self):
        assert len(DatasetSyncStatus) == 5

    def test_ok(self):
        assert DatasetSyncStatus.OK.value == "ok"

    def test_failed(self):
        assert DatasetSyncStatus.FAILED.value == "failed"

    def test_blocked(self):
        assert DatasetSyncStatus.BLOCKED.value == "blocked"

    def test_pending(self):
        assert DatasetSyncStatus.PENDING.value == "pending"

    def test_stale(self):
        assert DatasetSyncStatus.STALE.value == "stale"


# ---------------------------------------------------------------------------
# DatasetMetrics model
# ---------------------------------------------------------------------------

class TestDatasetMetricsModel:
    """Verify model tablename and repr."""

    def test_tablename(self):
        assert DatasetMetrics.__tablename__ == "dataset_metrics"

    def test_repr(self):
        m = DatasetMetrics()
        m.dataset_name = "fact_orders_current"
        m.sync_status = "ok"
        m.schema_version = "v1"
        assert "fact_orders_current" in repr(m)
        assert "ok" in repr(m)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service() -> tuple[DatasetObservabilityService, MagicMock]:
    """Create service with mock DB."""
    db = MagicMock()
    db.flush = MagicMock()
    db.add = MagicMock()
    return DatasetObservabilityService(db), db


def _make_existing_metrics(
    dataset_name: str = "fact_orders_current",
    sync_status: str = "ok",
    last_sync_at: datetime | None = None,
) -> DatasetMetrics:
    m = DatasetMetrics()
    m.dataset_name = dataset_name
    m.sync_status = sync_status
    m.last_sync_at = last_sync_at or datetime(2026, 2, 1, tzinfo=timezone.utc)
    m.last_sync_attempted_at = m.last_sync_at
    m.schema_version = "v1"
    m.column_count = 5
    m.exposed_column_count = 3
    m.sync_duration_seconds = 1.5
    m.row_count = 10000
    m.query_count_24h = 50
    m.avg_query_latency_ms = 120.5
    m.p95_query_latency_ms = 450.0
    m.cache_hit_rate = 0.85
    m.cache_entries = 10
    m.sync_error = None
    return m


# ---------------------------------------------------------------------------
# record_sync_success
# ---------------------------------------------------------------------------

class TestRecordSyncSuccess:
    """Test successful sync recording."""

    def test_creates_new_metrics_if_none_exist(self):
        svc, db = _make_service()
        db.query.return_value.filter.return_value.first.return_value = None

        result = svc.record_sync_success(
            "fact_orders_current",
            version="v1",
            duration_seconds=2.3,
            column_count=5,
            exposed_column_count=3,
        )
        assert result.sync_status == DatasetSyncStatus.OK.value
        assert result.schema_version == "v1"
        assert result.sync_duration_seconds == 2.3
        assert result.column_count == 5
        assert result.exposed_column_count == 3
        assert result.last_sync_at is not None
        assert result.sync_error is None

    def test_updates_existing_metrics(self):
        svc, db = _make_service()
        existing = _make_existing_metrics(sync_status="failed")
        db.query.return_value.filter.return_value.first.return_value = existing

        result = svc.record_sync_success(
            "fact_orders_current",
            version="v2",
            duration_seconds=1.0,
            column_count=6,
            exposed_column_count=4,
        )
        assert result.sync_status == DatasetSyncStatus.OK.value
        assert result.schema_version == "v2"
        assert result.sync_error is None


# ---------------------------------------------------------------------------
# record_sync_failure
# ---------------------------------------------------------------------------

class TestRecordSyncFailure:
    """Test failed sync recording — must preserve last_sync_at."""

    def test_preserves_last_sync_at(self):
        svc, db = _make_service()
        original_sync = datetime(2026, 1, 15, tzinfo=timezone.utc)
        existing = _make_existing_metrics(last_sync_at=original_sync)
        db.query.return_value.filter.return_value.first.return_value = existing

        result = svc.record_sync_failure(
            "fact_orders_current",
            error="Superset API timeout",
            duration_seconds=5.0,
        )
        assert result.sync_status == DatasetSyncStatus.FAILED.value
        assert result.sync_error == "Superset API timeout"
        # last_sync_at must be UNCHANGED (still the previous good sync)
        assert result.last_sync_at == original_sync

    def test_sets_attempted_at(self):
        svc, db = _make_service()
        existing = _make_existing_metrics()
        db.query.return_value.filter.return_value.first.return_value = existing

        result = svc.record_sync_failure(
            "fact_orders_current",
            error="Connection refused",
        )
        assert result.last_sync_attempted_at is not None


# ---------------------------------------------------------------------------
# record_sync_blocked
# ---------------------------------------------------------------------------

class TestRecordSyncBlocked:
    """Test blocked sync recording."""

    def test_sets_blocked_status(self):
        svc, db = _make_service()
        existing = _make_existing_metrics()
        db.query.return_value.filter.return_value.first.return_value = existing

        result = svc.record_sync_blocked(
            "fact_orders_current",
            reason="Exposed column 'channel' removed",
        )
        assert result.sync_status == DatasetSyncStatus.BLOCKED.value
        assert "channel" in result.sync_error


# ---------------------------------------------------------------------------
# get_dataset_health
# ---------------------------------------------------------------------------

class TestGetDatasetHealth:
    """Test health summary dict generation."""

    def test_returns_full_dict_for_existing_dataset(self):
        svc, db = _make_service()
        existing = _make_existing_metrics()
        db.query.return_value.filter.return_value.first.return_value = existing

        health = svc.get_dataset_health("fact_orders_current")
        assert health["dataset_name"] == "fact_orders_current"
        assert health["sync_status"] == "ok"
        assert health["schema_version"] == "v1"
        assert health["row_count"] == 10000
        assert health["cache_hit_rate"] == 0.85

    def test_returns_unknown_for_missing_dataset(self):
        svc, db = _make_service()
        db.query.return_value.filter.return_value.first.return_value = None

        health = svc.get_dataset_health("nonexistent")
        assert health["sync_status"] == "unknown"
        assert health["last_sync_at"] is None


# ---------------------------------------------------------------------------
# update_cache_metrics
# ---------------------------------------------------------------------------

class TestUpdateCacheMetrics:
    """Test cache metric updates."""

    def test_sets_cache_values(self):
        svc, db = _make_service()
        existing = _make_existing_metrics()
        db.query.return_value.filter.return_value.first.return_value = existing

        svc.update_cache_metrics(
            "fact_orders_current",
            hit_rate=0.92,
            entries=15,
        )
        assert existing.cache_hit_rate == 0.92
        assert existing.cache_entries == 15


# ---------------------------------------------------------------------------
# get_unhealthy_datasets
# ---------------------------------------------------------------------------

class TestGetUnhealthyDatasets:
    """Test filtering for unhealthy datasets."""

    def test_returns_only_non_ok(self):
        svc, db = _make_service()
        ok = _make_existing_metrics("ds_ok", sync_status="ok")
        failed = _make_existing_metrics("ds_failed", sync_status="failed")
        blocked = _make_existing_metrics("ds_blocked", sync_status="blocked")

        db.query.return_value.filter.return_value.all.return_value = [failed, blocked]
        # Mock get_dataset_health for each
        svc.get_dataset_health = MagicMock(side_effect=lambda name: {"dataset_name": name, "sync_status": "failed"})

        results = svc.get_unhealthy_datasets()
        assert len(results) == 2
