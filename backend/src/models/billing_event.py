"""
BillingEvent model for immutable audit trail.

CRITICAL: This table is APPEND-ONLY for finance audit compliance.
Never update or delete billing events - only insert new ones.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, DateTime, Enum, Text,
    ForeignKey, Index
)
from sqlalchemy.orm import relationship

from src.models.base import Base, TenantScopedMixin, generate_uuid


class BillingEventType:
    """Billing event type constants."""
    # Subscription lifecycle
    SUBSCRIPTION_CREATED = "subscription_created"
    SUBSCRIPTION_ACTIVATED = "subscription_activated"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled"
    SUBSCRIPTION_UPGRADED = "subscription_upgraded"
    SUBSCRIPTION_DOWNGRADED = "subscription_downgraded"
    SUBSCRIPTION_EXPIRED = "subscription_expired"
    SUBSCRIPTION_REACTIVATED = "subscription_reactivated"

    # Payment events
    PAYMENT_SUCCEEDED = "payment_succeeded"
    PAYMENT_FAILED = "payment_failed"
    PAYMENT_REFUNDED = "payment_refunded"

    # Trial events
    TRIAL_STARTED = "trial_started"
    TRIAL_ENDED = "trial_ended"
    TRIAL_CONVERTED = "trial_converted"

    # Grace period
    GRACE_PERIOD_STARTED = "grace_period_started"
    GRACE_PERIOD_ENDED = "grace_period_ended"

    # Plan changes
    PLAN_CHANGED = "plan_changed"

    # Usage events
    USAGE_LIMIT_WARNING = "usage_limit_warning"
    USAGE_LIMIT_REACHED = "usage_limit_reached"

    # Store events
    STORE_INSTALLED = "store_installed"
    STORE_UNINSTALLED = "store_uninstalled"


class ActorType:
    """Actor type constants."""
    USER = "user"
    SYSTEM = "system"
    SHOPIFY = "shopify"
    WEBHOOK = "webhook"
    CRON = "cron"


class BillingEvent(Base, TenantScopedMixin):
    """
    Immutable audit log of all billing events.

    CRITICAL REQUIREMENTS:
    - APPEND-ONLY: Never update or delete records
    - Complete audit trail for finance compliance
    - All state changes must be recorded
    - Includes monetary amounts for reconciliation

    NOTE: Does not use TimestampMixin - uses occurred_at for event time
    and has separate created_at for record insertion time.
    """

    __tablename__ = "billing_events"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )

    # Foreign keys (nullable for flexibility)
    subscription_id = Column(
        String(36),
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Related subscription (may be null for store-level events)"
    )
    store_id = Column(
        String(36),
        ForeignKey("shopify_stores.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Related store"
    )

    # Event identification
    event_type = Column(
        Enum(
            # Subscription lifecycle
            "subscription_created",
            "subscription_activated",
            "subscription_cancelled",
            "subscription_upgraded",
            "subscription_downgraded",
            "subscription_expired",
            "subscription_reactivated",
            # Payment events
            "payment_succeeded",
            "payment_failed",
            "payment_refunded",
            # Trial events
            "trial_started",
            "trial_ended",
            "trial_converted",
            # Grace period
            "grace_period_started",
            "grace_period_ended",
            # Plan changes
            "plan_changed",
            # Usage events
            "usage_limit_warning",
            "usage_limit_reached",
            # Store events
            "store_installed",
            "store_uninstalled",
            name="billing_event_type"
        ),
        nullable=False,
        index=True,
        comment="Type of billing event"
    )

    # Timing
    occurred_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
        comment="When the event occurred"
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="When the record was created (may differ from occurred_at)"
    )

    # Monetary values (in cents)
    amount_cents = Column(
        Integer,
        nullable=True,
        comment="Monetary amount in cents (if applicable)"
    )
    currency = Column(
        String(10),
        default="USD",
        comment="Currency code"
    )

    # Plan context (for plan change events)
    from_plan_id = Column(
        String(36),
        ForeignKey("plans.id", ondelete="SET NULL"),
        nullable=True,
        comment="Previous plan (for upgrades/downgrades)"
    )
    to_plan_id = Column(
        String(36),
        ForeignKey("plans.id", ondelete="SET NULL"),
        nullable=True,
        comment="New plan (for upgrades/downgrades)"
    )

    # External references
    shopify_charge_id = Column(
        String(50),
        nullable=True,
        comment="Shopify charge ID"
    )
    shopify_transaction_id = Column(
        String(50),
        nullable=True,
        comment="Shopify transaction ID"
    )

    # Event metadata (JSON for flexible data)
    metadata = Column(
        Text,
        nullable=True,
        comment="Additional event data as JSON"
    )

    # Actor information (who/what triggered the event)
    actor_type = Column(
        Enum("user", "system", "shopify", "webhook", "cron", name="actor_type"),
        default="system",
        comment="Type of actor that triggered the event"
    )
    actor_id = Column(
        String(255),
        nullable=True,
        comment="ID of the actor (user_id, job name, etc.)"
    )

    # Description for human readability
    description = Column(
        Text,
        nullable=True,
        comment="Human-readable event description"
    )

    # Relationships
    subscription = relationship("Subscription", back_populates="billing_events")
    store = relationship("ShopifyStore", back_populates="billing_events")

    # Indexes for audit queries
    __table_args__ = (
        Index("ix_billing_events_tenant_time", "tenant_id", "occurred_at"),
        Index("ix_billing_events_type_time", "event_type", "occurred_at"),
        Index("ix_billing_events_store_time", "store_id", "occurred_at"),
        Index("ix_billing_events_subscription_time", "subscription_id", "occurred_at"),
    )

    def __repr__(self) -> str:
        return f"<BillingEvent(id={self.id}, type={self.event_type}, occurred_at={self.occurred_at})>"

    @property
    def amount_dollars(self) -> float | None:
        """Get amount in dollars."""
        if self.amount_cents is None:
            return None
        return self.amount_cents / 100
