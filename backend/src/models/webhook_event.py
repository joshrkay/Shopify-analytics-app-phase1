"""
WebhookEvent model for tracking processed Shopify webhooks.

Used for idempotency - ensures webhooks are processed exactly once.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, Index, func

from src.db_base import Base


class WebhookEvent(Base):
    """
    Tracks processed Shopify webhook events for deduplication.

    Shopify may deliver webhooks multiple times. This table ensures
    each unique event is processed exactly once.
    """

    __tablename__ = "webhook_events"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)"
    )

    shopify_event_id = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="Shopify webhook event ID (X-Shopify-Webhook-Id header)"
    )

    topic = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Webhook topic (e.g., app_subscriptions/update)"
    )

    shop_domain = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Shop domain from webhook"
    )

    payload_hash = Column(
        String(64),
        nullable=True,
        comment="SHA-256 hash of payload for debugging"
    )

    processed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When the webhook was processed"
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="When the record was created"
    )

    __table_args__ = (
        Index(
            "idx_webhook_events_shop_topic",
            "shop_domain",
            "topic"
        ),
        Index(
            "idx_webhook_events_processed",
            "processed_at",
            postgresql_ops={"processed_at": "DESC"}
        ),
    )

    def __repr__(self) -> str:
        return f"<WebhookEvent(id={self.id}, event_id={self.shopify_event_id}, topic={self.topic})>"
