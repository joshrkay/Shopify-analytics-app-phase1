"""
TenantAirbyteConnection model - Maps Airbyte connections to tenants.

SECURITY: tenant_id is ONLY extracted from JWT, never from client input.
This ensures complete tenant isolation for data source connections.
"""

import uuid
import enum

from sqlalchemy import Column, String, Enum, DateTime, Text, Index, Boolean, JSON
from sqlalchemy.dialects.postgresql import JSONB

# Use JSONB for PostgreSQL (optimized for queries), JSON for other databases (testing)
JSONType = JSON().with_variant(JSONB(), "postgresql")

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin


class ConnectionStatus(str, enum.Enum):
    """Airbyte connection status enumeration."""
    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"
    DELETED = "deleted"


class ConnectionType(str, enum.Enum):
    """Airbyte connection type enumeration."""
    SOURCE = "source"
    DESTINATION = "destination"


class TenantAirbyteConnection(Base, TimestampMixin, TenantScopedMixin):
    """
    Maps an Airbyte connection to a tenant for multi-tenant isolation.

    CRITICAL: Each Airbyte connection belongs to exactly one tenant.
    Cross-tenant access is enforced at repository and service layers.

    Attributes:
        id: Primary key (UUID)
        tenant_id: Tenant identifier from JWT org_id (NEVER from client input)
        airbyte_connection_id: Airbyte's internal connection ID
        airbyte_source_id: Airbyte source ID (for source connections)
        airbyte_destination_id: Airbyte destination ID (for destination connections)
        connection_name: Human-readable connection name
        connection_type: Type of connection (source/destination)
        status: Current status of the connection
        source_type: Type of data source (e.g., shopify, postgres, etc.)
        configuration: Connection configuration metadata (non-sensitive)
        last_sync_at: Timestamp of last successful sync
        is_enabled: Whether the connection is enabled for syncing
    """

    __tablename__ = "tenant_airbyte_connections"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)"
    )

    # Airbyte identifiers
    airbyte_connection_id = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="Airbyte connection ID (unique across all tenants)"
    )
    airbyte_source_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Airbyte source ID"
    )
    airbyte_destination_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Airbyte destination ID"
    )

    # Connection metadata
    connection_name = Column(
        String(255),
        nullable=False,
        comment="Human-readable connection name"
    )
    connection_type = Column(
        Enum(ConnectionType),
        nullable=False,
        default=ConnectionType.SOURCE,
        comment="Type of connection (source/destination)"
    )
    source_type = Column(
        String(100),
        nullable=True,
        comment="Type of data source (e.g., shopify, postgres)"
    )

    # Status and configuration
    status = Column(
        Enum(ConnectionStatus),
        default=ConnectionStatus.PENDING,
        nullable=False,
        index=True,
        comment="Current connection status"
    )
    configuration = Column(
        JSONType,
        nullable=True,
        default=dict,
        comment="Non-sensitive connection configuration metadata"
    )

    # Sync tracking
    last_sync_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last successful sync"
    )
    last_sync_status = Column(
        String(50),
        nullable=True,
        comment="Status of the last sync (success/failed)"
    )
    sync_frequency_minutes = Column(
        String(50),
        nullable=True,
        default="60",
        comment="Sync frequency in minutes"
    )

    # Control flags
    is_enabled = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether the connection is enabled for syncing"
    )

    # Table constraints and indexes for tenant isolation
    __table_args__ = (
        # Composite index for tenant-scoped queries
        Index("ix_tenant_airbyte_connections_tenant_status", "tenant_id", "status"),
        # Composite index for tenant + connection type queries
        Index("ix_tenant_airbyte_connections_tenant_type", "tenant_id", "connection_type"),
        # Index for finding connections by source type within tenant
        Index("ix_tenant_airbyte_connections_tenant_source", "tenant_id", "source_type"),
        # Index for enabled connections per tenant
        Index(
            "ix_tenant_airbyte_connections_tenant_enabled",
            "tenant_id",
            "is_enabled",
            postgresql_where=Column("is_enabled").is_(True)
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<TenantAirbyteConnection("
            f"id={self.id}, "
            f"tenant_id={self.tenant_id}, "
            f"airbyte_connection_id={self.airbyte_connection_id}, "
            f"name={self.connection_name}"
            f")>"
        )

    @property
    def is_active(self) -> bool:
        """Check if connection is currently active and enabled."""
        return self.status == ConnectionStatus.ACTIVE and self.is_enabled

    @property
    def can_sync(self) -> bool:
        """Check if connection can perform syncs."""
        return self.is_enabled and self.status in (
            ConnectionStatus.ACTIVE,
            ConnectionStatus.PENDING
        )
