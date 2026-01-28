"""
Notification service for Story 9.1.

Creates and routes notifications to appropriate channels.
Handles idempotency, preference checking, and email queueing.

SECURITY: tenant_id from JWT only, never from client input.

Story 9.1 - Notification Framework (Events → Channels)
"""

import logging
from datetime import datetime, timezone, date
from typing import Optional, List, Tuple

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.models.notification import (
    Notification,
    NotificationEventType,
    NotificationImportance,
    NotificationStatus,
    EVENT_IMPORTANCE_MAP,
)
from src.models.notification_preference import NotificationPreference


logger = logging.getLogger(__name__)


class NotificationService:
    """
    Service for creating and managing notifications.

    Handles:
    - Notification creation with idempotency
    - Channel routing (in-app vs email)
    - Preference checking
    - Email queue management
    """

    def __init__(self, db_session: Session, tenant_id: str):
        """
        Initialize notification service.

        Args:
            db_session: Database session
            tenant_id: Tenant identifier (from JWT only)
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id

    def notify(
        self,
        event_type: NotificationEventType,
        title: str,
        message: str,
        user_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        action_url: Optional[str] = None,
        event_metadata: Optional[dict] = None,
    ) -> Optional[Notification]:
        """
        Create and route a notification.

        Idempotent: Returns None if duplicate exists for same day.

        Args:
            event_type: Type of event triggering notification
            title: Notification title
            message: Notification body
            user_id: Target user (optional for tenant-wide)
            entity_type: Related entity type
            entity_id: Related entity ID
            action_url: Deep link URL
            event_metadata: Additional event-specific data

        Returns:
            Created Notification or None if duplicate
        """
        notification = Notification.create(
            tenant_id=self.tenant_id,
            event_type=event_type,
            title=title,
            message=message,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action_url=action_url,
            event_metadata=event_metadata,
        )

        try:
            self.db.add(notification)
            self.db.flush()

            # Mark as delivered to in-app channel immediately
            notification.mark_delivered()

            # Queue email if important and preferences allow
            if notification.is_important and self._should_send_email(event_type, user_id):
                notification.mark_email_queued()

            self.db.flush()

            logger.info(
                "Notification created",
                extra={
                    "tenant_id": self.tenant_id,
                    "notification_id": notification.id,
                    "event_type": event_type.value,
                    "user_id": user_id,
                    "importance": notification.importance.value,
                    "email_queued": notification.email_queued_at is not None,
                },
            )

            return notification

        except IntegrityError:
            # Duplicate idempotency key - notification already exists
            self.db.rollback()
            logger.info(
                "Duplicate notification skipped",
                extra={
                    "tenant_id": self.tenant_id,
                    "event_type": event_type.value,
                    "entity_id": entity_id,
                    "idempotency_key": notification.idempotency_key,
                },
            )
            return None

    def notify_connector_failed(
        self,
        connector_id: str,
        connector_name: str,
        error_message: str,
        user_ids: Optional[List[str]] = None,
    ) -> List[Notification]:
        """
        Create notifications for connector failure.

        Args:
            connector_id: ID of failed connector
            connector_name: Name of connector
            error_message: Error description
            user_ids: Target users (None for tenant-wide)

        Returns:
            List of created notifications
        """
        title = f"Data sync failed: {connector_name}"
        message = (
            f"Your {connector_name} connection failed to sync. "
            f"Error: {error_message}. Please check the connection settings."
        )
        action_url = f"/connectors/{connector_id}"

        notifications = []

        if user_ids:
            for user_id in user_ids:
                notification = self.notify(
                    event_type=NotificationEventType.CONNECTOR_FAILED,
                    title=title,
                    message=message,
                    user_id=user_id,
                    entity_type="connector",
                    entity_id=connector_id,
                    action_url=action_url,
                    event_metadata={"connector_name": connector_name, "error": error_message},
                )
                if notification:
                    notifications.append(notification)
        else:
            notification = self.notify(
                event_type=NotificationEventType.CONNECTOR_FAILED,
                title=title,
                message=message,
                entity_type="connector",
                entity_id=connector_id,
                action_url=action_url,
                event_metadata={"connector_name": connector_name, "error": error_message},
            )
            if notification:
                notifications.append(notification)

        return notifications

    def notify_action_requires_approval(
        self,
        action_id: str,
        action_type: str,
        description: str,
        user_ids: List[str],
    ) -> List[Notification]:
        """
        Create notifications for action requiring approval.

        Args:
            action_id: ID of action
            action_type: Type of action
            description: Action description
            user_ids: Target approvers

        Returns:
            List of created notifications
        """
        title = f"Action requires approval: {action_type}"
        message = f"{description}. Please review and approve or reject this action."
        action_url = f"/actions/{action_id}"

        notifications = []
        for user_id in user_ids:
            notification = self.notify(
                event_type=NotificationEventType.ACTION_REQUIRES_APPROVAL,
                title=title,
                message=message,
                user_id=user_id,
                entity_type="action",
                entity_id=action_id,
                action_url=action_url,
                event_metadata={"action_type": action_type},
            )
            if notification:
                notifications.append(notification)

        return notifications

    def notify_action_executed(
        self,
        action_id: str,
        action_type: str,
        user_id: str,
    ) -> Optional[Notification]:
        """
        Create notification for successfully executed action.

        Args:
            action_id: ID of action
            action_type: Type of action
            user_id: User who triggered the action

        Returns:
            Created notification or None
        """
        return self.notify(
            event_type=NotificationEventType.ACTION_EXECUTED,
            title=f"Action completed: {action_type}",
            message=f"Your {action_type} action has been executed successfully.",
            user_id=user_id,
            entity_type="action",
            entity_id=action_id,
            action_url=f"/actions/{action_id}",
            event_metadata={"action_type": action_type},
        )

    def notify_action_failed(
        self,
        action_id: str,
        action_type: str,
        error_message: str,
        user_id: str,
    ) -> Optional[Notification]:
        """
        Create notification for failed action.

        Args:
            action_id: ID of action
            action_type: Type of action
            error_message: Error description
            user_id: User who triggered the action

        Returns:
            Created notification or None
        """
        return self.notify(
            event_type=NotificationEventType.ACTION_FAILED,
            title=f"Action failed: {action_type}",
            message=f"Your {action_type} action failed. Error: {error_message}",
            user_id=user_id,
            entity_type="action",
            entity_id=action_id,
            action_url=f"/actions/{action_id}",
            event_metadata={"action_type": action_type, "error": error_message},
        )

    def notify_incident_declared(
        self,
        incident_id: str,
        severity: str,
        title: str,
        description: str,
        user_ids: Optional[List[str]] = None,
    ) -> List[Notification]:
        """
        Create notifications for declared incident.

        Args:
            incident_id: ID of incident
            severity: Incident severity
            title: Incident title
            description: Incident description
            user_ids: Target users (None for tenant-wide)

        Returns:
            List of created notifications
        """
        notification_title = f"Incident: {title}"
        message = f"{description} (Severity: {severity})"
        action_url = f"/incidents/{incident_id}"

        notifications = []

        if user_ids:
            for user_id in user_ids:
                notification = self.notify(
                    event_type=NotificationEventType.INCIDENT_DECLARED,
                    title=notification_title,
                    message=message,
                    user_id=user_id,
                    entity_type="incident",
                    entity_id=incident_id,
                    action_url=action_url,
                    event_metadata={"severity": severity},
                )
                if notification:
                    notifications.append(notification)
        else:
            notification = self.notify(
                event_type=NotificationEventType.INCIDENT_DECLARED,
                title=notification_title,
                message=message,
                entity_type="incident",
                entity_id=incident_id,
                action_url=action_url,
                event_metadata={"severity": severity},
            )
            if notification:
                notifications.append(notification)

        return notifications

    def get_notifications(
        self,
        user_id: Optional[str] = None,
        event_type: Optional[NotificationEventType] = None,
        status: Optional[NotificationStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Notification], int]:
        """
        Get notifications with filtering and pagination.

        Args:
            user_id: Filter by user (optional)
            event_type: Filter by event type (optional)
            status: Filter by status (optional)
            limit: Maximum results
            offset: Pagination offset

        Returns:
            Tuple of (notifications, total_count)
        """
        query = self.db.query(Notification).filter(
            Notification.tenant_id == self.tenant_id
        )

        if user_id:
            query = query.filter(Notification.user_id == user_id)

        if event_type:
            query = query.filter(Notification.event_type == event_type)

        if status:
            query = query.filter(Notification.status == status)

        total = query.count()

        notifications = (
            query
            .order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return notifications, total

    def get_unread_notifications(
        self,
        user_id: str,
        limit: int = 50,
    ) -> List[Notification]:
        """
        Get unread notifications for a user.

        Args:
            user_id: Target user ID
            limit: Maximum results

        Returns:
            List of unread notifications
        """
        return (
            self.db.query(Notification)
            .filter(
                Notification.tenant_id == self.tenant_id,
                Notification.user_id == user_id,
                Notification.status.in_([
                    NotificationStatus.PENDING,
                    NotificationStatus.DELIVERED,
                ]),
            )
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_unread_count(self, user_id: str) -> int:
        """
        Get count of unread notifications for a user.

        Args:
            user_id: Target user ID

        Returns:
            Count of unread notifications
        """
        return (
            self.db.query(Notification)
            .filter(
                Notification.tenant_id == self.tenant_id,
                Notification.user_id == user_id,
                Notification.status.in_([
                    NotificationStatus.PENDING,
                    NotificationStatus.DELIVERED,
                ]),
            )
            .count()
        )

    def mark_as_read(self, notification_id: str, user_id: str) -> bool:
        """
        Mark a notification as read.

        Args:
            notification_id: ID of notification
            user_id: User marking as read

        Returns:
            True if successful, False if not found or unauthorized
        """
        notification = (
            self.db.query(Notification)
            .filter(
                Notification.id == notification_id,
                Notification.tenant_id == self.tenant_id,
                Notification.user_id == user_id,
            )
            .first()
        )

        if not notification:
            return False

        notification.mark_read()
        self.db.flush()

        logger.info(
            "Notification marked as read",
            extra={
                "tenant_id": self.tenant_id,
                "notification_id": notification_id,
                "user_id": user_id,
            },
        )

        return True

    def mark_all_as_read(self, user_id: str) -> int:
        """
        Mark all notifications as read for a user.

        Args:
            user_id: Target user ID

        Returns:
            Count of notifications marked as read
        """
        now = datetime.now(timezone.utc)

        count = (
            self.db.query(Notification)
            .filter(
                Notification.tenant_id == self.tenant_id,
                Notification.user_id == user_id,
                Notification.status.in_([
                    NotificationStatus.PENDING,
                    NotificationStatus.DELIVERED,
                ]),
            )
            .update(
                {
                    Notification.status: NotificationStatus.READ,
                    Notification.read_at: now,
                },
                synchronize_session=False,
            )
        )

        self.db.flush()

        logger.info(
            "All notifications marked as read",
            extra={
                "tenant_id": self.tenant_id,
                "user_id": user_id,
                "count": count,
            },
        )

        return count

    def _should_send_email(
        self,
        event_type: NotificationEventType,
        user_id: Optional[str],
    ) -> bool:
        """
        Check if email should be sent based on preferences.

        Args:
            event_type: Event type to check
            user_id: User to check preferences for

        Returns:
            True if email should be sent
        """
        # First check user-specific preference
        if user_id:
            pref = (
                self.db.query(NotificationPreference)
                .filter(
                    NotificationPreference.tenant_id == self.tenant_id,
                    NotificationPreference.user_id == user_id,
                    NotificationPreference.event_type == event_type,
                )
                .first()
            )
            if pref:
                return pref.email_enabled

        # Check tenant default (user_id is NULL)
        tenant_pref = (
            self.db.query(NotificationPreference)
            .filter(
                NotificationPreference.tenant_id == self.tenant_id,
                NotificationPreference.user_id.is_(None),
                NotificationPreference.event_type == event_type,
            )
            .first()
        )

        if tenant_pref:
            return tenant_pref.email_enabled

        # Default: send email for important events
        return True

    def get_pending_emails(self, limit: int = 50) -> List[Notification]:
        """
        Get notifications pending email delivery.

        Args:
            limit: Maximum results

        Returns:
            List of notifications needing email
        """
        return (
            self.db.query(Notification)
            .filter(
                Notification.tenant_id == self.tenant_id,
                Notification.importance == NotificationImportance.IMPORTANT,
                Notification.email_queued_at.isnot(None),
                Notification.email_sent_at.is_(None),
                Notification.email_failed_at.is_(None),
            )
            .order_by(Notification.email_queued_at.asc())
            .limit(limit)
            .all()
        )
