"""
Dataset observability service — tracks health metrics for canonical datasets.

Collects and persists (Story 5.2.8 metrics):
- last_sync_time (last_sync_at), sync_status
- schema_version
- row_count (approximate, from pg_class)
- cache_hit_rate (from application-level tracking)
- Query performance (from pg_stat_statements if available)

All writes go through DatasetMetrics; this service never writes tenant data.

Story 5.2.8 — Dataset Observability & Metrics
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import text

from src.models.dataset_metrics import DatasetMetrics, DatasetSyncStatus

logger = logging.getLogger(__name__)


class DatasetObservabilityService:
    """
    Collects and records dataset-level health metrics.

    Usage:
        svc = DatasetObservabilityService(db_session)
        svc.record_sync_success("fact_orders_current", version="v1", duration=2.3)
        svc.refresh_query_metrics("fact_orders_current")
        health = svc.get_dataset_health("fact_orders_current")
    """

    def __init__(self, db: Session):
        self.db = db

    def _get_or_create(self, dataset_name: str) -> DatasetMetrics:
        """Get existing metrics row or create a new one."""
        metrics = (
            self.db.query(DatasetMetrics)
            .filter(DatasetMetrics.dataset_name == dataset_name)
            .first()
        )
        if metrics is None:
            metrics = DatasetMetrics(
                dataset_name=dataset_name,
                sync_status=DatasetSyncStatus.PENDING.value,
            )
            self.db.add(metrics)
            self.db.flush()
        return metrics

    def record_sync_success(
        self,
        dataset_name: str,
        *,
        version: str,
        duration_seconds: float,
        column_count: int,
        exposed_column_count: int,
    ) -> DatasetMetrics:
        """Record a successful sync attempt."""
        now = datetime.now(timezone.utc)
        metrics = self._get_or_create(dataset_name)

        metrics.last_sync_at = now
        metrics.last_sync_attempted_at = now
        metrics.sync_status = DatasetSyncStatus.OK.value
        metrics.sync_error = None
        metrics.sync_duration_seconds = duration_seconds
        metrics.schema_version = version
        metrics.column_count = column_count
        metrics.exposed_column_count = exposed_column_count

        self.db.flush()
        logger.info(
            "dataset_observability.sync_success",
            extra={
                "dataset_name": dataset_name,
                "version": version,
                "duration_seconds": duration_seconds,
            },
        )
        return metrics

    def record_sync_failure(
        self,
        dataset_name: str,
        *,
        error: str,
        duration_seconds: float | None = None,
    ) -> DatasetMetrics:
        """Record a failed sync attempt (keeps last_sync_at unchanged)."""
        now = datetime.now(timezone.utc)
        metrics = self._get_or_create(dataset_name)

        metrics.last_sync_attempted_at = now
        metrics.sync_status = DatasetSyncStatus.FAILED.value
        metrics.sync_error = error
        if duration_seconds is not None:
            metrics.sync_duration_seconds = duration_seconds

        self.db.flush()
        logger.warning(
            "dataset_observability.sync_failure",
            extra={"dataset_name": dataset_name, "error": error},
        )
        return metrics

    def record_sync_blocked(
        self,
        dataset_name: str,
        *,
        reason: str,
    ) -> DatasetMetrics:
        """Record a blocked sync (incompatible schema)."""
        now = datetime.now(timezone.utc)
        metrics = self._get_or_create(dataset_name)

        metrics.last_sync_attempted_at = now
        metrics.sync_status = DatasetSyncStatus.BLOCKED.value
        metrics.sync_error = reason

        self.db.flush()
        logger.warning(
            "dataset_observability.sync_blocked",
            extra={"dataset_name": dataset_name, "reason": reason},
        )
        return metrics

    def refresh_row_count(self, dataset_name: str) -> int | None:
        """
        Update approximate row count from pg_class (fast, no table scan).

        Returns the row count or None if the table doesn't exist.
        """
        try:
            result = self.db.execute(
                text(
                    "SELECT reltuples::BIGINT "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'analytics' AND c.relname = :table_name"
                ),
                {"table_name": dataset_name},
            )
            row = result.fetchone()
            if row is None:
                return None

            count = int(row[0])
            metrics = self._get_or_create(dataset_name)
            metrics.row_count = count
            metrics.row_count_evaluated_at = datetime.now(timezone.utc)
            self.db.flush()
            return count
        except Exception:
            logger.warning(
                "dataset_observability.row_count_failed",
                extra={"dataset_name": dataset_name},
                exc_info=True,
            )
            return None

    def refresh_query_metrics(self, dataset_name: str) -> None:
        """
        Update query performance metrics from pg_stat_statements.

        Requires pg_stat_statements extension. Silently skips if unavailable.
        """
        try:
            result = self.db.execute(
                text(
                    "SELECT "
                    "  COUNT(*) AS query_count, "
                    "  AVG(mean_exec_time) AS avg_latency_ms, "
                    "  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY mean_exec_time) "
                    "    AS p95_latency_ms "
                    "FROM pg_stat_statements "
                    "WHERE query ILIKE :pattern"
                ),
                {"pattern": f"%{dataset_name}%"},
            )
            row = result.fetchone()
            if row is None:
                return

            metrics = self._get_or_create(dataset_name)
            metrics.query_count_24h = int(row[0])
            metrics.avg_query_latency_ms = float(row[1]) if row[1] else None
            metrics.p95_query_latency_ms = float(row[2]) if row[2] else None
            self.db.flush()
        except Exception:
            logger.debug(
                "dataset_observability.query_metrics_unavailable",
                extra={"dataset_name": dataset_name},
            )

    def update_cache_metrics(
        self,
        dataset_name: str,
        *,
        hit_rate: float,
        entries: int,
    ) -> None:
        """Update cache performance metrics (called by Superset integration)."""
        metrics = self._get_or_create(dataset_name)
        metrics.cache_hit_rate = hit_rate
        metrics.cache_entries = entries
        self.db.flush()

    def get_dataset_health(self, dataset_name: str) -> dict:
        """
        Return a summary dict of dataset health for the API layer.

        Returns a dict with all metric fields, safe for JSON serialization.
        """
        metrics = (
            self.db.query(DatasetMetrics)
            .filter(DatasetMetrics.dataset_name == dataset_name)
            .first()
        )
        if metrics is None:
            return {
                "dataset_name": dataset_name,
                "sync_status": "unknown",
                "last_sync_at": None,
            }

        return {
            "dataset_name": metrics.dataset_name,
            "sync_status": metrics.sync_status,
            "sync_error": metrics.sync_error,
            "last_sync_at": (
                metrics.last_sync_at.isoformat() if metrics.last_sync_at else None
            ),
            "last_sync_attempted_at": (
                metrics.last_sync_attempted_at.isoformat()
                if metrics.last_sync_attempted_at
                else None
            ),
            "sync_duration_seconds": metrics.sync_duration_seconds,
            "schema_version": metrics.schema_version,
            "column_count": metrics.column_count,
            "exposed_column_count": metrics.exposed_column_count,
            "row_count": metrics.row_count,
            "query_count_24h": metrics.query_count_24h,
            "avg_query_latency_ms": metrics.avg_query_latency_ms,
            "p95_query_latency_ms": metrics.p95_query_latency_ms,
            "cache_hit_rate": metrics.cache_hit_rate,
            "cache_entries": metrics.cache_entries,
        }

    def get_all_dataset_health(self) -> list[dict]:
        """Return health summaries for all tracked datasets."""
        all_metrics = self.db.query(DatasetMetrics).all()
        return [
            self.get_dataset_health(m.dataset_name) for m in all_metrics
        ]

    def get_unhealthy_datasets(self) -> list[dict]:
        """Return only datasets that are not in OK status."""
        unhealthy = (
            self.db.query(DatasetMetrics)
            .filter(DatasetMetrics.sync_status != DatasetSyncStatus.OK.value)
            .all()
        )
        return [self.get_dataset_health(m.dataset_name) for m in unhealthy]
