"""
Subscription model - Per-store subscription to a plan.

Links a ShopifyStore to a Plan via Shopify Billing API.
"""

import uuid
import enum
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from src.repositories.base_repo import Base
from src.models.base import TimestampMixin, TenantScopedMixin


class SubscriptionStatus(str, enum.Enum):
    """Subscription status enumeration."""
    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    TRIALING = "trialing"


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
