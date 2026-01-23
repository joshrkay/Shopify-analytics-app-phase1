"""
Audit logging for AI Growth Analytics.

CRITICAL SECURITY REQUIREMENTS:
- Audit logs MUST be append-only (no UPDATE/DELETE)
- All sensitive actions MUST write an audit event
- Events must include: tenant_id, user_id, action, timestamp, IP, user_agent, metadata

Sensitive actions that require audit logging:
- Auth/session events
- Billing changes
- Connector changes (store add/remove)
- AI key/model changes
- Data exports
- Automation approvals/executions
- Feature flag changes
- Permission/role changes
- Admin actions
"""

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from dataclasses import dataclass, field, asdict

from fastapi import Request
from sqlalchemy import Column, String, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.declarative import declarative_base

# Use separate Base to avoid circular imports
# This model will need to be registered with the main Base during app initialization
AuditBase = declarative_base()

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    """
    Enumeration of all auditable actions.

    Add new actions here as features are developed.
    """
    # Auth events
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_TOKEN_REFRESH = "auth.token_refresh"
    AUTH_PASSWORD_CHANGE = "auth.password_change"
    AUTH_MFA_ENABLED = "auth.mfa_enabled"
    AUTH_MFA_DISABLED = "auth.mfa_disabled"

    # Billing events
    BILLING_PLAN_CHANGED = "billing.plan_changed"
    BILLING_SUBSCRIPTION_CREATED = "billing.subscription_created"
    BILLING_SUBSCRIPTION_CANCELLED = "billing.subscription_cancelled"
    BILLING_PAYMENT_FAILED = "billing.payment_failed"
    BILLING_PAYMENT_SUCCESS = "billing.payment_success"

    # Store/connector events
    STORE_CONNECTED = "store.connected"
    STORE_DISCONNECTED = "store.disconnected"
    STORE_UPDATED = "store.updated"
    STORE_SYNC_STARTED = "store.sync_started"
    STORE_SYNC_COMPLETED = "store.sync_completed"
    STORE_SYNC_FAILED = "store.sync_failed"

    # AI events
    AI_KEY_CREATED = "ai.key_created"
    AI_KEY_ROTATED = "ai.key_rotated"
    AI_KEY_DELETED = "ai.key_deleted"
    AI_MODEL_CHANGED = "ai.model_changed"
    AI_ACTION_REQUESTED = "ai.action_requested"
    AI_ACTION_EXECUTED = "ai.action_executed"
    AI_ACTION_REJECTED = "ai.action_rejected"

    # Data export events
    EXPORT_REQUESTED = "export.requested"
    EXPORT_COMPLETED = "export.completed"
    EXPORT_FAILED = "export.failed"
    EXPORT_DOWNLOADED = "export.downloaded"

    # Automation events
    AUTOMATION_CREATED = "automation.created"
    AUTOMATION_UPDATED = "automation.updated"
    AUTOMATION_DELETED = "automation.deleted"
    AUTOMATION_APPROVED = "automation.approved"
    AUTOMATION_REJECTED = "automation.rejected"
    AUTOMATION_EXECUTED = "automation.executed"
    AUTOMATION_FAILED = "automation.failed"

    # Feature flag events
    FEATURE_FLAG_ENABLED = "feature_flag.enabled"
    FEATURE_FLAG_DISABLED = "feature_flag.disabled"
    FEATURE_FLAG_OVERRIDE = "feature_flag.override"

    # Team/permission events
    TEAM_MEMBER_INVITED = "team.member_invited"
    TEAM_MEMBER_REMOVED = "team.member_removed"
    TEAM_ROLE_CHANGED = "team.role_changed"

    # Settings events
    SETTINGS_UPDATED = "settings.updated"

    # Admin events
    ADMIN_PLAN_CREATED = "admin.plan_created"
    ADMIN_PLAN_UPDATED = "admin.plan_updated"
    ADMIN_PLAN_DELETED = "admin.plan_deleted"
    ADMIN_CONFIG_CHANGED = "admin.config_changed"

    # Backfill events
    BACKFILL_STARTED = "backfill.started"
    BACKFILL_COMPLETED = "backfill.completed"
    BACKFILL_FAILED = "backfill.failed"


class AuditLog(AuditBase):
    """
    Audit log database model.

    CRITICAL: This table is append-only. No UPDATE or DELETE operations are allowed.
    """
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(255), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    ip_address = Column(String(45), nullable=True)  # IPv6 max length
    user_agent = Column(Text, nullable=True)
    resource_type = Column(String(100), nullable=True, index=True)
    resource_id = Column(String(255), nullable=True, index=True)
    event_metadata = Column(JSONB, nullable=False, default=dict)
    correlation_id = Column(String(36), nullable=True, index=True)

    __table_args__ = (
        Index("ix_audit_logs_tenant_timestamp", "tenant_id", "timestamp"),
        Index("ix_audit_logs_tenant_action", "tenant_id", "action"),
        Index("ix_audit_logs_tenant_user", "tenant_id", "user_id"),
    )


@dataclass
class AuditEvent:
    """
    Immutable audit event data structure.

    Use this to construct audit events before writing to the database.
    """
    tenant_id: str
    user_id: str
    action: AuditAction
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "action": self.action.value if isinstance(self.action, AuditAction) else self.action,
            "timestamp": self.timestamp,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "event_metadata": self.metadata,
            "correlation_id": self.correlation_id,
        }


