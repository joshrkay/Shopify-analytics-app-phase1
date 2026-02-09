"""
GA Audit Log Model for auth and dashboard access events.

Canonical, append-only audit log with:
- PII auto-redaction via sanitization layer
- Correlation ID generation for every request
- Multi-tenant scoping (tenant_id on every row)
- access_surface tracking (shopify_embed | external_app)

CRITICAL SECURITY:
- This table is append-only. No UPDATE or DELETE except retention job.
- PII is stripped before persistence via PIIRedactor.
- tenant_id is ALWAYS from JWT, NEVER from client input.

GA Scope: auth events + dashboard access only.
"""

import uuid
import re
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, FrozenSet, Optional

from dataclasses import dataclass, field

from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    Index,
    JSON,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.db_base import Base

logger = logging.getLogger(__name__)

# Use JSON with PostgreSQL variant for JSONB - allows SQLite in tests
JSONType = JSON().with_variant(JSONB(), "postgresql")


# ---------------------------------------------------------------------------
# GA Event Types (auth + dashboard only)
# ---------------------------------------------------------------------------

class AuditEventType(str, Enum):
    """GA-scope audit event types for auth and dashboard access."""

    # Auth events
    AUTH_LOGIN_SUCCESS = "auth.login_success"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_JWT_ISSUED = "auth.jwt_issued"
    AUTH_JWT_REFRESH = "auth.jwt_refresh"
    AUTH_JWT_REVOKED = "auth.jwt_revoked"

    # Dashboard events
    DASHBOARD_VIEWED = "dashboard.viewed"
    DASHBOARD_LOAD_FAILED = "dashboard.load_failed"
    DASHBOARD_ACCESS_DENIED = "dashboard.access_denied"


class AccessSurface(str, Enum):
    """Where the access occurred."""
    SHOPIFY_EMBED = "shopify_embed"
    EXTERNAL_APP = "external_app"


# ---------------------------------------------------------------------------
# PII Sanitization
# ---------------------------------------------------------------------------

class PIISanitizer:
    """
    Strips PII from audit metadata before persistence.

    Redacted fields are replaced with "[REDACTED]" to preserve structure
    while removing sensitive data. Emails are partially masked (domain only).
    Tokens and secrets are fully redacted.
    """

    REDACTED_FIELDS: FrozenSet[str] = frozenset({
        # Authentication tokens & secrets
        "email", "phone", "phone_number",
        "token", "access_token", "refresh_token",
        "api_key", "api_secret", "password", "secret",
        "credential", "credentials", "authorization",
        "session_token", "jwt_token", "bearer_token",
        # Personal identifiers
        "ssn", "social_security", "tax_id", "national_id",
        # Financial
        "credit_card", "card_number", "cvv", "bank_account",
        "routing_number",
        # Address
        "street_address", "address_line_1", "address_line_2",
    })

    # Patterns that look like tokens/secrets in values
    _TOKEN_PATTERNS = [
        re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),  # JWT
        re.compile(r"^sk_[a-zA-Z0-9]{20,}"),   # Stripe-style secret keys
        re.compile(r"^Bearer\s+.+", re.IGNORECASE),  # Bearer tokens
    ]

    REDACTION_MARKER = "[REDACTED]"

    @classmethod
    def sanitize(cls, data: dict[str, Any]) -> dict[str, Any]:
        """
        Recursively sanitize PII from a dictionary.

        Args:
            data: Dictionary potentially containing PII

        Returns:
            New dictionary with PII fields redacted
        """
        if not isinstance(data, dict):
            return data
        return cls._sanitize_dict(data)

    @classmethod
    def _sanitize_dict(cls, d: dict[str, Any]) -> dict[str, Any]:
        result = {}
        for key, value in d.items():
            lower_key = key.lower()
            if lower_key in cls.REDACTED_FIELDS:
                result[key] = cls._redact_value(lower_key, value)
            elif isinstance(value, str) and cls._looks_like_secret(value):
                result[key] = cls.REDACTION_MARKER
            elif isinstance(value, dict):
                result[key] = cls._sanitize_dict(value)
            elif isinstance(value, list):
                result[key] = cls._sanitize_list(value)
            else:
                result[key] = value
        return result

    @classmethod
    def _redact_value(cls, key: str, value: Any) -> str:
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
    def _looks_like_secret(cls, value: str) -> bool:
        """Check if a string value looks like a token or secret."""
        for pattern in cls._TOKEN_PATTERNS:
            if pattern.match(value):
                return True
        return False

    @classmethod
    def _sanitize_list(cls, lst: list[Any]) -> list[Any]:
        result = []
        for item in lst:
            if isinstance(item, dict):
                result.append(cls._sanitize_dict(item))
            elif isinstance(item, list):
                result.append(cls._sanitize_list(item))
            else:
                result.append(item)
        return result


