"""
Billing service for managing Shopify subscriptions.

Orchestrates:
- Checkout URL creation
- Subscription storage
- Status updates
- Entitlement enforcement

CRITICAL: All operations are tenant-scoped via tenant_id from JWT.
"""

import os
import uuid
import logging
from typing import Optional
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.integrations.shopify.billing_client import (
    ShopifyBillingClient,
    BillingInterval,
    ShopifyAPIError,
    get_billing_client
)
from src.models.subscription import Subscription, SubscriptionStatus
from src.models.plan import Plan
from src.models.store import ShopifyStore
from src.models.billing_event import BillingEvent, BillingEventType

logger = logging.getLogger(__name__)

# Default free plan ID
FREE_PLAN_ID = "plan_free"

# Grace period for failed payments (days)
PAYMENT_GRACE_PERIOD_DAYS = 3


@dataclass
class CheckoutResult:
    """Result of creating a checkout URL."""
    checkout_url: str
    subscription_id: str
    shopify_subscription_id: Optional[str] = None
    success: bool = True
    error: Optional[str] = None


@dataclass
class SubscriptionInfo:
    """Current subscription information for a tenant."""
    subscription_id: Optional[str]
    plan_id: str
    plan_name: str
    status: str
    is_active: bool
    current_period_end: Optional[datetime]
    trial_end: Optional[datetime]
    can_access_features: bool
    downgraded_reason: Optional[str] = None


class BillingServiceError(Exception):
    """Base exception for billing service errors."""
    pass


class PlanNotFoundError(BillingServiceError):
    """Requested plan does not exist."""
    pass


class StoreNotFoundError(BillingServiceError):
    """Store not found for tenant."""
    pass


class SubscriptionError(BillingServiceError):
    """Error creating or updating subscription."""
    pass


