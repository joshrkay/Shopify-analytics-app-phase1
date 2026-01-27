"""
Retention Cleanup Job.

Background worker that enforces 13-month retention policy on DQ data:
- dq_results: Delete records older than 13 months
- dq_incidents: Delete resolved incidents older than 13 months
- sync_runs: Delete records older than 13 months
- backfill_jobs: Delete completed jobs older than 13 months

Run as a daily cron job:
    python -m src.jobs.retention_cleanup

Configuration:
- DQ_RETENTION_MONTHS: Retention period in months (default: 13)
- DQ_CLEANUP_BATCH_SIZE: Records to delete per batch (default: 1000)
"""

import os
import sys
import logging
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from typing import Dict

from sqlalchemy import delete, and_

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.session import get_db_session_sync
from src.models.dq_models import (
    DQResult, DQIncident, SyncRun, BackfillJob,
    DQIncidentStatus, BackfillJobStatus,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
DQ_RETENTION_MONTHS = int(os.getenv("DQ_RETENTION_MONTHS", "13"))
DQ_CLEANUP_BATCH_SIZE = int(os.getenv("DQ_CLEANUP_BATCH_SIZE", "1000"))


class RetentionCleanup:
    """
    Enforces data retention policies for DQ tables.

    Retention policy: 13 months
    - Keeps recent data for trend analysis
    - Complies with data governance requirements
    """

    def __init__(self, db_session, retention_months: int = DQ_RETENTION_MONTHS):
        """
        Initialize retention cleanup.

        Args:
            db_session: Database session
            retention_months: Number of months to retain data
        """
        self.db = db_session
        self.retention_months = retention_months
        self.cutoff_date = datetime.now(timezone.utc) - relativedelta(months=retention_months)
        self.stats = {
            "dq_results_deleted": 0,
            "dq_incidents_deleted": 0,
            "sync_runs_deleted": 0,
            "backfill_jobs_deleted": 0,
            "errors": 0,
        }

    def _delete_in_batches(self, model_class, condition, timestamp_column, name: str) -> int:
        """
        Delete records in batches to avoid long-running transactions.

        Args:
            model_class: SQLAlchemy model class
            condition: Additional filter condition
            timestamp_column: Column to use for timestamp filtering
            name: Name for logging

        Returns:
            Total number of records deleted
        """
        total_deleted = 0

        while True:
            # Find records to delete (using subquery for batch)
            subquery = self.db.query(model_class.id if hasattr(model_class, 'id') else model_class.run_id).filter(
                timestamp_column < self.cutoff_date,
                condition if condition is not None else True,
            ).limit(DQ_CLEANUP_BATCH_SIZE).subquery()

            # For models with 'id' primary key
            if hasattr(model_class, 'id'):
                result = self.db.execute(
                    delete(model_class).where(model_class.id.in_(subquery))
                )
            else:
                # For SyncRun which uses 'run_id' as primary key
                result = self.db.execute(
                    delete(model_class).where(model_class.run_id.in_(subquery))
                )

            deleted_count = result.rowcount
            self.db.commit()

            total_deleted += deleted_count

            logger.info(
                f"Deleted {deleted_count} {name} records (batch)",
                extra={
                    "table": name,
                    "batch_size": deleted_count,
                    "total_deleted": total_deleted,
                },
            )

            # If we deleted less than batch size, we're done
            if deleted_count < DQ_CLEANUP_BATCH_SIZE:
                break

        return total_deleted

    def cleanup_dq_results(self) -> int:
        """
        Delete DQ results older than retention period.

        Returns:
            Number of records deleted
        """
        logger.info(
            "Cleaning up dq_results",
            extra={
                "cutoff_date": self.cutoff_date.isoformat(),
                "retention_months": self.retention_months,
            },
        )

        try:
            # Delete old results
            deleted = self._delete_in_batches(
                DQResult,
                None,  # No additional condition
                DQResult.executed_at,
                "dq_results",
            )
            self.stats["dq_results_deleted"] = deleted
            return deleted

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(
                "Error cleaning up dq_results",
                extra={"error": str(e)},
                exc_info=True,
            )
            return 0

    def cleanup_dq_incidents(self) -> int:
        """
        Delete resolved DQ incidents older than retention period.

        Only deletes resolved incidents - open incidents are retained.

        Returns:
            Number of records deleted
        """
        logger.info(
            "Cleaning up dq_incidents",
            extra={
                "cutoff_date": self.cutoff_date.isoformat(),
            },
        )

        try:
            # Only delete resolved incidents
            resolved_statuses = [
                DQIncidentStatus.RESOLVED.value,
                DQIncidentStatus.AUTO_RESOLVED.value,
            ]

            deleted = self._delete_in_batches(
                DQIncident,
                DQIncident.status.in_(resolved_statuses),
                DQIncident.opened_at,
                "dq_incidents",
            )
            self.stats["dq_incidents_deleted"] = deleted
            return deleted

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(
                "Error cleaning up dq_incidents",
                extra={"error": str(e)},
                exc_info=True,
            )
            return 0

    def cleanup_sync_runs(self) -> int:
        """
        Delete sync runs older than retention period.

        Returns:
            Number of records deleted
        """
        logger.info(
            "Cleaning up sync_runs",
            extra={
                "cutoff_date": self.cutoff_date.isoformat(),
            },
        )

        try:
            deleted = self._delete_in_batches(
                SyncRun,
                None,
                SyncRun.started_at,
                "sync_runs",
            )
            self.stats["sync_runs_deleted"] = deleted
            return deleted

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(
                "Error cleaning up sync_runs",
                extra={"error": str(e)},
                exc_info=True,
            )
            return 0

    def cleanup_backfill_jobs(self) -> int:
        """
        Delete completed backfill jobs older than retention period.

        Only deletes completed/failed/cancelled jobs - running jobs are retained.

        Returns:
            Number of records deleted
        """
        logger.info(
            "Cleaning up backfill_jobs",
            extra={
                "cutoff_date": self.cutoff_date.isoformat(),
            },
        )

        try:
            # Only delete completed jobs
            completed_statuses = [
                BackfillJobStatus.SUCCESS.value,
                BackfillJobStatus.FAILED.value,
                BackfillJobStatus.CANCELLED.value,
            ]

            deleted = self._delete_in_batches(
                BackfillJob,
                BackfillJob.status.in_(completed_statuses),
                BackfillJob.created_at,
                "backfill_jobs",
            )
            self.stats["backfill_jobs_deleted"] = deleted
            return deleted

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(
                "Error cleaning up backfill_jobs",
                extra={"error": str(e)},
                exc_info=True,
            )
            return 0

    def run(self) -> Dict:
        """
        Run all cleanup operations.

        Returns:
            Statistics dictionary
        """
        start_time = datetime.now(timezone.utc)
        logger.info(
            "Starting retention cleanup",
            extra={
                "retention_months": self.retention_months,
                "cutoff_date": self.cutoff_date.isoformat(),
            },
        )

        # Run cleanup for each table
        self.cleanup_dq_results()
        self.cleanup_dq_incidents()
        self.cleanup_sync_runs()
        self.cleanup_backfill_jobs()

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        self.stats["duration_seconds"] = duration
        self.stats["cutoff_date"] = self.cutoff_date.isoformat()
        self.stats["retention_months"] = self.retention_months

        total_deleted = (
            self.stats["dq_results_deleted"] +
            self.stats["dq_incidents_deleted"] +
            self.stats["sync_runs_deleted"] +
            self.stats["backfill_jobs_deleted"]
        )

        logger.info(
            "Retention cleanup completed",
            extra={
                "total_deleted": total_deleted,
                "duration_seconds": duration,
                **self.stats,
            },
        )

        return self.stats


def main():
    """Main entry point for retention cleanup job."""
    logger.info("Retention Cleanup starting")

    try:
        for session in get_db_session_sync():
            cleanup = RetentionCleanup(session)
            stats = cleanup.run()
            logger.info("Retention Cleanup stats", extra=stats)
    except Exception as e:
        logger.error("Retention Cleanup failed", extra={"error": str(e)}, exc_info=True)
        sys.exit(1)

    logger.info("Retention Cleanup finished")


if __name__ == "__main__":
    main()
