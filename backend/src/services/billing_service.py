"""
Billing service for managing Shopify subscriptions.

Orchestrates:
- Subscription creation via Shopify Billing API
- Subscription state persistence
- Webhook event processing
- Entitlement management based on subscription status
"""

import logging
import uuid
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.integrations.shopify.billing_client import (
    ShopifyBillingClient,
    ShopifyPlanConfig,
    ShopifyBillingError,
)
from src.models.subscription import Subscription, SubscriptionStatus
from src.models.billing_event import BillingEvent, BillingEventType
from src.models.plan import Plan
from src.models.store import ShopifyStore

logger = logging.getLogger(__name__)


@dataclass
class CheckoutResult:
    """Result of creating a checkout URL."""
    checkout_url: str
    subscription_id: str
    plan_id: str


@dataclass
class SubscriptionInfo:
    """Subscription information for API responses."""
    id: str
    tenant_id: str
    plan_id: str
    plan_name: str
    status: str
    shopify_subscription_id: Optional[str]
    current_period_end: Optional[datetime]
    cancelled_at: Optional[datetime]
    created_at: datetime


class BillingServiceError(Exception):
    """Error from billing service operations."""
    pass


class BillingService:
    """
    Service for managing Shopify billing operations.

    SECURITY: tenant_id is ALWAYS from JWT, never from request.
    All operations are scoped by tenant_id.
    """

    def __init__(self, db_session: Session, tenant_id: str):
        """
        Initialize billing service with tenant scope.

        Args:
            db_session: SQLAlchemy database session
            tenant_id: Tenant identifier (from JWT only)

        Raises:
            ValueError: If tenant_id is empty
        """
        if not tenant_id:
            raise ValueError("tenant_id is required and cannot be empty")

        self.db_session = db_session
        self.tenant_id = tenant_id

    async def create_checkout_url(
        self,
        plan_id: str,
        return_url: str,
        shop_domain: str,
        access_token: str,
    ) -> CheckoutResult:
        """
        Create a Shopify checkout URL for subscription.

        Args:
            plan_id: Internal plan ID to subscribe to
            return_url: URL to redirect after checkout
            shop_domain: Shopify shop domain
            access_token: Shop's Shopify access token

        Returns:
            CheckoutResult with checkout URL

        Raises:
            BillingServiceError: If plan not found or checkout creation fails
        """
        # Get plan details
        plan = self.db_session.query(Plan).filter(
            Plan.id == plan_id,
            Plan.is_active == True,
        ).first()

        if not plan:
            logger.warning("Plan not found for checkout", extra={
                "tenant_id": self.tenant_id,
                "plan_id": plan_id,
            })
            raise BillingServiceError(f"Plan not found: {plan_id}")

        # Check for existing active subscription
        existing = self.db_session.query(Subscription).filter(
            Subscription.tenant_id == self.tenant_id,
            Subscription.status == SubscriptionStatus.ACTIVE.value,
        ).first()

        if existing:
            logger.warning("Tenant already has active subscription", extra={
                "tenant_id": self.tenant_id,
                "existing_subscription_id": existing.id,
            })
            raise BillingServiceError("Active subscription already exists")

        # Create Shopify billing client
        async with ShopifyBillingClient(shop_domain, access_token) as client:
            # Configure plan for Shopify
            # Use test mode based on environment
            import os
            is_test_mode = os.getenv("SHOPIFY_BILLING_TEST_MODE", "false").lower() == "true"

            shopify_plan = ShopifyPlanConfig(
                name=plan.display_name,
                price=plan.price_monthly_cents / 100 if plan.price_monthly_cents else 0,
                interval="EVERY_30_DAYS",
                trial_days=0,
                test=is_test_mode,  # Enable via SHOPIFY_BILLING_TEST_MODE=true
            )

            try:
                # Create subscription in Shopify
                result = await client.create_subscription(shopify_plan, return_url)

                # Create pending subscription record
                subscription = Subscription(
                    id=str(uuid.uuid4()),
                    tenant_id=self.tenant_id,
                    plan_id=plan_id,
                    shopify_subscription_id=result.subscription_id,
                    status=SubscriptionStatus.TRIALING.value,  # Pending approval
                    current_period_end=result.current_period_end,
                )

                self.db_session.add(subscription)

                # Record billing event
                event = BillingEvent(
                    id=str(uuid.uuid4()),
                    tenant_id=self.tenant_id,
                    event_type=BillingEventType.SUBSCRIPTION_CREATED.value,
                    subscription_id=subscription.id,
                    to_plan_id=plan_id,
                    shopify_subscription_id=result.subscription_id,
                    extra_metadata={
                        "checkout_url": result.confirmation_url,
                        "shop_domain": shop_domain,
                    },
                )
                self.db_session.add(event)

                self.db_session.commit()

                logger.info("Checkout URL created", extra={
                    "tenant_id": self.tenant_id,
                    "subscription_id": subscription.id,
                    "plan_id": plan_id,
                })

                return CheckoutResult(
                    checkout_url=result.confirmation_url,
                    subscription_id=subscription.id,
                    plan_id=plan_id,
                )

            except ShopifyBillingError as e:
                self.db_session.rollback()
                logger.error("Shopify checkout creation failed", extra={
                    "tenant_id": self.tenant_id,
                    "plan_id": plan_id,
                    "error": str(e),
                })
                raise BillingServiceError(f"Checkout creation failed: {str(e)}")

    def get_subscription(self) -> Optional[SubscriptionInfo]:
        """
        Get the current active subscription for the tenant.

        Returns:
            SubscriptionInfo or None if no active subscription
        """
        subscription = self.db_session.query(Subscription).filter(
            Subscription.tenant_id == self.tenant_id,
            Subscription.status.in_([
                SubscriptionStatus.ACTIVE.value,
                SubscriptionStatus.TRIALING.value,
            ]),
        ).first()

        if not subscription:
            return None

        plan = self.db_session.query(Plan).filter(Plan.id == subscription.plan_id).first()

        return SubscriptionInfo(
            id=subscription.id,
            tenant_id=subscription.tenant_id,
            plan_id=subscription.plan_id,
            plan_name=plan.display_name if plan else "Unknown",
            status=subscription.status,
            shopify_subscription_id=subscription.shopify_subscription_id,
            current_period_end=subscription.current_period_end,
            cancelled_at=subscription.cancelled_at,
            created_at=subscription.created_at,
        )

    def get_all_subscriptions(self) -> list[SubscriptionInfo]:
        """
        Get all subscriptions for the tenant (including cancelled).

        Returns:
            List of SubscriptionInfo
        """
        subscriptions = self.db_session.query(Subscription).filter(
            Subscription.tenant_id == self.tenant_id,
        ).order_by(Subscription.created_at.desc()).all()

        results = []
        for sub in subscriptions:
            plan = self.db_session.query(Plan).filter(Plan.id == sub.plan_id).first()
            results.append(SubscriptionInfo(
                id=sub.id,
                tenant_id=sub.tenant_id,
                plan_id=sub.plan_id,
                plan_name=plan.display_name if plan else "Unknown",
                status=sub.status,
                shopify_subscription_id=sub.shopify_subscription_id,
                current_period_end=sub.current_period_end,
                cancelled_at=sub.cancelled_at,
                created_at=sub.created_at,
            ))

        return results

    def handle_subscription_activated(
        self,
        shopify_subscription_id: str,
        current_period_end: Optional[datetime] = None,
    ) -> Optional[Subscription]:
        """
        Handle subscription activation (from webhook).

        Args:
            shopify_subscription_id: Shopify subscription GID
            current_period_end: End of current billing period

        Returns:
            Updated subscription or None if not found
        """
        subscription = self.db_session.query(Subscription).filter(
            Subscription.tenant_id == self.tenant_id,
            Subscription.shopify_subscription_id == shopify_subscription_id,
        ).first()

        if not subscription:
            logger.warning("Subscription not found for activation", extra={
                "tenant_id": self.tenant_id,
                "shopify_subscription_id": shopify_subscription_id,
            })
            return None

        old_status = subscription.status
        subscription.status = SubscriptionStatus.ACTIVE.value
        if current_period_end:
            subscription.current_period_end = current_period_end

        # Record event
        event = BillingEvent(
            id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            event_type=BillingEventType.SUBSCRIPTION_UPDATED.value,
            subscription_id=subscription.id,
            shopify_subscription_id=shopify_subscription_id,
            extra_metadata={
                "old_status": old_status,
                "new_status": SubscriptionStatus.ACTIVE.value,
            },
        )
        self.db_session.add(event)
        self.db_session.commit()

        logger.info("Subscription activated", extra={
            "tenant_id": self.tenant_id,
            "subscription_id": subscription.id,
            "shopify_subscription_id": shopify_subscription_id,
        })

        return subscription

    def handle_subscription_cancelled(
        self,
        shopify_subscription_id: str,
    ) -> Optional[Subscription]:
        """
        Handle subscription cancellation (from webhook).

        Downgrades entitlements immediately.

        Args:
            shopify_subscription_id: Shopify subscription GID

        Returns:
            Updated subscription or None if not found
        """
        subscription = self.db_session.query(Subscription).filter(
            Subscription.tenant_id == self.tenant_id,
            Subscription.shopify_subscription_id == shopify_subscription_id,
        ).first()

        if not subscription:
            logger.warning("Subscription not found for cancellation", extra={
                "tenant_id": self.tenant_id,
                "shopify_subscription_id": shopify_subscription_id,
            })
            return None

        old_status = subscription.status
        subscription.status = SubscriptionStatus.CANCELLED.value
        subscription.cancelled_at = datetime.now(timezone.utc)

        # Record event
        event = BillingEvent(
            id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            event_type=BillingEventType.SUBSCRIPTION_CANCELLED.value,
            subscription_id=subscription.id,
            shopify_subscription_id=shopify_subscription_id,
            extra_metadata={
                "old_status": old_status,
            },
        )
        self.db_session.add(event)
        self.db_session.commit()

        logger.info("Subscription cancelled", extra={
            "tenant_id": self.tenant_id,
            "subscription_id": subscription.id,
            "shopify_subscription_id": shopify_subscription_id,
        })

        # Downgrade entitlements
        self._downgrade_entitlements()

        return subscription

    def handle_payment_failed(
        self,
        shopify_subscription_id: str,
    ) -> Optional[Subscription]:
        """
        Handle failed payment (from webhook).

        Downgrades access after payment failure.

        Args:
            shopify_subscription_id: Shopify subscription GID

        Returns:
            Updated subscription or None if not found
        """
        subscription = self.db_session.query(Subscription).filter(
            Subscription.tenant_id == self.tenant_id,
            Subscription.shopify_subscription_id == shopify_subscription_id,
        ).first()

        if not subscription:
            return None

        # Record failed payment event
        event = BillingEvent(
            id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            event_type=BillingEventType.CHARGE_FAILED.value,
            subscription_id=subscription.id,
            shopify_subscription_id=shopify_subscription_id,
        )
        self.db_session.add(event)

        # Mark subscription as expired
        subscription.status = SubscriptionStatus.EXPIRED.value
        self.db_session.commit()

        logger.warning("Payment failed, subscription expired", extra={
            "tenant_id": self.tenant_id,
            "subscription_id": subscription.id,
        })

        # Downgrade entitlements
        self._downgrade_entitlements()

        return subscription

    def _downgrade_entitlements(self) -> None:
        """
        Downgrade tenant entitlements to free tier.

        Called when subscription is cancelled or payment fails.
        """
        logger.info("Downgrading entitlements to free tier", extra={
            "tenant_id": self.tenant_id,
        })
        # Entitlement enforcement is typically done at access time
        # by checking subscription status. This method is a hook
        # for any immediate cleanup needed.
        pass

    def check_entitlement(self, feature_key: str) -> bool:
        """
        Check if tenant has entitlement to a feature.

        Args:
            feature_key: Feature identifier to check

        Returns:
            True if tenant has access to the feature
        """
        subscription = self.get_subscription()

        if not subscription:
            # No active subscription - check free tier
            return self._check_free_tier_feature(feature_key)

        # Check plan features
        from src.models.plan import PlanFeature
        feature = self.db_session.query(PlanFeature).filter(
            PlanFeature.plan_id == subscription.plan_id,
            PlanFeature.feature_key == feature_key,
            PlanFeature.is_enabled == True,
        ).first()

        return feature is not None

    def _check_free_tier_feature(self, feature_key: str) -> bool:
        """Check if feature is available in free tier."""
        from src.models.plan import PlanFeature
        free_plan = self.db_session.query(Plan).filter(
            Plan.name == "free",
            Plan.is_active == True,
        ).first()

        if not free_plan:
            return False

        feature = self.db_session.query(PlanFeature).filter(
            PlanFeature.plan_id == free_plan.id,
            PlanFeature.feature_key == feature_key,
            PlanFeature.is_enabled == True,
        ).first()

        return feature is not None


