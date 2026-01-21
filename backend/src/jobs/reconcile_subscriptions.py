"""
Subscription reconciliation job.

Runs hourly to sync subscription status with Shopify Billing API.
Ensures subscription state is always accurate even if webhooks are missed.

Usage:
    python -m src.jobs.reconcile_subscriptions

Deployed as a cron job in render.yaml.
"""

import os
import sys
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Maximum age of subscriptions to check (don't check very old ones)
MAX_SUBSCRIPTION_AGE_DAYS = 90

# Maximum stores to process per run (for rate limiting)
MAX_STORES_PER_RUN = 100


class ReconciliationStats:
    """Track reconciliation run statistics."""

    def __init__(self):
        self.stores_processed = 0
        self.subscriptions_checked = 0
        self.subscriptions_updated = 0
        self.errors = 0
        self.start_time = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        duration = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        return {
            "stores_processed": self.stores_processed,
            "subscriptions_checked": self.subscriptions_checked,
            "subscriptions_updated": self.subscriptions_updated,
            "errors": self.errors,
            "duration_seconds": duration
        }


def get_database_session() -> Session:
    """Create database session for reconciliation job."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is required")

    # Handle Render's postgres:// URL format
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


async def reconcile_store_subscriptions(
    session: Session,
    store,
    stats: ReconciliationStats
) -> None:
    """
    Reconcile subscriptions for a single store.

    Args:
        session: Database session
        store: ShopifyStore instance
        stats: Statistics tracker
    """
    from src.models.subscription import Subscription, SubscriptionStatus
    from src.integrations.shopify.billing_client import get_billing_client, ShopifyAPIError
    from src.services.billing_service import BillingService

    logger.info("Reconciling store", extra={
        "shop_domain": store.shop_domain,
        "tenant_id": store.tenant_id
    })

    # Get active subscriptions for this store
    subscriptions = session.query(Subscription).filter(
        Subscription.store_id == store.id,
        Subscription.status.in_([
            SubscriptionStatus.ACTIVE.value,
            SubscriptionStatus.PENDING.value,
            SubscriptionStatus.FROZEN.value
        ]),
        Subscription.shopify_subscription_id.isnot(None)
    ).all()

    if not subscriptions:
        logger.debug("No active subscriptions for store", extra={
            "shop_domain": store.shop_domain
        })
        return

    # Decrypt access token
    if not store.access_token_encrypted:
        logger.warning("Store has no access token, skipping", extra={
            "shop_domain": store.shop_domain
        })
        return

    access_token = store.access_token_encrypted  # TODO: Implement decryption

    try:
        async with get_billing_client(store.shop_domain, access_token) as client:
            # Get active subscriptions from Shopify
            shopify_subs = await client.get_active_subscriptions()
            shopify_sub_ids = {sub.id: sub for sub in shopify_subs}

            for subscription in subscriptions:
                stats.subscriptions_checked += 1

                shopify_sub = shopify_sub_ids.get(subscription.shopify_subscription_id)

                if shopify_sub:
                    # Subscription exists in Shopify - sync status
                    if subscription.status != shopify_sub.status.lower():
                        logger.info("Status mismatch detected", extra={
                            "shop_domain": store.shop_domain,
                            "subscription_id": subscription.id,
                            "local_status": subscription.status,
                            "shopify_status": shopify_sub.status
                        })

                        billing_service = BillingService(session, store.tenant_id)
                        billing_service.sync_with_shopify(
                            subscription.shopify_subscription_id,
                            shopify_sub.status
                        )
                        stats.subscriptions_updated += 1

                    # Update period end if changed
                    if shopify_sub.current_period_end and subscription.current_period_end != shopify_sub.current_period_end:
                        subscription.current_period_end = shopify_sub.current_period_end
                        session.commit()

                else:
                    # Subscription not found in Shopify active list
                    # It may have been cancelled
                    if subscription.status in [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.PENDING.value]:
                        # Try to get specific subscription to check status
                        specific_sub = await client.get_subscription(subscription.shopify_subscription_id)

                        if specific_sub:
                            if specific_sub.status.upper() in ["CANCELLED", "EXPIRED", "DECLINED"]:
                                logger.info("Subscription no longer active in Shopify", extra={
                                    "shop_domain": store.shop_domain,
                                    "subscription_id": subscription.id,
                                    "shopify_status": specific_sub.status
                                })

                                billing_service = BillingService(session, store.tenant_id)
                                billing_service.sync_with_shopify(
                                    subscription.shopify_subscription_id,
                                    specific_sub.status
                                )
                                stats.subscriptions_updated += 1
                        else:
                            logger.warning("Subscription not found in Shopify", extra={
                                "shop_domain": store.shop_domain,
                                "subscription_id": subscription.id,
                                "shopify_subscription_id": subscription.shopify_subscription_id
                            })

    except ShopifyAPIError as e:
        logger.error("Shopify API error during reconciliation", extra={
            "shop_domain": store.shop_domain,
            "error": str(e)
        })
        stats.errors += 1
    except Exception as e:
        logger.error("Error reconciling store", extra={
            "shop_domain": store.shop_domain,
            "error": str(e)
        })
        stats.errors += 1


async def check_grace_period_expirations(session: Session, stats: ReconciliationStats) -> None:
    """
    Check for frozen subscriptions with expired grace periods.

    When grace period expires, downgrade the subscription to cancelled.
    """
    from src.models.subscription import Subscription, SubscriptionStatus
    from src.services.billing_service import BillingService

    now = datetime.now(timezone.utc)

    # Find frozen subscriptions with expired grace periods
    expired_subscriptions = session.query(Subscription).filter(
        Subscription.status == SubscriptionStatus.FROZEN.value,
        Subscription.grace_period_ends_on.isnot(None),
        Subscription.grace_period_ends_on < now
    ).all()

    for subscription in expired_subscriptions:
        logger.info("Grace period expired, cancelling subscription", extra={
            "subscription_id": subscription.id,
            "tenant_id": subscription.tenant_id,
            "grace_period_ended": subscription.grace_period_ends_on.isoformat()
        })

        billing_service = BillingService(session, subscription.tenant_id)

        # This will log the cancellation event
        subscription.status = SubscriptionStatus.CANCELLED.value
        subscription.cancelled_at = now

        stats.subscriptions_updated += 1

    if expired_subscriptions:
        session.commit()
        logger.info("Processed expired grace periods", extra={
            "count": len(expired_subscriptions)
        })


async def run_reconciliation() -> dict:
    """
    Run the subscription reconciliation job.

    Returns:
        Statistics dictionary with job results
    """
    logger.info("Starting subscription reconciliation job")

    stats = ReconciliationStats()
    session = get_database_session()

    try:
        from src.models.store import ShopifyStore

        # Get active stores to reconcile
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=MAX_SUBSCRIPTION_AGE_DAYS)

        stores = session.query(ShopifyStore).filter(
            ShopifyStore.status == "active",
            ShopifyStore.access_token_encrypted.isnot(None),
            ShopifyStore.updated_at > cutoff_date
        ).limit(MAX_STORES_PER_RUN).all()

        logger.info("Found stores to reconcile", extra={
            "store_count": len(stores)
        })

        # Reconcile each store
        for store in stores:
            stats.stores_processed += 1
            await reconcile_store_subscriptions(session, store, stats)

            # Small delay between stores to avoid rate limiting
            await asyncio.sleep(0.5)

        # Check grace period expirations
        await check_grace_period_expirations(session, stats)

        result = stats.to_dict()
        logger.info("Reconciliation job completed", extra=result)
        return result

    except Exception as e:
        logger.error("Reconciliation job failed", extra={
            "error": str(e)
        })
        raise
    finally:
        session.close()


def main():
    """Entry point for running reconciliation job from command line."""
    try:
        result = asyncio.run(run_reconciliation())
        print(f"Reconciliation completed: {result}")
        sys.exit(0)
    except Exception as e:
        print(f"Reconciliation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
