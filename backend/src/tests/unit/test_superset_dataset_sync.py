"""
Unit tests for SupersetDatasetSync.

Covers: load manifest failure, compatibility blocked, idempotent upsert (create then update),
observability record_sync_success/record_sync_failure/record_sync_blocked, superset_expose filtering.

Story 5.2 — Prompt 5.2.4
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.services.schema_compatibility_checker import (
    DatasetSchemaSnapshot,
    DatasetViewSchema,
    ColumnSchema,
    build_snapshot_from_manifest,
)
from src.services.superset_dataset_sync import (
    SupersetDatasetSync,
    SyncResult,
    _parse_manifest,
    _get_semantic_models_with_exposed_columns,
    _is_semantic_view,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_manifest_one_model() -> dict:
    """Manifest with one semantic view and one exposed column."""
    return {
        "nodes": {
            "model.markinsight.fact_orders_current": {
                "unique_id": "model.markinsight.fact_orders_current",
                "name": "fact_orders_current",
                "schema": "semantic",
                "columns": {
                    "tenant_id": {"data_type": "VARCHAR", "meta": {"superset_expose": True}},
                    "id": {"data_type": "VARCHAR", "meta": {"superset_expose": False}},
                },
            },
        },
    }


def _make_sync_service(db=None):
    db = db or MagicMock()
    return SupersetDatasetSync(
        db=db,
        superset_url="http://superset.example.com",
        superset_username="u",
        superset_password="p",
        database_name="markinsight",
    )


# ---------------------------------------------------------------------------
# _parse_manifest, _is_semantic_view, _get_semantic_models_with_exposed_columns
# ---------------------------------------------------------------------------


class TestParseManifest:
    def test_parse_manifest_loads_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"nodes": {}}, f)
            path = f.name
        try:
            out = _parse_manifest(path)
            assert out == {"nodes": {}}
        finally:
            Path(path).unlink(missing_ok=True)

    def test_parse_manifest_missing_raises(self):
        with pytest.raises(FileNotFoundError):
            _parse_manifest("/nonexistent/manifest.json")


class TestIsSemanticView:
    def test_fact_current(self):
        assert _is_semantic_view("fact_orders_current") is True

    def test_sem_v1(self):
        assert _is_semantic_view("sem_orders_v1") is True

    def test_other_fails(self):
        assert _is_semantic_view("orders") is False
        assert _is_semantic_view("stg_orders") is False


class TestGetSemanticModelsWithExposedColumns:
    def test_only_exposed_included(self):
        manifest = _minimal_manifest_one_model()
        models = _get_semantic_models_with_exposed_columns(manifest)
        assert "fact_orders_current" in models
        names = [c["column_name"] for c in models["fact_orders_current"]]
        assert "tenant_id" in names
        assert "id" not in names


# ---------------------------------------------------------------------------
# SupersetDatasetSync.sync
# ---------------------------------------------------------------------------


class TestSyncManifestNotFound:
    def test_returns_error_result(self):
        svc = _make_sync_service()
        result = svc.sync("/nonexistent/manifest.json")
        assert result.success is False
        assert any(e.get("stage") == "load_manifest" for e in result.errors)
        assert result.blocked is False


class TestSyncBlockedByCompatibility:
    def test_breaking_changes_record_blocked_and_return(self):
        db = MagicMock()
        svc = _make_sync_service(db)
        svc.observability = MagicMock()
        manifest = _minimal_manifest_one_model()
        # Current state has an extra exposed column that manifest doesn't have -> breaking
        current = DatasetSchemaSnapshot(
            datasets={
                "fact_orders_current": DatasetViewSchema(
                    name="fact_orders_current",
                    columns=(
                        ColumnSchema("tenant_id", "VARCHAR", True),
                        ColumnSchema("removed_col", "VARCHAR", True),
                    ),
                ),
            }
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest, f)
            path = f.name
        try:
            result = svc.sync(path, current_state=current)
        finally:
            Path(path).unlink(missing_ok=True)
        assert result.blocked is True
        assert result.success is False
        assert len(result.blocking_reasons) >= 1
        svc.observability.record_sync_blocked.assert_called()


class TestSyncIdempotentUpsert:
    """First call creates; second call with same manifest updates (get_dataset returns existing)."""

    def test_create_then_update_paths(self):
        db = MagicMock()
        svc = _make_sync_service(db)
        manifest = _minimal_manifest_one_model()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest, f)
            path = f.name
        try:
            # First run: get_dataset returns None -> create path
            with patch.object(svc.client, "get_database_id", return_value=1):
                with patch.object(svc.client, "get_dataset", return_value=None):
                    with patch.object(svc.client, "create_dataset"):
                        with patch.object(svc.client, "refresh_dataset_columns"):
                            result = svc.sync(path)
            assert result.success is True
            assert "fact_orders_current" in result.created

            # Second run: get_dataset returns existing -> update path
            with patch.object(svc.client, "get_database_id", return_value=1):
                with patch.object(svc.client, "get_dataset", return_value={"id": 42}):
                    with patch.object(svc.client, "update_dataset"):
                        with patch.object(svc.client, "refresh_dataset_columns"):
                            result2 = svc.sync(path)
            assert result2.success is True
            assert "fact_orders_current" in result2.updated
        finally:
            Path(path).unlink(missing_ok=True)


class TestSyncApiFailureRecordsFailure:
    def test_record_sync_failure_on_api_error(self):
        db = MagicMock()
        svc = _make_sync_service(db)
        svc.observability = MagicMock()
        manifest = _minimal_manifest_one_model()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest, f)
            path = f.name
        try:
            with patch.object(svc.client, "get_database_id", return_value=1):
                with patch.object(svc.client, "get_dataset", side_effect=Exception("API error")):
                    result = svc.sync(path)
            assert result.success is False
            assert len(result.errors) >= 1
            svc.observability.record_sync_failure.assert_called()
        finally:
            Path(path).unlink(missing_ok=True)
