"""
Backfill executor — orchestrates chunked backfill execution.

Splits approved HistoricalBackfillRequests into 7-day BackfillJobs,
executes them via BackfillService, handles retry with exponential
backoff, and supports pause/resume/cancel.

CONSTRAINTS:
- One active backfill job per tenant (rate limit)
- Progress persisted after each chunk (survives restarts)
- Exponential backoff on failure: 60s × 2^attempt + jitter

Story 3.4 - Backfill Execution
"""

import logging
import random
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.models.backfill_job import (
    BackfillJob,
    BackfillJobStatus,
)
from src.models.historical_backfill import (
    HistoricalBackfillRequest,
    HistoricalBackfillStatus,
)
from src.services.backfill_planner import BackfillPlanner

logger = logging.getLogger(__name__)

# Chunk configuration
CHUNK_SIZE_DAYS = 7

# Retry configuration (exponential backoff)
BASE_RETRY_DELAY_SECONDS = 60.0
MAX_RETRY_DELAY_SECONDS = 3600.0
JITTER_FACTOR = 0.25

# Stale job recovery — jobs RUNNING longer than this are assumed crashed
STALE_JOB_MINUTES = 30


def calculate_backoff(attempt: int) -> float:
    """Exponential backoff with jitter: base * 2^attempt ± jitter, capped."""
    delay = BASE_RETRY_DELAY_SECONDS * (2 ** attempt)
    jitter_range = delay * JITTER_FACTOR
    delay += random.uniform(-jitter_range, jitter_range)
    return max(min(delay, MAX_RETRY_DELAY_SECONDS), 1.0)


def compute_chunks(start_date: date, end_date: date) -> list[tuple[date, date]]:
    """Split a date range into CHUNK_SIZE_DAYS-day slices."""
    chunks: list[tuple[date, date]] = []
    current = start_date
    while current <= end_date:
        chunk_end = min(current + timedelta(days=CHUNK_SIZE_DAYS - 1), end_date)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


