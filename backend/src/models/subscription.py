"""
Subscription model for tracking store subscriptions.

CRITICAL: One subscription per store (Shopify limitation).
Subscription status is synced with Shopify via webhooks and reconciliation.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, DateTime, Enum, Text,
    ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship

from src.models.base import Base, TimestampMixin, TenantScopedMixin, generate_uuid


class SubscriptionStatus(str):
    """Subscription status values."""
    PENDING = "pending"          # Charge created, awaiting merchant approval
    ACTIVE = "active"            # Merchant approved, subscription active
    FROZEN = "frozen"            # Payment failed, in grace period
    CANCELLED = "cancelled"      # Merchant cancelled
    DECLINED = "declined"        # Merchant declined charge
    EXPIRED = "expired"          # Trial expired without conversion


class Subscription(Base, TimestampMixin, TenantScopedMixin):
    """
    Tracks subscription status for each Shopify store.

    CRITICAL DESIGN:
    - ONE subscription per store (Shopify limitation)
    - Status synced via webhooks + hourly reconciliation
    - Grace period handling for failed payments
    """

    __tablename__ = "subscriptions"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )

    # Foreign keys
    store_id = Column(
        String(36),
        ForeignKey("shopify_stores.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="One subscription per store"
    )
    plan_id = Column(
        String(36),
        ForeignKey("plans.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Current plan"
    )

    # Shopify charge references
    shopify_charge_id = Column(
        String(50),
        nullable=True,
        index=True,
        comment="Shopify RecurringApplicationCharge ID"
    )
    shopify_subscription_id = Column(
        String(100),
        nullable=True,
        comment="Shopify AppSubscription GID"
    )

    # Subscription lifecycle
    status = Column(
        Enum(
            "pending", "active", "frozen", "cancelled", "declined", "expired",
            name="subscription_status"
        ),
        default="pending",
        nullable=False,
        index=True,
        comment="Current subscription status"
    )

    # Billing dates
    billing_on = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Next billing date"
    )
    activated_on = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When subscription was activated"
    )
    cancelled_on = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When subscription was cancelled"
    )
    trial_ends_on = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Trial expiration date"
    )

    # Grace period for failed payments
    grace_period_ends_on = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="End of grace period after payment failure"
    )
    failed_payment_count = Column(
        Integer,
        default=0,
        comment="Number of consecutive failed payment attempts"
    )

    # Current billing period
    current_period_start = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Start of current billing period"
    )
    current_period_end = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="End of current billing period"
    )

    # Shopify confirmation URL (for pending charges)
    confirmation_url = Column(
        Text,
        nullable=True,
        comment="URL for merchant to approve charge"
    )

    # Relationships
    store = relationship(
        "ShopifyStore",
        back_populates="subscription"
    )
    plan = relationship(
        "Plan",
        back_populates="subscriptions"
    )
    billing_events = relationship(
        "BillingEvent",
        back_populates="subscription",
        lazy="dynamic"
    )

    # Indexes
    __table_args__ = (
        Index("ix_subscriptions_tenant_status", "tenant_id", "status"),
        Index("ix_subscriptions_shopify_charge", "shopify_charge_id"),
        Index("ix_subscriptions_grace_period", "grace_period_ends_on"),
        UniqueConstraint("store_id", name="uq_subscriptions_store"),
    )

    def __repr__(self) -> str:
        return f"<Subscription(id={self.id}, store_id={self.store_id}, status={self.status})>"

    @property
    def is_active(self) -> bool:
        """Check if subscription is active (allows feature access)."""
        return self.status == SubscriptionStatus.ACTIVE

    @property
    def is_in_grace_period(self) -> bool:
        """Check if subscription is in grace period."""
        if self.status != SubscriptionStatus.FROZEN:
            return False
        if not self.grace_period_ends_on:
            return False
        return datetime.now(timezone.utc) < self.grace_period_ends_on

    @property
    def allows_access(self) -> bool:
        """Check if subscription allows feature access (active or in grace period)."""
        return self.is_active or self.is_in_grace_period

    @property
    def is_in_trial(self) -> bool:
        """Check if subscription is in trial period."""
        if not self.trial_ends_on:
            return False
        return datetime.now(timezone.utc) < self.trial_ends_on

    @property
    def trial_days_remaining(self) -> int:
        """Get number of trial days remaining."""
        if not self.is_in_trial:
            return 0
        delta = self.trial_ends_on - datetime.now(timezone.utc)
        return max(0, delta.days)

    @property
    def needs_payment_update(self) -> bool:
        """Check if subscription needs payment method update."""
        return self.status == SubscriptionStatus.FROZEN
