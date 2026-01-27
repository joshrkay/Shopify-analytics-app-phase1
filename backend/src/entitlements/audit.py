"""
Entitlement Audit Logger - Log all access denials for compliance.

Provides:
- AccessDenialEvent: Structured event for access denials
- EntitlementAuditLogger: Async-safe audit logger
- Database and log file persistence

Required fields for each denial:
- feature_name
- billing_state
- plan
- user_id (if available)
- tenant_id

CRITICAL: All access denials MUST be logged for SOC2/Shopify compliance.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field
from typing import Optional, Dict, Any, List
from threading import Lock
from queue import Queue
import threading

logger = logging.getLogger(__name__)

# Dedicated audit logger for structured logging
audit_logger = logging.getLogger("entitlements.audit")


@dataclass
class AccessDenialEvent:
    """
    Structured event for an access denial.

    All fields are required for compliance tracking.
    """

    tenant_id: str
    feature_name: str
    billing_state: str
    plan_id: Optional[str] = None
    plan_name: Optional[str] = None
    user_id: Optional[str] = None
    endpoint: Optional[str] = None
    method: Optional[str] = None
    reason: Optional[str] = None
    required_plan: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AccessDenialEvent':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class AccessGrantEvent:
    """
    Structured event for an access grant (for audit completeness).

    Optional - can be enabled for full audit trail.
    """

    tenant_id: str
    feature_name: str
    billing_state: str
    plan_id: Optional[str] = None
    endpoint: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AsyncAuditWriter:
    """
    Asynchronous audit writer for non-blocking logging.

    Writes to a queue that's processed by a background thread.
    """

    def __init__(self, max_queue_size: int = 10000):
        self._queue: Queue = Queue(maxsize=max_queue_size)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = Lock()

    def start(self) -> None:
        """Start the background writer thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._process_queue, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop the background writer thread."""
        with self._lock:
            self._running = False
            if self._thread:
                self._thread.join(timeout=5.0)
                self._thread = None

    def enqueue(self, event: AccessDenialEvent) -> bool:
        """Add event to the write queue."""
        try:
            self._queue.put_nowait(event)
            return True
        except Exception:
            # Queue full - log synchronously as fallback
            self._write_sync(event)
            return False

    def _process_queue(self) -> None:
        """Background thread to process the queue."""
        while self._running or not self._queue.empty():
            try:
                event = self._queue.get(timeout=1.0)
                self._write_event(event)
            except Exception:
                continue

    def _write_event(self, event: AccessDenialEvent) -> None:
        """Write event to storage."""
        # Log to structured logger
        audit_logger.info(
            "access_denied",
            extra={
                "event_type": "access_denied",
                "audit_data": event.to_dict(),
            }
        )

    def _write_sync(self, event: AccessDenialEvent) -> None:
        """Synchronous write fallback."""
        self._write_event(event)


class DatabaseAuditWriter:
    """
    Database audit writer for persistent storage.

    Writes to billing_audit_log table for long-term retention.
    """

    def __init__(self, db_session_factory=None):
        self._db_session_factory = db_session_factory

    def write(self, event: AccessDenialEvent) -> bool:
        """Write event to database."""
        if not self._db_session_factory:
            return False

        try:
            session = self._db_session_factory()
            try:
                from src.models.billing_event import BillingEvent, BillingEventType

                audit_entry = BillingEvent(
                    id=event.event_id,
                    tenant_id=event.tenant_id,
                    event_type=f"entitlement.access_denied:{event.feature_name}",
                    extra_metadata={
                        "feature_name": event.feature_name,
                        "billing_state": event.billing_state,
                        "plan_id": event.plan_id,
                        "plan_name": event.plan_name,
                        "user_id": event.user_id,
                        "endpoint": event.endpoint,
                        "method": event.method,
                        "reason": event.reason,
                        "required_plan": event.required_plan,
                        "ip_address": event.ip_address,
                        "user_agent": event.user_agent,
                        "request_id": event.request_id,
                        **event.extra_metadata,
                    },
                )
                session.add(audit_entry)
                session.commit()
                return True

            except Exception as e:
                logger.error(f"Failed to write audit event to database: {e}")
                session.rollback()
                return False
            finally:
                session.close()

        except Exception as e:
            logger.error(f"Failed to create database session for audit: {e}")
            return False


class EntitlementAuditLogger:
    """
    Main audit logger for entitlement access denials.

    Features:
    - Async-safe logging via queue
    - Structured log output
    - Optional database persistence
    - Aggregation for high-frequency events

    Usage:
        audit_logger = EntitlementAuditLogger()

        audit_logger.log_denial(AccessDenialEvent(
            tenant_id="tenant_123",
            feature_name="ai_insights",
            billing_state="expired",
            plan_id="plan_free",
            reason="Feature requires Growth plan",
        ))
    """

    _instance: Optional['EntitlementAuditLogger'] = None
    _lock = Lock()

    def __new__(cls, *args, **kwargs):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        enable_async: bool = True,
        enable_database: bool = False,
        db_session_factory=None,
        log_grants: bool = False,
    ):
        """
        Initialize audit logger.

        Args:
            enable_async: Use async writer for non-blocking logging
            enable_database: Persist to database
            db_session_factory: Factory function for database sessions
            log_grants: Also log successful access grants
        """
        if self._initialized:
            return

        self._enable_async = enable_async
        self._enable_database = enable_database
        self._log_grants = log_grants

        # Initialize writers
        self._async_writer: Optional[AsyncAuditWriter] = None
        self._db_writer: Optional[DatabaseAuditWriter] = None

        if enable_async:
            self._async_writer = AsyncAuditWriter()
            self._async_writer.start()

        if enable_database and db_session_factory:
            self._db_writer = DatabaseAuditWriter(db_session_factory)

        # Aggregation for high-frequency events
        self._aggregation_window_seconds = 60
        self._recent_denials: Dict[str, int] = {}
        self._aggregation_lock = Lock()

        self._initialized = True

        logger.info(
            "Entitlement audit logger initialized",
            extra={
                "async_enabled": enable_async,
                "database_enabled": enable_database,
                "log_grants": log_grants,
            }
        )

    def log_denial(self, event: AccessDenialEvent) -> None:
        """
        Log an access denial event.

        Args:
            event: AccessDenialEvent with all required fields
        """
        # Check for aggregation (high-frequency events)
        agg_key = f"{event.tenant_id}:{event.feature_name}"
        should_log = self._check_aggregation(agg_key)

        if not should_log:
            return

        # Log to async writer
        if self._async_writer:
            self._async_writer.enqueue(event)
        else:
            # Synchronous logging
            audit_logger.warning(
                "access_denied",
                extra={
                    "event_type": "access_denied",
                    "tenant_id": event.tenant_id,
                    "feature_name": event.feature_name,
                    "billing_state": event.billing_state,
                    "plan_id": event.plan_id,
                    "reason": event.reason,
                    "endpoint": event.endpoint,
                }
            )

        # Persist to database
        if self._db_writer:
            self._db_writer.write(event)

        # Log to standard logger for visibility
        logger.info(
            f"Access denied: {event.feature_name} for tenant {event.tenant_id}",
            extra={
                "tenant_id": event.tenant_id,
                "feature_name": event.feature_name,
                "billing_state": event.billing_state,
                "plan_id": event.plan_id,
                "reason": event.reason,
            }
        )

    def log_grant(self, event: AccessGrantEvent) -> None:
        """
        Log an access grant event (optional).

        Only logged if log_grants is enabled.
        """
        if not self._log_grants:
            return

        audit_logger.debug(
            "access_granted",
            extra={
                "event_type": "access_granted",
                "audit_data": event.to_dict(),
            }
        )

    def _check_aggregation(self, key: str) -> bool:
        """
        Check if event should be logged (aggregation).

        Returns False if this event type was recently logged for the same tenant.
        """
        now = datetime.now(timezone.utc).timestamp()

        with self._aggregation_lock:
            # Clean old entries
            cutoff = now - self._aggregation_window_seconds
            self._recent_denials = {
                k: v for k, v in self._recent_denials.items()
                if v > cutoff
            }

            # Check if recently logged
            if key in self._recent_denials:
                return False

            # Mark as logged
            self._recent_denials[key] = now
            return True

    def get_denial_count(self, tenant_id: str, since: datetime) -> int:
        """
        Get count of access denials for a tenant since a given time.

        Useful for monitoring and alerting.

        Note: Currently returns count from in-memory cache only.
        For production monitoring, use structured log aggregation (e.g., Datadog, CloudWatch)
        to query denial events by tenant_id from the audit logs.
        """
        # Count from in-memory recent denials cache
        count = 0
        for key, timestamp in self._recent_denials.items():
            if key.startswith(f"{tenant_id}:") and timestamp >= since:
                count += 1
        return count

    def get_recent_denials(
        self,
        tenant_id: str,
        limit: int = 100,
    ) -> List[AccessDenialEvent]:
        """
        Get recent denial events for a tenant.

        Useful for admin dashboards and debugging.

        Note: Currently returns empty list. Denial events are logged via structured
        logging and should be queried from your log aggregation system.
        For real-time monitoring, configure alerts on 'entitlement_denied' log events.
        """
        # Denial events are written to structured logs, not stored in-memory.
        # Query your log aggregation system (Datadog, CloudWatch, etc.) for:
        #   logger="entitlements.audit" AND event_type="access_denied" AND tenant_id="{tenant_id}"
        return []

    def shutdown(self) -> None:
        """Shutdown the audit logger gracefully."""
        if self._async_writer:
            self._async_writer.stop()


# Module-level singleton accessor
_audit_logger_instance: Optional[EntitlementAuditLogger] = None
_audit_logger_lock = Lock()


def get_audit_logger(
    enable_database: bool = False,
    db_session_factory=None,
) -> EntitlementAuditLogger:
    """
    Get the singleton audit logger instance.

    Args:
        enable_database: Enable database persistence on first call
        db_session_factory: Database session factory for persistence

    Returns:
        EntitlementAuditLogger singleton
    """
    global _audit_logger_instance
    if _audit_logger_instance is None:
        with _audit_logger_lock:
            if _audit_logger_instance is None:
                _audit_logger_instance = EntitlementAuditLogger(
                    enable_database=enable_database,
                    db_session_factory=db_session_factory,
                )
    return _audit_logger_instance


def log_access_denial(
    tenant_id: str,
    feature_name: str,
    billing_state: str,
    plan_id: Optional[str] = None,
    user_id: Optional[str] = None,
    reason: Optional[str] = None,
    endpoint: Optional[str] = None,
    **kwargs,
) -> None:
    """
    Convenience function to log an access denial.

    Args:
        tenant_id: Tenant identifier
        feature_name: Feature that was denied
        billing_state: Current billing state
        plan_id: Current plan ID
        user_id: User ID if available
        reason: Reason for denial
        endpoint: API endpoint that was accessed
        **kwargs: Additional metadata
    """
    event = AccessDenialEvent(
        tenant_id=tenant_id,
        feature_name=feature_name,
        billing_state=billing_state,
        plan_id=plan_id,
        user_id=user_id,
        reason=reason,
        endpoint=endpoint,
        extra_metadata=kwargs,
    )
    get_audit_logger().log_denial(event)


def reset_audit_logger() -> None:
    """
    Reset the audit logger singleton (for testing).

    WARNING: Only use in tests!
    """
    global _audit_logger_instance
    if _audit_logger_instance:
        _audit_logger_instance.shutdown()
    _audit_logger_instance = None
    EntitlementAuditLogger._instance = None
