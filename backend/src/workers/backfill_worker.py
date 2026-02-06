"""
Backfill worker — Render managed background worker for executing
historical data backfills.

Runs as a long-lived process. Each cycle:
1. Recovers stale RUNNING jobs (crash recovery)
2. Creates chunk jobs for newly approved requests
3. Picks and executes queued jobs (one per tenant at a time)

CONSTRAINTS:
- One active backfill job per tenant (rate limit)
- No Celery, no Temporal — driven by Postgres job state
- Graceful shutdown on SIGTERM/SIGINT
- Survives worker restarts (progress persisted in DB)

Usage:
    python -m src.workers.backfill_worker

Deployed as a Render worker service in render.yaml.

Story 3.4 - Backfill Execution
"""

import os
import sys
import signal
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = int(
    os.getenv("BACKFILL_POLL_INTERVAL_SECONDS", "30")
)
MAX_JOBS_PER_CYCLE = int(
    os.getenv("BACKFILL_MAX_JOBS_PER_CYCLE", "2")
)


@dataclass
class WorkerStats:
    """Cumulative statistics for the worker process lifetime."""

    cycles: int = 0
    requests_created: int = 0
    jobs_executed: int = 0
    jobs_recovered: int = 0
    errors: int = 0
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        uptime = (
            datetime.now(timezone.utc) - self.started_at
        ).total_seconds()
        return {
            "cycles": self.cycles,
            "requests_created": self.requests_created,
            "jobs_executed": self.jobs_executed,
            "jobs_recovered": self.jobs_recovered,
            "errors": self.errors,
            "uptime_seconds": round(uptime, 2),
        }


def _get_database_session() -> Session:
    """Create a fresh database session."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is required")

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(database_url, pool_pre_ping=True)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return factory()


async def run_cycle(db_session: Session, stats: WorkerStats) -> None:
    """
    Run one worker cycle: recover stale jobs, create chunk jobs,
    execute queued jobs.
    """
    from src.services.backfill_executor import BackfillExecutor

    executor = BackfillExecutor(db_session)

    try:
        # Phase 1: Recover stale RUNNING jobs (crash recovery)
        recovered = executor.recover_stale_jobs()
        stats.jobs_recovered += recovered

        # Phase 2: Create chunk jobs for newly approved requests
        approved = executor.find_approved_requests()
        for request in approved:
            executor.create_jobs_for_request(request)
            stats.requests_created += 1

        # Phase 3: Execute queued jobs (one per tenant — rate limit)
        busy_tenants = executor.get_tenants_with_running_jobs()
        executed_this_cycle = 0

        for _ in range(MAX_JOBS_PER_CYCLE):
            job = executor.pick_next_job(exclude_tenant_ids=busy_tenants)
            if not job:
                break

            await executor.execute_job(job)
            executed_this_cycle += 1
            stats.jobs_executed += 1

            # Block this tenant from running another job this cycle
            busy_tenants.add(job.tenant_id)

        stats.cycles += 1

        if approved or executed_this_cycle > 0 or recovered > 0:
            logger.info(
                "backfill_worker.cycle_completed",
                extra={
                    "cycle": stats.cycles,
                    "requests_created": len(approved),
                    "jobs_executed": executed_this_cycle,
                    "jobs_recovered": recovered,
                },
            )

    except Exception:
        stats.errors += 1
        db_session.rollback()
        logger.exception(
            "backfill_worker.cycle_error",
            extra={"cycle": stats.cycles},
        )


async def run_worker() -> None:
    """
    Main worker loop. Runs until SIGTERM/SIGINT.

    Creates a fresh DB session each cycle for connection health.
    """
    stats = WorkerStats()
    shutdown_event = asyncio.Event()

    def _handle_signal(sig, _frame):
        logger.info("Received signal %s, shutting down gracefully", sig)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info(
        "Backfill worker starting",
        extra={
            "poll_interval_seconds": POLL_INTERVAL_SECONDS,
            "max_jobs_per_cycle": MAX_JOBS_PER_CYCLE,
        },
    )

    while not shutdown_event.is_set():
        session = _get_database_session()
        try:
            await run_cycle(session, stats)
        finally:
            session.close()

        try:
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=POLL_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            pass  # Normal: timeout = no shutdown, continue loop

    logger.info("Backfill worker stopped", extra=stats.to_dict())


def main():
    """Entry point for running worker from command line."""
    try:
        asyncio.run(run_worker())
        sys.exit(0)
    except Exception as e:
        logger.error("Backfill worker crashed", extra={"error": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    main()
