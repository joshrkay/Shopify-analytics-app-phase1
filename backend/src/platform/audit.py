"""
Audit logging for AI Growth Analytics.

CRITICAL SECURITY REQUIREMENTS:
- Audit logs MUST be append-only (no UPDATE/DELETE)
- All sensitive actions MUST write an audit event
- Events must include: tenant_id, user_id, action, timestamp, IP, user_agent, metadata
- PII fields MUST be redacted before persistence
- Failed logging attempts MUST fall back to secondary logger

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

Story 10.1 - Audit Event Schema & Logging Foundation
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, FrozenSet

from dataclasses import dataclass, field, asdict

from fastapi import Request
from sqlalchemy import Column, String, DateTime, Text, Index, Enum as SAEnum, JSON
from sqlalchemy.dialects.postgresql import JSONB

# Use JSON with PostgreSQL variant for JSONB - allows SQLite in tests
JSONType = JSON().with_variant(JSONB(), "postgresql")
from sqlalchemy.orm import Session

from src.db_base import Base
from src.monitoring.audit_metrics import get_audit_metrics
from src.monitoring.audit_alerts import get_audit_alert_manager

logger = logging.getLogger(__name__)
fallback_logger = logging.getLogger("audit.fallback")


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
    
    # Entitlement events
    ENTITLEMENT_DENIED = "entitlement.denied"
    ENTITLEMENT_ALLOWED = "entitlement.allowed"
    
    # Job entitlement events
    JOB_SKIPPED_DUE_TO_ENTITLEMENT = "job.skipped_due_to_entitlement"
    JOB_ALLOWED = "job.allowed"

    # AI Safety events (Story 8.6)
    AI_RATE_LIMIT_HIT = "ai.safety.rate_limit_hit"
    AI_COOLDOWN_ENFORCED = "ai.safety.cooldown_enforced"
    AI_ACTION_BLOCKED = "ai.safety.action_blocked"
    AI_ACTION_SUPPRESSED = "ai.safety.action_suppressed"
    AI_KILL_SWITCH_ACTIVATED = "ai.safety.kill_switch_activated"

    # AI Lifecycle events (Story 8.7)
    AI_INSIGHT_GENERATED = "ai.insight.generated"
    AI_RECOMMENDATION_CREATED = "ai.recommendation.created"
    AI_ACTION_CREATED = "ai.action.created"
    AI_ACTION_APPROVED = "ai.action.approved"
    AI_ACTION_EXECUTION_STARTED = "ai.action.execution_started"
    AI_ACTION_EXECUTION_SUCCEEDED = "ai.action.execution_succeeded"
    AI_ACTION_EXECUTION_FAILED = "ai.action.execution_failed"
    AI_ROLLBACK_REQUESTED = "ai.rollback.requested"
    AI_ROLLBACK_SUCCEEDED = "ai.rollback.succeeded"
    AI_ROLLBACK_FAILED = "ai.rollback.failed"

    # Data Access events (Story 10.1)
    DATA_ACCESSED = "data.accessed"
    DATA_EXPORTED = "data.exported"
    DATA_DELETED = "data.deleted"

    # Governance events (Story 10.1)
    GOVERNANCE_CONFIG_CHANGED = "governance.config_changed"
    GOVERNANCE_RETENTION_APPLIED = "governance.retention_applied"

    # Security events (Story 10.6)
    SECURITY_CROSS_TENANT_DENIED = "security.cross_tenant_denied"

    # Retention events (Story 10.4)
    AUDIT_RETENTION_STARTED = "audit.retention.started"
    AUDIT_RETENTION_COMPLETED = "audit.retention.completed"
    AUDIT_RETENTION_FAILED = "audit.retention.failed"

    # Identity events
    IDENTITY_USER_FIRST_SEEN = "identity.user_first_seen"
    IDENTITY_USER_LINKED_TO_TENANT = "identity.user_linked_to_tenant"
    IDENTITY_ROLE_ASSIGNED = "identity.role_assigned"
    IDENTITY_ROLE_REVOKED = "identity.role_revoked"
    IDENTITY_TENANT_CREATED = "identity.tenant_created"
    IDENTITY_TENANT_DEACTIVATED = "identity.tenant_deactivated"


class AuditOutcome(str, Enum):
    """Outcome of the audited action."""
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


class PIIRedactor:
    """
    Redacts PII fields from audit metadata before persistence.

    Redacted fields are replaced with "[REDACTED]" to maintain
    structure while removing sensitive data.

    Story 10.1 - Audit Event Schema & Logging Foundation
    """

    REDACTED_FIELDS: FrozenSet[str] = frozenset({
        # Authentication
        "email",
        "phone",
        "phone_number",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "api_secret",
        "password",
        "secret",
        "credential",
        "credentials",
        # Personal identifiers
        "ssn",
        "social_security",
        "tax_id",
        "national_id",
        # Financial
        "credit_card",
        "card_number",
        "cvv",
        "bank_account",
        "routing_number",
        # Address components
        "street_address",
        "address_line_1",
        "address_line_2",
    })

    REDACTION_MARKER = "[REDACTED]"

    @classmethod
    def redact(cls, data: dict[str, Any]) -> dict[str, Any]:
        """
        Recursively redact PII from a dictionary.

        Args:
            data: Dictionary potentially containing PII

        Returns:
            New dictionary with PII fields redacted
        """
        if not isinstance(data, dict):
            return data
        return cls._redact_dict(data)

    @classmethod
    def _redact_dict(cls, d: dict[str, Any]) -> dict[str, Any]:
        """Recursively process a dictionary."""
        result = {}
        for key, value in d.items():
            lower_key = key.lower()
            if lower_key in cls.REDACTED_FIELDS:
                result[key] = cls._redact_value(lower_key, value)
            elif isinstance(value, dict):
                result[key] = cls._redact_dict(value)
            elif isinstance(value, list):
                result[key] = cls._redact_list(value)
            else:
                result[key] = value
        return result

    @classmethod
    def _redact_value(cls, key: str, value: Any) -> str:
        """Redact a single value, with partial redaction for some fields."""
        if value is None:
            return cls.REDACTION_MARKER
        # Partial redaction for email (show domain)
        if key == "email" and isinstance(value, str) and "@" in value:
            try:
                return f"***@{value.split('@')[1]}"
            except (IndexError, AttributeError):
                return cls.REDACTION_MARKER
        # Partial redaction for phone (show last 4)
        if key in ("phone", "phone_number") and value:
            str_val = str(value)
            if len(str_val) >= 4:
                return f"***{str_val[-4:]}"
        return cls.REDACTION_MARKER

    @classmethod
    def _redact_list(cls, lst: list[Any]) -> list[Any]:
        """Process a list, redacting any nested dicts."""
        result = []
        for item in lst:
            if isinstance(item, dict):
                result.append(cls._redact_dict(item))
            elif isinstance(item, list):
                result.append(cls._redact_list(item))
            else:
                result.append(item)
        return result


class AuditLog(Base):
    """
    Audit log database model.

    CRITICAL: This table is append-only. No UPDATE or DELETE operations are allowed.
    Immutability is enforced via database trigger.

    Story 10.1 - Audit Event Schema & Logging Foundation
    """
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(255), nullable=False, index=True)
    user_id = Column(String(255), nullable=True, index=True)  # NULL for system events
    action = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    ip_address = Column(String(45), nullable=True)  # IPv6 max length
    user_agent = Column(Text, nullable=True)
    resource_type = Column(String(100), nullable=True, index=True)
    resource_id = Column(String(255), nullable=True, index=True)
    event_metadata = Column(JSONType, nullable=False, default=dict)
    correlation_id = Column(String(36), nullable=False, index=True)
    # New fields for Story 10.1
    source = Column(String(50), nullable=False, default="api")  # api, worker, system, webhook
    outcome = Column(String(20), nullable=False, default="success")  # success, failure, denied
    error_code = Column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_audit_logs_tenant_timestamp", "tenant_id", "timestamp"),
        Index("ix_audit_logs_tenant_action", "tenant_id", "action"),
        Index("ix_audit_logs_tenant_user", "tenant_id", "user_id"),
        Index("ix_audit_logs_correlation", "correlation_id"),
    )


@dataclass
class AuditEvent:
    """
    Immutable audit event data structure.

    Use this to construct audit events before writing to the database.
    PII in metadata is automatically redacted before persistence.

    Story 10.1 - Audit Event Schema & Logging Foundation
    """
    tenant_id: str
    action: AuditAction
    user_id: Optional[str] = None  # NULL for system events
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "api"  # api, worker, system, webhook
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    error_code: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion with PII redaction."""
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "action": self.action.value if isinstance(self.action, AuditAction) else self.action,
            "timestamp": self.timestamp,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "event_metadata": PIIRedactor.redact(self.metadata),
            "correlation_id": self.correlation_id,
            "source": self.source,
            "outcome": self.outcome.value if isinstance(self.outcome, AuditOutcome) else self.outcome,
            "error_code": self.error_code,
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


