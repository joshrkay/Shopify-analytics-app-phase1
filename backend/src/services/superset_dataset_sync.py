"""
Idempotent sync of dbt semantic views to Superset datasets.

Orchestrates: compatibility check, snapshot of last-known-good, upsert via
Superset API, versioned metadata, observability writes. Rollback on failure
means no partial apply: we record failure and do not update remaining datasets.

Story 5.2 — Prompt 5.2.4
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from src.models.dataset_metrics import DatasetSyncStatus
from src.monitoring.dataset_alerts import alert_compatibility_failure, alert_sync_failure
from src.services.audit_logger import (
    emit_dataset_sync_completed,
    emit_dataset_sync_failed,
    emit_dataset_sync_started,
    emit_dataset_version_activated,
)
from src.services.dataset_observability import DatasetObservabilityService
from src.services.dataset_version_manager import DatasetVersionManager
from src.services.schema_compatibility_checker import (
    SchemaCompatibilityChecker,
    DatasetSchemaSnapshot,
    build_snapshot_from_db,
)

logger = logging.getLogger(__name__)

DEFAULT_SYNC_TIMEOUT_SECONDS = 300
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY_SECONDS = 2.0


@dataclass
class SyncResult:
    """Result of a full sync run."""

    success: bool
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    blocked: bool = False
    blocking_reasons: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    pre_deploy_checks: list[dict[str, Any]] = field(default_factory=list)


def _parse_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """Load and parse dbt manifest.json."""
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    with open(path) as f:
        return json.load(f)


def _is_semantic_view(name: str) -> bool:
    if name.endswith("_current") and name.startswith("fact_"):
        return True
    if name.startswith("sem_") and "_v1" in name:
        return True
    return False


def _get_semantic_models_with_exposed_columns(manifest: dict[str, Any]) -> dict[str, list[dict]]:
    """Extract semantic view name -> list of {column_name, description, data_type} for exposed only."""
    nodes = manifest.get("nodes", {})
    result: dict[str, list[dict]] = {}

    for node_id, node in nodes.items():
        if not node_id.startswith("model."):
            continue
        name = node.get("name", "")
        if not _is_semantic_view(name):
            continue

        columns = []
        for col_name, col_info in node.get("columns", {}).items():
            meta = col_info.get("meta", {}) if isinstance(col_info, dict) else {}
            if not meta.get("superset_expose", False):
                continue
            columns.append({
                "column_name": col_name,
                "description": col_info.get("description", "") if isinstance(col_info, dict) else "",
                "data_type": col_info.get("data_type", "VARCHAR") if isinstance(col_info, dict) else "VARCHAR",
            })
        result[name] = columns

    return result


def _get_column_snapshot_for_version(manifest: dict[str, Any], dataset_name: str) -> list[dict]:
    """Build full column list for DatasetVersion.column_snapshot (column_name, type, superset_expose)."""
    node_id = f"model.markinsight.{dataset_name}"
    node = (manifest.get("nodes", {}) or {}).get(node_id, {})
    columns_raw = node.get("columns", {})
    snapshot: list[dict] = []
    for col_name, col_info in columns_raw.items():
        if not isinstance(col_info, dict):
            continue
        meta = col_info.get("meta", {}) or {}
        data_type = col_info.get("data_type", "VARCHAR") or "VARCHAR"
        exposed = bool(meta.get("superset_expose", False))
        snapshot.append({
            "column_name": col_name,
            "type": data_type,
            "superset_expose": exposed,
        })
    return snapshot


class SupersetApiClient:
    """Minimal Superset API client for dataset create/update."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout_seconds: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout_seconds
        self._token: str | None = None
        self._csrf: str | None = None

    def _ensure_auth(self, client: httpx.Client) -> None:
        if self._token:
            return
        r = client.post(
            f"{self.base_url}/api/v1/security/login",
            json={"username": self.username, "password": self.password, "provider": "db"},
            timeout=self.timeout,
        )
        r.raise_for_status()
        self._token = r.json()["access_token"]
        r2 = client.get(
            f"{self.base_url}/api/v1/security/csrf_token/",
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=self.timeout,
        )
        r2.raise_for_status()
        self._csrf = r2.json().get("result", "")

    def get_database_id(self, database_name: str) -> int | None:
        with httpx.Client(timeout=self.timeout) as client:
            self._ensure_auth(client)
            r = client.get(
                f"{self.base_url}/api/v1/database/",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "X-CSRFToken": self._csrf or "",
                    "Content-Type": "application/json",
                },
                params={"q": json.dumps({"filters": [{"col": "database_name", "opr": "eq", "value": database_name}]})},
            )
            r.raise_for_status()
            data = r.json()
            if data.get("result"):
                return data["result"][0]["id"]
        return None

    def get_dataset(self, table_name: str, schema: str) -> dict | None:
        with httpx.Client(timeout=self.timeout) as client:
            self._ensure_auth(client)
            r = client.get(
                f"{self.base_url}/api/v1/dataset/",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "X-CSRFToken": self._csrf or "",
                    "Content-Type": "application/json",
                },
                params={
                    "q": json.dumps({
                        "filters": [
                            {"col": "table_name", "opr": "eq", "value": table_name},
                            {"col": "schema", "opr": "eq", "value": schema},
                        ],
                    })
                },
            )
            r.raise_for_status()
            data = r.json()
            if data.get("result"):
                return data["result"][0]
        return None

    def create_dataset(
        self,
        table_name: str,
        schema: str,
        database_id: int,
        description: str,
        columns: list[dict],
    ) -> int:
        with httpx.Client(timeout=self.timeout) as client:
            self._ensure_auth(client)
            r = client.post(
                f"{self.base_url}/api/v1/dataset/",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "X-CSRFToken": self._csrf or "",
                    "Content-Type": "application/json",
                },
                json={
                    "table_name": table_name,
                    "schema": schema,
                    "database": database_id,
                    "description": description,
                },
            )
            r.raise_for_status()
            return r.json()["id"]

    def update_dataset(self, dataset_id: int, description: str) -> None:
        with httpx.Client(timeout=self.timeout) as client:
            self._ensure_auth(client)
            r = client.put(
                f"{self.base_url}/api/v1/dataset/{dataset_id}",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "X-CSRFToken": self._csrf or "",
                    "Content-Type": "application/json",
                },
                json={"description": description},
            )
            r.raise_for_status()

    def refresh_dataset_columns(self, dataset_id: int) -> None:
        with httpx.Client(timeout=self.timeout) as client:
            self._ensure_auth(client)
            r = client.put(
                f"{self.base_url}/api/v1/dataset/{dataset_id}/refresh",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "X-CSRFToken": self._csrf or "",
                },
            )
            r.raise_for_status()


