#!/usr/bin/env python
"""
Insight Worker CLI - Entry point for cron-triggered insight generation.

Commands:
    dispatch    Create insight generation jobs for eligible tenants
    process     Execute queued insight generation jobs

Usage:
    # Daily job dispatch (run at 2am UTC via cron)
    python -m scripts.insight_worker dispatch --cadence daily

    # Hourly job dispatch (enterprise tenants only)
    python -m scripts.insight_worker dispatch --cadence hourly

    # Process queued jobs (run every 5 minutes via cron)
    python -m scripts.insight_worker process --limit 10

Cron Examples:
    # Daily dispatch at 2am UTC
    0 2 * * * cd /app && python -m scripts.insight_worker dispatch --cadence daily

    # Hourly dispatch (top of each hour)
    0 * * * * cd /app && python -m scripts.insight_worker dispatch --cadence hourly

    # Process jobs every 5 minutes
    */5 * * * * cd /app && python -m scripts.insight_worker process --limit 10

Story 8.1 - AI Insight Generation (Read-Only Analytics)
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

from src.database.session import get_db_session
from src.services.insight_job_dispatcher import (
    dispatch_daily_insight_jobs,
    dispatch_hourly_insight_jobs,
)
from src.services.insight_job_runner import run_insight_worker_cycle

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def cmd_dispatch(args) -> int:
    """Dispatch insight jobs for eligible tenants."""
    logger.info(
        "insight_worker.dispatch.start",
        extra={"cadence": args.cadence},
    )

    try:
        with get_db_session() as db:
            if args.cadence == "daily":
                jobs = dispatch_daily_insight_jobs(db)
            elif args.cadence == "hourly":
                jobs = dispatch_hourly_insight_jobs(db)
            else:
                logger.error(f"Unknown cadence: {args.cadence}")
                return 1

        logger.info(
            "insight_worker.dispatch.complete",
            extra={
                "cadence": args.cadence,
                "jobs_created": len(jobs),
                "job_ids": [j.job_id for j in jobs],
            },
        )
        print(f"Dispatched {len(jobs)} {args.cadence} insight jobs")
        return 0

    except Exception as e:
        logger.exception(
            "insight_worker.dispatch.error",
            extra={"cadence": args.cadence, "error": str(e)},
        )
        print(f"Error dispatching jobs: {e}", file=sys.stderr)
        return 1


def cmd_process(args) -> int:
    """Process queued insight jobs."""
    logger.info(
        "insight_worker.process.start",
        extra={"limit": args.limit},
    )

    try:
        with get_db_session() as db:
            result = run_insight_worker_cycle(db, limit=args.limit)

        logger.info(
            "insight_worker.process.complete",
            extra={
                "jobs_processed": result["jobs_processed"],
                "jobs_succeeded": result["jobs_succeeded"],
                "jobs_failed": result["jobs_failed"],
            },
        )
        print(
            f"Processed {result['jobs_processed']} jobs: "
            f"{result['jobs_succeeded']} succeeded, {result['jobs_failed']} failed"
        )
        return 0 if result["jobs_failed"] == 0 else 1

    except Exception as e:
        logger.exception(
            "insight_worker.process.error",
            extra={"error": str(e)},
        )
        print(f"Error processing jobs: {e}", file=sys.stderr)
        return 1


def main() -> int:
    """Main entry point for insight worker CLI."""
    parser = argparse.ArgumentParser(
        description="Insight Worker - AI insight generation job scheduler and processor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s dispatch --cadence daily    Dispatch daily insight jobs
  %(prog)s dispatch --cadence hourly   Dispatch hourly jobs (enterprise only)
  %(prog)s process --limit 10          Process up to 10 queued jobs
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # dispatch subcommand
    dispatch_parser = subparsers.add_parser(
        "dispatch",
        help="Dispatch insight generation jobs for eligible tenants",
    )
    dispatch_parser.add_argument(
        "--cadence",
        choices=["daily", "hourly"],
        required=True,
        help="Job cadence (daily for all tiers, hourly for enterprise only)",
    )
    dispatch_parser.set_defaults(func=cmd_dispatch)

    # process subcommand
    process_parser = subparsers.add_parser(
        "process",
        help="Process queued insight generation jobs",
    )
    process_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of jobs to process (default: 10)",
    )
    process_parser.set_defaults(func=cmd_process)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
