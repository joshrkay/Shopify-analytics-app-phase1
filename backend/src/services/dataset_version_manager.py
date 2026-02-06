"""
Dataset version manager — fail-safe versioning for canonical Superset datasets.

Ensures that:
1. If a sync fails, the previous ACTIVE version is preserved.
2. Breaking schema changes (column removals/renames) block activation.
3. Operators are alerted and can manually roll back.

All operations are idempotent: re-running with the same manifest hash
produces identical state.

Story 5.2.7 — Fail-Safe Dataset Versioning
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.models.dataset_version import DatasetVersion, DatasetVersionStatus
from src.monitoring.dataset_alerts import alert_version_rolled_back
from src.services.audit_logger import emit_dataset_version_rolled_back

logger = logging.getLogger(__name__)


class SchemaCompatibilityError(Exception):
    """Raised when a new version is incompatible with the active version."""

    def __init__(self, dataset_name: str, reason: str):
        self.dataset_name = dataset_name
        self.reason = reason
        super().__init__(f"Incompatible schema for {dataset_name}: {reason}")


class DatasetVersionManager:
    """
    Manages dataset version lifecycle.

    Usage:
        mgr = DatasetVersionManager(db_session)
        version = mgr.create_pending_version("fact_orders_current", "v2", columns)
        mgr.validate_compatibility("fact_orders_current", columns)
        mgr.activate_version(version.id)
    """

    def __init__(self, db: Session):
        self.db = db

    def get_active_version(self, dataset_name: str) -> DatasetVersion | None:
        """Return the currently ACTIVE version for a dataset, or None."""
        return (
            self.db.query(DatasetVersion)
            .filter(
                DatasetVersion.dataset_name == dataset_name,
                DatasetVersion.status == DatasetVersionStatus.ACTIVE.value,
            )
            .first()
        )

    def get_version_by_id(self, version_id: str) -> DatasetVersion | None:
        """Return a version by its primary key."""
        return self.db.query(DatasetVersion).get(version_id)

    def create_pending_version(
        self,
        dataset_name: str,
        version: str,
        columns: list[dict],
        *,
        schema_name: str = "analytics",
        dbt_manifest_hash: str | None = None,
    ) -> DatasetVersion:
        """
        Create a new PENDING version for a dataset.

        If a PENDING version with the same dataset_name + version already
        exists (idempotency), return it instead of creating a duplicate.
        """
        existing = (
            self.db.query(DatasetVersion)
            .filter(
                DatasetVersion.dataset_name == dataset_name,
                DatasetVersion.version == version,
            )
            .first()
        )
        if existing:
            logger.info(
                "dataset_version.already_exists",
                extra={
                    "dataset_name": dataset_name,
                    "version": version,
                    "status": existing.status,
                },
            )
            return existing

        exposed_count = sum(
            1 for col in columns if col.get("superset_expose", False)
        )

        new_version = DatasetVersion(
            dataset_name=dataset_name,
            schema_name=schema_name,
            version=version,
            status=DatasetVersionStatus.PENDING.value,
            column_snapshot=json.dumps(columns),
            column_count=len(columns),
            exposed_column_count=exposed_count,
            is_compatible=True,
            sync_started_at=datetime.now(timezone.utc),
            dbt_manifest_hash=dbt_manifest_hash,
        )
        self.db.add(new_version)
        self.db.flush()

        logger.info(
            "dataset_version.created",
            extra={
                "dataset_name": dataset_name,
                "version": version,
                "column_count": len(columns),
                "exposed_column_count": exposed_count,
            },
        )
        return new_version

    def validate_compatibility(
        self,
        dataset_name: str,
        new_columns: list[dict],
    ) -> tuple[bool, str]:
        """
        Check whether new_columns are compatible with the active version.

        Rules:
        - Additive changes (new columns) are always safe.
        - Removing or renaming an exposed column is a BREAKING change.
        - Type changes on exposed columns are a BREAKING change.

        Returns:
            (is_compatible, reason_if_not)
        """
        active = self.get_active_version(dataset_name)
        if active is None:
            return True, ""

        old_columns = json.loads(active.column_snapshot)
        old_exposed = {
            col["column_name"]
            for col in old_columns
            if col.get("superset_expose", False)
        }
        new_col_names = {col["column_name"] for col in new_columns}

        removed = old_exposed - new_col_names
        if removed:
            reason = f"Exposed columns removed: {sorted(removed)}"
            return False, reason

        old_types = {
            col["column_name"]: col.get("type", "")
            for col in old_columns
            if col.get("superset_expose", False)
        }
        new_types = {
            col["column_name"]: col.get("type", "")
            for col in new_columns
        }
        type_changes = []
        for col_name in old_exposed & new_col_names:
            if old_types.get(col_name) and new_types.get(col_name):
                if old_types[col_name] != new_types[col_name]:
                    type_changes.append(
                        f"{col_name}: {old_types[col_name]} → {new_types[col_name]}"
                    )
        if type_changes:
            reason = f"Exposed column type changes: {type_changes}"
            return False, reason

        return True, ""

    def activate_version(self, version_id: str) -> DatasetVersion:
        """
        Promote a PENDING version to ACTIVE.

        Demotes the current ACTIVE version to SUPERSEDED.
        Raises if the version is not PENDING or not compatible.
        """
        version = self.get_version_by_id(version_id)
        if version is None:
            raise ValueError(f"Version {version_id} not found")

        if version.status != DatasetVersionStatus.PENDING.value:
            raise ValueError(
                f"Cannot activate version in status '{version.status}' "
                f"(expected '{DatasetVersionStatus.PENDING.value}')"
            )

        if not version.is_compatible:
            raise SchemaCompatibilityError(
                version.dataset_name,
                version.incompatibility_reason or "Unknown incompatibility",
            )

        now = datetime.now(timezone.utc)

        current_active = self.get_active_version(version.dataset_name)
        if current_active:
            current_active.status = DatasetVersionStatus.SUPERSEDED.value
            current_active.deactivated_at = now
            logger.info(
                "dataset_version.superseded",
                extra={
                    "dataset_name": current_active.dataset_name,
                    "version": current_active.version,
                },
            )

        version.status = DatasetVersionStatus.ACTIVE.value
        version.activated_at = now
        version.sync_completed_at = now
        self.db.flush()

        logger.info(
            "dataset_version.activated",
            extra={
                "dataset_name": version.dataset_name,
                "version": version.version,
            },
        )
        return version

    def mark_failed(
        self,
        version_id: str,
        error: str,
    ) -> DatasetVersion:
        """
        Mark a PENDING version as FAILED.

        The currently ACTIVE version remains untouched (fail-safe).
        """
        version = self.get_version_by_id(version_id)
        if version is None:
            raise ValueError(f"Version {version_id} not found")

        version.status = DatasetVersionStatus.FAILED.value
        version.sync_error = error
        version.sync_completed_at = datetime.now(timezone.utc)
        version.is_compatible = False
        version.incompatibility_reason = error
        self.db.flush()

        logger.warning(
            "dataset_version.failed",
            extra={
                "dataset_name": version.dataset_name,
                "version": version.version,
                "error": error,
            },
        )
        return version

    def rollback(self, dataset_name: str) -> DatasetVersion | None:
        """
        Roll back to the most recent SUPERSEDED version.

        Demotes the current ACTIVE version to ROLLED_BACK and
        re-activates the latest SUPERSEDED version.

        Returns the re-activated version, or None if no rollback target.
        """
        now = datetime.now(timezone.utc)

        current_active = self.get_active_version(dataset_name)
        if current_active:
            current_active.status = DatasetVersionStatus.ROLLED_BACK.value
            current_active.deactivated_at = now

        previous = (
            self.db.query(DatasetVersion)
            .filter(
                DatasetVersion.dataset_name == dataset_name,
                DatasetVersion.status == DatasetVersionStatus.SUPERSEDED.value,
            )
            .order_by(DatasetVersion.activated_at.desc())
            .first()
        )

        if previous is None:
            logger.warning(
                "dataset_version.rollback_no_target",
                extra={"dataset_name": dataset_name},
            )
            self.db.flush()
            return None

        previous.status = DatasetVersionStatus.ACTIVE.value
        previous.activated_at = now
        previous.deactivated_at = None
        self.db.flush()

        rolled_back_version = current_active.version if current_active else "unknown"
        emit_dataset_version_rolled_back(
            self.db,
            dataset_name,
            rolled_back_version,
            previous.version,
        )
        alert_version_rolled_back(dataset_name, rolled_back_version, previous.version)

        logger.info(
            "dataset_version.rolled_back",
            extra={
                "dataset_name": dataset_name,
                "restored_version": previous.version,
            },
        )
        return previous
