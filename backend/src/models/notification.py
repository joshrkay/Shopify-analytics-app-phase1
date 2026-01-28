"""
Notification model for storing user notifications.

Stores all notifications for audit and in-app display.
Supports multiple delivery channels with tracking.

SECURITY:
- Tenant isolation via TenantScopedMixin
- tenant_id from JWT only

Story 9.1 - Notification Framework (Events → Channels)
"""

import enum
import uuid
from datetime import datetime, timezone, date
from typing import Optional

from sqlalchemy import Column, String, Text, Enum, DateTime, Index, JSON
from sqlalchemy.dialects.postgresql import JSONB

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin


JSONType = JSON().with_variant(JSONB(), "postgresql")


class NotificationEventType(str, enum.Enum):
    """Types of events that can trigger notifications."""
    CONNECTOR_FAILED = "connector_failed"
    ACTION_REQUIRES_APPROVAL = "action_requires_approval"
    ACTION_EXECUTED = "action_executed"
    ACTION_FAILED = "action_failed"
    INCIDENT_DECLARED = "incident_declared"
    INCIDENT_RESOLVED = "incident_resolved"
    SYNC_COMPLETED = "sync_completed"
    INSIGHT_GENERATED = "insight_generated"
    RECOMMENDATION_CREATED = "recommendation_created"


class NotificationImportance(str, enum.Enum):
    """
    Notification importance level.

    Determines channel routing:
    - IMPORTANT: Email + In-App
    - ROUTINE: In-App only
    """
    IMPORTANT = "important"
    ROUTINE = "routine"


class NotificationStatus(str, enum.Enum):
    """
    Notification delivery/read status.

    Lifecycle: pending -> delivered -> read
    """
    PENDING = "pending"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


# Event type to importance mapping
EVENT_IMPORTANCE_MAP = {
    NotificationEventType.CONNECTOR_FAILED: NotificationImportance.IMPORTANT,
    NotificationEventType.ACTION_REQUIRES_APPROVAL: NotificationImportance.IMPORTANT,
    NotificationEventType.INCIDENT_DECLARED: NotificationImportance.IMPORTANT,
    NotificationEventType.ACTION_FAILED: NotificationImportance.IMPORTANT,
    NotificationEventType.ACTION_EXECUTED: NotificationImportance.ROUTINE,
    NotificationEventType.INCIDENT_RESOLVED: NotificationImportance.ROUTINE,
    NotificationEventType.SYNC_COMPLETED: NotificationImportance.ROUTINE,
    NotificationEventType.INSIGHT_GENERATED: NotificationImportance.ROUTINE,
    NotificationEventType.RECOMMENDATION_CREATED: NotificationImportance.ROUTINE,
}


class Notification(Base, TimestampMixin, TenantScopedMixin):
    """
    Core notification record.

    Stores all notifications for audit and in-app display.
    Tracks delivery status across multiple channels.

    SECURITY: tenant_id from TenantScopedMixin ensures isolation.
    """

    __tablename__ = "notifications"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    user_id = Column(String(255), nullable=True, index=True)
    event_type = Column(Enum(NotificationEventType), nullable=False, index=True)
    importance = Column(Enum(NotificationImportance), nullable=False)

    title = Column(String(500), nullable=False)
    message = Column(Text, nullable=False)
    action_url = Column(String(1000), nullable=True)

    entity_type = Column(String(100), nullable=True)
    entity_id = Column(String(255), nullable=True, index=True)
    idempotency_key = Column(String(255), nullable=False, unique=True)

    status = Column(
        Enum(NotificationStatus),
        nullable=False,
        default=NotificationStatus.PENDING,
        index=True,
    )

    in_app_delivered_at = Column(DateTime(timezone=True), nullable=True)
    email_queued_at = Column(DateTime(timezone=True), nullable=True)
    email_sent_at = Column(DateTime(timezone=True), nullable=True)
    email_failed_at = Column(DateTime(timezone=True), nullable=True)
    email_error = Column(String(500), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)

    event_metadata = Column(JSONType, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_notifications_tenant_user_status", "tenant_id", "user_id", "status"),
        Index("ix_notifications_entity", "tenant_id", "entity_type", "entity_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Notification(id={self.id}, tenant_id={self.tenant_id}, "
            f"event_type={self.event_type.value if self.event_type else None})>"
        )

    @property
    def is_pending(self) -> bool:
        return self.status == NotificationStatus.PENDING

    @property
    def is_delivered(self) -> bool:
        return self.status == NotificationStatus.DELIVERED

    @property
    def is_read(self) -> bool:
        return self.status == NotificationStatus.READ

    @property
    def is_important(self) -> bool:
        return self.importance == NotificationImportance.IMPORTANT

    @property
    def requires_email(self) -> bool:
        """Check if this notification should be sent via email."""
        return self.is_important and self.email_sent_at is None and self.email_failed_at is None

    def mark_delivered(self) -> None:
        """Mark notification as delivered to in-app channel."""
        self.status = NotificationStatus.DELIVERED
        self.in_app_delivered_at = datetime.now(timezone.utc)

    def mark_read(self) -> None:
        """Mark notification as read by user."""
        if self.status != NotificationStatus.READ:
            self.status = NotificationStatus.READ
            self.read_at = datetime.now(timezone.utc)

    def mark_email_queued(self) -> None:
        """Mark email as queued for sending."""
        self.email_queued_at = datetime.now(timezone.utc)

    def mark_email_sent(self) -> None:
        """Mark email as successfully sent."""
        self.email_sent_at = datetime.now(timezone.utc)

    def mark_email_failed(self, error: str) -> None:
        """Mark email as failed with error."""
        self.email_failed_at = datetime.now(timezone.utc)
        self.email_error = error[:500] if error else None

    @classmethod
    def create(
        cls,
        tenant_id: str,
        event_type: NotificationEventType,
        title: str,
        message: str,
        user_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        action_url: Optional[str] = None,
        event_metadata: Optional[dict] = None,
    ) -> "Notification":
        """Factory method to create a notification with automatic importance."""
        importance = EVENT_IMPORTANCE_MAP.get(event_type, NotificationImportance.ROUTINE)

        date_str = date.today().isoformat()
        idempotency_key = f"{tenant_id}:{event_type.value}:{entity_id or 'none'}:{date_str}"

        return cls(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=event_type,
            importance=importance,
            title=title,
            message=message,
            action_url=action_url,
            entity_type=entity_type,
            entity_id=entity_id,
            idempotency_key=idempotency_key,
            event_metadata=event_metadata or {},
        )
