"""
Unit tests for DbtRunListener.

Covers: skip sync when run_results has test failures, handle missing manifest,
trigger sync when compatible (delegates to SupersetDatasetSync.sync).

Story 5.2 — Prompt 5.2.4
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.services.dbt_run_listener import DbtRunListener
from src.services.superset_dataset_sync import SyncResult


def _make_listener(db=None):
    db = db or MagicMock()
    return DbtRunListener(
        db=db,
        superset_url="http://superset.example.com",
        superset_username="u",
        superset_password="p",
        database_name="markinsight",
    )


def _minimal_manifest() -> dict:
    return {
        "nodes": {
            "model.markinsight.fact_orders_current": {
                "name": "fact_orders_current",
                "schema": "semantic",
                "columns": {
                    "tenant_id": {"data_type": "VARCHAR", "meta": {"superset_expose": True}},
                },
            },
        },
    }


class TestOnDbtRunCompleteSkipsOnTestFailures:
    def test_returns_failed_result_when_run_results_has_failures(self):
        listener = _make_listener()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(_minimal_manifest(), f)
            path = f.name
        try:
            run_results = {"results": [{"status": "pass"}, {"status": "fail"}]}
            result = listener.on_dbt_run_complete(path, run_results=run_results)
        finally:
            Path(path).unlink(missing_ok=True)
        assert result.success is False
        assert any("test" in str(e) for e in result.errors)

    def test_does_not_call_sync_service_when_failures(self):
        listener = _make_listener()
        listener.sync_service = MagicMock()
        run_results = {"results": [{"status": "fail"}]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(_minimal_manifest(), f)
            path = f.name
        try:
            listener.on_dbt_run_complete(path, run_results=run_results)
        finally:
            Path(path).unlink(missing_ok=True)
        listener.sync_service.sync.assert_not_called()


class TestOnDbtRunCompleteMissingManifest:
    def test_returns_error_result_when_manifest_missing(self):
        listener = _make_listener()
        result = listener.on_dbt_run_complete("/nonexistent/manifest.json")
        assert result.success is False
        assert any("manifest" in str(e).lower() for e in result.errors)


class TestOnDbtRunCompleteTriggersSyncWhenCompatible:
    def test_calls_sync_service_when_no_failures_and_manifest_exists(self):
        listener = _make_listener()
        listener.sync_service = MagicMock(return_value=SyncResult(success=True))
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(_minimal_manifest(), f)
            path = f.name
        try:
            result = listener.on_dbt_run_complete(path, run_results=None)
        finally:
            Path(path).unlink(missing_ok=True)
        listener.sync_service.sync.assert_called_once()
        call_kw = listener.sync_service.sync.call_args[1]
        assert call_kw.get("current_state") is not None
