"""
Access Revocation Enforcement Worker.

Polls for expired grace-period revocations and enforces them
by deactivating UserRoleAssignment and UserTenantRole records.

Run as: python -m src.workers.access_revocation_job

Configuration:
- REVOCATION_POLL_INTERVAL: Seconds between cycles (default: 300)
- ACCESS_REVOCATION_GRACE_HOURS: Default grace period (default: 24)

Story 5.5.4 - Grace-Period Access Removal
"""

import os
import sys
import signal
import logging
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.session import get_db_session_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.getenv("REVOCATION_POLL_INTERVAL", "300"))

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Shutdown signal received", extra={"signal": signum})
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def run_cycle() -> int:
    """Run one enforcement cycle. Returns count of enforced revocations."""
    db_gen = get_db_session_sync()
    db = next(db_gen)
    try:
        from src.services.access_revocation_service import AccessRevocationService

        service = AccessRevocationService(db)
        enforced = service.enforce_expired_revocations()
        db.commit()

        if enforced:
            logger.info(
                "Revocation enforcement cycle complete",
                extra={"enforced_count": len(enforced)},
            )
        return len(enforced)

    except Exception:
        logger.error("Revocation enforcement cycle failed", exc_info=True)
        db.rollback()
        return 0
    finally:
        db.close()


def main():
    logger.info(
        "Access revocation worker started",
        extra={"poll_interval": POLL_INTERVAL},
    )

    while not _shutdown:
        run_cycle()
        for _ in range(POLL_INTERVAL):
            if _shutdown:
                break
            time.sleep(1)

    logger.info("Access revocation worker stopped")


if __name__ == "__main__":
    main()
