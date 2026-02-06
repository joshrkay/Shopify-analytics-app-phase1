"""
Listens for successful dbt run completions and triggers Superset dataset sync.

Decoupled from dbt runtime: does not make HTTP calls during dbt run. The
on-run-end macro emits JSON metadata to stdout; a CI step or job parses it
and calls on_dbt_run_complete() with the manifest path and run results.

Story 5.2 — Prompt 5.2.4
"""

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.services.schema_compatibility_checker import (
    SchemaCompatibilityChecker,
    build_snapshot_from_manifest,
)
from src.services.superset_dataset_sync import SupersetDatasetSync, SyncResult

logger = logging.getLogger(__name__)


class DbtRunListener:
    """Listens for dbt run completions and triggers Superset sync."""

    def __init__(
        self,
        db: Session,
        superset_url: str,
        superset_username: str,
        superset_password: str,
        database_name: str = "markinsight",
    ):
        self.db = db
        self.checker = SchemaCompatibilityChecker()
        self.sync_service = SupersetDatasetSync(
            db=db,
            superset_url=superset_url,
            superset_username=superset_username,
            superset_password=superset_password,
            database_name=database_name,
        )

    def on_dbt_run_complete(
        self,
        manifest_path: str,
        run_results: dict[str, Any] | None = None,
    ) -> SyncResult:
        """
        Called when dbt run completes successfully.

        1. If run_results has test failures, skip sync and return a failed result.
        2. Build current state from manifest (first run or CI: no prior snapshot).
        3. Run schema compatibility check.
        4. If compatible, run SupersetDatasetSync.sync().
        5. If breaking changes, sync() records blocked status and returns.
        """
        if run_results is not None:
            results_list = run_results.get("results", [])
            failures = [r for r in results_list if r.get("status") == "fail"]
            if failures:
                logger.warning(
                    "dbt_run_listener.skipped_due_to_test_failures",
                    extra={"manifest_path": manifest_path, "failure_count": len(failures)},
                )
                return SyncResult(
                    success=False,
                    errors=[{"stage": "dbt_tests", "error": f"{len(failures)} test(s) failed"}],
                )

        path = Path(manifest_path)
        if not path.exists():
            logger.error("dbt_run_listener.manifest_not_found", extra={"manifest_path": manifest_path})
            return SyncResult(
                success=False,
                errors=[{"stage": "load_manifest", "error": f"Manifest not found: {path}"}],
            )

        with open(path) as f:
            manifest = json.load(f)
        current_state = build_snapshot_from_manifest(manifest)

        compat = self.checker.validate(current_state, manifest)
        if not compat.compatibility_passed:
            logger.warning(
                "dbt_run_listener.sync_blocked",
                extra={
                    "manifest_path": manifest_path,
                    "breaking_changes": [b.message for b in compat.breaking_changes],
                },
            )

        return self.sync_service.sync(manifest_path, current_state=current_state)