class WebhookProcessor:
    """
    Processor for Shopify billing webhooks.

    Handles webhook events and updates subscription state.
    """

    def __init__(self, db_session: Session):
        """Initialize webhook processor."""
        self.db_session = db_session

    def process_webhook(
        self,
        topic: str,
        shop_domain: str,
        payload: Dict[str, Any],
    ) -> bool:
        """
        Process a Shopify billing webhook.

        Args:
            topic: Webhook topic (e.g., 'app_subscriptions/update')
            shop_domain: Shop domain that triggered the webhook
            payload: Webhook payload

        Returns:
            True if processed successfully
        """
        logger.info("Processing Shopify webhook", extra={
            "topic": topic,
            "shop_domain": shop_domain,
        })

        # Find tenant by shop domain
        store = self.db_session.query(ShopifyStore).filter(
            ShopifyStore.shop_domain == shop_domain,
        ).first()

        if not store:
            logger.warning("Store not found for webhook", extra={
                "shop_domain": shop_domain,
                "topic": topic,
            })
            return False

        tenant_id = store.tenant_id
        billing_service = BillingService(self.db_session, tenant_id)

        # Route to appropriate handler
        if topic == "app_subscriptions/update":
            return self._handle_subscription_update(billing_service, payload)
        elif topic == "subscription_billing_attempts/success":
            return self._handle_billing_success(billing_service, payload)
        elif topic == "subscription_billing_attempts/failure":
            return self._handle_billing_failure(billing_service, payload)
        else:
            logger.warning("Unhandled webhook topic", extra={"topic": topic})
            return False

    def _handle_subscription_update(
        self,
        billing_service: BillingService,
        payload: Dict[str, Any],
    ) -> bool:
        """Handle app_subscriptions/update webhook."""
        subscription_id = payload.get("app_subscription", {}).get("admin_graphql_api_id")
        status = payload.get("app_subscription", {}).get("status")

        if not subscription_id:
            return False

        if status == "ACTIVE":
            billing_service.handle_subscription_activated(subscription_id)
        elif status == "CANCELLED":
            billing_service.handle_subscription_cancelled(subscription_id)

        return True

    def _handle_billing_success(
        self,
        billing_service: BillingService,
        payload: Dict[str, Any],
    ) -> bool:
        """Handle successful billing attempt."""
        subscription_id = payload.get("subscription_contract", {}).get("admin_graphql_api_id")
        if subscription_id:
            billing_service.handle_subscription_activated(subscription_id)
        return True

    def _handle_billing_failure(
        self,
        billing_service: BillingService,
        payload: Dict[str, Any],
    ) -> bool:
        """Handle failed billing attempt."""
        subscription_id = payload.get("subscription_contract", {}).get("admin_graphql_api_id")
        if subscription_id:
            billing_service.handle_payment_failed(subscription_id)
        return True
