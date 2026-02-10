"""
Entitlement Reconciliation Worker.

Background job that ensures entitlement cache consistency by:
1. Cleaning up expired per-tenant overrides
2. Detecting drift between cached and computed entitlements
3. Catching missed trial expirations (EC4)
4. Verifying grace period consistency

Run as: python -m src.workers.entitlement_reconcile_job

Configuration:
- ENTITLEMENT_RECONCILE_INTERVAL: Seconds between cycles (default: 300)
- ENTITLEMENT_RECONCILE_BATCH_SIZE: Tenants per cycle (default: 200)

Story 6.2 — Entitlement drift reconciliation
"""

import os
import sys
import signal
import logging
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.session import get_db_session_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.getenv("ENTITLEMENT_RECONCILE_INTERVAL", "300"))
BATCH_SIZE = int(os.getenv("ENTITLEMENT_RECONCILE_BATCH_SIZE", "200"))

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Shutdown signal received", extra={"signal": signum})
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


@dataclass
class ReconciliationStats:
    """Track reconciliation run statistics."""

    overrides_expired: int = 0
    tenants_reconciled: int = 0
    drift_detected: int = 0
    trials_expired: int = 0
    grace_periods_expired: int = 0
    errors: int = 0
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        duration = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        return {
            "overrides_expired": self.overrides_expired,
            "tenants_reconciled": self.tenants_reconciled,
            "drift_detected": self.drift_detected,
            "trials_expired": self.trials_expired,
            "grace_periods_expired": self.grace_periods_expired,
            "errors": self.errors,
            "duration_seconds": round(duration, 2),
        }


def _cleanup_expired_overrides(db) -> int:
    """
    Phase 1: Delete expired overrides and invalidate affected tenants.

    Returns count of cleaned-up overrides.
    """
    from src.entitlements.service import EntitlementService

    try:
        service = EntitlementService(db)
        count = service.cleanup_expired_overrides()
        db.commit()
        return count
    except Exception:
        logger.error("Failed to clean up expired overrides", exc_info=True)
        db.rollback()
        return 0


def _check_trial_expirations(db, stats: ReconciliationStats) -> None:
    """
    Phase 2: Catch subscriptions with expired trials that were never updated.

    If Shopify webhook for trial expiry was missed, the subscription remains
    ACTIVE/PENDING with trial_end in the past.  Mark these as EXPIRED and
    invalidate their entitlement cache.
    """
    from src.models.subscription import Subscription, SubscriptionStatus
    from src.entitlements.service import invalidate_entitlements

    now = datetime.now(timezone.utc)

    try:
        stale_trials = db.query(Subscription).filter(
            Subscription.status.in_([
                SubscriptionStatus.ACTIVE.value,
                SubscriptionStatus.PENDING.value,
            ]),
            Subscription.trial_end.isnot(None),
            Subscription.trial_end < now,
            # Only catch subscriptions that were on trial
            # (current_period_start is None → never activated beyond trial)
            Subscription.current_period_start.is_(None),
        ).limit(BATCH_SIZE).all()

        for sub in stale_trials:
            logger.warning("Trial expired but subscription still active", extra={
                "subscription_id": sub.id,
                "tenant_id": sub.tenant_id,
                "trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
                "status": sub.status,
            })

            sub.status = SubscriptionStatus.EXPIRED.value
            invalidate_entitlements(sub.tenant_id, "trial_expired_reconciliation")
            stats.trials_expired += 1

        if stale_trials:
            db.commit()
            logger.info("Expired stale trials", extra={
                "count": len(stale_trials),
            })

    except Exception:
        logger.error("Failed to check trial expirations", exc_info=True)
        db.rollback()
        stats.errors += 1