# ---------------------------------------------------------------------------
# Correlation ID generation
# ---------------------------------------------------------------------------

def generate_correlation_id() -> str:
    """Generate a new UUID v4 correlation ID for request tracing."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# GA Audit Log Model
# ---------------------------------------------------------------------------

class GAAuditLog(Base):
    """
    GA Audit Log database model (auth + dashboard access).

    CRITICAL: This table is append-only. No UPDATE or DELETE operations
    except the 90-day retention job (which disables the immutability trigger).

    Schema columns per GA requirements:
    - id (uuid, PK)
    - event_type (string)
    - user_id (nullable)
    - tenant_id (nullable)
    - dashboard_id (nullable)
    - access_surface (shopify_embed | external_app)
    - success (boolean)
    - event_metadata (JSONB, sanitized)
    - correlation_id (uuid)
    - created_at (timestamp)
    """
    __tablename__ = "ga_audit_logs"

    id = Column(
        String(36), primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    event_type = Column(String(100), nullable=False, index=True)
    user_id = Column(String(255), nullable=True, index=True)
    tenant_id = Column(String(255), nullable=True, index=True)
    dashboard_id = Column(String(255), nullable=True, index=True)
    access_surface = Column(
        String(50), nullable=False, default=AccessSurface.EXTERNAL_APP.value,
    )
    success = Column(Boolean, nullable=False, default=True)
    event_metadata = Column(JSONType, nullable=False, default=dict)
    correlation_id = Column(
        String(36), nullable=False, index=True,
        default=generate_correlation_id,
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        # Primary query: Recent logs by tenant
        Index(
            "ix_ga_audit_tenant_created",
            "tenant_id", "created_at",
            postgresql_using="btree",
        ),
        # Query by event type within tenant
        Index(
            "ix_ga_audit_tenant_event_type",
            "tenant_id", "event_type",
        ),
        # Dashboard-specific queries
        Index(
            "ix_ga_audit_tenant_dashboard",
            "tenant_id", "dashboard_id", "created_at",
            postgresql_using="btree",
        ),
        # Correlation tracing
        Index("ix_ga_audit_correlation", "correlation_id"),
        # Failure analysis
        Index(
            "ix_ga_audit_tenant_success",
            "tenant_id", "success", "created_at",
            postgresql_using="btree",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"GAAuditLog(id={self.id}, event_type={self.event_type}, "
            f"tenant_id={self.tenant_id}, success={self.success})"
        )


# ---------------------------------------------------------------------------
# Audit Event dataclass (pre-persistence)
# ---------------------------------------------------------------------------

@dataclass
class GAAuditEvent:
    """
    Immutable audit event data structure for GA scope.

    Construct this before writing to the database.
    PII in event_metadata is automatically sanitized before persistence.
    """
    event_type: AuditEventType
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    dashboard_id: Optional[str] = None
    access_surface: AccessSurface = AccessSurface.EXTERNAL_APP
    success: bool = True
    event_metadata: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=generate_correlation_id)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for DB insertion with PII sanitization."""
        return {
            "event_type": (
                self.event_type.value
                if isinstance(self.event_type, AuditEventType)
                else self.event_type
            ),
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "dashboard_id": self.dashboard_id,
            "access_surface": (
                self.access_surface.value
                if isinstance(self.access_surface, AccessSurface)
                else self.access_surface
            ),
            "success": self.success,
            "event_metadata": PIISanitizer.sanitize(self.event_metadata),
            "correlation_id": self.correlation_id,
            "created_at": self.created_at,
        }
