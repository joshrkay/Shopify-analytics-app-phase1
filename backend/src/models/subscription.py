"""
Subscription model for tracking store subscriptions.

CRITICAL: One subscription per store (Shopify limitation).
Subscription status is synced with Shopify via webhooks and reconciliation.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, DateTime, Enum, Text,
    ForeignKey, Index, UniqueConstraint, text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from src.models.base import TimestampMixin, TenantScopedMixin
from src.repositories.base_repo import Base


from enum import Enum as PyEnum

class SubscriptionStatus(str, PyEnum):
    """Subscription status values."""
    PENDING = "pending"          # Charge created, awaiting merchant approval
    ACTIVE = "active"            # Merchant approved, subscription active
    FROZEN = "frozen"            # Payment failed, in grace period
    CANCELLED = "cancelled"      # Merchant cancelled
    DECLINED = "declined"        # Merchant declined charge
    EXPIRED = "expired"          # Trial expired without conversion


class Subscription(Base, TimestampMixin, TenantScopedMixin):
    """
    Per-store subscription to a plan.
    
    Links a ShopifyStore (via tenant_id) to a Plan.
    Tracks Shopify Billing API subscription and charge IDs.
    """
    
    __tablename__ = "tenant_subscriptions"
    
    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)"
    )
    
    store_id = Column(
        String(255),
        ForeignKey("shopify_stores.id"),
        nullable=True,
        index=True,
        comment="Foreign key to shopify_stores.id (optional, can link via tenant_id)"
    )
    
    plan_id = Column(
        String(255),
        ForeignKey("plans.id"),
        nullable=False,
        index=True,
        comment="Foreign key to plans.id"
    )
    
    shopify_subscription_id = Column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
        comment="Shopify Billing API subscription ID (unique)"
    )
    
    shopify_charge_id = Column(
        String(255),
        nullable=True,
        comment="Shopify charge ID for one-time charges"
    )
    
    status = Column(
        String(50),
        nullable=False,
        default=SubscriptionStatus.ACTIVE.value,
        index=True,
        comment="Subscription status: active, cancelled, expired, trialing"
    )
    
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
    
    trial_end = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Trial expiration (if applicable)"
    )
    
    cancelled_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When subscription was cancelled"
    )
    
    grace_period_ends_on = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When grace period ends (if applicable)"
    )
    
    extra_metadata = Column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Additional subscription metadata"
    )
    
    # Relationships
    plan = relationship("Plan", foreign_keys=[plan_id])
    store = relationship("ShopifyStore", back_populates="subscription")
    
    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "plan_id",
            "status",
            name="uk_tenant_subscriptions_tenant_plan",
            deferrable=True,
            initially="DEFERRED"
        ),
        Index(
            "idx_tenant_subscriptions_tenant_status",
            "tenant_id",
            "status",
            postgresql_where=text("status = 'active'")
        ),
    )
    
    def __repr__(self) -> str:
        return f"<Subscription(id={self.id}, tenant_id={self.tenant_id}, plan_id={self.plan_id}, status={self.status})>"