class BillingService:
    """
    Service for managing Shopify billing operations.

    All methods require tenant_id from JWT context.
    """

    def __init__(self, db_session: Session, tenant_id: str):
        """
        Initialize billing service.

        Args:
            db_session: Database session
            tenant_id: Tenant ID from JWT (org_id)
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id

    def _get_store(self) -> ShopifyStore:
        """Get the Shopify store for current tenant."""
        store = self.db.query(ShopifyStore).filter(
            ShopifyStore.tenant_id == self.tenant_id,
            ShopifyStore.status == "active"
        ).first()

        if not store:
            raise StoreNotFoundError(f"No active store found for tenant {self.tenant_id}")

        return store

    def _get_plan(self, plan_id: str) -> Plan:
        """Get plan by ID."""
        plan = self.db.query(Plan).filter(
            Plan.id == plan_id,
            Plan.is_active == True
        ).first()

        if not plan:
            raise PlanNotFoundError(f"Plan not found or inactive: {plan_id}")

        return plan

    def _get_active_subscription(self) -> Optional[Subscription]:
        """Get active subscription for tenant."""
        return self.db.query(Subscription).filter(
            Subscription.tenant_id == self.tenant_id,
            Subscription.status.in_([
                SubscriptionStatus.ACTIVE.value,
                SubscriptionStatus.PENDING.value,
                SubscriptionStatus.FROZEN.value
            ])
        ).first()

    def _decrypt_access_token(self, encrypted_token: str) -> str:
        """
        Decrypt the Shopify access token.

        TODO: Implement proper encryption using a key management service.
        For now, returns token as-is (assumes token storage handles encryption).
        """
        # SECURITY: Use ENCRYPTION_KEY env var in Render for proper encryption
        # This is a placeholder - the actual implementation should decrypt the token
        return encrypted_token

    def _log_billing_event(
        self,
        event_type: str,
        store_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        from_plan_id: Optional[str] = None,
        to_plan_id: Optional[str] = None,
        amount_cents: Optional[int] = None,
        shopify_subscription_id: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> BillingEvent:
        """Log a billing event (append-only audit log)."""
        event = BillingEvent(
            id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            event_type=event_type,
            store_id=store_id,
            subscription_id=subscription_id,
            from_plan_id=from_plan_id,
            to_plan_id=to_plan_id,
            amount_cents=amount_cents,
            shopify_subscription_id=shopify_subscription_id,
            extra_metadata=metadata
        )
        self.db.add(event)
        return event

    async def create_checkout_url(
        self,
        plan_id: str,
        return_url: Optional[str] = None,
        test_mode: bool = False
    ) -> CheckoutResult:
        """
        Create a Shopify Billing checkout URL for a plan.

        This creates a pending subscription and returns a URL
        where the merchant can approve the charge.

        Args:
            plan_id: Plan ID to subscribe to
            return_url: URL to redirect after approval (optional)
            test_mode: If True, creates a test charge (no real money)

        Returns:
            CheckoutResult with checkout URL

        Raises:
            PlanNotFoundError: If plan doesn't exist
            StoreNotFoundError: If store not found for tenant
            SubscriptionError: If subscription creation fails
        """
        # Get store and plan
        store = self._get_store()
        plan = self._get_plan(plan_id)

        # Check for existing active subscription
        existing_sub = self._get_active_subscription()
        if existing_sub and existing_sub.status == SubscriptionStatus.ACTIVE.value:
            # Already has active subscription - Shopify will replace it
            logger.info("Replacing existing subscription", extra={
                "tenant_id": self.tenant_id,
                "existing_plan_id": existing_sub.plan_id,
                "new_plan_id": plan_id
            })

        # Determine billing interval based on plan
        interval = BillingInterval.EVERY_30_DAYS
        price_cents = plan.price_monthly_cents

        if not price_cents:
            # Free plan - no checkout needed
            return await self._activate_free_plan(store, plan)

        price_amount = price_cents / 100.0

        # Build return URL
        if not return_url:
            app_url = os.getenv("APP_URL", f"https://{store.shop_domain}")
            return_url = f"{app_url}/billing/callback?shop={store.shop_domain}"

        # Decrypt access token
        if not store.access_token_encrypted:
            raise SubscriptionError("Store has no access token")

        access_token = self._decrypt_access_token(store.access_token_encrypted)

        # Determine if test mode
        is_test = test_mode or os.getenv("SHOPIFY_BILLING_TEST_MODE", "false").lower() == "true"

        try:
            async with get_billing_client(store.shop_domain, access_token) as client:
                result = await client.create_subscription(
                    name=f"AI Growth Analytics - {plan.display_name}",
                    price_amount=price_amount,
                    currency_code=store.currency or "USD",
                    interval=interval,
                    return_url=return_url,
                    trial_days=0,  # Configure trial in plan if needed
                    test=is_test,
                    replacement_behavior="APPLY_IMMEDIATELY"
                )

                if not result.success:
                    error_msg = "; ".join([e.get("message", str(e)) for e in result.user_errors])
                    logger.error("Shopify subscription creation failed", extra={
                        "tenant_id": self.tenant_id,
                        "plan_id": plan_id,
                        "errors": result.user_errors
                    })
                    raise SubscriptionError(f"Shopify error: {error_msg}")

                # Create pending subscription record
                shopify_sub_id = result.app_subscription.id if result.app_subscription else None
                subscription = self._create_or_update_subscription(
                    store=store,
                    plan=plan,
                    status=SubscriptionStatus.PENDING,
                    shopify_subscription_id=shopify_sub_id
                )

                # Log billing event
                self._log_billing_event(
                    event_type=BillingEventType.SUBSCRIPTION_CREATED.value,
                    store_id=store.id,
                    subscription_id=subscription.id,
                    to_plan_id=plan_id,
                    amount_cents=price_cents,
                    shopify_subscription_id=shopify_sub_id,
                    metadata={"test_mode": is_test}
                )

                self.db.commit()

                logger.info("Checkout URL created", extra={
                    "tenant_id": self.tenant_id,
                    "plan_id": plan_id,
                    "subscription_id": subscription.id,
                    "shopify_subscription_id": shopify_sub_id
                })

                return CheckoutResult(
                    checkout_url=result.confirmation_url,
                    subscription_id=subscription.id,
                    shopify_subscription_id=shopify_sub_id,
                    success=True
                )

        except ShopifyAPIError as e:
            logger.error("Shopify API error during checkout", extra={
                "tenant_id": self.tenant_id,
                "plan_id": plan_id,
                "error": str(e)
            })
            raise SubscriptionError(f"Failed to create checkout: {e}")

    async def _activate_free_plan(self, store: ShopifyStore, plan: Plan) -> CheckoutResult:
        """Activate a free plan without Shopify checkout."""
        subscription = self._create_or_update_subscription(
            store=store,
            plan=plan,
            status=SubscriptionStatus.ACTIVE,
            shopify_subscription_id=None
        )

        self._log_billing_event(
            event_type=BillingEventType.SUBSCRIPTION_CREATED.value,
            store_id=store.id,
            subscription_id=subscription.id,
            to_plan_id=plan.id,
            amount_cents=0,
            metadata={"free_plan": True}
        )

        self.db.commit()

        return CheckoutResult(
            checkout_url="",  # No checkout needed for free plan
            subscription_id=subscription.id,
            success=True
        )

    def _create_or_update_subscription(
        self,
        store: ShopifyStore,
        plan: Plan,
        status: SubscriptionStatus,
        shopify_subscription_id: Optional[str] = None,
        current_period_end: Optional[datetime] = None
    ) -> Subscription:
        """Create or update subscription record."""
        # Check for existing subscription
        existing = self.db.query(Subscription).filter(
            Subscription.tenant_id == self.tenant_id,
            Subscription.store_id == store.id
        ).first()

        now = datetime.now(timezone.utc)

        if existing:
            # Update existing
            existing.plan_id = plan.id
            existing.status = status.value
            existing.shopify_subscription_id = shopify_subscription_id or existing.shopify_subscription_id
            existing.current_period_start = now
            existing.current_period_end = current_period_end
            return existing
        else:
            # Create new
            subscription = Subscription(
                id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                store_id=store.id,
                plan_id=plan.id,
                status=status.value,
                shopify_subscription_id=shopify_subscription_id,
                current_period_start=now,
                current_period_end=current_period_end
            )
            self.db.add(subscription)
            return subscription

    def activate_subscription(
        self,
        shopify_subscription_id: str,
        current_period_end: Optional[datetime] = None
    ) -> Optional[Subscription]:
        """
        Activate a pending subscription after merchant approval.

        Called by webhook handler when subscription is approved.

        Args:
            shopify_subscription_id: Shopify subscription GID
            current_period_end: When the current billing period ends

        Returns:
            Updated Subscription or None if not found
        """
        subscription = self.db.query(Subscription).filter(
            Subscription.tenant_id == self.tenant_id,
            Subscription.shopify_subscription_id == shopify_subscription_id
        ).first()

        if not subscription:
            logger.warning("Subscription not found for activation", extra={
                "tenant_id": self.tenant_id,
                "shopify_subscription_id": shopify_subscription_id
            })
            return None

        old_status = subscription.status
        subscription.status = SubscriptionStatus.ACTIVE.value
        subscription.current_period_end = current_period_end

        self._log_billing_event(
            event_type=BillingEventType.SUBSCRIPTION_UPDATED.value,
            store_id=subscription.store_id,
            subscription_id=subscription.id,
            shopify_subscription_id=shopify_subscription_id,
            metadata={
                "old_status": old_status,
                "new_status": SubscriptionStatus.ACTIVE.value,
                "action": "activated"
            }
        )

        self.db.commit()

        logger.info("Subscription activated", extra={
            "tenant_id": self.tenant_id,
            "subscription_id": subscription.id,
            "shopify_subscription_id": shopify_subscription_id
        })

        return subscription

    def cancel_subscription(
        self,
        shopify_subscription_id: str,
        cancelled_at: Optional[datetime] = None
    ) -> Optional[Subscription]:
        """
        Cancel a subscription.

        Called by webhook handler when subscription is cancelled.
        This triggers downgrade to free plan.

        Args:
            shopify_subscription_id: Shopify subscription GID
            cancelled_at: When the cancellation occurred

        Returns:
            Updated Subscription or None if not found
        """
        subscription = self.db.query(Subscription).filter(
            Subscription.tenant_id == self.tenant_id,
            Subscription.shopify_subscription_id == shopify_subscription_id
        ).first()

        if not subscription:
            logger.warning("Subscription not found for cancellation", extra={
                "tenant_id": self.tenant_id,
                "shopify_subscription_id": shopify_subscription_id
            })
            return None

        old_status = subscription.status
        old_plan_id = subscription.plan_id

        subscription.status = SubscriptionStatus.CANCELLED.value
        subscription.cancelled_at = cancelled_at or datetime.now(timezone.utc)

        self._log_billing_event(
            event_type=BillingEventType.SUBSCRIPTION_CANCELLED.value,
            store_id=subscription.store_id,
            subscription_id=subscription.id,
            from_plan_id=old_plan_id,
            shopify_subscription_id=shopify_subscription_id,
            metadata={
                "old_status": old_status,
                "cancelled_at": subscription.cancelled_at.isoformat()
            }
        )

        self.db.commit()

        logger.info("Subscription cancelled", extra={
            "tenant_id": self.tenant_id,
            "subscription_id": subscription.id,
            "shopify_subscription_id": shopify_subscription_id
        })

        return subscription

    def freeze_subscription(
        self,
        shopify_subscription_id: str,
        reason: str = "payment_failed"
    ) -> Optional[Subscription]:
        """
        Freeze subscription due to payment failure.

        Subscription enters grace period where access is maintained
        but limited. After grace period, access is revoked.

        Args:
            shopify_subscription_id: Shopify subscription GID
            reason: Reason for freezing

        Returns:
            Updated Subscription or None if not found
        """
        subscription = self.db.query(Subscription).filter(
            Subscription.tenant_id == self.tenant_id,
            Subscription.shopify_subscription_id == shopify_subscription_id
        ).first()

        if not subscription:
            return None

        old_status = subscription.status
        subscription.status = SubscriptionStatus.FROZEN.value
        subscription.grace_period_ends_on = datetime.now(timezone.utc) + timedelta(days=PAYMENT_GRACE_PERIOD_DAYS)

        self._log_billing_event(
            event_type=BillingEventType.CHARGE_FAILED.value,
            store_id=subscription.store_id,
            subscription_id=subscription.id,
            shopify_subscription_id=shopify_subscription_id,
            metadata={
                "old_status": old_status,
                "reason": reason,
                "grace_period_ends_on": subscription.grace_period_ends_on.isoformat()
            }
        )

        self.db.commit()

        logger.warning("Subscription frozen due to payment failure", extra={
            "tenant_id": self.tenant_id,
            "subscription_id": subscription.id,
            "grace_period_ends_on": subscription.grace_period_ends_on.isoformat()
        })

        return subscription

    def get_subscription_info(self) -> SubscriptionInfo:
        """
        Get current subscription information for tenant.

        Used for entitlement checks and displaying subscription status.

        Returns:
            SubscriptionInfo with current status and access permissions
        """
        # First check for active subscription
        subscription = self._get_active_subscription()

        # If no active subscription, check for recently cancelled/declined/expired
        if not subscription:
            subscription = self.db.query(Subscription).filter(
                Subscription.tenant_id == self.tenant_id,
                Subscription.status.in_([
                    SubscriptionStatus.CANCELLED.value,
                    SubscriptionStatus.DECLINED.value,
                    SubscriptionStatus.EXPIRED.value
                ])
            ).order_by(Subscription.cancelled_at.desc().nullslast()).first()

        if not subscription:
            # No subscription at all - default to free plan
            free_plan = self.db.query(Plan).filter(Plan.id == FREE_PLAN_ID).first()
            return SubscriptionInfo(
                subscription_id=None,
                plan_id=FREE_PLAN_ID,
                plan_name=free_plan.display_name if free_plan else "Free",
                status="none",
                is_active=False,
                current_period_end=None,
                trial_end=None,
                can_access_features=True,  # Free tier always accessible
                downgraded_reason="No active subscription"
            )

        plan = self.db.query(Plan).filter(Plan.id == subscription.plan_id).first()

        # Determine access permissions
        can_access = True
        downgraded_reason = None

        if subscription.status == SubscriptionStatus.CANCELLED.value:
            can_access = False
            downgraded_reason = "Subscription cancelled"
        elif subscription.status == SubscriptionStatus.FROZEN.value:
            # Check if grace period has expired
            if subscription.grace_period_ends_on and datetime.now(timezone.utc) > subscription.grace_period_ends_on:
                can_access = False
                downgraded_reason = "Payment failed - grace period expired"
            else:
                can_access = True  # Still in grace period
                downgraded_reason = "Payment failed - in grace period"
        elif subscription.status == SubscriptionStatus.DECLINED.value:
            can_access = False
            downgraded_reason = "Subscription declined"
        elif subscription.status == SubscriptionStatus.EXPIRED.value:
            can_access = False
            downgraded_reason = "Trial expired"

        return SubscriptionInfo(
            subscription_id=subscription.id,
            plan_id=subscription.plan_id,
            plan_name=plan.display_name if plan else "Unknown",
            status=subscription.status,
            is_active=subscription.status == SubscriptionStatus.ACTIVE.value,
            current_period_end=subscription.current_period_end,
            trial_end=subscription.trial_end,
            can_access_features=can_access,
            downgraded_reason=downgraded_reason
        )

    def sync_with_shopify(self, shopify_subscription_id: str, shopify_status: str) -> Optional[Subscription]:
        """
        Sync local subscription status with Shopify.

        Used by reconciliation job to ensure consistency.

        Args:
            shopify_subscription_id: Shopify subscription GID
            shopify_status: Status from Shopify API

        Returns:
            Updated Subscription or None if not found
        """
        subscription = self.db.query(Subscription).filter(
            Subscription.shopify_subscription_id == shopify_subscription_id
        ).first()

        if not subscription:
            return None

        # Map Shopify status to our status
        status_map = {
            "ACTIVE": SubscriptionStatus.ACTIVE,
            "PENDING": SubscriptionStatus.PENDING,
            "FROZEN": SubscriptionStatus.FROZEN,
            "CANCELLED": SubscriptionStatus.CANCELLED,
            "DECLINED": SubscriptionStatus.DECLINED,
            "EXPIRED": SubscriptionStatus.EXPIRED
        }

        new_status = status_map.get(shopify_status.upper())
        if not new_status:
            logger.warning("Unknown Shopify status", extra={
                "shopify_status": shopify_status,
                "shopify_subscription_id": shopify_subscription_id
            })
            return subscription

        if subscription.status != new_status.value:
            old_status = subscription.status
            subscription.status = new_status.value

            self._log_billing_event(
                event_type=BillingEventType.SUBSCRIPTION_UPDATED.value,
                store_id=subscription.store_id,
                subscription_id=subscription.id,
                shopify_subscription_id=shopify_subscription_id,
                metadata={
                    "old_status": old_status,
                    "new_status": new_status.value,
                    "source": "reconciliation"
                }
            )

            self.db.commit()

            logger.info("Subscription synced with Shopify", extra={
                "tenant_id": subscription.tenant_id,
                "subscription_id": subscription.id,
                "old_status": old_status,
                "new_status": new_status.value
            })

        return subscription

    async def upgrade_subscription(
        self,
        new_plan_id: str,
        timing: str = "immediate",
        return_url: Optional[str] = None,
        test_mode: bool = False
    ) -> CheckoutResult:
        """
        Upgrade to a higher-tier plan.

        Creates a new Shopify subscription that replaces the current one.
        For immediate upgrades, proration is handled by Shopify.

        Args:
            new_plan_id: Target plan ID (must be higher tier)
            timing: 'immediate' or 'next_cycle'
            return_url: URL to redirect after checkout
            test_mode: If True, creates test charge

        Returns:
            CheckoutResult with checkout URL

        Raises:
            PlanNotFoundError: If plan doesn't exist
            SubscriptionError: If not a valid upgrade
        """
        current_sub = self._get_active_subscription()
        if not current_sub:
            raise SubscriptionError("No active subscription to upgrade")

        current_plan = self._get_plan(current_sub.plan_id)
        new_plan = self._get_plan(new_plan_id)

        # Validate upgrade (new plan must have higher price)
        current_price = current_plan.price_monthly_cents or 0
        new_price = new_plan.price_monthly_cents or 0

        if new_price <= current_price:
            raise SubscriptionError(
                f"Cannot upgrade: {new_plan.display_name} (${new_price/100}) is not higher than "
                f"{current_plan.display_name} (${current_price/100})"
            )

        # Log the upgrade intent
        self._log_billing_event(
            event_type=BillingEventType.PLAN_CHANGED.value,
            store_id=current_sub.store_id,
            subscription_id=current_sub.id,
            from_plan_id=current_plan.id,
            to_plan_id=new_plan.id,
            metadata={
                "action": "upgrade_initiated",
                "timing": timing,
                "from_price_cents": current_price,
                "to_price_cents": new_price
            }
        )

        # Create new subscription (replaces existing)
        return await self.create_checkout_url(
            plan_id=new_plan_id,
            return_url=return_url,
            test_mode=test_mode
        )

    async def downgrade_subscription(
        self,
        new_plan_id: str,
        return_url: Optional[str] = None,
        test_mode: bool = False
    ) -> CheckoutResult:
        """
        Downgrade to a lower-tier plan.

        Downgrades always take effect at the end of the current billing period.
        No proration or refund is provided by default.

        Args:
            new_plan_id: Target plan ID (must be lower tier)
            return_url: URL to redirect after checkout
            test_mode: If True, creates test charge

        Returns:
            CheckoutResult with checkout URL

        Raises:
            PlanNotFoundError: If plan doesn't exist
            SubscriptionError: If not a valid downgrade
        """
        current_sub = self._get_active_subscription()
        if not current_sub:
            raise SubscriptionError("No active subscription to downgrade")

        current_plan = self._get_plan(current_sub.plan_id)
        new_plan = self._get_plan(new_plan_id)

        # Validate downgrade (new plan must have lower or equal price)
        current_price = current_plan.price_monthly_cents or 0
        new_price = new_plan.price_monthly_cents or 0

        if new_price >= current_price:
            raise SubscriptionError(
                f"Cannot downgrade: {new_plan.display_name} (${new_price/100}) is not lower than "
                f"{current_plan.display_name} (${current_price/100})"
            )

        # Log the downgrade intent
        self._log_billing_event(
            event_type=BillingEventType.PLAN_CHANGED.value,
            store_id=current_sub.store_id,
            subscription_id=current_sub.id,
            from_plan_id=current_plan.id,
            to_plan_id=new_plan.id,
            metadata={
                "action": "downgrade_initiated",
                "timing": "end_of_period",
                "from_price_cents": current_price,
                "to_price_cents": new_price,
                "effective_at": current_sub.current_period_end.isoformat() if current_sub.current_period_end else None
            }
        )

        self.db.commit()

        logger.info("Downgrade initiated", extra={
            "tenant_id": self.tenant_id,
            "from_plan": current_plan.id,
            "to_plan": new_plan.id,
            "effective_at": current_sub.current_period_end
        })

        # For free plan, we can handle without Shopify checkout
        if new_price == 0:
            store = self._get_store()
            return await self._schedule_downgrade_to_free(current_sub, new_plan, store)

        # For paid downgrades, create new subscription
        return await self.create_checkout_url(
            plan_id=new_plan_id,
            return_url=return_url,
            test_mode=test_mode
        )

    async def _schedule_downgrade_to_free(
        self,
        current_sub,
        free_plan: Plan,
        store
    ) -> CheckoutResult:
        """
        Schedule downgrade to free plan at end of billing period.

        For free plan downgrades, we don't need Shopify checkout.
        The subscription will be updated at period end by reconciliation job.
        """
        # Store the scheduled downgrade in metadata
        current_sub.extra_metadata = current_sub.extra_metadata or {}
        current_sub.extra_metadata["scheduled_downgrade"] = {
            "to_plan_id": free_plan.id,
            "effective_at": current_sub.current_period_end.isoformat() if current_sub.current_period_end else None,
            "scheduled_at": datetime.now(timezone.utc).isoformat()
        }

        self.db.commit()

        return CheckoutResult(
            checkout_url="",
            subscription_id=current_sub.id,
            success=True
        )

    def get_plan_tier(self, plan_id: str) -> int:
        """
        Get the tier level of a plan for comparison.

        Higher tier = higher number = more features/higher price.
        """
        plan = self._get_plan(plan_id)
        price = plan.price_monthly_cents or 0

        if price == 0:
            return 0
        elif price <= 3000:
            return 1
        elif price <= 10000:
            return 2
        else:
            return 3

    def can_upgrade_to(self, plan_id: str) -> bool:
        """
        Check if current subscription can upgrade to the given plan.

        Args:
            plan_id: Target plan ID

        Returns:
            True if upgrade is valid, False otherwise
        """
        current_sub = self._get_active_subscription()
        if not current_sub:
            return True

        current_tier = self.get_plan_tier(current_sub.plan_id)
        target_tier = self.get_plan_tier(plan_id)

        return target_tier > current_tier

    def can_downgrade_to(self, plan_id: str) -> bool:
        """
        Check if current subscription can downgrade to the given plan.

        Args:
            plan_id: Target plan ID

        Returns:
            True if downgrade is valid, False otherwise
        """
        current_sub = self._get_active_subscription()
        if not current_sub:
            return False

        current_tier = self.get_plan_tier(current_sub.plan_id)
        target_tier = self.get_plan_tier(plan_id)

        return target_tier < current_tier
