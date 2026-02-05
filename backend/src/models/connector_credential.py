"""
ConnectorCredential model - Encrypted connector credential storage.

Stores Fernet-encrypted platform credentials (OAuth tokens, API keys)
with tenant isolation and soft/hard delete lifecycle.

SECURITY:
- encrypted_payload is Fernet-encrypted via src.platform.secrets
- metadata column MUST NOT contain tokens, keys, or secrets
- tenant_id is ONLY extracted from JWT, never from client input
- Tokens are NEVER logged or exposed in __repr__
"""

import enum
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import JSON

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin

# Use JSONB for PostgreSQL, JSON for other databases (testing)
JSONType = JSON().with_variant(JSONB(), "postgresql")

# Soft delete restoration window (days)
SOFT_DELETE_RESTORE_WINDOW_DAYS = 5

# Hard delete deadline after soft delete (days)
HARD_DELETE_AFTER_DAYS = 20


class CredentialStatus(str, enum.Enum):
    """
    Canonical credential lifecycle status.

    Used by both the ConnectorCredential model (DB column) and the
    PlatformCredentialsService validation layer. Import from here
    instead of redefining elsewhere.

    MISSING is a runtime-only status indicating no credential row exists.
    It is never stored in the database.
    """
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INVALID = "invalid"
    MISSING = "missing"


class ConnectorCredential(Base, TimestampMixin, TenantScopedMixin):
    """
    Encrypted connector credential for a tenant.

    The encrypted_payload column stores a Fernet-encrypted JSON blob
    containing sensitive tokens/keys. It is encrypted/decrypted via
    src.platform.secrets and NEVER logged or exposed directly.

    Metadata stores non-sensitive display data: account name, source
    type labels, last validation time. MUST NOT contain secrets.

    Lifecycle:
    - Active: soft_deleted_at IS NULL, status = active
    - Soft-deleted: soft_deleted_at set, restorable within 5 days
    - Hard-deleted: after 20 days, encrypted_payload wiped permanently

    Attributes:
        id: Primary key (UUID)
        tenant_id: Tenant identifier from JWT org_id (NEVER client input)
        credential_name: Human-readable label
        source_type: Connector type (shopify, meta, google_ads, etc.)
        encrypted_payload: Fernet-encrypted JSON of sensitive credentials
        metadata: Non-sensitive metadata (account_name, labels)
        status: Credential lifecycle status
        created_by: clerk_user_id of creating user
        soft_deleted_at: When soft delete triggered (NULL = active)
        hard_delete_after: Scheduled permanent wipe deadline
    """

    __tablename__ = "connector_credentials"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)",
    )

    credential_name = Column(
        String(255),
        nullable=False,
        comment="Human-readable label for the credential set",
    )

    source_type = Column(
        String(100),
        nullable=False,
        comment="Connector source type (e.g., shopify, meta, google_ads)",
    )

    # SECURITY: Fernet-encrypted JSON blob. NEVER log this value.
    encrypted_payload = Column(
        Text,
        nullable=True,
        comment="Fernet-encrypted JSON of sensitive tokens/keys. "
                "Wiped to NULL on hard delete. NEVER log this value.",
    )

    # Python attribute renamed to avoid clash with SQLAlchemy's reserved
    # 'metadata' attribute. DB column is still named 'metadata'.
    credential_metadata = Column(
        "metadata",
        JSONType,
        nullable=False,
        default=dict,
        comment="Non-sensitive metadata: account_name, labels. "
                "MUST NOT contain secrets.",
    )

    status = Column(
        Enum(CredentialStatus),
        nullable=False,
        default=CredentialStatus.ACTIVE,
        index=True,
        comment="Credential lifecycle: active, expired, revoked, invalid",
    )

    created_by = Column(
        String(255),
        nullable=False,
        comment="clerk_user_id of the user who stored these credentials",
    )

    soft_deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When soft delete was triggered. NULL = active. "
                "Restorable within 5 days.",
    )

    hard_delete_after = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Scheduled permanent wipe deadline. "
                "Set to soft_deleted_at + 20 days.",
    )

    __table_args__ = (
        # Active credentials per tenant (excludes soft-deleted)
        Index(
            "ix_connector_credentials_tenant_active",
            "tenant_id",
            "status",
            postgresql_where=Column("soft_deleted_at").is_(None),
        ),
        # Tenant + source type lookup
        Index(
            "ix_connector_credentials_tenant_source",
            "tenant_id",
            "source_type",
            postgresql_where=Column("soft_deleted_at").is_(None),
        ),
        # Hard delete reaper query
        Index(
            "ix_connector_credentials_hard_delete",
            "hard_delete_after",
            postgresql_where=(
                Column("hard_delete_after").isnot(None)
                & Column("soft_deleted_at").isnot(None)
            ),
        ),
    )

    def __repr__(self) -> str:
        """Safe repr that NEVER includes encrypted_payload."""
        return (
            f"<ConnectorCredential("
            f"id={self.id}, "
            f"tenant_id={self.tenant_id}, "
            f"source_type={self.source_type}, "
            f"status={self.status}"
            f")>"
        )

    @property
    def is_active(self) -> bool:
        """Check if credential is active and not soft-deleted."""
        return (
            self.status == CredentialStatus.ACTIVE
            and self.soft_deleted_at is None
        )

    @property
    def is_soft_deleted(self) -> bool:
        """Check if credential has been soft-deleted."""
        return self.soft_deleted_at is not None

    @property
    def is_restorable(self) -> bool:
        """Check if soft-deleted credential can still be restored."""
        if self.soft_deleted_at is None:
            return False
        cutoff = self.soft_deleted_at + timedelta(
            days=SOFT_DELETE_RESTORE_WINDOW_DAYS
        )
        return datetime.now(timezone.utc) < cutoff

    @property
    def is_payload_wiped(self) -> bool:
        """Check if encrypted payload has been permanently wiped."""
        return self.encrypted_payload is None

    def safe_metadata(self) -> dict:
        """Return metadata dict safe for logging/display."""
        return {
            "id": self.id,
            "credential_name": self.credential_name,
            "source_type": self.source_type,
            "status": self.status.value if self.status else None,
            "metadata": self.credential_metadata or {},
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
            "is_active": self.is_active,
        }