def write_audit_log_sync(
    db: Session,
    event: AuditEvent,
) -> Optional[AuditLog]:
    """
    Write an audit event to the database (synchronous version).

    CRITICAL: This is an append-only operation. Events cannot be modified or deleted.
    On failure, writes to fallback logger and returns None (never crashes request flow).

    Args:
        db: SQLAlchemy Session
        event: The audit event to write

    Returns:
        The created AuditLog record, or None if fallback was used

    Story 10.1 - Audit Event Schema & Logging Foundation
    """
    audit_id = str(uuid.uuid4())
    try:
        audit_log = AuditLog(
            id=audit_id,
            **event.to_dict()
        )
        db.add(audit_log)
        db.commit()

        action_str = event.action.value if isinstance(event.action, AuditAction) else event.action
        outcome_str = event.outcome.value if isinstance(event.outcome, AuditOutcome) else event.outcome

        logger.info(
            "Audit event recorded",
            extra={
                "audit_id": audit_log.id,
                "tenant_id": event.tenant_id,
                "user_id": event.user_id,
                "action": action_str,
                "correlation_id": event.correlation_id,
                "source": event.source,
                "outcome": outcome_str,
            }
        )

        # Record metric for monitoring
        get_audit_metrics().record_event(
            action=action_str,
            outcome=outcome_str,
            tenant_id=event.tenant_id,
            source=event.source,
        )

        return audit_log

    except Exception as e:
        # Rollback and fall back to stdout logging - NEVER crash
        try:
            db.rollback()
        except Exception:
            pass

        _write_fallback_log(event, audit_id, str(e))
        return None


