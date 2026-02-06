"""
Backfill status service — computes progress and ETA for backfill requests.

Derives all status information from HistoricalBackfillRequest and its child
BackfillJob records. No additional columns required — percent complete, ETA,
and effective status are computed at query time from chunk-level data.

Story 3.4 - Backfill Status API
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from src.models.backfill_job import BackfillJob, BackfillJobStatus
from src.models.historical_backfill import (
    HistoricalBackfillRequest,
    HistoricalBackfillStatus,
)

logger = logging.getLogger(__name__)

# Map internal model statuses → the 5 exposed status values
_PENDING_STATUSES = {
    HistoricalBackfillStatus.PENDING,
    HistoricalBackfillStatus.APPROVED,
}
_FAILED_STATUSES = {
    HistoricalBackfillStatus.FAILED,
    HistoricalBackfillStatus.REJECTED,
}
_COMPLETED_STATUSES = {
    HistoricalBackfillStatus.COMPLETED,
    HistoricalBackfillStatus.CANCELLED,
}


class BackfillStatusService:
    """
    Computes backfill status, progress, and ETA from request + chunk data.

    Not tenant-scoped: super admins can view any tenant's backfills.
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    def get_request_status(self, request_id: str) -> Optional[dict]:
        """
        Compute detailed status for a single backfill request.

        Returns None if request not found.
        """
        request = (
            self.db.query(HistoricalBackfillRequest)
            .filter(HistoricalBackfillRequest.id == request_id)
            .first()
        )
        if not request:
            return None

        jobs = (
            self.db.query(BackfillJob)
            .filter(BackfillJob.backfill_request_id == request_id)
            .order_by(BackfillJob.chunk_index.asc())
            .all()
        )

        return self._build_status(request, jobs)

    def list_requests(
        self,
        tenant_id: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> list[dict]:
        """
        List backfill requests with computed status.

        Args:
            tenant_id: Optional filter by target tenant.
            status_filter: Optional filter by effective status
                (pending, running, paused, failed, completed).
        """
        query = self.db.query(HistoricalBackfillRequest)

        if tenant_id:
            query = query.filter(
                HistoricalBackfillRequest.tenant_id == tenant_id
            )

        # Pre-filter at DB level where exposed status maps cleanly
        # to internal statuses ("running"/"paused" both map to RUNNING,
        # so those still need Python-level refinement).
        _STATUS_DB_FILTER = {
            "pending": [
                HistoricalBackfillStatus.PENDING,
                HistoricalBackfillStatus.APPROVED,
            ],
            "completed": [
                HistoricalBackfillStatus.COMPLETED,
                HistoricalBackfillStatus.CANCELLED,
            ],
            "failed": [
                HistoricalBackfillStatus.FAILED,
                HistoricalBackfillStatus.REJECTED,
            ],
            "running": [HistoricalBackfillStatus.RUNNING],
            "paused": [HistoricalBackfillStatus.RUNNING],
        }
        if status_filter and status_filter in _STATUS_DB_FILTER:
            query = query.filter(
                HistoricalBackfillRequest.status.in_(
                    _STATUS_DB_FILTER[status_filter]
                )
            )

        requests = query.order_by(
            HistoricalBackfillRequest.created_at.desc()
        ).all()

        if not requests:
            return []

        # Batch-load all jobs for these requests in one query
        request_ids = [r.id for r in requests]
        all_jobs = (
            self.db.query(BackfillJob)
            .filter(BackfillJob.backfill_request_id.in_(request_ids))
            .order_by(BackfillJob.chunk_index.asc())
            .all()
        )

        # Group jobs by request
        jobs_by_request: dict[str, list[BackfillJob]] = {}
        for job in all_jobs:
            jobs_by_request.setdefault(job.backfill_request_id, []).append(job)

        results = []
        for req in requests:
            jobs = jobs_by_request.get(req.id, [])
            status_data = self._build_status(req, jobs)
            # "running" vs "paused" both map to RUNNING at DB level,
            # so Python-level check is still needed for those two.
            if status_filter and status_data["status"] != status_filter:
                continue
            results.append(status_data)

        return results

    def _build_status(
        self,
        request: HistoricalBackfillRequest,
        jobs: list[BackfillJob],
    ) -> dict:
        """Build status dict from a request and its chunk jobs."""
        total_chunks = len(jobs)
        completed_chunks = sum(
            1 for j in jobs if j.status == BackfillJobStatus.SUCCESS
        )
        failed_chunks = sum(
            1 for j in jobs
            if j.status == BackfillJobStatus.FAILED and not j.can_retry
        )

        effective_status = self._compute_effective_status(request, jobs)
        current_chunk = self._get_current_chunk(jobs)
        failure_reasons = self._collect_failure_reasons(jobs)
        estimated_remaining = self._estimate_remaining(
            jobs, total_chunks, completed_chunks, failed_chunks,
        )

        percent_complete = (
            (completed_chunks / total_chunks * 100.0) if total_chunks > 0
            else 0.0
        )

        status_val = (
            request.status.value
            if isinstance(request.status, HistoricalBackfillStatus)
            else request.status
        )

        return {
            "id": request.id,
            "tenant_id": request.tenant_id,
            "source_system": request.source_system,
            "start_date": (
                request.start_date.isoformat() if request.start_date else ""
            ),
            "end_date": (
                request.end_date.isoformat() if request.end_date else ""
            ),
            "status": effective_status,
            "percent_complete": round(percent_complete, 1),
            "total_chunks": total_chunks,
            "completed_chunks": completed_chunks,
            "failed_chunks": failed_chunks,
            "current_chunk": current_chunk,
            "failure_reasons": failure_reasons,
            "estimated_seconds_remaining": estimated_remaining,
            "reason": request.reason,
            "requested_by": request.requested_by,
            "started_at": request.started_at,
            "completed_at": request.completed_at,
            "created_at": request.created_at,
        }

    def _compute_effective_status(
        self,
        request: HistoricalBackfillRequest,
        jobs: list[BackfillJob],
    ) -> str:
        """
        Map internal model status to one of the 5 exposed statuses.

        For RUNNING requests, checks child jobs to detect effective "paused".
        """
        req_status = (
            request.status
            if isinstance(request.status, HistoricalBackfillStatus)
            else HistoricalBackfillStatus(request.status)
        )

        if req_status in _PENDING_STATUSES:
            return "pending"
        if req_status in _COMPLETED_STATUSES:
            return "completed"
        if req_status in _FAILED_STATUSES:
            return "failed"

        # RUNNING — check if effectively paused (all non-terminal jobs paused)
        if req_status == HistoricalBackfillStatus.RUNNING and jobs:
            non_terminal = [j for j in jobs if not j.is_terminal]
            if non_terminal and all(
                j.status == BackfillJobStatus.PAUSED for j in non_terminal
            ):
                return "paused"

        return "running"

    def _get_current_chunk(
        self, jobs: list[BackfillJob]
    ) -> Optional[dict]:
        """Return the currently RUNNING chunk, or None."""
        for job in jobs:
            if job.status == BackfillJobStatus.RUNNING:
                return {
                    "chunk_index": job.chunk_index,
                    "chunk_start_date": (
                        job.chunk_start_date.isoformat()
                        if job.chunk_start_date else ""
                    ),
                    "chunk_end_date": (
                        job.chunk_end_date.isoformat()
                        if job.chunk_end_date else ""
                    ),
                    "status": job.status.value,
                    "attempt": job.attempt,
                    "duration_seconds": job.duration_seconds,
                    "rows_affected": job.rows_affected,
                    "error_message": job.error_message,
                }
        return None

    def _collect_failure_reasons(self, jobs: list[BackfillJob]) -> list[str]:
        """Collect error messages from failed chunks."""
        reasons = []
        for job in jobs:
            if job.status == BackfillJobStatus.FAILED and job.error_message:
                reasons.append(
                    f"Chunk {job.chunk_index} "
                    f"({job.chunk_start_date} - {job.chunk_end_date}): "
                    f"{job.error_message}"
                )
        return reasons

    def _estimate_remaining(
        self,
        jobs: list[BackfillJob],
        total_chunks: int,
        completed_chunks: int,
        failed_chunks: int,
    ) -> Optional[float]:
        """
        Estimate seconds remaining based on average completed chunk duration.

        Returns None if no completed chunks to base estimate on,
        or if backfill is not actively running.
        """
        if completed_chunks == 0:
            return None

        completed_durations = [
            j.duration_seconds
            for j in jobs
            if j.status == BackfillJobStatus.SUCCESS and j.duration_seconds
        ]
        if not completed_durations:
            return None

        avg_duration = sum(completed_durations) / len(completed_durations)
        remaining = total_chunks - completed_chunks - failed_chunks
        if remaining <= 0:
            return None

        return round(avg_duration * remaining, 1)