def extract_client_info(request: Request) -> tuple[Optional[str], Optional[str]]:
    """
    Extract client IP and user agent from request.

    Handles X-Forwarded-For for proxied requests.
    """
    # Get IP address (handle proxies)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP (client IP)
        ip_address = forwarded_for.split(",")[0].strip()
    else:
        ip_address = request.client.host if request.client else None

    # Get user agent
    user_agent = request.headers.get("User-Agent")

    return ip_address, user_agent


def get_correlation_id(request: Request) -> Optional[str]:
    """Get correlation ID from request state or headers."""
    if hasattr(request.state, "correlation_id"):
        return request.state.correlation_id
    return request.headers.get("X-Correlation-ID")


async def write_audit_log(
    db: AsyncSession,
    event: AuditEvent,
) -> AuditLog:
    """
    Write an audit event to the database.

    CRITICAL: This is an append-only operation. Events cannot be modified or deleted.

    Args:
        db: Database session
        event: The audit event to write

    Returns:
        The created AuditLog record
    """
    audit_log = AuditLog(
        id=str(uuid.uuid4()),
        **event.to_dict()
    )
    db.add(audit_log)
    await db.commit()
    await db.refresh(audit_log)

    logger.info(
        "Audit event recorded",
        extra={
            "audit_id": audit_log.id,
            "tenant_id": event.tenant_id,
            "user_id": event.user_id,
            "action": event.action.value if isinstance(event.action, AuditAction) else event.action,
            "resource_type": event.resource_type,
            "resource_id": event.resource_id,
            "correlation_id": event.correlation_id,
        }
    )

    return audit_log


async def log_audit_event(
    db: AsyncSession,
    request: Request,
    action: AuditAction,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> AuditLog:
    """
    Convenience function to log an audit event from a request context.

    Automatically extracts tenant context, IP, user agent, and correlation ID.

    Args:
        db: Database session
        request: FastAPI request object
        action: The audit action
        resource_type: Type of resource being acted upon (e.g., "store", "plan")
        resource_id: ID of the resource
        metadata: Additional metadata to include

    Returns:
        The created AuditLog record

    Example:
        await log_audit_event(
            db=db,
            request=request,
            action=AuditAction.STORE_CONNECTED,
            resource_type="store",
            resource_id=store_id,
            metadata={"shop_domain": "example.myshopify.com"}
        )
    """
    from src.platform.tenant_context import get_tenant_context

    tenant_context = get_tenant_context(request)
    ip_address, user_agent = extract_client_info(request)
    correlation_id = get_correlation_id(request)

    event = AuditEvent(
        tenant_id=tenant_context.tenant_id,
        user_id=tenant_context.user_id,
        action=action,
        ip_address=ip_address,
        user_agent=user_agent,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata=metadata or {},
        correlation_id=correlation_id,
    )

    return await write_audit_log(db, event)


async def log_system_audit_event(
    db: AsyncSession,
    tenant_id: str,
    action: AuditAction,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> AuditLog:
    """
    Log an audit event from a system context (background jobs, webhooks).

    Use this when there is no request context available.

    Args:
        db: Database session
        tenant_id: The tenant ID
        action: The audit action
        resource_type: Type of resource being acted upon
        resource_id: ID of the resource
        metadata: Additional metadata to include
        correlation_id: Optional correlation ID for tracing

    Returns:
        The created AuditLog record
    """
    event = AuditEvent(
        tenant_id=tenant_id,
        user_id="system",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata=metadata or {},
        correlation_id=correlation_id,
    )

    return await write_audit_log(db, event)


def create_audit_decorator(
    action: AuditAction,
    resource_type: Optional[str] = None,
    resource_id_param: Optional[str] = None,
):
    """
    Create a decorator that automatically logs audit events.

    Args:
        action: The audit action to log
        resource_type: Type of resource being acted upon
        resource_id_param: Name of the parameter that contains the resource ID

    Usage:
        @app.post("/api/stores/{store_id}/disconnect")
        @create_audit_decorator(AuditAction.STORE_DISCONNECTED, "store", "store_id")
        async def disconnect_store(request: Request, store_id: str, db: AsyncSession = Depends(get_db)):
            ...
    """
    def decorator(func):
        from functools import wraps

        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Execute the function first
            result = await func(*args, **kwargs)

            # Find request and db in kwargs
            request = kwargs.get("request")
            db = kwargs.get("db")

            if request and db:
                resource_id = kwargs.get(resource_id_param) if resource_id_param else None

                try:
                    await log_audit_event(
                        db=db,
                        request=request,
                        action=action,
                        resource_type=resource_type,
                        resource_id=str(resource_id) if resource_id else None,
                    )
                except Exception as e:
                    # Don't fail the request if audit logging fails
                    # But do log the error for investigation
                    logger.error(
                        "Failed to write audit log",
                        extra={
                            "error": str(e),
                            "action": action.value,
                            "resource_type": resource_type,
                            "resource_id": str(resource_id) if resource_id else None,
                        }
                    )

            return result
        return wrapper
    return decorator