def _check_grace_period_expirations(db, stats: ReconciliationStats) -> None:
    """
    Phase 3: Verify grace period consistency.

    Frozen subscriptions with expired grace periods should have their
    entitlement cache invalidated to reflect degraded access.
    """
    from src.models.subscription import Subscription, SubscriptionStatus
    from src.entitlements.service import invalidate_entitlements

    now = datetime.now(timezone.utc)

    try:
        expired_grace = db.query(Subscription).filter(
            Subscription.status == SubscriptionStatus.FROZEN.value,
            Subscription.grace_period_ends_on.isnot(None),
            Subscription.grace_period_ends_on < now,
        ).limit(BATCH_SIZE).all()

        for sub in expired_grace:
            logger.info("Grace period expired, invalidating entitlements", extra={
                "subscription_id": sub.id,
                "tenant_id": sub.tenant_id,
                "grace_period_ends_on": sub.grace_period_ends_on.isoformat(),
            })

            # Invalidate cache so next request sees degraded access
            invalidate_entitlements(
                sub.tenant_id, "grace_period_expired_reconciliation"
            )
            stats.grace_periods_expired += 1

        # Note: actual subscription status change (FROZEN → CANCELLED) is
        # handled by reconcile_subscriptions.py.  This worker only ensures
        # the entitlement cache reflects the degraded state promptly.

    except Exception:
        logger.error("Failed to check grace period expirations", exc_info=True)
        stats.errors += 1


def _reconcile_cached_entitlements(db, stats: ReconciliationStats) -> None:
    """
    Phase 4: Detect drift between cached and freshly computed entitlements.

    Samples a batch of tenants with cached entitlements and verifies the
    cached billing_state and plan_id match what the database says.
    """
    from src.models.subscription import Subscription, SubscriptionStatus
    from src.entitlements.cache import get_entitlement_cache
    from src.entitlements.service import invalidate_entitlements
    from src.entitlements.models import BillingState
    from src.models.plan import Plan

    cache = get_entitlement_cache()

    try:
        # Get a sample of tenants with active subscriptions
        subscriptions = (
            db.query(Subscription)
            .filter(
                Subscription.status.in_([
                    SubscriptionStatus.ACTIVE.value,
                    SubscriptionStatus.FROZEN.value,
                ]),
            )
            .limit(BATCH_SIZE)
            .all()
        )

        for sub in subscriptions:
            stats.tenants_reconciled += 1

            cached = cache.get(sub.tenant_id)
            if cached is None:
                continue  # Not cached — nothing to drift-check

            # Derive expected billing state
            expected_state = BillingState.from_subscription_status(
                status=sub.status,
                grace_period_ends_on=getattr(sub, "grace_period_ends_on", None),
                current_period_end=getattr(sub, "current_period_end", None),
            )

            # Check for drift
            drifted = False
            if cached.billing_state != expected_state.value:
                logger.warning("Entitlement drift: billing_state mismatch", extra={
                    "tenant_id": sub.tenant_id,
                    "cached_state": cached.billing_state,
                    "expected_state": expected_state.value,
                })
                drifted = True

            if cached.plan_id != sub.plan_id:
                logger.warning("Entitlement drift: plan_id mismatch", extra={
                    "tenant_id": sub.tenant_id,
                    "cached_plan": cached.plan_id,
                    "expected_plan": sub.plan_id,
                })
                drifted = True

            if drifted:
                invalidate_entitlements(sub.tenant_id, "drift_reconciliation")
                stats.drift_detected += 1

    except Exception:
        logger.error("Failed to reconcile cached entitlements", exc_info=True)
        stats.errors += 1


def run_cycle() -> ReconciliationStats:
    """Run one full reconciliation cycle."""
    stats = ReconciliationStats()
    db_gen = get_db_session_sync()
    db = next(db_gen)

    try:
        # Phase 1: Clean expired overrides
        stats.overrides_expired = _cleanup_expired_overrides(db)

        # Phase 2: Catch missed trial expirations
        _check_trial_expirations(db, stats)

        # Phase 3: Grace period consistency
        _check_grace_period_expirations(db, stats)

        # Phase 4: Drift detection
        _reconcile_cached_entitlements(db, stats)

        result = stats.to_dict()
        if any(v > 0 for k, v in result.items() if k != "duration_seconds"):
            logger.info("Reconciliation cycle complete", extra=result)

        return stats

    except Exception:
        logger.error("Reconciliation cycle failed", exc_info=True)
        stats.errors += 1
        return stats
    finally:
        db.close()


def main():
    logger.info(
        "Entitlement reconciliation worker started",
        extra={"poll_interval": POLL_INTERVAL, "batch_size": BATCH_SIZE},
    )

    while not _shutdown:
        run_cycle()
        # Sleep in 1-second increments for responsive shutdown
        for _ in range(POLL_INTERVAL):
            if _shutdown:
                break
            time.sleep(1)

    logger.info("Entitlement reconciliation worker stopped")


if __name__ == "__main__":
    main()
