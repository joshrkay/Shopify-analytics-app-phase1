"""
Subscription repository for data access operations.

Encapsulates all database operations for subscriptions with:
- Tenant isolation enforcement
- Consistent query patterns
- Optimized lookups
"""

import logging
from typing import Optional, List
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from src.models.subscription import Subscription, SubscriptionStatus
from src.models.billing_event import BillingEvent, BillingEventType

logger = logging.getLogger(__name__)


class SubscriptionRepository:
    """
    Repository for subscription data access.

    All methods enforce tenant isolation via tenant_id parameter.
    """

    def __init__(self, db_session: Session):
        """
        Initialize repository with database session.

        Args:
            db_session: SQLAlchemy database session
        """
        self.db = db_session

    def get_by_id(self, subscription_id: str, tenant_id: str) -> Optional[Subscription]:
        """
        Get subscription by ID with tenant isolation.

        Args:
            subscription_id: Subscription ID
            tenant_id: Tenant ID for isolation

        Returns:
            Subscription if found, None otherwise
        """
        return self.db.query(Subscription).filter(
            Subscription.id == subscription_id,
            Subscription.tenant_id == tenant_id
        ).first()

    def get_by_shopify_id(
        self,
        shopify_subscription_id: str,
        tenant_id: Optional[str] = None
    ) -> Optional[Subscription]:
        """
        Get subscription by Shopify subscription ID.

        Args:
            shopify_subscription_id: Shopify GraphQL ID
            tenant_id: Optional tenant ID for additional isolation

        Returns:
            Subscription if found, None otherwise
        """
        query = self.db.query(Subscription).filter(
            Subscription.shopify_subscription_id == shopify_subscription_id
        )

        if tenant_id:
            query = query.filter(Subscription.tenant_id == tenant_id)

        return query.first()

    def get_active_for_tenant(self, tenant_id: str) -> Optional[Subscription]:
        """
        Get active subscription for a tenant.

        Returns subscriptions in ACTIVE, PENDING, or FROZEN status.

        Args:
            tenant_id: Tenant ID

        Returns:
            Active subscription if found, None otherwise
        """
        return self.db.query(Subscription).filter(
            Subscription.tenant_id == tenant_id,
            Subscription.status.in_([
                SubscriptionStatus.ACTIVE.value,
                SubscriptionStatus.PENDING.value,
                SubscriptionStatus.FROZEN.value
            ])
        ).first()

    def get_active_for_store(self, store_id: str, tenant_id: str) -> Optional[Subscription]:
        """
        Get active subscription for a specific store.

        Args:
            store_id: Store ID
            tenant_id: Tenant ID for isolation

        Returns:
            Active subscription if found, None otherwise
        """
        return self.db.query(Subscription).filter(
            Subscription.store_id == store_id,
            Subscription.tenant_id == tenant_id,
            Subscription.status.in_([
                SubscriptionStatus.ACTIVE.value,
                SubscriptionStatus.PENDING.value,
                SubscriptionStatus.FROZEN.value
            ])
        ).first()

    def get_all_for_tenant(
        self,
        tenant_id: str,
        include_cancelled: bool = False
    ) -> List[Subscription]:
        """
        Get all subscriptions for a tenant.

        Args:
            tenant_id: Tenant ID
            include_cancelled: Whether to include cancelled subscriptions

        Returns:
            List of subscriptions
        """
        query = self.db.query(Subscription).filter(
            Subscription.tenant_id == tenant_id
        )

        if not include_cancelled:
            query = query.filter(
                Subscription.status.notin_([
                    SubscriptionStatus.CANCELLED.value,
                    SubscriptionStatus.DECLINED.value,
                    SubscriptionStatus.EXPIRED.value
                ])
            )

        return query.order_by(Subscription.created_at.desc()).all()

    def get_frozen_with_expired_grace(self) -> List[Subscription]:
        """
        Get all frozen subscriptions with expired grace periods.

        Used by reconciliation job to cancel overdue subscriptions.

        Returns:
            List of subscriptions needing cancellation
        """
        now = datetime.now(timezone.utc)

        return self.db.query(Subscription).filter(
            Subscription.status == SubscriptionStatus.FROZEN.value,
            Subscription.grace_period_ends_on.isnot(None),
            Subscription.grace_period_ends_on < now
        ).all()

    def get_pending_older_than(self, days: int) -> List[Subscription]:
        """
        Get pending subscriptions older than specified days.

        Used to identify stuck pending subscriptions.

        Args:
            days: Number of days threshold

        Returns:
            List of old pending subscriptions
        """
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        return self.db.query(Subscription).filter(
            Subscription.status == SubscriptionStatus.PENDING.value,
            Subscription.created_at < cutoff
        ).all()

    def get_subscriptions_for_reconciliation(
        self,
        store_id: str,
        max_age_days: int = 90
    ) -> List[Subscription]:
        """
        Get subscriptions eligible for reconciliation.

        Args:
            store_id: Store ID
            max_age_days: Maximum subscription age to reconcile

        Returns:
            List of subscriptions to reconcile
        """
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

        return self.db.query(Subscription).filter(
            Subscription.store_id == store_id,
            Subscription.status.in_([
                SubscriptionStatus.ACTIVE.value,
                SubscriptionStatus.PENDING.value,
                SubscriptionStatus.FROZEN.value
            ]),
            Subscription.shopify_subscription_id.isnot(None),
            Subscription.created_at > cutoff
        ).all()

    def create(self, subscription: Subscription) -> Subscription:
        """
        Create a new subscription.

        Args:
            subscription: Subscription instance to create

        Returns:
            Created subscription
        """
        self.db.add(subscription)
        self.db.flush()

        logger.info("Subscription created", extra={
            "subscription_id": subscription.id,
            "tenant_id": subscription.tenant_id,
            "plan_id": subscription.plan_id
        })

        return subscription

    def update_status(
        self,
        subscription: Subscription,
        new_status: SubscriptionStatus,
        metadata: Optional[dict] = None
    ) -> Subscription:
        """
        Update subscription status with logging.

        Args:
            subscription: Subscription to update
            new_status: New status value
            metadata: Optional metadata for audit log

        Returns:
            Updated subscription
        """
        old_status = subscription.status
        subscription.status = new_status.value

        logger.info("Subscription status updated", extra={
            "subscription_id": subscription.id,
            "tenant_id": subscription.tenant_id,
            "old_status": old_status,
            "new_status": new_status.value
        })

        return subscription

    def save(self, subscription: Subscription) -> Subscription:
        """
        Save subscription changes.

        Args:
            subscription: Subscription with changes

        Returns:
            Saved subscription
        """
        self.db.add(subscription)
        self.db.flush()
        return subscription

    def commit(self) -> None:
        """Commit current transaction."""
        self.db.commit()

    def rollback(self) -> None:
        """Rollback current transaction."""
        self.db.rollback()