def _write_fallback_log(event: AuditEvent, audit_id: str, error_reason: str) -> None:
    """Write audit event to fallback logger when primary DB fails."""
    fallback_entry = {
        "event_id": audit_id,
        "tenant_id": event.tenant_id,
        "user_id": event.user_id,
        "action": event.action.value if isinstance(event.action, AuditAction) else event.action,
        "timestamp": event.timestamp.isoformat(),
        "correlation_id": event.correlation_id,
        "source": event.source,
        "outcome": event.outcome.value if isinstance(event.outcome, AuditOutcome) else event.outcome,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "metadata": PIIRedactor.redact(event.metadata),
        "ip_address": event.ip_address,
        "fallback_reason": error_reason,
    }
    fallback_logger.error(
        "Audit log fallback",
        extra={"audit_entry": json.dumps(fallback_entry)},
    )

    # Record failure metric for monitoring/alerting
    get_audit_metrics().record_failure(
        error_type=type(Exception(error_reason)).__name__,
        tenant_id=event.tenant_id,
    )

    # Check alert threshold
    get_audit_alert_manager().record_logging_failure(
        tenant_id=event.tenant_id,
        error_type=type(Exception(error_reason)).__name__,
    )


async def write_audit_log(
    db: Session,
    event: AuditEvent,
) -> Optional[AuditLog]:
    """
    Write an audit event to the database (async-compatible wrapper).

    CRITICAL: This is an append-only operation. Events cannot be modified or deleted.
    On failure, writes to fallback logger and returns None (never crashes request flow).

    Args:
        db: Database session (sync or async)
        event: The audit event to write

    Returns:
        The created AuditLog record, or None if fallback was used

    Story 10.1 - Audit Event Schema & Logging Foundation
    """
    # Use sync version - works with both sync and async sessions
    return write_audit_log_sync(db, event)


def log_audit_event_sync(
    db: Session,
    request: Request,
    action: AuditAction,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    error_code: Optional[str] = None,
) -> str:
    """
    Log an audit event from a request context (synchronous version).

    Automatically extracts tenant context, IP, user agent, and correlation ID.
    Returns the correlation_id for request tracing.

    Args:
        db: Database session
        request: FastAPI request object
        action: The audit action
        resource_type: Type of resource being acted upon (e.g., "store", "plan")
        resource_id: ID of the resource
        metadata: Additional metadata to include
        outcome: Outcome of the action (success, failure, denied)
        error_code: Error code if outcome is failure

    Returns:
        The correlation_id for the logged event

    Story 10.1 - Audit Event Schema & Logging Foundation
    """
    from src.platform.tenant_context import get_tenant_context

    tenant_context = get_tenant_context(request)
    ip_address, user_agent = extract_client_info(request)
    correlation_id = get_correlation_id(request) or str(uuid.uuid4())

    event = AuditEvent(
        tenant_id=tenant_context.tenant_id,
        action=action,
        user_id=tenant_context.user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata=metadata or {},
        correlation_id=correlation_id,
        source="api",
        outcome=outcome,
        error_code=error_code,
    )

    write_audit_log_sync(db, event)
    return correlation_id


async def log_audit_event(
    db: Session,
    request: Request,
    action: AuditAction,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    error_code: Optional[str] = None,
) -> str:
    """
    Log an audit event from a request context (async-compatible).

    Automatically extracts tenant context, IP, user agent, and correlation ID.
    Returns the correlation_id for request tracing.

    Args:
        db: Database session
        request: FastAPI request object
        action: The audit action
        resource_type: Type of resource being acted upon (e.g., "store", "plan")
        resource_id: ID of the resource
        metadata: Additional metadata to include
        outcome: Outcome of the action (success, failure, denied)
        error_code: Error code if outcome is failure

    Returns:
        The correlation_id for the logged event

    Example:
        correlation_id = await log_audit_event(
            db=db,
            request=request,
            action=AuditAction.STORE_CONNECTED,
            resource_type="store",
            resource_id=store_id,
            metadata={"shop_domain": "example.myshopify.com"}
        )

    Story 10.1 - Audit Event Schema & Logging Foundation
    """
    return log_audit_event_sync(
        db=db,
        request=request,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata=metadata,
        outcome=outcome,
        error_code=error_code,
    )


def log_system_audit_event_sync(
    db: Session,
    tenant_id: str,
    action: AuditAction,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
    source: str = "system",
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    error_code: Optional[str] = None,
) -> str:
    """
    Log an audit event from a system context (synchronous version).

    Use this when there is no request context available.
    Returns the correlation_id for request tracing.

    Args:
        db: Database session
        tenant_id: The tenant ID
        action: The audit action
        resource_type: Type of resource being acted upon
        resource_id: ID of the resource
        metadata: Additional metadata to include
        correlation_id: Optional correlation ID for tracing
        source: Event source (system, worker, webhook)
        outcome: Outcome of the action
        error_code: Error code if outcome is failure

    Returns:
        The correlation_id for the logged event

    Story 10.1 - Audit Event Schema & Logging Foundation
    """
    correlation_id = correlation_id or str(uuid.uuid4())

    event = AuditEvent(
        tenant_id=tenant_id,
        action=action,
        user_id=None,  # System events have no user
        resource_type=resource_type,
        resource_id=resource_id,
        metadata=metadata or {},
        correlation_id=correlation_id,
        source=source,
        outcome=outcome,
        error_code=error_code,
    )

    write_audit_log_sync(db, event)
    return correlation_id


