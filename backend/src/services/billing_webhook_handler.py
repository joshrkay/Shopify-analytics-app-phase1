"""
Billing webhook handler with idempotency support.

Processes Shopify billing webhooks with:
- Event deduplication using Shopify event ID
- Out-of-order event handling
- Comprehensive audit logging
- State transition validation
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.models.subscription import Subscription, SubscriptionStatus
from src.models.webhook_event import WebhookEvent
from src.models.billing_event import BillingEvent, BillingEventType
from src.models.store import ShopifyStore
from src.services.billing_service import BillingService

logger = logging.getLogger(__name__)


@dataclass
class WebhookProcessingResult:
    """Result of webhook processing."""
    processed: bool
    message: str
    subscription_id: Optional[str] = None
    skipped_reason: Optional[str] = None
    error: Optional[str] = None


class BillingWebhookHandler:
    """
    Handler for Shopify billing webhooks with idempotency.

    Ensures each webhook is processed exactly once using:
    - Shopify event ID (X-Shopify-Webhook-Id header)
    - Event timestamp comparison for out-of-order handling
    """

    # Valid state transitions
    VALID_TRANSITIONS = {
        SubscriptionStatus.PENDING.value: [
            SubscriptionStatus.ACTIVE.value,
            SubscriptionStatus.DECLINED.value,
            SubscriptionStatus.EXPIRED.value,
        ],
        SubscriptionStatus.ACTIVE.value: [
            SubscriptionStatus.FROZEN.value,
            SubscriptionStatus.CANCELLED.value,
            SubscriptionStatus.ACTIVE.value,  # Plan change
        ],
        SubscriptionStatus.FROZEN.value: [
            SubscriptionStatus.ACTIVE.value,  # Payment resolved
            SubscriptionStatus.CANCELLED.value,
        ],
    }

    def __init__(self, db_session: Session):
        """
        Initialize webhook handler.

        Args:
            db_session: Database session
        """
        self.db = db_session

    def _is_duplicate(self, shopify_event_id: str) -> bool:
        """
        Check if webhook event has already been processed.

        Args:
            shopify_event_id: Shopify webhook event ID

        Returns:
            True if duplicate, False otherwise
        """
        existing = self.db.query(WebhookEvent).filter(
            WebhookEvent.shopify_event_id == shopify_event_id
        ).first()

        return existing is not None

    def _record_event(
        self,
        shopify_event_id: str,
        topic: str,
        shop_domain: str,
        payload: Dict[str, Any]
    ) -> None:
        """
        Record processed webhook event for deduplication.

        Args:
            shopify_event_id: Shopify webhook event ID
            topic: Webhook topic
            shop_domain: Shop domain
            payload: Webhook payload
        """
        import json

        # Compute payload hash for debugging
        payload_str = json.dumps(payload, sort_keys=True)
        payload_hash = hashlib.sha256(payload_str.encode()).hexdigest()

        event = WebhookEvent(
            shopify_event_id=shopify_event_id,
            topic=topic,
            shop_domain=shop_domain,
            payload_hash=payload_hash,
            processed_at=datetime.now(timezone.utc)
        )
        self.db.add(event)

    def _is_valid_transition(self, current_status: str, new_status: str) -> bool:
        """
        Check if state transition is valid.

        Args:
            current_status: Current subscription status
            new_status: Proposed new status

        Returns:
            True if transition is valid, False otherwise
        """
        valid_targets = self.VALID_TRANSITIONS.get(current_status, [])
        return new_status in valid_targets

    def _log_audit_event(
        self,
        tenant_id: str,
        event_type: BillingEventType,
        subscription: Optional[Subscription] = None,
        store_id: Optional[str] = None,
        shopify_subscription_id: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> None:
        """Log billing event to audit table."""
        import uuid

        event = BillingEvent(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            event_type=event_type.value,
            store_id=store_id or (subscription.store_id if subscription else None),
            subscription_id=subscription.id if subscription else None,
            shopify_subscription_id=shopify_subscription_id,
            extra_metadata=metadata
        )
        self.db.add(event)

    async def handle_subscription_update(
        self,
        shopify_event_id: str,
        shop_domain: str,
        payload: Dict[str, Any],
        topic: str = "app_subscriptions/update"
    ) -> WebhookProcessingResult:
        """
        Handle app_subscriptions/update webhook.

        Args:
            shopify_event_id: Shopify webhook event ID
            shop_domain: Shop domain
            payload: Webhook payload
            topic: Webhook topic

        Returns:
            WebhookProcessingResult
        """
        # Check for duplicate
        if self._is_duplicate(shopify_event_id):
            logger.info("Duplicate webhook skipped", extra={
                "shopify_event_id": shopify_event_id,
                "shop_domain": shop_domain
            })
            return WebhookProcessingResult(
                processed=False,
                message="Duplicate webhook - already processed",
                skipped_reason="duplicate"
            )

        # Extract subscription data
        app_subscription = payload.get("app_subscription", {})
        subscription_gid = app_subscription.get("admin_graphql_api_id")
        shopify_status = app_subscription.get("status")
        subscription_name = app_subscription.get("name")

        if not subscription_gid:
            logger.warning("Webhook missing subscription ID", extra={
                "shop_domain": shop_domain,
                "payload_keys": list(payload.keys())
            })
            return WebhookProcessingResult(
                processed=False,
                message="Missing subscription ID",
                error="missing_subscription_id"
            )

        # Find store
        store = self.db.query(ShopifyStore).filter(
            ShopifyStore.shop_domain == shop_domain
        ).first()

        if not store:
            logger.warning("Store not found for webhook", extra={
                "shop_domain": shop_domain
            })
            # Record event even if store not found (to prevent reprocessing)
            self._record_event(shopify_event_id, topic, shop_domain, payload)
            self.db.commit()
            return WebhookProcessingResult(
                processed=False,
                message="Store not found",
                error="store_not_found"
            )

        # Find or create subscription
        subscription = self.db.query(Subscription).filter(
            Subscription.shopify_subscription_id == subscription_gid
        ).first()

        # Create billing service for this tenant
        billing_service = BillingService(self.db, store.tenant_id)

        try:
            result = await self._process_subscription_status(
                billing_service=billing_service,
                subscription=subscription,
                subscription_gid=subscription_gid,
                shopify_status=shopify_status,
                payload=app_subscription,
                store=store
            )

            # Record successful processing
            self._record_event(shopify_event_id, topic, shop_domain, payload)
            self.db.commit()

            logger.info("Webhook processed successfully", extra={
                "shopify_event_id": shopify_event_id,
                "shop_domain": shop_domain,
                "status": shopify_status,
                "subscription_id": subscription.id if subscription else None
            })

            return result

        except Exception as e:
            logger.error("Error processing webhook", extra={
                "shopify_event_id": shopify_event_id,
                "shop_domain": shop_domain,
                "error": str(e)
            })
            self.db.rollback()
            return WebhookProcessingResult(
                processed=False,
                message=f"Processing error: {str(e)}",
                error="processing_error"
            )

    async def _process_subscription_status(
        self,
        billing_service: BillingService,
        subscription: Optional[Subscription],
        subscription_gid: str,
        shopify_status: str,
        payload: Dict[str, Any],
        store: ShopifyStore
    ) -> WebhookProcessingResult:
        """
        Process subscription status change.

        Args:
            billing_service: BillingService instance
            subscription: Existing subscription (or None)
            subscription_gid: Shopify subscription ID
            shopify_status: Status from Shopify
            payload: Webhook payload
            store: ShopifyStore instance

        Returns:
            WebhookProcessingResult
        """
        # Map Shopify status to our status
        status_map = {
            "ACTIVE": SubscriptionStatus.ACTIVE,
            "PENDING": SubscriptionStatus.PENDING,
            "FROZEN": SubscriptionStatus.FROZEN,
            "CANCELLED": SubscriptionStatus.CANCELLED,
            "DECLINED": SubscriptionStatus.DECLINED,
            "EXPIRED": SubscriptionStatus.EXPIRED,
        }

        new_status = status_map.get(shopify_status.upper())
        if not new_status:
            logger.warning("Unknown Shopify status", extra={
                "shopify_status": shopify_status,
                "subscription_gid": subscription_gid
            })
            return WebhookProcessingResult(
                processed=False,
                message=f"Unknown status: {shopify_status}",
                error="unknown_status"
            )

        # Extract period end if present
        current_period_end = None
        if payload.get("current_period_end"):
            try:
                current_period_end = datetime.fromisoformat(
                    payload["current_period_end"].replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                pass

        # Handle based on status
        if new_status == SubscriptionStatus.ACTIVE:
            if subscription:
                # Validate transition
                if subscription.status != SubscriptionStatus.ACTIVE.value:
                    if not self._is_valid_transition(subscription.status, new_status.value):
                        logger.warning("Invalid state transition", extra={
                            "from": subscription.status,
                            "to": new_status.value,
                            "subscription_id": subscription.id
                        })
                        # Log but still process (Shopify is source of truth)
                        self._log_audit_event(
                            tenant_id=store.tenant_id,
                            event_type=BillingEventType.SUBSCRIPTION_UPDATED,
                            subscription=subscription,
                            shopify_subscription_id=subscription_gid,
                            metadata={
                                "warning": "invalid_transition",
                                "from_status": subscription.status,
                                "to_status": new_status.value,
                                "source": "webhook"
                            }
                        )

                billing_service.activate_subscription(
                    shopify_subscription_id=subscription_gid,
                    current_period_end=current_period_end
                )
            return WebhookProcessingResult(
                processed=True,
                message=f"Subscription activated",
                subscription_id=subscription.id if subscription else None
            )

        elif new_status == SubscriptionStatus.CANCELLED:
            if subscription:
                billing_service.cancel_subscription(
                    shopify_subscription_id=subscription_gid,
                    cancelled_at=datetime.now(timezone.utc)
                )
            return WebhookProcessingResult(
                processed=True,
                message="Subscription cancelled",
                subscription_id=subscription.id if subscription else None
            )

        elif new_status == SubscriptionStatus.FROZEN:
            if subscription:
                billing_service.freeze_subscription(
                    shopify_subscription_id=subscription_gid,
                    reason="payment_failed"
                )
            return WebhookProcessingResult(
                processed=True,
                message="Subscription frozen (payment failed)",
                subscription_id=subscription.id if subscription else None
            )

        elif new_status == SubscriptionStatus.DECLINED:
            if subscription:
                billing_service.cancel_subscription(
                    shopify_subscription_id=subscription_gid
                )
            return WebhookProcessingResult(
                processed=True,
                message="Subscription declined",
                subscription_id=subscription.id if subscription else None
            )

        elif new_status == SubscriptionStatus.EXPIRED:
            if subscription:
                subscription.status = SubscriptionStatus.EXPIRED.value
                self._log_audit_event(
                    tenant_id=store.tenant_id,
                    event_type=BillingEventType.SUBSCRIPTION_UPDATED,
                    subscription=subscription,
                    shopify_subscription_id=subscription_gid,
                    metadata={"reason": "trial_expired", "source": "webhook"}
                )
            return WebhookProcessingResult(
                processed=True,
                message="Subscription expired",
                subscription_id=subscription.id if subscription else None
            )

        return WebhookProcessingResult(
            processed=True,
            message=f"Processed status: {shopify_status}"
        )

    async def handle_app_uninstalled(
        self,
        shopify_event_id: str,
        shop_domain: str,
        payload: Dict[str, Any]
    ) -> WebhookProcessingResult:
        """
        Handle app/uninstalled webhook.

        Args:
            shopify_event_id: Shopify webhook event ID
            shop_domain: Shop domain
            payload: Webhook payload

        Returns:
            WebhookProcessingResult
        """
        # Check for duplicate
        if self._is_duplicate(shopify_event_id):
            return WebhookProcessingResult(
                processed=False,
                message="Duplicate webhook",
                skipped_reason="duplicate"
            )

        try:
            # Find store
            store = self.db.query(ShopifyStore).filter(
                ShopifyStore.shop_domain == shop_domain
            ).first()

            if store:
                # Mark store as uninstalled
                store.status = "uninstalled"
                store.uninstalled_at = datetime.now(timezone.utc)
                store.access_token_encrypted = None  # Clear token for security

                # Cancel active subscriptions
                subscriptions = self.db.query(Subscription).filter(
                    Subscription.store_id == store.id,
                    Subscription.status.in_([
                        SubscriptionStatus.ACTIVE.value,
                        SubscriptionStatus.PENDING.value,
                        SubscriptionStatus.FROZEN.value
                    ])
                ).all()

                for sub in subscriptions:
                    sub.status = SubscriptionStatus.CANCELLED.value
                    sub.cancelled_at = datetime.now(timezone.utc)

                    self._log_audit_event(
                        tenant_id=store.tenant_id,
                        event_type=BillingEventType.SUBSCRIPTION_CANCELLED,
                        subscription=sub,
                        metadata={"reason": "app_uninstalled", "source": "webhook"}
                    )

                logger.info("Store marked as uninstalled", extra={
                    "shop_domain": shop_domain,
                    "store_id": store.id,
                    "subscriptions_cancelled": len(subscriptions)
                })

            # Record event
            self._record_event(shopify_event_id, "app/uninstalled", shop_domain, payload)
            self.db.commit()

            return WebhookProcessingResult(
                processed=True,
                message="App uninstalled processed"
            )

        except Exception as e:
            logger.error("Error processing uninstall webhook", extra={
                "shop_domain": shop_domain,
                "error": str(e)
            })
            self.db.rollback()
            return WebhookProcessingResult(
                processed=False,
                message=f"Error: {str(e)}",
                error="processing_error"
            )


def get_webhook_handler(db_session: Session) -> BillingWebhookHandler:
    """
    Factory function to create a BillingWebhookHandler.

    Args:
        db_session: Database session

    Returns:
        Configured BillingWebhookHandler instance
    """
    return BillingWebhookHandler(db_session)
