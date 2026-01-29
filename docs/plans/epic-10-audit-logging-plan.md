# Epic 10 - Audit Logging, Exports & Governance
## Story 10.1 - Audit Event Schema & Logging Foundation

**Implementation Plan**

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Audit Event Schema Design](#3-audit-event-schema-design)
4. [Audit Logger Service Design](#4-audit-logger-service-design)
5. [PII Redaction Strategy](#5-pii-redaction-strategy)
6. [Database Migration](#6-database-migration)
7. [Event Types Catalog](#7-event-types-catalog)
8. [Error Handling & Fallback Strategy](#8-error-handling--fallback-strategy)
9. [Testing Strategy](#9-testing-strategy)
10. [Implementation Checklist](#10-implementation-checklist)
11. [Human-Required Approvals](#11-human-required-approvals)

---

## 1. Executive Summary

### Purpose

This plan outlines the implementation of a production-grade audit logging system for the Shopify Analytics Platform. The system will provide:

- **Complete audit trail** for security, billing, data access, and governance actions
- **Compliance readiness** for SOC2 and enterprise governance requirements
- **Incident investigation** capabilities with correlation IDs for request tracing
- **PII protection** through automatic redaction before persistence
- **High availability** through fallback logging when primary storage fails

### Scope

| In Scope | Out of Scope |
|----------|--------------|
| Canonical audit log schema | Legal hold functionality |
| Append-only PostgreSQL storage | Cold storage/archival |
| PII redaction | Log analysis/alerting |
| Correlation ID tracking | Real-time streaming |
| Fallback logging to stdout | Cross-region replication |
| Core event type definitions | Export functionality (Story 10.2+) |

### Key Design Decisions

1. **PostgreSQL as primary store** - Leverages existing infrastructure, supports JSONB for flexible metadata
2. **Append-only constraint** - No UPDATE/DELETE at application level; enforced via service layer
3. **Async-capable with sync fallback** - Non-blocking writes that never crash request flow
4. **Tenant-scoped by default** - All queries automatically filtered by tenant_id

---

## 2. Architecture Overview

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           FastAPI Application                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐    ┌─────────────────────────────────────────────┐    │
│  │   Routes/    │───▶│           AnalyticsAuditLogger              │    │
│  │  Services    │    │                                              │    │
│  └──────────────┘    │  ┌─────────────────────────────────────┐    │    │
│                       │  │       Correlation ID Generator      │    │    │
│                       │  └─────────────────────────────────────┘    │    │
│                       │                                              │    │
│                       │  ┌─────────────────────────────────────┐    │    │
│                       │  │         PII Redactor               │    │    │
│                       │  └─────────────────────────────────────┘    │    │
│                       │                                              │    │
│                       │  ┌─────────────┐   ┌──────────────────┐    │    │
│                       │  │  Primary    │   │    Fallback      │    │    │
│                       │  │  Writer     │   │    Writer        │    │    │
│                       │  │ (Database)  │   │   (Stdout)       │    │    │
│                       │  └──────┬──────┘   └────────┬─────────┘    │    │
│                       └─────────┼──────────────────┼───────────────┘    │
│                                 │                  │                     │
└─────────────────────────────────┼──────────────────┼─────────────────────┘
                                  │                  │
                                  ▼                  ▼
                         ┌───────────────┐   ┌─────────────┐
                         │  PostgreSQL   │   │   Stdout    │
                         │  audit_logs   │   │   (JSON)    │
                         └───────────────┘   └─────────────┘
```

### Integration Points

| Component | Integration Method |
|-----------|-------------------|
| API Routes | Middleware injection + explicit logger calls |
| Services | Constructor injection of logger instance |
| Background Workers | Logger singleton with worker context |
| Database | SQLAlchemy session management |

### File Structure

```
backend/
├── src/
│   ├── models/
│   │   └── audit_log.py              # AuditLog model + AuditEventType enum
│   ├── services/
│   │   └── audit_logger.py           # AnalyticsAuditLogger service
│   └── tests/
│       ├── unit/
│       │   └── test_audit_logger.py  # Unit tests with mocks
│       └── integration/
│           └── test_audit_log_integration.py  # Database integration tests
├── migrations/
│   └── 012_create_audit_logs.sql     # Schema migration
```

---

## 3. Audit Event Schema Design

### 3.1 Canonical Schema Definition

```python
# backend/src/models/audit_log.py

class AuditLog(Base):
    """
    Immutable audit log entry for compliance and security tracking.

    This table is append-only. No UPDATE or DELETE operations are permitted
    at the application level. All entries are retained according to the
    configured retention policy.
    """
    __tablename__ = "audit_logs"

    # Primary identifier
    event_id = Column(String(36), primary_key=True, default=generate_uuid)

    # Event classification
    event_type = Column(Enum(AuditEventType), nullable=False, index=True)

    # Actor identification
    user_id = Column(String(255), nullable=True, index=True)  # NULL for system events
    tenant_id = Column(String(255), nullable=False, index=True)

    # Request tracing
    correlation_id = Column(String(36), nullable=False, index=True)

    # Timing
    timestamp = Column(DateTime(timezone=True), nullable=False,
                       server_default=func.now(), index=True)

    # Event context
    source = Column(String(100), nullable=False)  # e.g., "api", "worker", "system"

    # Flexible payload (PII-redacted)
    metadata = Column(JSONB, nullable=False, default=dict)

    # Resource tracking (optional)
    resource_type = Column(String(100), nullable=True)  # e.g., "store", "action"
    resource_id = Column(String(255), nullable=True)

    # Security context
    ip_address = Column(String(45), nullable=True)  # IPv6 compatible
    user_agent = Column(String(500), nullable=True)

    # Outcome tracking
    outcome = Column(Enum(AuditOutcome), nullable=False, default=AuditOutcome.SUCCESS)
    error_code = Column(String(50), nullable=True)
```

### 3.2 Field Specifications

| Field | Type | Nullable | Index | Description |
|-------|------|----------|-------|-------------|
| `event_id` | UUID/String(36) | No | PK | Unique identifier for the audit entry |
| `event_type` | Enum | No | Yes | Category of auditable action |
| `user_id` | String(255) | Yes | Yes | Actor user ID (NULL for system) |
| `tenant_id` | String(255) | No | Yes | Tenant scope (always required) |
| `correlation_id` | UUID/String(36) | No | Yes | Request trace ID |
| `timestamp` | DateTime(tz) | No | Yes | When event occurred (UTC) |
| `source` | String(100) | No | No | Origin: api, worker, system, webhook |
| `metadata` | JSONB | No | No | Event-specific details (redacted) |
| `resource_type` | String(100) | Yes | No | Type of affected resource |
| `resource_id` | String(255) | Yes | No | ID of affected resource |
| `ip_address` | String(45) | Yes | No | Client IP (IPv6 ready) |
| `user_agent` | String(500) | Yes | No | Client user agent |
| `outcome` | Enum | No | No | SUCCESS, FAILURE, DENIED |
| `error_code` | String(50) | Yes | No | Error code if outcome=FAILURE |

### 3.3 Indexes

```sql
-- Primary query patterns
CREATE INDEX idx_audit_logs_tenant_timestamp
    ON audit_logs (tenant_id, timestamp DESC);

CREATE INDEX idx_audit_logs_tenant_event_type
    ON audit_logs (tenant_id, event_type, timestamp DESC);

CREATE INDEX idx_audit_logs_correlation_id
    ON audit_logs (correlation_id);

CREATE INDEX idx_audit_logs_user_tenant
    ON audit_logs (user_id, tenant_id, timestamp DESC)
    WHERE user_id IS NOT NULL;

CREATE INDEX idx_audit_logs_resource
    ON audit_logs (tenant_id, resource_type, resource_id, timestamp DESC)
    WHERE resource_type IS NOT NULL;
```

### 3.4 Constraints

```sql
-- Append-only enforcement via trigger (optional, defense in depth)
CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit logs are immutable. UPDATE and DELETE operations are not permitted.';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_log_modification();
```

---

## 4. Audit Logger Service Design

### 4.1 Class Structure

```python
# backend/src/services/audit_logger.py

class AnalyticsAuditLogger:
    """
    Production-grade audit logging service with:
    - Primary database persistence
    - Fallback stdout logging
    - Automatic PII redaction
    - Correlation ID generation and tracking
    - Non-blocking operation (never crashes request flow)
    """

    def __init__(
        self,
        db_session: Session,
        tenant_id: str,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        source: str = "api",
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        """
        Initialize audit logger with context.

        Args:
            db_session: SQLAlchemy session for database operations
            tenant_id: Required tenant context (from JWT)
            user_id: Optional user ID (NULL for system operations)
            correlation_id: Optional existing correlation ID (generates if None)
            source: Event source identifier (api, worker, system, webhook)
            ip_address: Client IP address
            user_agent: Client user agent string
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for audit logging")

        self._db = db_session
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._correlation_id = correlation_id or self._generate_correlation_id()
        self._source = source
        self._ip_address = ip_address
        self._user_agent = user_agent
        self._redactor = PIIRedactor()
        self._fallback_logger = logging.getLogger("audit.fallback")

    @property
    def correlation_id(self) -> str:
        """Return correlation ID for request tracing."""
        return self._correlation_id

    def log(
        self,
        event_type: AuditEventType,
        metadata: Optional[Dict[str, Any]] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        error_code: Optional[str] = None,
    ) -> str:
        """
        Log an audit event.

        Returns:
            correlation_id for the logged event

        Note:
            This method never raises exceptions. Failures are logged
            to the fallback logger and do not interrupt request flow.
        """
        # Implementation details below
```

### 4.2 Core Methods

```python
class AnalyticsAuditLogger:
    # ... __init__ above ...

    def log(
        self,
        event_type: AuditEventType,
        metadata: Optional[Dict[str, Any]] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        error_code: Optional[str] = None,
    ) -> str:
        """Log an audit event with automatic PII redaction."""
        try:
            # Redact PII from metadata
            safe_metadata = self._redactor.redact(metadata or {})

            # Create audit log entry
            entry = AuditLog(
                event_type=event_type,
                user_id=self._user_id,
                tenant_id=self._tenant_id,
                correlation_id=self._correlation_id,
                source=self._source,
                metadata=safe_metadata,
                resource_type=resource_type,
                resource_id=resource_id,
                ip_address=self._ip_address,
                user_agent=self._user_agent,
                outcome=outcome,
                error_code=error_code,
            )

            # Attempt primary persistence
            self._write_to_database(entry)

        except Exception as e:
            # Fallback to stdout - NEVER crash
            self._write_to_fallback(event_type, metadata, outcome, error_code, e)

        return self._correlation_id

    def log_authentication(
        self,
        action: str,
        success: bool,
        failure_reason: Optional[str] = None,
    ) -> str:
        """Convenience method for authentication events."""
        return self.log(
            event_type=AuditEventType.AUTHENTICATION,
            metadata={
                "action": action,  # "login", "logout", "token_refresh"
                "success": success,
                "failure_reason": failure_reason,
            },
            outcome=AuditOutcome.SUCCESS if success else AuditOutcome.FAILURE,
            error_code=failure_reason,
        )

    def log_data_access(
        self,
        resource_type: str,
        resource_id: str,
        access_type: str,
        granted: bool,
        denial_reason: Optional[str] = None,
    ) -> str:
        """Convenience method for data access events."""
        return self.log(
            event_type=AuditEventType.DATA_ACCESS,
            metadata={
                "access_type": access_type,  # "read", "write", "delete"
                "granted": granted,
                "denial_reason": denial_reason,
            },
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=AuditOutcome.SUCCESS if granted else AuditOutcome.DENIED,
        )

    def log_billing_event(
        self,
        action: str,
        amount: Optional[float] = None,
        currency: Optional[str] = None,
        plan: Optional[str] = None,
        **extra_metadata,
    ) -> str:
        """Convenience method for billing events."""
        return self.log(
            event_type=AuditEventType.BILLING,
            metadata={
                "action": action,  # "subscription_created", "payment_processed"
                "amount": amount,
                "currency": currency,
                "plan": plan,
                **extra_metadata,
            },
        )

    def log_security_event(
        self,
        action: str,
        severity: str = "info",
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Convenience method for security events."""
        return self.log(
            event_type=AuditEventType.SECURITY,
            metadata={
                "action": action,
                "severity": severity,
                "details": details or {},
            },
        )

    def log_governance_action(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        before_state: Optional[Dict[str, Any]] = None,
        after_state: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Convenience method for governance/admin actions."""
        return self.log(
            event_type=AuditEventType.GOVERNANCE,
            metadata={
                "action": action,
                "before_state": before_state,
                "after_state": after_state,
            },
            resource_type=resource_type,
            resource_id=resource_id,
        )

    # Private methods

    @staticmethod
    def _generate_correlation_id() -> str:
        """Generate a new correlation ID."""
        return str(uuid.uuid4())

    def _write_to_database(self, entry: AuditLog) -> None:
        """Write audit entry to database."""
        self._db.add(entry)
        self._db.commit()

    def _write_to_fallback(
        self,
        event_type: AuditEventType,
        metadata: Optional[Dict[str, Any]],
        outcome: AuditOutcome,
        error_code: Optional[str],
        original_error: Exception,
    ) -> None:
        """Write to fallback logger when primary fails."""
        fallback_entry = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type.value,
            "user_id": self._user_id,
            "tenant_id": self._tenant_id,
            "correlation_id": self._correlation_id,
            "timestamp": datetime.utcnow().isoformat(),
            "source": self._source,
            "metadata": self._redactor.redact(metadata or {}),
            "outcome": outcome.value,
            "error_code": error_code,
            "ip_address": self._ip_address,
            "fallback_reason": str(original_error),
        }

        self._fallback_logger.error(
            "Audit log fallback",
            extra={"audit_entry": json.dumps(fallback_entry)},
        )
```

### 4.3 Factory Function for Easy Creation

```python
def create_audit_logger(
    request: Request,
    db_session: Session,
    source: str = "api",
) -> AnalyticsAuditLogger:
    """
    Factory function to create audit logger from FastAPI request context.

    Usage in routes:
        audit_logger = create_audit_logger(request, db_session)
        audit_logger.log_data_access(...)
    """
    from src.platform.tenant_context import get_tenant_context

    tenant_ctx = get_tenant_context(request)

    # Extract correlation ID from request headers if present
    correlation_id = request.headers.get("X-Correlation-ID")

    # Extract client info
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    return AnalyticsAuditLogger(
        db_session=db_session,
        tenant_id=tenant_ctx.tenant_id,
        user_id=tenant_ctx.user_id,
        correlation_id=correlation_id,
        source=source,
        ip_address=ip_address,
        user_agent=user_agent,
    )
```

---

## 5. PII Redaction Strategy

### 5.1 Redactor Implementation

```python
# backend/src/services/audit_logger.py (continued)

class PIIRedactor:
    """
    Redacts PII fields from audit metadata before persistence.

    Redacted fields are replaced with "[REDACTED]" to maintain
    structure while removing sensitive data.
    """

    # Fields that should always be redacted
    REDACTED_FIELDS = frozenset({
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

        # Address components (configurable)
        "street_address",
        "address_line_1",
        "address_line_2",
    })

    # Patterns for partial redaction
    PARTIAL_REDACTION_PATTERNS = {
        "email": lambda v: f"***@{v.split('@')[1]}" if "@" in str(v) else "[REDACTED]",
        "phone": lambda v: f"***{str(v)[-4:]}" if len(str(v)) >= 4 else "[REDACTED]",
        "phone_number": lambda v: f"***{str(v)[-4:]}" if len(str(v)) >= 4 else "[REDACTED]",
    }

    REDACTION_MARKER = "[REDACTED]"

    def redact(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively redact PII from a dictionary.

        Args:
            data: Dictionary potentially containing PII

        Returns:
            New dictionary with PII fields redacted
        """
        if not isinstance(data, dict):
            return data

        return self._redact_dict(data)

    def _redact_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively process a dictionary."""
        result = {}
        for key, value in d.items():
            lower_key = key.lower()

            if lower_key in self.REDACTED_FIELDS:
                # Check for partial redaction
                if lower_key in self.PARTIAL_REDACTION_PATTERNS and value:
                    try:
                        result[key] = self.PARTIAL_REDACTION_PATTERNS[lower_key](value)
                    except Exception:
                        result[key] = self.REDACTION_MARKER
                else:
                    result[key] = self.REDACTION_MARKER
            elif isinstance(value, dict):
                result[key] = self._redact_dict(value)
            elif isinstance(value, list):
                result[key] = self._redact_list(value)
            else:
                result[key] = value

        return result

    def _redact_list(self, lst: List[Any]) -> List[Any]:
        """Process a list, redacting any nested dicts."""
        result = []
        for item in lst:
            if isinstance(item, dict):
                result.append(self._redact_dict(item))
            elif isinstance(item, list):
                result.append(self._redact_list(item))
            else:
                result.append(item)
        return result
```

### 5.2 Redaction Rules Summary

| Field Category | Fields | Redaction Method |
|----------------|--------|------------------|
| **Email** | email | Partial: `***@domain.com` |
| **Phone** | phone, phone_number | Partial: `***1234` |
| **Tokens** | token, access_token, refresh_token, api_key, api_secret | Full: `[REDACTED]` |
| **Credentials** | password, secret, credential, credentials | Full: `[REDACTED]` |
| **Financial** | credit_card, card_number, cvv, bank_account | Full: `[REDACTED]` |
| **Government IDs** | ssn, social_security, tax_id, national_id | Full: `[REDACTED]` |

### 5.3 Configurable Extensions

```python
# Allow runtime configuration of additional PII fields
class PIIRedactor:
    def __init__(self, additional_fields: Optional[Set[str]] = None):
        self._redacted_fields = self.REDACTED_FIELDS.copy()
        if additional_fields:
            self._redacted_fields = self._redacted_fields | additional_fields
```

---

## 6. Database Migration

### 6.1 Migration File

```sql
-- migrations/012_create_audit_logs.sql
-- Audit Logging Foundation for Epic 10
-- Story 10.1: Audit Event Schema & Logging Foundation

-- Create enum types
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'audit_event_type') THEN
        CREATE TYPE audit_event_type AS ENUM (
            'authentication',
            'authorization',
            'data_access',
            'data_modification',
            'billing',
            'security',
            'governance',
            'integration',
            'system'
        );
    END IF;
END$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'audit_outcome') THEN
        CREATE TYPE audit_outcome AS ENUM (
            'success',
            'failure',
            'denied'
        );
    END IF;
END$$;

-- Create audit_logs table
CREATE TABLE IF NOT EXISTS audit_logs (
    -- Primary identifier
    event_id VARCHAR(36) PRIMARY KEY,

    -- Event classification
    event_type audit_event_type NOT NULL,

    -- Actor identification
    user_id VARCHAR(255),
    tenant_id VARCHAR(255) NOT NULL,

    -- Request tracing
    correlation_id VARCHAR(36) NOT NULL,

    -- Timing
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Event context
    source VARCHAR(100) NOT NULL,

    -- Flexible payload (PII-redacted)
    metadata JSONB NOT NULL DEFAULT '{}',

    -- Resource tracking
    resource_type VARCHAR(100),
    resource_id VARCHAR(255),

    -- Security context
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),

    -- Outcome tracking
    outcome audit_outcome NOT NULL DEFAULT 'success',
    error_code VARCHAR(50)
);

-- Create indexes for common query patterns
-- Primary query: Recent logs by tenant
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_timestamp
    ON audit_logs (tenant_id, timestamp DESC);

-- Query by event type within tenant
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_event_type
    ON audit_logs (tenant_id, event_type, timestamp DESC);

-- Request tracing
CREATE INDEX IF NOT EXISTS idx_audit_logs_correlation_id
    ON audit_logs (correlation_id);

-- User activity audit
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_tenant
    ON audit_logs (user_id, tenant_id, timestamp DESC)
    WHERE user_id IS NOT NULL;

-- Resource history
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource
    ON audit_logs (tenant_id, resource_type, resource_id, timestamp DESC)
    WHERE resource_type IS NOT NULL;

-- Immutability trigger (defense in depth)
CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit logs are immutable. UPDATE and DELETE operations are not permitted.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_immutable ON audit_logs;
CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_log_modification();

-- Add comment for documentation
COMMENT ON TABLE audit_logs IS
    'Immutable audit log for compliance and security tracking. Story 10.1.';
COMMENT ON COLUMN audit_logs.metadata IS
    'Event-specific details. PII is automatically redacted before storage.';
COMMENT ON COLUMN audit_logs.correlation_id IS
    'Request trace ID for correlating events across services.';
```

### 6.2 Migration Rollback (Emergency Only)

```sql
-- migrations/012_rollback_audit_logs.sql
-- EMERGENCY ONLY - Removes audit logging infrastructure

DROP TRIGGER IF EXISTS audit_log_immutable ON audit_logs;
DROP FUNCTION IF EXISTS prevent_audit_log_modification();
DROP TABLE IF EXISTS audit_logs;
DROP TYPE IF EXISTS audit_outcome;
DROP TYPE IF EXISTS audit_event_type;
```

---

## 7. Event Types Catalog

### 7.1 Event Type Enum

```python
# backend/src/models/audit_log.py

from enum import Enum

class AuditEventType(str, Enum):
    """
    Canonical audit event types.

    These categories cover all auditable actions in the platform.
    Each event type maps to specific compliance requirements.
    """

    # Authentication & Identity
    AUTHENTICATION = "authentication"  # Login, logout, token refresh, MFA
    AUTHORIZATION = "authorization"    # Permission checks, role changes

    # Data Operations
    DATA_ACCESS = "data_access"        # Read operations on sensitive data
    DATA_MODIFICATION = "data_modification"  # Create, update, delete

    # Billing & Subscription
    BILLING = "billing"                # Payments, plan changes, usage

    # Security Events
    SECURITY = "security"              # Rate limits, suspicious activity

    # Administrative Actions
    GOVERNANCE = "governance"          # Admin actions, config changes

    # External Integrations
    INTEGRATION = "integration"        # OAuth, API calls, webhooks

    # System Events
    SYSTEM = "system"                  # Background jobs, maintenance


class AuditOutcome(str, Enum):
    """Outcome of the audited action."""

    SUCCESS = "success"   # Action completed successfully
    FAILURE = "failure"   # Action failed (error)
    DENIED = "denied"     # Action denied (authorization)
```

### 7.2 Event Mapping Table

| Event Type | Example Actions | SOC2 Control |
|------------|-----------------|--------------|
| **AUTHENTICATION** | login, logout, token_refresh, mfa_challenge, password_reset | CC6.1 |
| **AUTHORIZATION** | permission_check, role_assigned, role_revoked, access_denied | CC6.1, CC6.2 |
| **DATA_ACCESS** | report_viewed, export_requested, pii_accessed | CC6.1, CC6.6 |
| **DATA_MODIFICATION** | record_created, record_updated, record_deleted | CC6.1, CC8.1 |
| **BILLING** | subscription_created, payment_processed, plan_changed | CC6.1 |
| **SECURITY** | rate_limit_exceeded, suspicious_activity, ip_blocked | CC6.1, CC6.8 |
| **GOVERNANCE** | config_changed, retention_applied, data_purged | CC6.1, CC7.2 |
| **INTEGRATION** | oauth_connected, oauth_disconnected, webhook_received | CC6.1, CC6.6 |
| **SYSTEM** | job_started, job_completed, maintenance_mode | CC7.1 |

### 7.3 Required Actions by Event Type

```python
# Recommended minimum auditable actions per type

REQUIRED_AUDIT_ACTIONS = {
    AuditEventType.AUTHENTICATION: [
        "login_success",
        "login_failure",
        "logout",
        "token_refresh",
        "password_reset_requested",
        "password_reset_completed",
    ],
    AuditEventType.AUTHORIZATION: [
        "permission_denied",
        "role_assigned",
        "role_revoked",
        "tenant_switched",
    ],
    AuditEventType.DATA_ACCESS: [
        "sensitive_data_accessed",
        "report_generated",
        "export_requested",
        "bulk_query_executed",
    ],
    AuditEventType.DATA_MODIFICATION: [
        "store_connected",
        "store_disconnected",
        "action_created",
        "action_approved",
        "action_executed",
    ],
    AuditEventType.BILLING: [
        "subscription_created",
        "subscription_updated",
        "subscription_cancelled",
        "payment_succeeded",
        "payment_failed",
        "usage_recorded",
    ],
    AuditEventType.SECURITY: [
        "rate_limit_exceeded",
        "invalid_token_used",
        "suspicious_activity_detected",
        "ip_blocked",
    ],
    AuditEventType.GOVERNANCE: [
        "retention_policy_applied",
        "data_deletion_requested",
        "admin_action_taken",
        "configuration_changed",
    ],
    AuditEventType.INTEGRATION: [
        "oauth_connected",
        "oauth_disconnected",
        "oauth_token_refreshed",
        "webhook_received",
        "api_rate_limited",
    ],
    AuditEventType.SYSTEM: [
        "sync_started",
        "sync_completed",
        "sync_failed",
        "migration_executed",
        "maintenance_mode_toggled",
    ],
}
```

---

## 8. Error Handling & Fallback Strategy

### 8.1 Failure Modes

| Failure Mode | Detection | Response | Recovery |
|--------------|-----------|----------|----------|
| **DB Connection Lost** | SQLAlchemy exception | Write to fallback logger | Auto-reconnect on next request |
| **DB Timeout** | Timeout exception | Write to fallback logger | Retry not attempted |
| **Serialization Error** | JSON encode failure | Log error, skip metadata | Continue with empty metadata |
| **PII Redaction Error** | Exception in redactor | Use full redaction | Continue with `{}` metadata |
| **Correlation ID Missing** | None value | Generate new UUID | Log warning |

### 8.2 Fallback Logger Format

```python
# Structured JSON output for fallback logs
{
    "level": "ERROR",
    "logger": "audit.fallback",
    "message": "Audit log fallback",
    "audit_entry": {
        "event_id": "uuid",
        "event_type": "authentication",
        "user_id": "user-123",
        "tenant_id": "tenant-456",
        "correlation_id": "corr-789",
        "timestamp": "2024-01-15T10:30:00Z",
        "source": "api",
        "metadata": {},
        "outcome": "success",
        "ip_address": "192.168.1.1",
        "fallback_reason": "Database connection refused"
    }
}
```

### 8.3 Fallback Recovery Process

1. **Immediate**: Event logged to stdout in JSON format
2. **Log Aggregation**: External system (e.g., CloudWatch, Datadog) captures stdout
3. **Alerting**: Ops team notified of fallback events (configurable threshold)
4. **Recovery**: No automatic recovery - fallback logs remain in external system
5. **Reconciliation**: Manual process if needed (out of scope for Story 10.1)

---

## 9. Testing Strategy

### 9.1 Test Coverage Requirements

| Component | Coverage Target | Test Type |
|-----------|-----------------|-----------|
| `AuditLog` model | 100% | Unit |
| `AnalyticsAuditLogger` | 95% | Unit + Integration |
| `PIIRedactor` | 100% | Unit |
| Factory functions | 100% | Unit |
| Database constraints | 100% | Integration |
| Fallback behavior | 100% | Unit |

### 9.2 Unit Test Cases

```python
# backend/src/tests/unit/test_audit_logger.py

class TestAuditLogModel:
    """Tests for AuditLog SQLAlchemy model."""

    def test_model_creates_with_required_fields(self):
        """Should create audit log with all required fields."""

    def test_model_generates_event_id_if_not_provided(self):
        """Should auto-generate event_id as UUID."""

    def test_model_sets_default_timestamp(self):
        """Should set timestamp to current time if not provided."""

    def test_model_accepts_all_event_types(self):
        """Should accept all AuditEventType enum values."""

    def test_model_accepts_all_outcomes(self):
        """Should accept all AuditOutcome enum values."""

    def test_metadata_must_be_json_serializable(self):
        """Should reject non-serializable metadata."""


class TestPIIRedactor:
    """Tests for PII redaction functionality."""

    def test_redacts_email_with_partial_mask(self):
        """Should redact email to ***@domain.com format."""

    def test_redacts_phone_with_last_four(self):
        """Should redact phone to ***1234 format."""

    def test_redacts_token_completely(self):
        """Should replace token with [REDACTED]."""

    def test_redacts_nested_pii_fields(self):
        """Should redact PII in nested dictionaries."""

    def test_redacts_pii_in_lists(self):
        """Should redact PII in list items."""

    def test_preserves_non_pii_fields(self):
        """Should not modify non-PII fields."""

    def test_handles_empty_input(self):
        """Should return empty dict for empty input."""

    def test_handles_none_values(self):
        """Should handle None values gracefully."""


class TestAnalyticsAuditLogger:
    """Tests for main audit logger service."""

    def test_requires_tenant_id(self):
        """Should raise ValueError if tenant_id is missing."""

    def test_generates_correlation_id_if_not_provided(self):
        """Should generate UUID correlation ID."""

    def test_uses_provided_correlation_id(self):
        """Should use correlation ID if provided."""

    def test_returns_correlation_id_on_log(self):
        """Should return correlation ID from log method."""

    def test_redacts_pii_before_persistence(self):
        """Should call PII redactor before saving."""

    def test_falls_back_to_stdout_on_db_error(self):
        """Should write to fallback logger when DB fails."""

    def test_never_raises_exception_from_log(self):
        """Should catch all exceptions and not re-raise."""

    def test_log_authentication_sets_correct_type(self):
        """Should use AUTHENTICATION event type."""

    def test_log_data_access_sets_correct_type(self):
        """Should use DATA_ACCESS event type."""

    def test_log_billing_event_sets_correct_type(self):
        """Should use BILLING event type."""


class TestCreateAuditLogger:
    """Tests for factory function."""

    def test_extracts_tenant_from_request(self):
        """Should extract tenant_id from request context."""

    def test_extracts_correlation_id_from_header(self):
        """Should use X-Correlation-ID header if present."""

    def test_extracts_client_ip(self):
        """Should extract client IP from request."""

    def test_extracts_user_agent(self):
        """Should extract User-Agent header."""
```

### 9.3 Integration Test Cases

```python
# backend/src/tests/integration/test_audit_log_integration.py

class TestAuditLogDatabaseIntegration:
    """Integration tests requiring real PostgreSQL."""

    def test_insert_and_retrieve_audit_log(self, db_session):
        """Should persist and retrieve audit log entry."""

    def test_immutability_trigger_blocks_update(self, db_session):
        """Should raise error when attempting UPDATE."""

    def test_immutability_trigger_blocks_delete(self, db_session):
        """Should raise error when attempting DELETE."""

    def test_query_by_tenant_and_timestamp(self, db_session):
        """Should efficiently query by tenant_id and timestamp."""

    def test_query_by_correlation_id(self, db_session):
        """Should find all events for a correlation ID."""

    def test_metadata_jsonb_queries(self, db_session):
        """Should support JSONB queries on metadata."""

    def test_concurrent_inserts(self, db_session):
        """Should handle concurrent audit log inserts."""

    def test_large_metadata_storage(self, db_session):
        """Should store metadata up to reasonable size limit."""
```

### 9.4 Test Fixtures

```python
# backend/src/tests/conftest.py additions

@pytest.fixture
def mock_audit_logger():
    """Create a mock audit logger for unit tests."""
    logger = Mock(spec=AnalyticsAuditLogger)
    logger.correlation_id = "test-correlation-id"
    logger.log.return_value = "test-correlation-id"
    return logger


@pytest.fixture
def audit_logger_factory(mock_db_session):
    """Factory for creating test audit loggers."""
    def _create(
        tenant_id: str = "test-tenant",
        user_id: str = "test-user",
        correlation_id: str = None,
    ):
        return AnalyticsAuditLogger(
            db_session=mock_db_session,
            tenant_id=tenant_id,
            user_id=user_id,
            correlation_id=correlation_id,
        )
    return _create


@pytest.fixture
def sample_audit_events():
    """Sample audit events for testing."""
    return [
        {
            "event_type": AuditEventType.AUTHENTICATION,
            "metadata": {"action": "login", "success": True},
        },
        {
            "event_type": AuditEventType.DATA_ACCESS,
            "metadata": {"resource": "report", "action": "view"},
            "resource_type": "report",
            "resource_id": "report-123",
        },
    ]
```

---

## 10. Implementation Checklist

### Phase 1: Foundation (Story 10.1)

- [ ] **Model Layer**
  - [ ] Create `AuditEventType` enum
  - [ ] Create `AuditOutcome` enum
  - [ ] Create `AuditLog` SQLAlchemy model
  - [ ] Add `__table_args__` with indexes
  - [ ] Document immutability constraint

- [ ] **Service Layer**
  - [ ] Create `PIIRedactor` class
  - [ ] Implement redaction for all PII fields
  - [ ] Create `AnalyticsAuditLogger` class
  - [ ] Implement `log()` method with fallback
  - [ ] Implement convenience methods (log_authentication, etc.)
  - [ ] Create `create_audit_logger()` factory function
  - [ ] Configure fallback logger

- [ ] **Database Migration**
  - [ ] Create enum types
  - [ ] Create `audit_logs` table
  - [ ] Add indexes
  - [ ] Add immutability trigger
  - [ ] Test migration on development database

- [ ] **Testing**
  - [ ] Write unit tests for `AuditLog` model
  - [ ] Write unit tests for `PIIRedactor`
  - [ ] Write unit tests for `AnalyticsAuditLogger`
  - [ ] Write integration tests for database operations
  - [ ] Verify immutability trigger works
  - [ ] Achieve 90%+ code coverage

- [ ] **Documentation**
  - [ ] Add docstrings to all public methods
  - [ ] Document event type catalog
  - [ ] Document PII redaction rules
  - [ ] Add inline comments for complex logic

### Phase 2: Integration (Post Story 10.1)

- [ ] Add audit logging to authentication flows
- [ ] Add audit logging to data access routes
- [ ] Add audit logging to billing events
- [ ] Add audit logging to admin actions
- [ ] Create audit log query endpoints (Story 10.2+)
- [ ] Create audit log export functionality (Story 10.2+)

---

## 11. Human-Required Approvals

### Before Implementation

| Item | Owner | Status | Notes |
|------|-------|--------|-------|
| Final list of auditable event types | Security/Compliance | Pending | Review Section 7 |
| PII redaction rules | Legal/Privacy | Pending | Review Section 5 |
| Retention duration | Legal/Compliance | Pending | Currently unspecified |
| Schema compliance sign-off | Compliance | Pending | Review Section 3 |

### Questions Requiring Answers

1. **Retention Period**: How long should audit logs be retained?
   - Suggested: 90 days (configurable)
   - Impacts: Storage costs, compliance requirements

2. **Additional PII Fields**: Are there business-specific fields to redact?
   - Currently covered: email, phone, tokens, financial
   - May need: Custom fields per tenant?

3. **Event Type Approval**: Are the 9 event types sufficient?
   - Current: authentication, authorization, data_access, data_modification, billing, security, governance, integration, system
   - Missing any critical categories?

4. **Metadata Size Limit**: Should we enforce a maximum metadata size?
   - Suggested: 64KB per event
   - Impacts: Storage, query performance

5. **Cross-Tenant Audit Access**: Should agency users see audit logs across tenants?
   - Suggested: No, audit logs scoped to active tenant only
   - Impacts: Security model

---

## Appendix A: Sample Usage

### Basic Logging

```python
from src.services.audit_logger import create_audit_logger, AuditEventType

@router.post("/stores/{store_id}/connect")
async def connect_store(
    store_id: str,
    request: Request,
    db_session=Depends(get_db_session),
):
    # Create logger from request context
    audit = create_audit_logger(request, db_session)

    try:
        # Perform store connection
        store = store_service.connect(store_id)

        # Log successful data modification
        audit.log(
            event_type=AuditEventType.DATA_MODIFICATION,
            metadata={
                "action": "store_connected",
                "store_domain": store.domain,
            },
            resource_type="store",
            resource_id=store_id,
        )

        return {"status": "connected", "correlation_id": audit.correlation_id}

    except StoreConnectionError as e:
        # Log failure
        audit.log(
            event_type=AuditEventType.DATA_MODIFICATION,
            metadata={"action": "store_connection_failed", "error": str(e)},
            resource_type="store",
            resource_id=store_id,
            outcome=AuditOutcome.FAILURE,
            error_code="STORE_CONNECTION_FAILED",
        )
        raise
```

### Authentication Events

```python
@router.post("/auth/login")
async def login(credentials: LoginRequest, request: Request, db_session=Depends(get_db_session)):
    # Create logger (tenant_id from credentials for login)
    audit = AnalyticsAuditLogger(
        db_session=db_session,
        tenant_id=credentials.organization_id,
        source="api",
        ip_address=request.client.host,
        user_agent=request.headers.get("User-Agent"),
    )

    try:
        user = auth_service.authenticate(credentials)

        audit.log_authentication(
            action="login_success",
            success=True,
        )

        return {"token": user.token, "correlation_id": audit.correlation_id}

    except AuthenticationError as e:
        audit.log_authentication(
            action="login_failure",
            success=False,
            failure_reason=e.code,
        )
        raise
```

### Data Access Logging

```python
@router.get("/reports/{report_id}")
async def get_report(
    report_id: str,
    request: Request,
    db_session=Depends(get_db_session),
):
    audit = create_audit_logger(request, db_session)

    # Check authorization and log
    if not can_access_report(request, report_id):
        audit.log_data_access(
            resource_type="report",
            resource_id=report_id,
            access_type="read",
            granted=False,
            denial_reason="insufficient_permissions",
        )
        raise HTTPException(status_code=403)

    report = report_service.get(report_id)

    audit.log_data_access(
        resource_type="report",
        resource_id=report_id,
        access_type="read",
        granted=True,
    )

    return report
```

---

## Appendix B: Compliance Mapping

| SOC2 Control | Audit Event Coverage |
|--------------|---------------------|
| CC6.1 (Logical Access) | AUTHENTICATION, AUTHORIZATION |
| CC6.2 (Access Controls) | AUTHORIZATION, SECURITY |
| CC6.6 (Data Protection) | DATA_ACCESS, DATA_MODIFICATION |
| CC6.8 (Security Events) | SECURITY |
| CC7.1 (System Operations) | SYSTEM |
| CC7.2 (Change Management) | GOVERNANCE |
| CC8.1 (Processing Integrity) | DATA_MODIFICATION |

---

*Plan Version: 1.0*
*Created: 2026-01-29*
*Story: 10.1 - Audit Event Schema & Logging Foundation*
*Epic: 10 - Audit Logging, Exports & Governance*
