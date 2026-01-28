# PLAN: Story 9.1 — Notification Framework (Events → Channels)

**Version:** 1.0.0
**Date:** 2026-01-28
**Status:** Draft
**Story:** 9.1 - Notification Framework (Events → Channels)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Database Schema](#3-database-schema)
4. [Models](#4-models)
5. [Services](#5-services)
6. [API Endpoints](#6-api-endpoints)
7. [Email Sender Abstraction](#7-email-sender-abstraction)
8. [Worker Design](#8-worker-design)
9. [Event Types & Routing](#9-event-types--routing)
10. [Testing Plan](#10-testing-plan)
11. [Additional Tasks](#11-additional-tasks)
12. [Story 9.2 Integration](#12-story-92-integration)
13. [Implementation Checklist](#13-implementation-checklist)

---

## 1. Overview

### 1.1 Purpose

Implement an event-driven notification framework that:
- Routes critical events to both in-app and email channels
- Routes routine events to in-app only (no email)
- Prevents notification fatigue through intelligent routing
- Provides a centralized, tenant-scoped notification system
- Supports idempotent delivery

### 1.2 Business Context

Users must be informed of important events without notification fatigue:
- **Important events** (sync failure, approval required) → Email + In-App
- **Routine events** (action executed, informational) → In-App only

### 1.3 Supported Events

| Event Type | Importance | Channels | Description |
|------------|------------|----------|-------------|
| `connector_failed` | IMPORTANT | Email + In-App | Data connector sync failure |
| `action_requires_approval` | IMPORTANT | Email + In-App | AI action needs user approval |
| `incident_declared` | IMPORTANT | Email + In-App | DQ incident opened |
| `action_executed` | ROUTINE | In-App | AI action executed successfully |
| `sync_completed` | ROUTINE | In-App | Connector sync finished |
| `insight_generated` | ROUTINE | In-App | New AI insight available |
| `recommendation_created` | ROUTINE | In-App | New AI recommendation |

### 1.4 Design Principles

1. **Tenant isolation** - All notifications are tenant-scoped via `tenant_id` from JWT
2. **Idempotent delivery** - Deduplication keys prevent duplicate notifications
3. **Audit trail** - All notifications persisted to database
4. **Extensible** - Easy to add new event types and channels
5. **Non-blocking** - Email sending is async/queued, doesn't block API responses

---

## 2. Architecture

### 2.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Notification Framework                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────┐    ┌──────────────────────┐                    │
│  │  Event Sources  │    │  NotificationService │                    │
│  │                 │───▶│                      │                    │
│  │ - ActionService │    │ - create_notification│                    │
│  │ - DQService     │    │ - route_to_channels  │                    │
│  │ - SyncService   │    │ - check_preferences  │                    │
│  │ - InsightService│    │                      │                    │
│  └─────────────────┘    └──────────┬───────────┘                    │
│                                    │                                 │
│                    ┌───────────────┼───────────────┐                │
│                    ▼               ▼               ▼                │
│           ┌──────────────┐ ┌──────────────┐ ┌──────────────┐       │
│           │  In-App      │ │   Email      │ │   Future:    │       │
│           │  Channel     │ │   Channel    │ │   SMS/Push   │       │
│           │              │ │              │ │              │       │
│           │ (immediate)  │ │ (queued)     │ │              │       │
│           └──────┬───────┘ └──────┬───────┘ └──────────────┘       │
│                  │                │                                  │
│                  ▼                ▼                                  │
│           ┌──────────────────────────────────────┐                  │
│           │         notifications table          │                  │
│           │   (persisted for audit + UI)         │                  │
│           └──────────────────────────────────────┘                  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow

```
1. Event Occurs (e.g., connector_failed)
   │
   ▼
2. Event Source calls NotificationService.notify()
   │
   ▼
3. NotificationService:
   a. Generates idempotency key (tenant_id + event_type + entity_id + date)
   b. Checks for duplicate (skip if exists within window)
   c. Creates Notification record in database
   d. Determines importance (IMPORTANT vs ROUTINE)
   e. Routes to appropriate channels
   │
   ├──▶ In-App: Mark as delivered immediately (stored in DB)
   │
   └──▶ Email (if IMPORTANT):
        a. Check user preferences (Story 9.2)
        b. Queue email job
        c. Worker picks up and sends via EmailSender
        d. Update notification.email_sent_at
```

---

## 3. Database Schema

### 3.1 Migration: `backend/migrations/notifications_schema.sql`

```sql
-- Notification Framework Schema
-- Version: 1.0.0
-- Date: 2026-01-28
-- Story: 9.1 - Notification Framework (Events → Channels)
--
-- Creates tables for:
--   - notifications: Core notification records
--   - notification_preferences: User preferences (Story 9.2)
--
-- SECURITY:
--   - tenant_id on all tables for tenant isolation
--   - user_id for per-user notifications
--   - No PII stored - only references to entities

-- Ensure uuid-ossp extension is available
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- ENUM TYPES
-- =============================================================================

-- Notification event types
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'notification_event_type') THEN
        CREATE TYPE notification_event_type AS ENUM (
            'connector_failed',
            'action_requires_approval',
            'action_executed',
            'action_failed',
            'incident_declared',
            'incident_resolved',
            'sync_completed',
            'insight_generated',
            'recommendation_created'
        );
    END IF;
END
$$;

-- Notification importance level
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'notification_importance') THEN
        CREATE TYPE notification_importance AS ENUM (
            'important',  -- Routes to email + in-app
            'routine'     -- Routes to in-app only
        );
    END IF;
END
$$;

-- Notification channels
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'notification_channel') THEN
        CREATE TYPE notification_channel AS ENUM (
            'in_app',
            'email'
        );
    END IF;
END
$$;

-- Notification delivery status
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'notification_status') THEN
        CREATE TYPE notification_status AS ENUM (
            'pending',      -- Created, not yet delivered
            'delivered',    -- Delivered to all channels
            'read',         -- User has seen/acknowledged
            'failed'        -- Delivery failed
        );
    END IF;
END
$$;

-- =============================================================================
-- NOTIFICATIONS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS notifications (
    -- Primary key
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Tenant isolation (CRITICAL: never from client input, only from JWT)
    tenant_id VARCHAR(255) NOT NULL,

    -- Target user (optional - some notifications are tenant-wide)
    user_id VARCHAR(255),

    -- Event information
    event_type notification_event_type NOT NULL,
    importance notification_importance NOT NULL,

    -- Content
    title VARCHAR(500) NOT NULL,
    message TEXT NOT NULL,
    action_url VARCHAR(1000),  -- Deep link to relevant page

    -- Related entity (for grouping and deduplication)
    entity_type VARCHAR(100),  -- 'connector', 'action', 'incident', etc.
    entity_id VARCHAR(255),    -- ID of the related entity

    -- Idempotency (prevents duplicate notifications)
    idempotency_key VARCHAR(255) NOT NULL,

    -- Delivery tracking
    status notification_status NOT NULL DEFAULT 'pending',

    -- Channel delivery tracking
    in_app_delivered_at TIMESTAMP WITH TIME ZONE,
    email_queued_at TIMESTAMP WITH TIME ZONE,
    email_sent_at TIMESTAMP WITH TIME ZONE,
    email_failed_at TIMESTAMP WITH TIME ZONE,
    email_error VARCHAR(500),

    -- Read tracking
    read_at TIMESTAMP WITH TIME ZONE,

    -- Metadata for extensibility
    metadata JSONB DEFAULT '{}'::JSONB,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- NOTIFICATION PREFERENCES TABLE (Story 9.2 preparation)
-- =============================================================================

CREATE TABLE IF NOT EXISTS notification_preferences (
    -- Primary key
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Tenant isolation
    tenant_id VARCHAR(255) NOT NULL,

    -- User (if NULL, applies as tenant default)
    user_id VARCHAR(255),

    -- Event type this preference applies to
    event_type notification_event_type NOT NULL,

    -- Channel-specific settings
    in_app_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    email_enabled BOOLEAN NOT NULL DEFAULT TRUE,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Unique constraint: one preference per user per event type
    CONSTRAINT uq_notification_pref_user_event
        UNIQUE (tenant_id, user_id, event_type)
);

-- =============================================================================
-- INDEXES FOR notifications
-- =============================================================================

-- Single column indexes
CREATE INDEX IF NOT EXISTS ix_notifications_tenant_id
    ON notifications(tenant_id);

CREATE INDEX IF NOT EXISTS ix_notifications_user_id
    ON notifications(user_id);

CREATE INDEX IF NOT EXISTS ix_notifications_event_type
    ON notifications(event_type);

CREATE INDEX IF NOT EXISTS ix_notifications_status
    ON notifications(status);

CREATE INDEX IF NOT EXISTS ix_notifications_created_at
    ON notifications(created_at);

-- Composite indexes for common queries
-- User's unread notifications (main inbox query)
CREATE INDEX IF NOT EXISTS ix_notifications_tenant_user_unread
    ON notifications(tenant_id, user_id, status, created_at DESC)
    WHERE status IN ('pending', 'delivered');

-- Tenant + created_at for listing recent notifications
CREATE INDEX IF NOT EXISTS ix_notifications_tenant_created
    ON notifications(tenant_id, created_at DESC);

-- Entity lookup (find notifications for specific connector/action/etc)
CREATE INDEX IF NOT EXISTS ix_notifications_entity
    ON notifications(tenant_id, entity_type, entity_id);

-- Idempotency key for deduplication (unique)
CREATE UNIQUE INDEX IF NOT EXISTS ix_notifications_idempotency_key
    ON notifications(idempotency_key);

-- Pending email delivery (for worker queue)
CREATE INDEX IF NOT EXISTS ix_notifications_pending_email
    ON notifications(email_queued_at, email_sent_at)
    WHERE importance = 'important'
      AND email_queued_at IS NOT NULL
      AND email_sent_at IS NULL
      AND email_failed_at IS NULL;

-- =============================================================================
-- INDEXES FOR notification_preferences
-- =============================================================================

CREATE INDEX IF NOT EXISTS ix_notification_prefs_tenant_id
    ON notification_preferences(tenant_id);

CREATE INDEX IF NOT EXISTS ix_notification_prefs_user_id
    ON notification_preferences(user_id);

-- Lookup user's preferences
CREATE INDEX IF NOT EXISTS ix_notification_prefs_tenant_user
    ON notification_preferences(tenant_id, user_id);

-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- Trigger for notifications updated_at
DROP TRIGGER IF EXISTS tr_notifications_updated_at ON notifications;
CREATE TRIGGER tr_notifications_updated_at
    BEFORE UPDATE ON notifications
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Trigger for notification_preferences updated_at
DROP TRIGGER IF EXISTS tr_notification_prefs_updated_at ON notification_preferences;
CREATE TRIGGER tr_notification_prefs_updated_at
    BEFORE UPDATE ON notification_preferences
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON TABLE notifications IS 'Core notification records for event-driven notifications. Story 9.1.';
COMMENT ON TABLE notification_preferences IS 'User notification preferences per event type and channel. Story 9.2.';

COMMENT ON COLUMN notifications.tenant_id IS 'Tenant isolation key - ONLY from JWT, never client input';
COMMENT ON COLUMN notifications.user_id IS 'Target user ID (optional - NULL for tenant-wide notifications)';
COMMENT ON COLUMN notifications.importance IS 'Determines routing: important = email+in_app, routine = in_app only';
COMMENT ON COLUMN notifications.idempotency_key IS 'Unique key for deduplication (tenant_id:event_type:entity_id:date)';
COMMENT ON COLUMN notifications.entity_type IS 'Type of related entity (connector, action, incident)';
COMMENT ON COLUMN notifications.entity_id IS 'ID of the related entity';
COMMENT ON COLUMN notifications.action_url IS 'Deep link URL for user to navigate to relevant page';

COMMENT ON COLUMN notification_preferences.user_id IS 'User ID (NULL = tenant default)';
COMMENT ON COLUMN notification_preferences.event_type IS 'Event type this preference applies to';
COMMENT ON COLUMN notification_preferences.in_app_enabled IS 'Whether in-app notifications are enabled';
COMMENT ON COLUMN notification_preferences.email_enabled IS 'Whether email notifications are enabled';
```

---

## 4. Models

### 4.1 Notification Model: `backend/src/models/notification.py`

```python
"""
Notification model for storing user notifications.

Stores all notifications for audit and in-app display.
Supports multiple delivery channels with tracking.

SECURITY:
- Tenant isolation via TenantScopedMixin
- tenant_id from JWT only

Story 9.1 - Notification Framework
"""

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

from sqlalchemy import (
    Column, String, Text, Enum, DateTime, Index,
    UniqueConstraint, Boolean, JSON,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin


# Use JSONB for PostgreSQL, JSON for other databases (testing)
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


class NotificationChannel(str, enum.Enum):
    """Supported notification channels."""
    IN_APP = "in_app"
    EMAIL = "email"


class NotificationStatus(str, enum.Enum):
    """
    Notification delivery/read status.

    Lifecycle:
    - pending -> delivered (channels notified)
    - delivered -> read (user acknowledged)
    """
    PENDING = "pending"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


# Event type to importance mapping (locked decision)
EVENT_IMPORTANCE_MAP = {
    NotificationEventType.CONNECTOR_FAILED: NotificationImportance.IMPORTANT,
    NotificationEventType.ACTION_REQUIRES_APPROVAL: NotificationImportance.IMPORTANT,
    NotificationEventType.INCIDENT_DECLARED: NotificationImportance.IMPORTANT,
    NotificationEventType.ACTION_FAILED: NotificationImportance.IMPORTANT,
    # Routine events
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
        comment="Unique notification identifier"
    )

    # Target user (optional for tenant-wide notifications)
    user_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Target user ID (NULL for tenant-wide)"
    )

    # Event information
    event_type = Column(
        Enum(NotificationEventType),
        nullable=False,
        index=True,
        comment="Type of event that triggered this notification"
    )

    importance = Column(
        Enum(NotificationImportance),
        nullable=False,
        comment="Importance level (determines channel routing)"
    )

    # Content
    title = Column(
        String(500),
        nullable=False,
        comment="Notification title"
    )

    message = Column(
        Text,
        nullable=False,
        comment="Notification body message"
    )

    action_url = Column(
        String(1000),
        nullable=True,
        comment="Deep link URL to relevant page"
    )

    # Related entity (for grouping and deduplication)
    entity_type = Column(
        String(100),
        nullable=True,
        comment="Type of related entity"
    )

    entity_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="ID of related entity"
    )

    # Idempotency
    idempotency_key = Column(
        String(255),
        nullable=False,
        unique=True,
        comment="Unique key for deduplication"
    )

    # Delivery status
    status = Column(
        Enum(NotificationStatus),
        nullable=False,
        default=NotificationStatus.PENDING,
        index=True,
        comment="Current status"
    )

    # Channel delivery tracking
    in_app_delivered_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When in-app notification was delivered"
    )

    email_queued_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When email was queued for sending"
    )

    email_sent_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When email was successfully sent"
    )

    email_failed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When email sending failed"
    )

    email_error = Column(
        String(500),
        nullable=True,
        comment="Email delivery error message"
    )

    # Read tracking
    read_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When user read/acknowledged notification"
    )

    # Metadata
    metadata = Column(
        JSONType,
        nullable=False,
        default=dict,
        comment="Additional event-specific metadata"
    )

    # Indexes
    __table_args__ = (
        Index(
            "ix_notifications_tenant_user_unread",
            "tenant_id", "user_id", "status", "created_at",
            postgresql_ops={"created_at": "DESC"}
        ),
        Index(
            "ix_notifications_entity",
            "tenant_id", "entity_type", "entity_id"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Notification("
            f"id={self.id}, "
            f"tenant_id={self.tenant_id}, "
            f"event_type={self.event_type.value if self.event_type else None}, "
            f"status={self.status.value if self.status else None}"
            f")>"
        )

    # =========================================================================
    # Status checks
    # =========================================================================

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
        return self.is_important and self.email_sent_at is None

    # =========================================================================
    # Status transitions
    # =========================================================================

    def mark_delivered(self) -> None:
        """Mark notification as delivered to all channels."""
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
        self.email_error = error[:500]  # Truncate to fit column

    # =========================================================================
    # Factory methods
    # =========================================================================

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
        metadata: Optional[dict] = None,
    ) -> "Notification":
        """
        Factory method to create a notification with automatic importance.

        Args:
            tenant_id: Tenant identifier
            event_type: Type of event
            title: Notification title
            message: Notification body
            user_id: Target user (optional)
            entity_type: Related entity type
            entity_id: Related entity ID
            action_url: Deep link URL
            metadata: Additional data

        Returns:
            New Notification instance
        """
        importance = EVENT_IMPORTANCE_MAP.get(
            event_type,
            NotificationImportance.ROUTINE
        )

        # Generate idempotency key
        from datetime import date
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
            metadata=metadata or {},
        )
```

### 4.2 NotificationPreference Model: `backend/src/models/notification_preference.py`

```python
"""
Notification preference model for user notification settings.

Allows users to control which notifications they receive
and through which channels.

Story 9.2 - Notification Preferences
"""

import uuid
from typing import Optional

from sqlalchemy import Column, String, Boolean, Enum, UniqueConstraint, Index

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin
from src.models.notification import NotificationEventType


class NotificationPreference(Base, TimestampMixin, TenantScopedMixin):
    """
    User notification preferences.

    Controls which event types are enabled for which channels.
    NULL user_id represents tenant default.
    """

    __tablename__ = "notification_preferences"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # User (NULL = tenant default)
    user_id = Column(
        String(255),
        nullable=True,
        index=True,
    )

    # Event type
    event_type = Column(
        Enum(NotificationEventType),
        nullable=False,
    )

    # Channel settings
    in_app_enabled = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    email_enabled = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "event_type",
            name="uq_notification_pref_user_event"
        ),
        Index("ix_notification_prefs_tenant_user", "tenant_id", "user_id"),
    )
```

---

## 5. Services

### 5.1 NotificationService: `backend/src/services/notification_service.py`

**Responsibilities:**
- Create notifications for events
- Handle idempotency (deduplication)
- Route to appropriate channels
- Check user preferences (Story 9.2)
- Queue email delivery

**Key Methods:**

```python
class NotificationService:
    def __init__(self, db_session: Session, tenant_id: str):
        """Initialize with required tenant_id."""

    def notify(
        self,
        event_type: NotificationEventType,
        title: str,
        message: str,
        user_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        action_url: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[Notification]:
        """
        Create and route a notification.

        Returns None if duplicate (idempotent).
        """

    def notify_connector_failed(
        self,
        connector_id: str,
        connector_name: str,
        error_message: str,
        user_ids: Optional[List[str]] = None,
    ) -> List[Notification]:
        """Create notifications for connector failure."""

    def notify_action_requires_approval(
        self,
        action_id: str,
        action_type: str,
        user_ids: List[str],
    ) -> List[Notification]:
        """Create notifications for action requiring approval."""

    def notify_action_executed(
        self,
        action_id: str,
        action_type: str,
        user_id: str,
    ) -> Optional[Notification]:
        """Create notification for executed action."""

    def notify_incident_declared(
        self,
        incident_id: str,
        severity: str,
        title: str,
        user_ids: Optional[List[str]] = None,
    ) -> List[Notification]:
        """Create notifications for declared incident."""

    def get_unread_notifications(
        self,
        user_id: str,
        limit: int = 50,
    ) -> List[Notification]:
        """Get unread notifications for user."""

    def get_notifications(
        self,
        user_id: Optional[str] = None,
        event_type: Optional[NotificationEventType] = None,
        status: Optional[NotificationStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Notification], int]:
        """Get notifications with filtering and pagination."""

    def mark_as_read(
        self,
        notification_id: str,
        user_id: str,
    ) -> bool:
        """Mark a notification as read."""

    def mark_all_as_read(
        self,
        user_id: str,
    ) -> int:
        """Mark all notifications as read. Returns count."""

    def get_unread_count(
        self,
        user_id: str,
    ) -> int:
        """Get count of unread notifications."""

    def _should_send_email(
        self,
        event_type: NotificationEventType,
        user_id: Optional[str],
    ) -> bool:
        """Check if email should be sent based on preferences."""

    def _queue_email(
        self,
        notification: Notification,
    ) -> None:
        """Queue notification for email delivery."""
```

### 5.2 EmailSenderService: `backend/src/services/email_sender.py`

**Responsibilities:**
- Abstract email sending
- Support multiple providers (SendGrid, SES, SMTP)
- Handle retries
- Template rendering

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class EmailMessage:
    """Email message data."""
    to_email: str
    to_name: Optional[str]
    subject: str
    html_body: str
    text_body: Optional[str]
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    reply_to: Optional[str] = None
    tags: Optional[List[str]] = None


class EmailSender(ABC):
    """Abstract base class for email sending."""

    @abstractmethod
    async def send(self, message: EmailMessage) -> bool:
        """Send an email. Returns True on success."""
        pass

    @abstractmethod
    def send_sync(self, message: EmailMessage) -> bool:
        """Synchronous send for non-async contexts."""
        pass


class SendGridEmailSender(EmailSender):
    """SendGrid implementation."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SENDGRID_API_KEY")

    async def send(self, message: EmailMessage) -> bool:
        # Implementation using SendGrid API
        pass


class SMTPEmailSender(EmailSender):
    """SMTP implementation for development/testing."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 587,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        pass


class MockEmailSender(EmailSender):
    """Mock implementation for testing."""

    def __init__(self):
        self.sent_messages: List[EmailMessage] = []

    async def send(self, message: EmailMessage) -> bool:
        self.sent_messages.append(message)
        return True
```

### 5.3 NotificationPreferenceService: `backend/src/services/notification_preference_service.py`

**(Story 9.2 preparation)**

```python
class NotificationPreferenceService:
    def __init__(self, db_session: Session, tenant_id: str):
        pass

    def get_preferences(
        self,
        user_id: str,
    ) -> Dict[NotificationEventType, dict]:
        """Get all preferences for a user."""

    def get_preference(
        self,
        user_id: str,
        event_type: NotificationEventType,
    ) -> NotificationPreference:
        """Get preference for specific event type."""

    def update_preference(
        self,
        user_id: str,
        event_type: NotificationEventType,
        in_app_enabled: Optional[bool] = None,
        email_enabled: Optional[bool] = None,
    ) -> NotificationPreference:
        """Update a preference."""

    def reset_to_defaults(
        self,
        user_id: str,
    ) -> None:
        """Reset user preferences to defaults."""

    def seed_defaults(
        self,
        user_id: Optional[str] = None,
    ) -> None:
        """Seed default preferences for user or tenant."""
```

---

## 6. API Endpoints

### 6.1 Notifications API: `backend/src/api/routes/notifications.py`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/notifications` | List notifications (paginated) |
| GET | `/api/notifications/unread/count` | Get unread count |
| GET | `/api/notifications/{id}` | Get single notification |
| PATCH | `/api/notifications/{id}/read` | Mark as read |
| POST | `/api/notifications/read-all` | Mark all as read |

**Request/Response Examples:**

```python
# GET /api/notifications
# Query params: status, event_type, limit, offset
{
    "notifications": [
        {
            "id": "uuid",
            "event_type": "connector_failed",
            "importance": "important",
            "title": "Data sync failed",
            "message": "Your Shopify connection failed to sync",
            "action_url": "/connectors/abc123",
            "status": "delivered",
            "created_at": "2026-01-28T12:00:00Z",
            "read_at": null
        }
    ],
    "total": 15,
    "unread_count": 3
}

# GET /api/notifications/unread/count
{
    "count": 3
}

# PATCH /api/notifications/{id}/read
{
    "success": true
}

# POST /api/notifications/read-all
{
    "marked_count": 5
}
```

### 6.2 Notification Preferences API: `backend/src/api/routes/notification_preferences.py`

**(Story 9.2)**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/notification-preferences` | Get all preferences |
| PATCH | `/api/notification-preferences/{event_type}` | Update preference |
| POST | `/api/notification-preferences/reset` | Reset to defaults |

---

## 7. Email Sender Abstraction

### 7.1 Provider Configuration

```python
# Environment variables
NOTIFICATION_EMAIL_PROVIDER=sendgrid  # sendgrid, ses, smtp
SENDGRID_API_KEY=SG.xxx
NOTIFICATION_FROM_EMAIL=notifications@app.com
NOTIFICATION_FROM_NAME=Shopify Analytics

# AWS SES (alternative)
AWS_SES_REGION=us-east-1
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx
```

### 7.2 Email Templates

Templates for each notification type:

```
backend/src/templates/email/
├── base.html                    # Base template with header/footer
├── connector_failed.html        # Connector failure
├── action_requires_approval.html # Action approval request
├── incident_declared.html       # Incident notification
└── styles.css                   # Inline styles
```

**Template Example (connector_failed.html):**

```html
{% extends "base.html" %}

{% block content %}
<h2>Data Sync Failed</h2>

<p>Hi {{ user_name }},</p>

<p>We noticed that your <strong>{{ connector_name }}</strong> data
   connection failed to sync.</p>

<div class="alert alert-warning">
    <strong>Error:</strong> {{ error_message }}
</div>

<p><strong>What this means:</strong> Your recent data may not appear
   in reports until the sync is restored.</p>

<p><strong>Recommended action:</strong></p>
<ul>
    <li>Check your {{ connector_name }} credentials</li>
    <li>Verify the connection is still active</li>
    <li>Try reconnecting the data source</li>
</ul>

<a href="{{ action_url }}" class="button">View Connection Status</a>
{% endblock %}
```

### 7.3 Email Copy Tone (Human Approval Required)

**Guiding principles:**
- Informational, not alarming
- Clear action items
- Professional but friendly
- No ALL CAPS or excessive punctuation

---

## 8. Worker Design

### 8.1 NotificationEmailWorker: `backend/src/jobs/notification_email_worker.py`

```python
"""
Worker for processing queued notification emails.

Picks up notifications with email_queued_at set but email_sent_at null,
and sends them via the configured email provider.

Run as: python -m src.jobs.notification_email_worker
"""

class NotificationEmailWorker:
    def __init__(
        self,
        db_session: Session,
        email_sender: Optional[EmailSender] = None,
        batch_size: int = 50,
    ):
        self.db = db_session
        self.email_sender = email_sender or get_email_sender()
        self.batch_size = batch_size
        self.stats = {
            "processed": 0,
            "sent": 0,
            "failed": 0,
        }

    async def run(self) -> Dict[str, int]:
        """
        Process queued email notifications.

        Returns statistics dict.
        """
        pending = self._get_pending_emails()

        for notification in pending:
            await self._process_notification(notification)
            self.db.commit()

        return self.stats

    def _get_pending_emails(self) -> List[Notification]:
        """Get notifications pending email delivery."""
        return (
            self.db.query(Notification)
            .filter(
                Notification.importance == NotificationImportance.IMPORTANT,
                Notification.email_queued_at.isnot(None),
                Notification.email_sent_at.is_(None),
                Notification.email_failed_at.is_(None),
            )
            .limit(self.batch_size)
            .all()
        )

    async def _process_notification(
        self,
        notification: Notification,
    ) -> bool:
        """Process a single notification."""
        try:
            # Build email message
            message = self._build_email_message(notification)

            # Send via provider
            success = await self.email_sender.send(message)

            if success:
                notification.mark_email_sent()
                self.stats["sent"] += 1
            else:
                notification.mark_email_failed("Send returned False")
                self.stats["failed"] += 1

            self.stats["processed"] += 1
            return success

        except Exception as e:
            notification.mark_email_failed(str(e))
            self.stats["failed"] += 1
            self.stats["processed"] += 1
            logger.error(
                "Failed to send notification email",
                extra={
                    "notification_id": notification.id,
                    "error": str(e),
                }
            )
            return False
```

---

## 9. Event Types & Routing

### 9.1 Event Routing Matrix

| Event Type | Importance | In-App | Email | Trigger Point |
|------------|------------|--------|-------|---------------|
| `connector_failed` | IMPORTANT | Yes | Yes | DQService.create_incident() |
| `action_requires_approval` | IMPORTANT | Yes | Yes | ActionApprovalService.approve_recommendation() |
| `incident_declared` | IMPORTANT | Yes | Yes | DQService.create_incident() |
| `action_failed` | IMPORTANT | Yes | Yes | ActionExecutionService.mark_failed() |
| `action_executed` | ROUTINE | Yes | No | ActionExecutionService.mark_succeeded() |
| `sync_completed` | ROUTINE | Yes | No | SyncOrchestrator.complete_sync() |
| `insight_generated` | ROUTINE | Yes | No | InsightGenerationService.create() |
| `recommendation_created` | ROUTINE | Yes | No | RecommendationService.create() |

### 9.2 Integration Points

Services that should call NotificationService:

1. **DQService** (`src/api/dq/service.py`)
   - `create_incident()` → `connector_failed`, `incident_declared`
   - `resolve_incident()` → `incident_resolved`

2. **ActionExecutionService** (`src/services/action_execution_service.py`)
   - `mark_succeeded()` → `action_executed`
   - `mark_failed()` → `action_failed`

3. **ActionApprovalService** (`src/services/action_approval_service.py`)
   - `approve_recommendation()` → `action_requires_approval`

4. **InsightGenerationService** (`src/services/insight_generation_service.py`)
   - `create_insight()` → `insight_generated`

5. **RecommendationGenerationService** (`src/services/recommendation_generation_service.py`)
   - `create_recommendation()` → `recommendation_created`

---

## 10. Testing Plan

### 10.1 Unit Tests

**File:** `backend/src/tests/unit/test_notification_models.py`

- Test Notification.create() factory method
- Test idempotency key generation
- Test status transitions
- Test importance mapping

**File:** `backend/src/tests/unit/test_notification_service.py`

- Test notify() creates notification
- Test idempotency (duplicate prevention)
- Test channel routing (important vs routine)
- Test preference checking
- Test email queueing

**File:** `backend/src/tests/unit/test_email_sender.py`

- Test SendGridEmailSender
- Test MockEmailSender
- Test error handling

### 10.2 Integration Tests

**File:** `backend/src/tests/integration/test_notifications_api.py`

- Test GET /api/notifications
- Test GET /api/notifications/unread/count
- Test PATCH /api/notifications/{id}/read
- Test POST /api/notifications/read-all
- Test tenant isolation
- Test permission checks

**File:** `backend/src/tests/integration/test_notification_email_worker.py`

- Test worker processes queued emails
- Test retry on failure
- Test statistics tracking

### 10.3 Test Fixtures

```python
@pytest.fixture
def notification_service(mock_db_session, tenant_id):
    return NotificationService(mock_db_session, tenant_id)

@pytest.fixture
def sample_notification(tenant_id):
    return Notification.create(
        tenant_id=tenant_id,
        event_type=NotificationEventType.CONNECTOR_FAILED,
        title="Test notification",
        message="Test message",
    )

@pytest.fixture
def mock_email_sender():
    return MockEmailSender()
```

---

## 11. Additional Tasks

### 11.1 Required Before Implementation

| Task | Owner | Description |
|------|-------|-------------|
| Approve "important" events | Human | Confirm which events trigger email |
| Approve email copy tone | Human | Review email templates for tone |
| Approve default notification behavior | Human | Confirm defaults for preferences |
| Select email provider | Human | SendGrid vs SES vs other |

### 11.2 Implementation Tasks

| # | Task | Priority | Est. Effort |
|---|------|----------|-------------|
| 1 | Create database migration | P0 | S |
| 2 | Create Notification model | P0 | S |
| 3 | Create NotificationPreference model | P1 | S |
| 4 | Create NotificationService | P0 | M |
| 5 | Create EmailSender abstraction | P0 | M |
| 6 | Create SendGridEmailSender | P0 | M |
| 7 | Create email templates | P1 | M |
| 8 | Create NotificationEmailWorker | P0 | M |
| 9 | Create notifications API routes | P0 | M |
| 10 | Integrate with DQService | P0 | S |
| 11 | Integrate with ActionExecutionService | P0 | S |
| 12 | Integrate with ActionApprovalService | P0 | S |
| 13 | Write unit tests | P0 | M |
| 14 | Write integration tests | P0 | M |

### 11.3 Edge Cases to Handle

1. **User without email** - Skip email channel, log warning
2. **Email provider down** - Queue with retry, don't block in-app
3. **High notification volume** - Rate limiting, batching
4. **Duplicate events** - Idempotency key handles this
5. **Unsubscribed user** - Check preferences before sending (Story 9.2)
6. **Template rendering failure** - Fallback to plain text
7. **Long messages** - Truncation with "View more" link

### 11.4 Security Considerations

1. **Tenant isolation** - All queries must filter by tenant_id
2. **User ownership** - Users can only read their own notifications
3. **No PII in notifications** - Store entity references, not names
4. **Email spoofing** - Use verified sender domain
5. **Rate limiting** - Prevent notification spam

### 11.5 Performance Considerations

1. **Async email sending** - Don't block API responses
2. **Batch email processing** - Worker handles in batches
3. **Database indexes** - Optimized for common queries
4. **Pagination** - Required for notification list endpoint
5. **Caching unread count** - Consider Redis for high-traffic

### 11.6 Monitoring & Observability

1. **Metrics to track:**
   - Notifications created per hour/day
   - Email send success/failure rate
   - Average time to email delivery
   - Unread notification counts

2. **Alerts:**
   - Email delivery failure spike
   - Worker not processing (queue growing)

3. **Logging:**
   - All notifications logged with tenant_id, event_type
   - Email send attempts logged with result

---

## 12. Story 9.2 Integration

### 12.1 Preference Schema Ready

The `notification_preferences` table is created as part of this story
to avoid a separate migration for Story 9.2.

### 12.2 Service Hook Points

NotificationService includes `_should_send_email()` which:
1. Checks if event is IMPORTANT (required for email)
2. Checks user preference (Story 9.2)
3. Falls back to tenant default if no user preference
4. Falls back to system default if no tenant default

### 12.3 Default Preferences

**Role-based defaults (Story 9.2):**

| Event Type | Merchant Default | Agency Default |
|------------|------------------|----------------|
| connector_failed | email=true | email=true |
| action_requires_approval | email=true | email=true |
| incident_declared | email=true | email=true |
| action_executed | email=false | email=false |

---

## 13. Implementation Checklist

### Phase 1: Core Infrastructure
- [ ] Create `notifications_schema.sql` migration
- [ ] Create `Notification` model
- [ ] Create `NotificationPreference` model
- [ ] Create `NotificationService`
- [ ] Create `EmailSender` abstraction
- [ ] Create `SendGridEmailSender` (or chosen provider)

### Phase 2: Delivery System
- [ ] Create email templates directory structure
- [ ] Create base email template
- [ ] Create `NotificationEmailWorker`
- [ ] Configure email provider (env vars)

### Phase 3: API Layer
- [ ] Create `/api/notifications` routes
- [ ] Create Pydantic schemas
- [ ] Add to main.py router

### Phase 4: Integration
- [ ] Integrate with `DQService.create_incident()`
- [ ] Integrate with `ActionExecutionService`
- [ ] Integrate with `ActionApprovalService`
- [ ] Add NotificationService to service layer exports

### Phase 5: Testing
- [ ] Unit tests for models
- [ ] Unit tests for services
- [ ] Integration tests for API
- [ ] Integration tests for worker

### Phase 6: Documentation
- [ ] Update API documentation
- [ ] Add environment variable documentation
- [ ] Add operational runbook for email worker

---

## Appendix A: Environment Variables

```bash
# Email Provider
NOTIFICATION_EMAIL_PROVIDER=sendgrid
SENDGRID_API_KEY=SG.xxx

# Sender Configuration
NOTIFICATION_FROM_EMAIL=notifications@shopify-analytics.com
NOTIFICATION_FROM_NAME=Shopify Analytics
NOTIFICATION_REPLY_TO=support@shopify-analytics.com

# Worker Configuration
NOTIFICATION_EMAIL_BATCH_SIZE=50
NOTIFICATION_EMAIL_RETRY_DELAY_SECONDS=60

# Feature Flags
NOTIFICATION_EMAIL_ENABLED=true
```

## Appendix B: API Response Schemas

```python
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class NotificationSchema(BaseModel):
    id: str
    event_type: str
    importance: str
    title: str
    message: str
    action_url: Optional[str]
    entity_type: Optional[str]
    entity_id: Optional[str]
    status: str
    created_at: datetime
    read_at: Optional[datetime]

class NotificationListResponse(BaseModel):
    notifications: List[NotificationSchema]
    total: int
    unread_count: int

class UnreadCountResponse(BaseModel):
    count: int

class MarkReadResponse(BaseModel):
    success: bool

class MarkAllReadResponse(BaseModel):
    marked_count: int
```
