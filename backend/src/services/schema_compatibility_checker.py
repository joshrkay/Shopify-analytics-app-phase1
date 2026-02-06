"""
Schema compatibility checker for Superset dataset updates.

Validates that a new dbt manifest does not introduce breaking changes relative
to the current Superset dataset state. Used before applying sync to block
updates that would break dashboards.

Checks:
- No exposed column removed
- No exposed column type changed
- No semantic view removed
- Additive changes (new columns, new views) are allowed

Story 5.2 — Prompt 5.2.3
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.models.dataset_version import DatasetVersion, DatasetVersionStatus

logger = logging.getLogger(__name__)

# Semantic view name patterns: _current aliases and sem_*_v1 versioned views
SEMANTIC_VIEW_PREFIXES = ("fact_", "sem_")
SEMANTIC_VIEW_SUFFIXES = ("_current", "_v1")


@dataclass(frozen=True)
class ColumnSchema:
    """Column metadata for compatibility checks."""

    name: str
    data_type: str
    exposed: bool


@dataclass(frozen=True)
class DatasetViewSchema:
    """Schema of a single dataset/view."""

    name: str
    columns: tuple[ColumnSchema, ...]

    @property
    def exposed_columns(self) -> tuple[ColumnSchema, ...]:
        return tuple(c for c in self.columns if c.exposed)


@dataclass(frozen=True)
class DatasetSchemaSnapshot:
    """Current state of datasets (from Superset or previous manifest)."""

    datasets: dict[str, DatasetViewSchema]

    def get(self, name: str) -> DatasetViewSchema | None:
        return self.datasets.get(name)


@dataclass(frozen=True)
class BreakingChange:
    """A single breaking change detected."""

    dataset_name: str
    change_type: str  # "column_removed" | "column_type_changed" | "view_removed"
    column_name: str | None
    old_value: str | None
    new_value: str | None
    message: str


@dataclass(frozen=True)
class CompatibilityResult:
    """Result of schema compatibility validation."""

    compatibility_passed: bool
    breaking_changes: tuple[BreakingChange, ...]
    additive_changes: tuple[str, ...]
    checked_at: datetime

    @property
    def breaking_changes_list(self) -> list[BreakingChange]:
        return list(self.breaking_changes)


def _is_semantic_view(model_name: str) -> bool:
    """True if the model is a semantic view (_current alias or sem_*_v1)."""
    if model_name.endswith("_current"):
        return model_name.startswith("fact_")
    if model_name.startswith("sem_") and "_v1" in model_name:
        return True
    return False


def _parse_manifest_models(manifest: dict[str, Any]) -> dict[str, DatasetViewSchema]:
    """Extract semantic view schemas from dbt manifest."""
    nodes = manifest.get("nodes", {})
    result: dict[str, DatasetViewSchema] = {}

    for node_id, node in nodes.items():
        if not node_id.startswith("model."):
            continue
        name = node.get("name", "")
        if not _is_semantic_view(name):
            continue

        columns_raw = node.get("columns", {})
        columns: list[ColumnSchema] = []
        for col_name, col_info in columns_raw.items():
            meta = col_info.get("meta", {}) if isinstance(col_info, dict) else {}
            exposed = meta.get("superset_expose", False) if meta else False
            data_type = (
                col_info.get("data_type", "VARCHAR")
                if isinstance(col_info, dict)
                else "VARCHAR"
            )
            columns.append(
                ColumnSchema(name=col_name, data_type=str(data_type), exposed=exposed)
            )
        result[name] = DatasetViewSchema(name=name, columns=tuple(columns))

    return result


def _normalize_type(data_type: str) -> str:
    """Normalize type string for comparison (e.g. VARCHAR vs varchar)."""
    if not data_type:
        return "VARCHAR"
    return data_type.upper().strip()


class SchemaCompatibilityChecker:
    """Validates schema compatibility before updating Superset datasets."""

    def validate(
        self,
        current_state: DatasetSchemaSnapshot,
        new_manifest: dict[str, Any],
    ) -> CompatibilityResult:
        """
        Compare current dataset state to new manifest.

        Returns CompatibilityResult with compatibility_passed=False if any
        breaking change is detected (exposed column removed, type changed,
        or semantic view removed).
        """
        breaking: list[BreakingChange] = []
        additive: list[str] = []

        new_views = _parse_manifest_models(new_manifest)

        # 1. No semantic view removed
        for name in current_state.datasets:
            if not _is_semantic_view(name):
                continue
            if name not in new_views:
                breaking.append(
                    BreakingChange(
                        dataset_name=name,
                        change_type="view_removed",
                        column_name=None,
                        old_value=name,
                        new_value=None,
                        message=f"Semantic view '{name}' was removed from manifest",
                    )
                )

        # 2. For each view in new manifest, check columns
        for view_name, new_schema in new_views.items():
            old_schema = current_state.get(view_name)
            if old_schema is None:
                additive.append(f"New view: {view_name}")
                continue

            old_exposed = {c.name: c for c in old_schema.exposed_columns}
            new_exposed = {c.name: c for c in new_schema.exposed_columns}

            # 2a. No exposed column removed
            for col_name in old_exposed:
                if col_name not in new_exposed:
                    breaking.append(
                        BreakingChange(
                            dataset_name=view_name,
                            change_type="column_removed",
                            column_name=col_name,
                            old_value=col_name,
                            new_value=None,
                            message=f"Exposed column '{col_name}' was removed from '{view_name}'",
                        )
                    )

            # 2b. No exposed column type changed
            for col_name, new_col in new_exposed.items():
                old_col = old_exposed.get(col_name)
                if old_col is None:
                    additive.append(f"{view_name}.{col_name} (new column)")
                    continue
                if _normalize_type(old_col.data_type) != _normalize_type(new_col.data_type):
                    breaking.append(
                        BreakingChange(
                            dataset_name=view_name,
                            change_type="column_type_changed",
                            column_name=col_name,
                            old_value=old_col.data_type,
                            new_value=new_col.data_type,
                            message=(
                                f"Column '{col_name}' type changed from "
                                f"'{old_col.data_type}' to '{new_col.data_type}' in '{view_name}'"
                            ),
                        )
                    )

        return CompatibilityResult(
            compatibility_passed=len(breaking) == 0,
            breaking_changes=tuple(breaking),
            additive_changes=tuple(additive),
            checked_at=datetime.now(timezone.utc),
        )

    def validate_from_manifest_path(
        self,
        current_state: DatasetSchemaSnapshot,
        manifest_path: str | Path,
    ) -> CompatibilityResult:
        """Load manifest from file and run validation."""
        path = Path(manifest_path)
        if not path.exists():
            raise FileNotFoundError(f"Manifest not found: {path}")
        with open(path) as f:
            manifest = json.load(f)
        return self.validate(current_state, manifest)


def build_snapshot_from_manifest(manifest: dict[str, Any]) -> DatasetSchemaSnapshot:
    """Build a DatasetSchemaSnapshot from a dbt manifest (e.g. for tests or CI)."""
    datasets = _parse_manifest_models(manifest)
    return DatasetSchemaSnapshot(datasets=datasets)


def build_snapshot_from_db(db: Session) -> DatasetSchemaSnapshot:
    """
    Build a DatasetSchemaSnapshot from the current ACTIVE dataset versions in the DB.

    Used as the baseline for compatibility checks so we validate the new manifest
    against the previously deployed state, not against itself. When no active
    versions exist (first deploy), returns an empty snapshot so all views are
    treated as additive and the check passes.
    """
    active_versions = (
        db.query(DatasetVersion)
        .filter(DatasetVersion.status == DatasetVersionStatus.ACTIVE.value)
        .all()
    )
    datasets: dict[str, DatasetViewSchema] = {}
    for row in active_versions:
        try:
            raw = json.loads(row.column_snapshot)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(
                "schema_compatibility.invalid_column_snapshot",
                extra={"dataset_name": row.dataset_name, "error": str(e)},
            )
            continue
        if not isinstance(raw, list):
            continue
        columns: list[ColumnSchema] = []
        for col in raw:
            if not isinstance(col, dict):
                continue
            name = col.get("column_name") or col.get("name") or ""
            if not name:
                continue
            data_type = str(col.get("type") or col.get("data_type") or "VARCHAR").strip() or "VARCHAR"
            exposed = bool(col.get("superset_expose", False))
            columns.append(ColumnSchema(name=name, data_type=data_type, exposed=exposed))
        if columns:
            datasets[row.dataset_name] = DatasetViewSchema(
                name=row.dataset_name, columns=tuple(columns)
            )
    return DatasetSchemaSnapshot(datasets=datasets)