class BackfillExecutor:
    """
    Orchestrates backfill execution: chunking, job management,
    execution delegation, retry, and parent status updates.

    Used by the backfill worker to process approved requests.
    """

    def __init__(self, db_session: Session):
        self.db = db_session
        self._planner = BackfillPlanner()

    def _get_request(
        self, request_id: str
    ) -> Optional[HistoricalBackfillRequest]:
        """Fetch a backfill request by ID."""
        return (
            self.db.query(HistoricalBackfillRequest)
            .filter(HistoricalBackfillRequest.id == request_id)
            .first()
        )

    # ------------------------------------------------------------------
    # Job creation
    # ------------------------------------------------------------------

    def create_jobs_for_request(
        self, request: HistoricalBackfillRequest
    ) -> list[BackfillJob]:
        """Split an approved request into chunk jobs. Transitions to RUNNING."""
        chunks = compute_chunks(request.start_date, request.end_date)

        jobs: list[BackfillJob] = []
        for idx, (chunk_start, chunk_end) in enumerate(chunks):
            job = BackfillJob(
                backfill_request_id=request.id,
                tenant_id=request.tenant_id,
                source_system=request.source_system,
                chunk_start_date=chunk_start,
                chunk_end_date=chunk_end,
                chunk_index=idx,
            )
            self.db.add(job)
            jobs.append(job)

        request.status = HistoricalBackfillStatus.RUNNING
        request.started_at = datetime.now(timezone.utc)
        self.db.commit()

        from src.services.audit_logger import emit_backfill_started

        emit_backfill_started(self.db, request, total_chunks=len(jobs))

        logger.info(
            "backfill_executor.jobs_created",
            extra={
                "request_id": request.id,
                "tenant_id": request.tenant_id,
                "chunk_count": len(jobs),
            },
        )
        return jobs

    def find_approved_requests(self) -> list[HistoricalBackfillRequest]:
        """Find approved requests that don't yet have chunk jobs."""
        approved = (
            self.db.query(HistoricalBackfillRequest)
            .filter(
                HistoricalBackfillRequest.status
                == HistoricalBackfillStatus.APPROVED,
            )
            .all()
        )

        result: list[HistoricalBackfillRequest] = []
        for req in approved:
            has_jobs = (
                self.db.query(BackfillJob)
                .filter(BackfillJob.backfill_request_id == req.id)
                .first()
            )
            if not has_jobs:
                result.append(req)
        return result

    # ------------------------------------------------------------------
    # Job picking (with rate limiting)
    # ------------------------------------------------------------------

    def get_tenants_with_running_jobs(self) -> set[str]:
        """Get tenant IDs that already have a RUNNING backfill job."""
        rows = (
            self.db.query(BackfillJob.tenant_id)
            .filter(BackfillJob.status == BackfillJobStatus.RUNNING)
            .distinct()
            .all()
        )
        return {r[0] for r in rows}

    def pick_next_job(
        self, exclude_tenant_ids: Optional[set[str]] = None
    ) -> Optional[BackfillJob]:
        """
        Pick the next QUEUED job ready to run.

        Respects next_retry_at, tenant exclusions (rate limiting),
        and chunk ordering.
        """
        now = datetime.now(timezone.utc)

        query = self.db.query(BackfillJob).filter(
            BackfillJob.status == BackfillJobStatus.QUEUED,
            or_(
                BackfillJob.next_retry_at.is_(None),
                BackfillJob.next_retry_at <= now,
            ),
        )

        if exclude_tenant_ids:
            query = query.filter(
                BackfillJob.tenant_id.notin_(exclude_tenant_ids)
            )

        return (
            query.order_by(
                BackfillJob.chunk_index.asc(),
                BackfillJob.created_at.asc(),
            )
            .first()
        )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute_job(self, job: BackfillJob) -> None:
        """Execute a single chunk job via BackfillService."""
        job.mark_running()
        self.db.commit()

        start_time = datetime.now(timezone.utc)

        try:
            plan = self._planner.plan(
                tenant_id=job.tenant_id,
                source_system=job.source_system,
                start_date=job.chunk_start_date,
                end_date=job.chunk_end_date,
            )

            if not plan.affected_models:
                job.mark_success(rows_affected=0, duration=0.0)
                self.db.commit()
                self._update_parent_status(job.backfill_request_id)
                return

            model_selector = " ".join(plan.affected_models)

            from src.services.backfill_service import BackfillService

            service = BackfillService(
                db_session=self.db,
                tenant_id=job.tenant_id,
            )

            result = await service.execute_backfill(
                model_selector=model_selector,
                start_date=job.chunk_start_date.isoformat(),
                end_date=job.chunk_end_date.isoformat(),
                backfill_id=job.id,
            )

            duration = (
                datetime.now(timezone.utc) - start_time
            ).total_seconds()

            if result and result.is_successful:
                job.mark_success(
                    rows_affected=result.rows_affected or 0,
                    duration=duration,
                )
            else:
                error = (
                    result.error_message if result else "No result returned"
                )
                job.mark_failed(error)
                self._maybe_schedule_retry(job)

        except Exception as e:
            duration = (
                datetime.now(timezone.utc) - start_time
            ).total_seconds()
            job.mark_failed(str(e))
            job.duration_seconds = duration
            self._maybe_schedule_retry(job)
            logger.exception(
                "backfill_executor.job_error",
                extra={
                    "job_id": job.id,
                    "tenant_id": job.tenant_id,
                    "chunk_index": job.chunk_index,
                },
            )

        self.db.commit()
        self._update_parent_status(job.backfill_request_id)

    # ------------------------------------------------------------------
    # Retry
    # ------------------------------------------------------------------

    def _maybe_schedule_retry(self, job: BackfillJob) -> None:
        """Schedule retry with exponential backoff if attempts remain."""
        if job.can_retry:
            delay = calculate_backoff(job.attempt)
            job.schedule_retry(delay)
            logger.info(
                "backfill_executor.retry_scheduled",
                extra={
                    "job_id": job.id,
                    "attempt": job.attempt,
                    "delay_seconds": round(delay, 1),
                },
            )

    # ------------------------------------------------------------------
    # Parent status roll-up
    # ------------------------------------------------------------------

    def _update_parent_status(self, request_id: str) -> None:
        """Update parent request status based on chunk job states."""
        jobs = (
            self.db.query(BackfillJob)
            .filter(BackfillJob.backfill_request_id == request_id)
            .all()
        )
        if not jobs:
            return

        request = self._get_request(request_id)
        if not request:
            return

        all_success = all(
            j.status == BackfillJobStatus.SUCCESS for j in jobs
        )
        any_terminal_failure = any(
            j.status == BackfillJobStatus.FAILED and not j.can_retry
            for j in jobs
        )
        all_cancelled = all(
            j.status == BackfillJobStatus.CANCELLED for j in jobs
        )

        now = datetime.now(timezone.utc)

        if all_success:
            request.status = HistoricalBackfillStatus.COMPLETED
            request.completed_at = now
        elif all_cancelled:
            request.status = HistoricalBackfillStatus.CANCELLED
            request.completed_at = now
        elif any_terminal_failure:
            request.status = HistoricalBackfillStatus.FAILED
            request.completed_at = now
            failed_count = sum(
                1
                for j in jobs
                if j.status == BackfillJobStatus.FAILED
            )
            request.error_message = (
                f"{failed_count} chunk(s) failed permanently"
            )

        self.db.commit()

        # Emit audit events for terminal transitions
        if all_success or all_cancelled:
            from src.services.audit_logger import emit_backfill_completed

            emit_backfill_completed(self.db, request)
        elif any_terminal_failure:
            from src.services.audit_logger import emit_backfill_failed

            emit_backfill_failed(self.db, request)

        # Trigger completion hooks when backfill reaches terminal state
        if all_success or all_cancelled or any_terminal_failure:
            self._on_request_terminal(request)

    def _on_request_terminal(
        self, request: HistoricalBackfillRequest
    ) -> None:
        """
        Called when a backfill request reaches a terminal state.

        Triggers freshness recalculation and cache clearing via
        BackfillStateGuard.on_backfill_completed().
        """
        try:
            from src.services.backfill_state_guard import BackfillStateGuard

            guard = BackfillStateGuard(self.db, request.tenant_id)
            guard.on_backfill_completed(request.id, request.source_system)
        except Exception:
            logger.warning(
                "backfill_executor.completion_hook_failed",
                extra={
                    "request_id": request.id,
                    "tenant_id": request.tenant_id,
                },
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Pause / Resume / Cancel
    # ------------------------------------------------------------------

    def pause_request(self, request_id: str) -> int:
        """Pause all queued jobs for a request. Returns count paused."""
        jobs = (
            self.db.query(BackfillJob)
            .filter(
                BackfillJob.backfill_request_id == request_id,
                BackfillJob.status == BackfillJobStatus.QUEUED,
            )
            .all()
        )

        for job in jobs:
            job.mark_paused()

        self.db.commit()

        request = self._get_request(request_id)
        if request:
            from src.services.audit_logger import emit_backfill_paused

            emit_backfill_paused(self.db, request, paused_chunks=len(jobs))

        logger.info(
            "backfill_executor.request_paused",
            extra={
                "request_id": request_id,
                "paused_count": len(jobs),
            },
        )
        return len(jobs)

    def resume_request(self, request_id: str) -> int:
        """Resume all paused jobs for a request. Returns count resumed."""
        jobs = (
            self.db.query(BackfillJob)
            .filter(
                BackfillJob.backfill_request_id == request_id,
                BackfillJob.status == BackfillJobStatus.PAUSED,
            )
            .all()
        )

        for job in jobs:
            job.status = BackfillJobStatus.QUEUED
            job.completed_at = None
            job.next_retry_at = None

        if jobs:
            request = self._get_request(request_id)
            if request and request.status != HistoricalBackfillStatus.RUNNING:
                request.status = HistoricalBackfillStatus.RUNNING

        self.db.commit()

        logger.info(
            "backfill_executor.request_resumed",
            extra={
                "request_id": request_id,
                "resumed_count": len(jobs),
            },
        )
        return len(jobs)

    def cancel_request(self, request_id: str) -> int:
        """Cancel all non-terminal jobs for a request. Returns count cancelled."""
        jobs = (
            self.db.query(BackfillJob)
            .filter(
                BackfillJob.backfill_request_id == request_id,
                BackfillJob.status.in_([
                    BackfillJobStatus.QUEUED,
                    BackfillJobStatus.PAUSED,
                ]),
            )
            .all()
        )

        for job in jobs:
            job.mark_cancelled()

        self.db.commit()
        self._update_parent_status(request_id)

        logger.info(
            "backfill_executor.request_cancelled",
            extra={
                "request_id": request_id,
                "cancelled_count": len(jobs),
            },
        )
        return len(jobs)

    # ------------------------------------------------------------------
    # Crash recovery
    # ------------------------------------------------------------------

    def recover_stale_jobs(self, stale_minutes: int = STALE_JOB_MINUTES) -> int:
        """
        Reset RUNNING jobs stuck longer than stale_minutes.

        Called at worker startup to recover from crashes mid-execution.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
        stale = (
            self.db.query(BackfillJob)
            .filter(
                BackfillJob.status == BackfillJobStatus.RUNNING,
                BackfillJob.started_at < cutoff,
            )
            .all()
        )

        for job in stale:
            job.status = BackfillJobStatus.QUEUED
            job.next_retry_at = None
            job.started_at = None

        if stale:
            self.db.commit()
            logger.warning(
                "backfill_executor.stale_jobs_recovered",
                extra={"count": len(stale)},
            )
        return len(stale)