async def log_system_audit_event(
    db: Session,
    tenant_id: str,
    action: AuditAction,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
    source: str = "system",
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    error_code: Optional[str] = None,
) -> str:
    """
    Log an audit event from a system context (async-compatible).

    Use this when there is no request context available.
    Returns the correlation_id for request tracing.

    Args:
        db: Database session
        tenant_id: The tenant ID
        action: The audit action
        resource_type: Type of resource being acted upon
        resource_id: ID of the resource
        metadata: Additional metadata to include
        correlation_id: Optional correlation ID for tracing
        source: Event source (system, worker, webhook)
        outcome: Outcome of the action
        error_code: Error code if outcome is failure

    Returns:
        The correlation_id for the logged event

    Story 10.1 - Audit Event Schema & Logging Foundation
    """
    return log_system_audit_event_sync(
        db=db,
        tenant_id=tenant_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata=metadata,
        correlation_id=correlation_id,
        source=source,
        outcome=outcome,
        error_code=error_code,
    )


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


# =============================================================================
# Story 10.2 - Audit Event Coverage Enforcement
# =============================================================================


@dataclass
class AuditableEventMetadata:
    """
    Metadata for auditable events defining required fields and classification.

    Story 10.2 - Audit Event Coverage Enforcement
    """
    description: str
    required_fields: tuple[str, ...] = ()  # Metadata fields that must be present
    risk_level: str = "medium"  # high, medium, low
    compliance_tags: tuple[str, ...] = ()  # SOC2, GDPR, PCI, etc.


