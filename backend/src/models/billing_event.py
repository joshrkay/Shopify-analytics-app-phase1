"""
BillingEvent model - Immutable audit log for billing events.

SECURITY: This is append-only. No UPDATE or DELETE operations allowed.
Used for audit trail and reconciliation with Shopify Billing API.
"""

import uuid
import enum
from sqlalchemy import Column, String, Integer, Numeric, DateTime, ForeignKey, Index, func, JSON

from src.repositories.base_repo import Base
from src.models.base import TenantScopedMixin


class BillingEventType(str, enum.Enum):
    """Billing event type enumeration."""
    SUBSCRIPTION_CREATED = "subscription_created"
    SUBSCRIPTION_UPDATED = "subscription_updated"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled"
    SUBSCRIPTION_RENEWED = "subscription_renewed"
    CHARGE_CREATED = "charge_created"
    CHARGE_SUCCEEDED = "charge_succeeded"
    CHARGE_FAILED = "charge_failed"
    PLAN_CHANGED = "plan_changed"
    REFUND_ISSUED = "refund_issued"


class BillingEvent(Base, TenantScopedMixin):
    """
    Immutable audit log for billing events.
    
    SECURITY: This is append-only. No UPDATE or DELETE operations allowed.
    All billing changes must be recorded here for audit and reconciliation.
    """
    
    __tablename__ = "billing_events"
    
    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)"
    )
    
    event_type = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Event type (e.g., 'subscription_created', 'charge_succeeded')"
    )
    
    store_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Foreign key to shopify_stores.id (optional)"
    )
    
    subscription_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Foreign key to tenant_subscriptions.id (optional)"
    )
    
    from_plan_id = Column(
        String(255),
        nullable=True,
        comment="Previous plan ID (for plan changes)"
    )
    
    to_plan_id = Column(
        String(255),
        nullable=True,
        comment="New plan ID (for plan changes)"
    )
    
    amount_cents = Column(
        Integer,
        nullable=True,
        comment="Amount in cents (for charges/refunds)"
    )
    
    shopify_subscription_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Shopify Billing API subscription ID"
    )
    
    shopify_charge_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Shopify charge ID"
    )
    
    extra_metadata = Column(
        "metadata",
        JSON,
        nullable=True,
        comment="Additional event metadata (JSON)"
    )
    
    # Note: No updated_at - this is append-only
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
        comment="Timestamp when event occurred (append-only)"
    )
    
    # Indexes
    __table_args__ = (
        Index(
            "idx_billing_events_tenant_created",
            "tenant_id",
            "created_at",
            postgresql_ops={"created_at": "DESC"}
        ),
        Index(
            "idx_billing_events_tenant_type",
            "tenant_id",
            "event_type"
        ),
    )
    
    def __repr__(self) -> str:
        return f"<BillingEvent(id={self.id}, tenant_id={self.tenant_id}, event_type={self.event_type}, amount_cents={self.amount_cents})>"