class WebhookEventRepository:
    """
    Repository for webhook event deduplication.

    Tracks processed webhook events to ensure idempotency.
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    def is_processed(self, event_id: str) -> bool:
        """
        Check if a webhook event has already been processed.

        Args:
            event_id: Shopify webhook event ID

        Returns:
            True if already processed, False otherwise
        """
        from src.models.webhook_event import WebhookEvent

        existing = self.db.query(WebhookEvent).filter(
            WebhookEvent.shopify_event_id == event_id
        ).first()

        return existing is not None

    def mark_processed(
        self,
        event_id: str,
        topic: str,
        shop_domain: str,
        payload_hash: Optional[str] = None
    ) -> None:
        """
        Mark a webhook event as processed.

        Args:
            event_id: Shopify webhook event ID
            topic: Webhook topic
            shop_domain: Shop domain
            payload_hash: Optional hash of payload for debugging
        """
        from src.models.webhook_event import WebhookEvent

        event = WebhookEvent(
            shopify_event_id=event_id,
            topic=topic,
            shop_domain=shop_domain,
            payload_hash=payload_hash,
            processed_at=datetime.now(timezone.utc)
        )
        self.db.add(event)
        self.db.flush()


class BillingAuditRepository:
    """
    Repository for billing audit log operations.

    Append-only - no update or delete operations.
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    def log_event(
        self,
        tenant_id: str,
        event_type: BillingEventType,
        store_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        from_plan_id: Optional[str] = None,
        to_plan_id: Optional[str] = None,
        amount_cents: Optional[int] = None,
        shopify_subscription_id: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> BillingEvent:
        """
        Log a billing event to the audit log.

        Args:
            tenant_id: Tenant ID
            event_type: Type of billing event
            store_id: Optional store ID
            subscription_id: Optional subscription ID
            from_plan_id: Previous plan (for changes)
            to_plan_id: New plan (for changes)
            amount_cents: Amount in cents
            shopify_subscription_id: Shopify subscription ID
            metadata: Additional event metadata

        Returns:
            Created BillingEvent
        """
        import uuid

        event = BillingEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            event_type=event_type.value,
            store_id=store_id,
            subscription_id=subscription_id,
            from_plan_id=from_plan_id,
            to_plan_id=to_plan_id,
            amount_cents=amount_cents,
            shopify_subscription_id=shopify_subscription_id,
            extra_metadata=metadata
        )
        self.db.add(event)
        self.db.flush()

        logger.info("Billing event logged", extra={
            "event_id": event.id,
            "tenant_id": tenant_id,
            "event_type": event_type.value
        })

        return event

    def get_events_for_tenant(
        self,
        tenant_id: str,
        event_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[BillingEvent]:
        """
        Get billing events for a tenant.

        Args:
            tenant_id: Tenant ID
            event_type: Optional event type filter
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of billing events
        """
        query = self.db.query(BillingEvent).filter(
            BillingEvent.tenant_id == tenant_id
        )

        if event_type:
            query = query.filter(BillingEvent.event_type == event_type)

        return query.order_by(
            BillingEvent.created_at.desc()
        ).offset(offset).limit(limit).all()

    def get_recent_for_subscription(
        self,
        subscription_id: str,
        limit: int = 10
    ) -> List[BillingEvent]:
        """
        Get recent events for a subscription.

        Args:
            subscription_id: Subscription ID
            limit: Maximum results

        Returns:
            List of recent billing events
        """
        return self.db.query(BillingEvent).filter(
            BillingEvent.subscription_id == subscription_id
        ).order_by(
            BillingEvent.created_at.desc()
        ).limit(limit).all()