# Registry of all auditable events with their requirements
AUDITABLE_EVENTS: dict[AuditAction, AuditableEventMetadata] = {
    # Auth events - HIGH RISK
    AuditAction.AUTH_LOGIN: AuditableEventMetadata(
        description="User login attempt",
        required_fields=(),
        risk_level="high",
        compliance_tags=("SOC2", "GDPR"),
    ),
    AuditAction.AUTH_LOGOUT: AuditableEventMetadata(
        description="User logout",
        required_fields=(),
        risk_level="low",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AUTH_LOGIN_FAILED: AuditableEventMetadata(
        description="Failed login attempt",
        required_fields=("reason",),
        risk_level="high",
        compliance_tags=("SOC2", "GDPR"),
    ),
    AuditAction.AUTH_TOKEN_REFRESH: AuditableEventMetadata(
        description="Token refresh",
        required_fields=(),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AUTH_PASSWORD_CHANGE: AuditableEventMetadata(
        description="Password changed",
        required_fields=(),
        risk_level="high",
        compliance_tags=("SOC2", "GDPR"),
    ),
    AuditAction.AUTH_MFA_ENABLED: AuditableEventMetadata(
        description="MFA enabled",
        required_fields=(),
        risk_level="high",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AUTH_MFA_DISABLED: AuditableEventMetadata(
        description="MFA disabled",
        required_fields=(),
        risk_level="high",
        compliance_tags=("SOC2",),
    ),
    # Billing events - HIGH RISK
    AuditAction.BILLING_PLAN_CHANGED: AuditableEventMetadata(
        description="Billing plan changed",
        required_fields=("old_plan", "new_plan"),
        risk_level="high",
        compliance_tags=("SOC2", "PCI"),
    ),
    AuditAction.BILLING_SUBSCRIPTION_CREATED: AuditableEventMetadata(
        description="Subscription created",
        required_fields=("plan_id",),
        risk_level="high",
        compliance_tags=("SOC2", "PCI"),
    ),
    AuditAction.BILLING_SUBSCRIPTION_CANCELLED: AuditableEventMetadata(
        description="Subscription cancelled",
        required_fields=("reason",),
        risk_level="high",
        compliance_tags=("SOC2", "PCI"),
    ),
    AuditAction.BILLING_PAYMENT_FAILED: AuditableEventMetadata(
        description="Payment failed",
        required_fields=("error_code",),
        risk_level="high",
        compliance_tags=("SOC2", "PCI"),
    ),
    AuditAction.BILLING_PAYMENT_SUCCESS: AuditableEventMetadata(
        description="Payment successful",
        required_fields=("amount",),
        risk_level="medium",
        compliance_tags=("SOC2", "PCI"),
    ),
    # Store/connector events - MEDIUM RISK
    AuditAction.STORE_CONNECTED: AuditableEventMetadata(
        description="Store connected",
        required_fields=("shop_domain",),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    AuditAction.STORE_DISCONNECTED: AuditableEventMetadata(
        description="Store disconnected",
        required_fields=("shop_domain",),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    AuditAction.STORE_UPDATED: AuditableEventMetadata(
        description="Store settings updated",
        required_fields=(),
        risk_level="low",
        compliance_tags=("SOC2",),
    ),
    AuditAction.STORE_SYNC_STARTED: AuditableEventMetadata(
        description="Store sync started",
        required_fields=(),
        risk_level="low",
        compliance_tags=(),
    ),
    AuditAction.STORE_SYNC_COMPLETED: AuditableEventMetadata(
        description="Store sync completed",
        required_fields=(),
        risk_level="low",
        compliance_tags=(),
    ),
    AuditAction.STORE_SYNC_FAILED: AuditableEventMetadata(
        description="Store sync failed",
        required_fields=("error",),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    # AI events - HIGH RISK
    AuditAction.AI_KEY_CREATED: AuditableEventMetadata(
        description="AI API key created",
        required_fields=("key_type",),
        risk_level="high",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AI_KEY_ROTATED: AuditableEventMetadata(
        description="AI API key rotated",
        required_fields=("key_type",),
        risk_level="high",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AI_KEY_DELETED: AuditableEventMetadata(
        description="AI API key deleted",
        required_fields=("key_type",),
        risk_level="high",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AI_MODEL_CHANGED: AuditableEventMetadata(
        description="AI model configuration changed",
        required_fields=("old_model", "new_model"),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AI_ACTION_REQUESTED: AuditableEventMetadata(
        description="AI action requested",
        required_fields=("action_type",),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AI_ACTION_EXECUTED: AuditableEventMetadata(
        description="AI action executed",
        required_fields=("action_type",),
        risk_level="high",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AI_ACTION_REJECTED: AuditableEventMetadata(
        description="AI action rejected",
        required_fields=("action_type", "reason"),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    # Export events - HIGH RISK (data exfiltration)
    AuditAction.EXPORT_REQUESTED: AuditableEventMetadata(
        description="Data export requested",
        required_fields=("export_type",),
        risk_level="high",
        compliance_tags=("SOC2", "GDPR"),
    ),
    AuditAction.EXPORT_COMPLETED: AuditableEventMetadata(
        description="Data export completed",
        required_fields=("export_type", "record_count"),
        risk_level="high",
        compliance_tags=("SOC2", "GDPR"),
    ),
    AuditAction.EXPORT_FAILED: AuditableEventMetadata(
        description="Data export failed",
        required_fields=("export_type", "error"),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    AuditAction.EXPORT_DOWNLOADED: AuditableEventMetadata(
        description="Export file downloaded",
        required_fields=("export_id",),
        risk_level="high",
        compliance_tags=("SOC2", "GDPR"),
    ),
    # Automation events - MEDIUM RISK
    AuditAction.AUTOMATION_CREATED: AuditableEventMetadata(
        description="Automation created",
        required_fields=("automation_type",),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AUTOMATION_UPDATED: AuditableEventMetadata(
        description="Automation updated",
        required_fields=(),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AUTOMATION_DELETED: AuditableEventMetadata(
        description="Automation deleted",
        required_fields=(),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AUTOMATION_APPROVED: AuditableEventMetadata(
        description="Automation approved",
        required_fields=(),
        risk_level="high",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AUTOMATION_REJECTED: AuditableEventMetadata(
        description="Automation rejected",
        required_fields=("reason",),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AUTOMATION_EXECUTED: AuditableEventMetadata(
        description="Automation executed",
        required_fields=(),
        risk_level="high",
        compliance_tags=("SOC2",),
    ),
    AuditAction.AUTOMATION_FAILED: AuditableEventMetadata(
        description="Automation failed",
        required_fields=("error",),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    # Feature flag events - MEDIUM RISK
    AuditAction.FEATURE_FLAG_ENABLED: AuditableEventMetadata(
        description="Feature flag enabled",
        required_fields=("flag_name",),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    AuditAction.FEATURE_FLAG_DISABLED: AuditableEventMetadata(
        description="Feature flag disabled",
        required_fields=("flag_name",),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    AuditAction.FEATURE_FLAG_OVERRIDE: AuditableEventMetadata(
        description="Feature flag override set",
        required_fields=("flag_name", "override_value"),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    # Team/permission events - HIGH RISK
    AuditAction.TEAM_MEMBER_INVITED: AuditableEventMetadata(
        description="Team member invited",
        required_fields=("role",),
        risk_level="high",
        compliance_tags=("SOC2", "GDPR"),
    ),
    AuditAction.TEAM_MEMBER_REMOVED: AuditableEventMetadata(
        description="Team member removed",
        required_fields=(),
        risk_level="high",
        compliance_tags=("SOC2", "GDPR"),
    ),
    AuditAction.TEAM_ROLE_CHANGED: AuditableEventMetadata(
        description="Team role changed",
        required_fields=("old_role", "new_role"),
        risk_level="high",
        compliance_tags=("SOC2",),
    ),
    # Settings events - LOW RISK
    AuditAction.SETTINGS_UPDATED: AuditableEventMetadata(
        description="Settings updated",
        required_fields=(),
        risk_level="low",
        compliance_tags=("SOC2",),
    ),
    # Admin events - HIGH RISK
    AuditAction.ADMIN_PLAN_CREATED: AuditableEventMetadata(
        description="Admin created plan",
        required_fields=("plan_name",),
        risk_level="high",
        compliance_tags=("SOC2",),
    ),
    AuditAction.ADMIN_PLAN_UPDATED: AuditableEventMetadata(
        description="Admin updated plan",
        required_fields=("plan_name",),
        risk_level="high",
        compliance_tags=("SOC2",),
    ),
    AuditAction.ADMIN_PLAN_DELETED: AuditableEventMetadata(
        description="Admin deleted plan",
        required_fields=("plan_name",),
        risk_level="high",
        compliance_tags=("SOC2",),
    ),
    AuditAction.ADMIN_CONFIG_CHANGED: AuditableEventMetadata(
        description="Admin configuration changed",
        required_fields=("config_key",),
        risk_level="high",
        compliance_tags=("SOC2",),
    ),
    # Backfill events - MEDIUM RISK
    AuditAction.BACKFILL_STARTED: AuditableEventMetadata(
        description="Data backfill started",
        required_fields=("backfill_type",),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    AuditAction.BACKFILL_COMPLETED: AuditableEventMetadata(
        description="Data backfill completed",
        required_fields=("backfill_type", "record_count"),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    AuditAction.BACKFILL_FAILED: AuditableEventMetadata(
        description="Data backfill failed",
        required_fields=("backfill_type", "error"),
        risk_level="medium",
        compliance_tags=("SOC2",),
    ),
    # Data access events - HIGH RISK
    AuditAction.DATA_ACCESSED: AuditableEventMetadata(
        description="Sensitive data accessed",
        required_fields=("data_type",),
        risk_level="high",
        compliance_tags=("SOC2", "GDPR"),
    ),
    AuditAction.DATA_EXPORTED: AuditableEventMetadata(
        description="Data exported",
        required_fields=("data_type", "record_count"),
        risk_level="high",
        compliance_tags=("SOC2", "GDPR"),
    ),
    AuditAction.DATA_DELETED: AuditableEventMetadata(
        description="Data deleted",
        required_fields=("data_type",),
        risk_level="high",
        compliance_tags=("SOC2", "GDPR"),
    ),
    # Governance events - HIGH RISK
    AuditAction.GOVERNANCE_CONFIG_CHANGED: AuditableEventMetadata(
        description="Governance configuration changed",
        required_fields=("config_type",),
        risk_level="high",
        compliance_tags=("SOC2", "GDPR"),
    ),
    AuditAction.GOVERNANCE_RETENTION_APPLIED: AuditableEventMetadata(
        description="Data retention policy applied",
        required_fields=("retention_period", "records_affected"),
        risk_level="high",
        compliance_tags=("SOC2", "GDPR"),
    ),
}


def validate_audit_metadata(
    action: AuditAction,
    metadata: dict[str, Any],
    strict: bool = False,
) -> list[str]:
    """
    Validate that audit metadata contains required fields.

    Args:
        action: The audit action
        metadata: The metadata dictionary
        strict: If True, raises error; if False, returns list of warnings

    Returns:
        List of validation warnings (empty if valid)

    Story 10.2 - Audit Event Coverage Enforcement
    """
    warnings = []

    event_meta = AUDITABLE_EVENTS.get(action)
    if not event_meta:
        warnings.append(f"Action {action.value} not in AUDITABLE_EVENTS registry")
        return warnings

    for required_field in event_meta.required_fields:
        if required_field not in metadata:
            warnings.append(
                f"Missing required field '{required_field}' for action {action.value}"
            )

    if strict and warnings:
        raise ValueError("; ".join(warnings))

    return warnings


def require_audit(
    action: AuditAction,
    resource_type: Optional[str] = None,
    resource_id_param: Optional[str] = None,
    validate_metadata: bool = True,
):
    """
    Decorator that enforces audit logging on sensitive endpoints.

    Logs audit event after successful execution. Validates metadata
    against AUDITABLE_EVENTS registry if validate_metadata is True.

    Args:
        action: The audit action to log
        resource_type: Type of resource being acted upon
        resource_id_param: Parameter name containing resource ID
        validate_metadata: Whether to validate metadata fields

    Usage:
        @app.post("/api/billing/plan")
        @require_audit(AuditAction.BILLING_PLAN_CHANGED, "plan")
        async def change_plan(
            request: Request,
            plan_data: PlanChange,
            db: AsyncSession = Depends(get_db)
        ):
            # audit_metadata is automatically extracted from response or set via request.state
            return {"old_plan": "free", "new_plan": "pro"}

    Story 10.2 - Audit Event Coverage Enforcement
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

                # Get metadata from request.state if set, otherwise from result
                metadata = {}
                if hasattr(request.state, "audit_metadata"):
                    metadata = request.state.audit_metadata
                elif isinstance(result, dict):
                    # Extract metadata from response dict
                    event_meta = AUDITABLE_EVENTS.get(action)
                    if event_meta:
                        for field in event_meta.required_fields:
                            if field in result:
                                metadata[field] = result[field]

                # Validate metadata if enabled
                if validate_metadata:
                    warnings = validate_audit_metadata(action, metadata)
                    for warning in warnings:
                        logger.warning(
                            f"Audit metadata validation: {warning}",
                            extra={
                                "action": action.value,
                                "resource_type": resource_type,
                            }
                        )

                try:
                    await log_audit_event(
                        db=db,
                        request=request,
                        action=action,
                        resource_type=resource_type,
                        resource_id=str(resource_id) if resource_id else None,
                        metadata=metadata,
                    )
                except Exception as e:
                    # Never fail the request if audit logging fails
                    logger.error(
                        "Failed to write required audit log",
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


def get_high_risk_actions() -> list[AuditAction]:
    """Get all high-risk actions that require strict auditing."""
    return [
        action for action, meta in AUDITABLE_EVENTS.items()
        if meta.risk_level == "high"
    ]


def get_compliance_actions(tag: str) -> list[AuditAction]:
    """Get all actions with a specific compliance tag (SOC2, GDPR, PCI)."""
    return [
        action for action, meta in AUDITABLE_EVENTS.items()
        if tag in meta.compliance_tags
    ]


# =============================================================================
# Story 10.3 - Audit Log Export
# =============================================================================


class AuditExportFormat(str, Enum):
    """Supported export formats for audit logs."""
    CSV = "csv"
    JSON = "json"


@dataclass
class AuditExportRequest:
    """Request parameters for audit log export."""
    tenant_id: str
    format: AuditExportFormat = AuditExportFormat.CSV
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    actions: Optional[list[AuditAction]] = None
    user_id: Optional[str] = None
    limit: int = 10000
    offset: int = 0


@dataclass
class AuditExportResult:
    """Result of an audit log export."""
    success: bool
    record_count: int
    format: AuditExportFormat
    content: Optional[str] = None
    error: Optional[str] = None
    export_id: Optional[str] = None
    is_async: bool = False


class AuditExportService:
    """
    Service for exporting audit logs to CSV or JSON.

    Features:
    - CSV and JSON export formats
    - Rate limiting (3 exports/tenant/24 hours)
    - Async job support for large exports (>10K rows)
    - Automatic audit logging of export events

    Story 10.3 - Audit Log Export

    Usage:
        service = AuditExportService(db)
        result = await service.export_audit_logs(
            tenant_id="tenant-123",
            format=AuditExportFormat.CSV,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
        )
    """

    # Rate limit: 3 exports per tenant per 24 hours
    RATE_LIMIT_EXPORTS = 3
    RATE_LIMIT_WINDOW_HOURS = 24

    # Threshold for async export
    ASYNC_THRESHOLD_ROWS = 10000

    def __init__(self, db: Session):
        self.db = db
        self._export_counts: dict[str, list[datetime]] = {}  # In-memory for simplicity

    def check_rate_limit(self, tenant_id: str) -> tuple[bool, int]:
        """
        Check if tenant is within rate limit.

        Args:
            tenant_id: The tenant ID

        Returns:
            Tuple of (is_allowed, remaining_exports)
        """
        now = datetime.now(timezone.utc)
        window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Clean old entries
        if tenant_id in self._export_counts:
            self._export_counts[tenant_id] = [
                ts for ts in self._export_counts[tenant_id]
                if ts >= window_start
            ]
        else:
            self._export_counts[tenant_id] = []

        current_count = len(self._export_counts[tenant_id])
        remaining = self.RATE_LIMIT_EXPORTS - current_count

        return remaining > 0, max(0, remaining)

    def record_export(self, tenant_id: str) -> None:
        """Record an export for rate limiting."""
        if tenant_id not in self._export_counts:
            self._export_counts[tenant_id] = []
        self._export_counts[tenant_id].append(datetime.now(timezone.utc))

    def query_audit_logs(
        self,
        tenant_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        actions: Optional[list[AuditAction]] = None,
        user_id: Optional[str] = None,
        limit: int = 10000,
        offset: int = 0,
    ) -> list[AuditLog]:
        """
        Query audit logs with filters.

        Args:
            tenant_id: Required tenant ID
            start_date: Optional start date filter
            end_date: Optional end date filter
            actions: Optional list of actions to filter
            user_id: Optional user ID filter
            limit: Maximum records to return
            offset: Offset for pagination

        Returns:
            List of AuditLog records
        """
        query = self.db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)

        if start_date:
            query = query.filter(AuditLog.timestamp >= start_date)
        if end_date:
            query = query.filter(AuditLog.timestamp <= end_date)
        if actions:
            action_values = [a.value for a in actions]
            query = query.filter(AuditLog.action.in_(action_values))
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)

        query = query.order_by(AuditLog.timestamp.desc())
        query = query.offset(offset).limit(limit)

        return query.all()

    def count_audit_logs(
        self,
        tenant_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        actions: Optional[list[AuditAction]] = None,
        user_id: Optional[str] = None,
    ) -> int:
        """Count audit logs matching filters."""
        from sqlalchemy import func

        query = self.db.query(func.count(AuditLog.id)).filter(
            AuditLog.tenant_id == tenant_id
        )

        if start_date:
            query = query.filter(AuditLog.timestamp >= start_date)
        if end_date:
            query = query.filter(AuditLog.timestamp <= end_date)
        if actions:
            action_values = [a.value for a in actions]
            query = query.filter(AuditLog.action.in_(action_values))
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)

        return query.scalar() or 0

    def format_csv(self, logs: list[AuditLog]) -> str:
        """
        Format audit logs as CSV.

        Args:
            logs: List of AuditLog records

        Returns:
            CSV string
        """
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)

        # Header row
        headers = [
            "id", "timestamp", "tenant_id", "user_id", "action",
            "resource_type", "resource_id", "ip_address", "user_agent",
            "source", "outcome", "error_code", "correlation_id", "metadata"
        ]
        writer.writerow(headers)

        # Data rows
        for log in logs:
            metadata_json = json.dumps(log.event_metadata) if log.event_metadata else "{}"
            writer.writerow([
                log.id,
                log.timestamp.isoformat() if log.timestamp else "",
                log.tenant_id,
                log.user_id or "",
                log.action,
                log.resource_type or "",
                log.resource_id or "",
                log.ip_address or "",
                log.user_agent or "",
                log.source,
                log.outcome,
                log.error_code or "",
                log.correlation_id,
                metadata_json,
            ])

        return output.getvalue()

    def format_json(self, logs: list[AuditLog]) -> str:
        """
        Format audit logs as JSON.

        Args:
            logs: List of AuditLog records

        Returns:
            JSON string
        """
        records = []
        for log in logs:
            records.append({
                "id": log.id,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "tenant_id": log.tenant_id,
                "user_id": log.user_id,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "source": log.source,
                "outcome": log.outcome,
                "error_code": log.error_code,
                "correlation_id": log.correlation_id,
                "metadata": log.event_metadata,
            })

        return json.dumps({"audit_logs": records, "count": len(records)}, indent=2)

    async def export_audit_logs(
        self,
        request: AuditExportRequest,
        requesting_user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> AuditExportResult:
        """
        Export audit logs to CSV or JSON.

        Args:
            request: Export request parameters
            requesting_user_id: User ID of the person requesting export
            ip_address: IP address of requester

        Returns:
            AuditExportResult with content or error
        """
        export_id = str(uuid.uuid4())

        # Check rate limit
        is_allowed, remaining = self.check_rate_limit(request.tenant_id)
        if not is_allowed:
            # Log the denied export attempt
            log_system_audit_event_sync(
                db=self.db,
                tenant_id=request.tenant_id,
                action=AuditAction.EXPORT_FAILED,
                metadata={
                    "export_type": "audit_logs",
                    "error": "Rate limit exceeded",
                    "format": request.format.value,
                },
                outcome=AuditOutcome.DENIED,
                error_code="RATE_LIMIT_EXCEEDED",
            )
            return AuditExportResult(
                success=False,
                record_count=0,
                format=request.format,
                error=f"Rate limit exceeded. Maximum {self.RATE_LIMIT_EXPORTS} exports per day.",
                export_id=export_id,
            )

        try:
            # Count total records
            total_count = self.count_audit_logs(
                tenant_id=request.tenant_id,
                start_date=request.start_date,
                end_date=request.end_date,
                actions=request.actions,
                user_id=request.user_id,
            )

            # Check if async export is needed
            if total_count > self.ASYNC_THRESHOLD_ROWS:
                # Log async export request
                log_system_audit_event_sync(
                    db=self.db,
                    tenant_id=request.tenant_id,
                    action=AuditAction.EXPORT_REQUESTED,
                    metadata={
                        "export_type": "audit_logs",
                        "format": request.format.value,
                        "record_count": total_count,
                        "export_id": export_id,
                        "async": True,
                    },
                    outcome=AuditOutcome.SUCCESS,
                )

                return AuditExportResult(
                    success=True,
                    record_count=total_count,
                    format=request.format,
                    export_id=export_id,
                    is_async=True,
                    error=f"Export queued for async processing ({total_count} records)",
                )

            # Log export request
            log_system_audit_event_sync(
                db=self.db,
                tenant_id=request.tenant_id,
                action=AuditAction.EXPORT_REQUESTED,
                metadata={
                    "export_type": "audit_logs",
                    "format": request.format.value,
                    "export_id": export_id,
                },
                outcome=AuditOutcome.SUCCESS,
            )

            # Query logs
            logs = self.query_audit_logs(
                tenant_id=request.tenant_id,
                start_date=request.start_date,
                end_date=request.end_date,
                actions=request.actions,
                user_id=request.user_id,
                limit=request.limit,
                offset=request.offset,
            )

            # Format output
            if request.format == AuditExportFormat.CSV:
                content = self.format_csv(logs)
            else:
                content = self.format_json(logs)

            # Record export for rate limiting
            self.record_export(request.tenant_id)

            # Log export completion
            log_system_audit_event_sync(
                db=self.db,
                tenant_id=request.tenant_id,
                action=AuditAction.EXPORT_COMPLETED,
                metadata={
                    "export_type": "audit_logs",
                    "format": request.format.value,
                    "record_count": len(logs),
                    "export_id": export_id,
                },
                outcome=AuditOutcome.SUCCESS,
            )

            return AuditExportResult(
                success=True,
                record_count=len(logs),
                format=request.format,
                content=content,
                export_id=export_id,
            )

        except Exception as e:
            logger.error(
                "Audit export failed",
                extra={
                    "tenant_id": request.tenant_id,
                    "export_id": export_id,
                    "error": str(e),
                }
            )

            # Log export failure
            log_system_audit_event_sync(
                db=self.db,
                tenant_id=request.tenant_id,
                action=AuditAction.EXPORT_FAILED,
                metadata={
                    "export_type": "audit_logs",
                    "format": request.format.value,
                    "error": str(e),
                    "export_id": export_id,
                },
                outcome=AuditOutcome.FAILURE,
                error_code="EXPORT_ERROR",
            )

            return AuditExportResult(
                success=False,
                record_count=0,
                format=request.format,
                error=str(e),
                export_id=export_id,
            )