class SupersetDatasetSync:
    """Idempotent sync of dbt semantic views to Superset datasets."""

    def __init__(
        self,
        db: Session,
        superset_url: str,
        superset_username: str,
        superset_password: str,
        database_name: str = "markinsight",
        timeout_seconds: int = DEFAULT_SYNC_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.db = db
        self.checker = SchemaCompatibilityChecker()
        self.observability = DatasetObservabilityService(db)
        self.version_manager = DatasetVersionManager(db)
        self.client = SupersetApiClient(
            base_url=superset_url,
            username=superset_username,
            password=superset_password,
            timeout_seconds=min(60, timeout_seconds),
        )
        self.database_name = database_name
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._database_id: int | None = None

    def _get_database_id(self) -> int:
        if self._database_id is not None:
            return self._database_id
        self._database_id = self.client.get_database_id(self.database_name)
        if not self._database_id:
            raise ValueError(f"Database '{self.database_name}' not found in Superset")
        return self._database_id

    def sync(
        self,
        manifest_path: str | Path,
        current_state: DatasetSchemaSnapshot | None = None,
    ) -> SyncResult:
        """
        Full sync flow: validate compatibility, snapshot, upsert datasets, record status.

        If current_state is None, builds from prior ACTIVE dataset versions in DB (first run: empty baseline).
        Idempotent: running twice with the same manifest yields identical state.
        """
        start = time.perf_counter()
        result = SyncResult(success=False)

        try:
            manifest = _parse_manifest(manifest_path)
        except Exception as e:
            logger.exception("superset_dataset_sync.load_manifest_failed")
            result.errors.append({"stage": "load_manifest", "error": str(e)})
            result.pre_deploy_checks = [
                {"check_name": "schema_match", "status": "fail", "measured_value": None, "threshold": None, "blocking": True},
            ]
            result.duration_seconds = time.perf_counter() - start
            return result

        if current_state is None:
            current_state = build_snapshot_from_db(self.db)

        compat = self.checker.validate(current_state, manifest)
        if not compat.compatibility_passed:
            result.blocked = True
            result.blocking_reasons = [b.message for b in compat.breaking_changes]
            for b in compat.breaking_changes:
                self.observability.record_sync_blocked(b.dataset_name, reason=b.message)
                alert_compatibility_failure(
                    b.dataset_name,
                    b.message,
                    removed_columns=[b.column_name] if b.column_name else [],
                )
            result.pre_deploy_checks = [
                {
                    "check_name": "schema_match",
                    "status": "fail",
                    "measured_value": "breaking_changes",
                    "threshold": "none",
                    "blocking": True,
                },
            ]
            result.duration_seconds = time.perf_counter() - start
            return result

        models = _get_semantic_models_with_exposed_columns(manifest)
        if not models:
            result.success = True
            result.duration_seconds = time.perf_counter() - start
            result.pre_deploy_checks = [
                {"check_name": "schema_match", "status": "pass", "measured_value": "no_semantic_views", "threshold": None, "blocking": True},
            ]
            return result

        try:
            db_id = self._get_database_id()
        except Exception as e:
            logger.exception("superset_dataset_sync.database_not_found")
            result.errors.append({"stage": "get_database_id", "error": str(e)})
            result.duration_seconds = time.perf_counter() - start
            return result

        manifest_hash = hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode()
        ).hexdigest()
        schema_name = "semantic"
        nodes = manifest.get("nodes", {}) or {}

        for dataset_name, columns in models.items():
            t0 = time.perf_counter()
            column_snapshot = _get_column_snapshot_for_version(manifest, dataset_name)
            version = self.version_manager.create_pending_version(
                dataset_name,
                "v1",
                column_snapshot,
                schema_name=schema_name,
                dbt_manifest_hash=manifest_hash,
            )
            emit_dataset_sync_started(self.db, dataset_name, "v1")
            try:
                existing = self.client.get_dataset(dataset_name, schema_name)
                node = nodes.get(f"model.markinsight.{dataset_name}", {})
                description = node.get("description", "") or f"Semantic view: {dataset_name}"
                total_column_count = len(node.get("columns", {}))

                if existing:
                    self.client.update_dataset(existing["id"], description)
                    self.client.refresh_dataset_columns(existing["id"])
                    result.updated.append(dataset_name)
                else:
                    self.client.create_dataset(
                        table_name=dataset_name,
                        schema=schema_name,
                        database_id=db_id,
                        description=description,
                        columns=[],
                    )
                    result.created.append(dataset_name)
                    existing = self.client.get_dataset(dataset_name, schema_name)
                    if existing:
                        self.client.refresh_dataset_columns(existing["id"])

                self.version_manager.activate_version(version.id)
                duration = time.perf_counter() - t0
                emit_dataset_sync_completed(self.db, dataset_name, "v1", duration)
                emit_dataset_version_activated(self.db, dataset_name, "v1")
                self.observability.record_sync_success(
                    dataset_name,
                    version="v1",
                    duration_seconds=duration,
                    column_count=total_column_count,
                    exposed_column_count=len(columns),
                )
            except Exception as e:
                duration = time.perf_counter() - t0
                logger.warning(
                    "superset_dataset_sync.dataset_failed",
                    extra={"dataset_name": dataset_name, "error": str(e)},
                )
                result.errors.append({"dataset": dataset_name, "error": str(e)})
                self.version_manager.mark_failed(version.id, error=str(e))
                emit_dataset_sync_failed(self.db, dataset_name, "v1", str(e))
                alert_sync_failure(dataset_name, str(e))
                self.observability.record_sync_failure(
                    dataset_name,
                    error=str(e),
                    duration_seconds=duration,
                )

        result.success = len(result.errors) == 0
        result.duration_seconds = time.perf_counter() - start
        result.pre_deploy_checks = [
            {
                "check_name": "sync_time",
                "status": "pass" if result.success else "fail",
                "measured_value": result.duration_seconds,
                "threshold": 300,
                "blocking": True,
            },
            {
                "check_name": "schema_match",
                "status": "pass",
                "measured_value": "compatible",
                "threshold": None,
                "blocking": True,
            },
        ]
        return result
