"""
Airbyte service for managing tenant-scoped data source connections.

CRITICAL: All operations are tenant-scoped via tenant_id from JWT.
Cross-tenant access is enforced at the repository layer.

This service orchestrates:
- Connection registration (mapping Airbyte connections to tenants)
- Connection lifecycle management
- Tenant-scoped connection queries
- Audit logging for connection changes
"""

import logging
from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.repositories.airbyte_connections import (
    AirbyteConnectionsRepository,
    ConnectionAlreadyExistsError,
)
from src.models.airbyte_connection import (
    TenantAirbyteConnection,
    ConnectionStatus,
    ConnectionType,
)

logger = logging.getLogger(__name__)


@dataclass
class ConnectionInfo:
    """Summary information about a connection."""
    id: str
    airbyte_connection_id: str
    connection_name: str
    connection_type: str
    source_type: Optional[str]
    status: str
    is_enabled: bool
    is_active: bool
    can_sync: bool
    last_sync_at: Optional[datetime]
    last_sync_status: Optional[str]
    created_at: datetime
    sync_frequency_minutes: Optional[str] = None


@dataclass
class ConnectionListResult:
    """Result of listing connections."""
    connections: List[ConnectionInfo]
    total_count: int
    has_more: bool


class AirbyteServiceError(Exception):
    """Base exception for Airbyte service errors."""
    pass


class ConnectionNotFoundServiceError(AirbyteServiceError):
    """Connection not found within tenant scope."""
    pass


class DuplicateConnectionError(AirbyteServiceError):
    """Connection with same Airbyte ID already exists."""
    pass


class AirbyteService:
    """
    Service for managing tenant-scoped Airbyte connections.

    SECURITY: All methods require tenant_id from JWT context.
    The service delegates to AirbyteConnectionsRepository which
    enforces tenant isolation at the database level.
    """

    def __init__(self, db_session: Session, tenant_id: str):
        """
        Initialize Airbyte service.

        Args:
            db_session: Database session
            tenant_id: Tenant ID from JWT (org_id)

        Raises:
            ValueError: If tenant_id is empty or None
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id
        self._repository = AirbyteConnectionsRepository(db_session, tenant_id)

    def _to_connection_info(
        self,
        connection: TenantAirbyteConnection
    ) -> ConnectionInfo:
        """Convert model to ConnectionInfo dataclass."""
        return ConnectionInfo(
            id=connection.id,
            airbyte_connection_id=connection.airbyte_connection_id,
            connection_name=connection.connection_name,
            connection_type=connection.connection_type.value if connection.connection_type else None,
            source_type=connection.source_type,
            status=connection.status.value if connection.status else None,
            is_enabled=connection.is_enabled,
            is_active=connection.is_active,
            can_sync=connection.can_sync,
            last_sync_at=connection.last_sync_at,
            last_sync_status=connection.last_sync_status,
            created_at=connection.created_at,
            sync_frequency_minutes=connection.sync_frequency_minutes,
        )

    def _normalize_shop_domain(self, shop_domain: str) -> str:
        """
        Normalize shop_domain using EXACT same logic as DBT and database constraint.

        This ensures validation uses identical normalization to prevent false negatives.

        Normalization steps:
        1. Convert to lowercase
        2. Strip leading https:// or http://
        3. Strip trailing /

        Args:
            shop_domain: Raw shop domain (may include protocol, trailing slash, mixed case)

        Returns:
            Normalized shop domain (e.g., "store.myshopify.com")

        Examples:
            "https://Store.myshopify.com/" -> "store.myshopify.com"
            "HTTP://store.myshopify.com" -> "store.myshopify.com"
            "store.myshopify.com" -> "store.myshopify.com"
        """
        if not shop_domain:
            return ""

        normalized = shop_domain.lower().strip()

        # Remove protocol
        if normalized.startswith('https://'):
            normalized = normalized[8:]
        elif normalized.startswith('http://'):
            normalized = normalized[7:]

        # Remove trailing slash
        normalized = normalized.rstrip('/')

        return normalized

    def _validate_shop_domain_unique(self, shop_domain: str, source_type: str) -> None:
        """
        Validate that shop_domain is not already connected to another tenant.

        CRITICAL SECURITY: Prevents data leakage via DBT JOIN on duplicate shop_domains.

        Background:
        - DBT derives tenant_id by JOINing Airbyte data on shop_domain
        - If two tenants have same shop_domain, JOIN returns duplicate rows
        - This causes cross-tenant data leakage

        This validation provides early detection and user-friendly error messages
        before the database constraint rejects the insert.

        Args:
            shop_domain: Shop domain to validate (will be normalized)
            source_type: Source type (validation only applies to Shopify)

        Raises:
            DuplicateConnectionError: If shop_domain already connected to different tenant

        Logs:
            ERROR: When duplicate detected for different tenant (security event)
            WARNING: When tenant tries to reconnect already-connected shop
        """
        # Only validate for Shopify sources
        if source_type not in ('shopify', 'source-shopify'):
            return

        # Normalize using same logic as DBT and database constraint
        normalized_shop_domain = self._normalize_shop_domain(shop_domain)

        if not normalized_shop_domain:
            # Empty shop_domain - will fail later validation
            return

        # Check for existing connection with same shop_domain
        # Uses EXACT same normalization as database constraint
        query = text("""
            SELECT
                tenant_id,
                connection_name,
                airbyte_connection_id,
                id
            FROM platform.tenant_airbyte_connections
            WHERE lower(
                    trim(
                        trailing '/' from
                        regexp_replace(
                            coalesce(configuration->>'shop_domain', ''),
                            '^https?://',
                            '',
                            'i'
                        )
                    )
                ) = :shop_domain
              AND source_type IN ('shopify', 'source-shopify')
              AND status = 'active'
              AND is_enabled = true
            LIMIT 1
        """)

        result = self.db.execute(query, {"shop_domain": normalized_shop_domain}).fetchone()

        if result:
            existing_tenant_id = result[0]
            existing_name = result[1]
            existing_airbyte_id = result[2]
            existing_connection_id = result[3]

            if existing_tenant_id != self.tenant_id:
                # CRITICAL: Different tenant owns this shop_domain
                logger.error(
                    "SECURITY: Duplicate shop_domain attempted by different tenant",
                    extra={
                        "event": "duplicate_shop_domain_blocked",
                        "attempted_tenant_id": self.tenant_id,
                        "existing_tenant_id": existing_tenant_id,
                        "shop_domain": normalized_shop_domain,
                        "existing_connection_name": existing_name,
                        "existing_airbyte_connection_id": existing_airbyte_id,
                        "severity": "critical",
                    }
                )

                raise DuplicateConnectionError(
                    f"This Shopify store ({shop_domain}) is already connected to another account. "
                    f"Each store can only be connected once across all accounts. "
                    f"If you believe this is an error, please contact support."
                )

            # Same tenant attempting duplicate connection
            logger.warning(
                "Tenant attempting to reconnect already-connected shop",
                extra={
                    "tenant_id": self.tenant_id,
                    "shop_domain": normalized_shop_domain,
                    "existing_connection_name": existing_name,
                    "existing_connection_id": existing_connection_id,
                }
            )

            raise DuplicateConnectionError(
                f"This Shopify store is already connected as '{existing_name}'. "
                f"Please disconnect the existing connection first before creating a new one."
            )

    def register_connection(
        self,
        airbyte_connection_id: str,
        connection_name: str,
        connection_type: str = "source",
        airbyte_source_id: Optional[str] = None,
        airbyte_destination_id: Optional[str] = None,
        source_type: Optional[str] = None,
        configuration: Optional[dict] = None,
        sync_frequency_minutes: Optional[str] = None
    ) -> ConnectionInfo:
        """
        Register a new Airbyte connection for the current tenant.

        This maps an existing Airbyte connection to the tenant,
        establishing ownership and enabling tenant-scoped access.

        SECURITY: The connection is automatically scoped to the
        tenant_id from JWT. No tenant_id parameter is accepted
        to prevent cross-tenant registration.

        Args:
            airbyte_connection_id: Airbyte's connection ID
            connection_name: Human-readable connection name
            connection_type: Type of connection (source/destination)
            airbyte_source_id: Airbyte source ID
            airbyte_destination_id: Airbyte destination ID
            source_type: Type of data source (e.g., shopify, postgres)
            configuration: Non-sensitive configuration metadata
            sync_frequency_minutes: Sync frequency

        Returns:
            ConnectionInfo for the registered connection

        Raises:
            DuplicateConnectionError: If connection already registered or shop_domain duplicate
        """
        # CRITICAL: Validate shop_domain uniqueness BEFORE creating connection
        # This prevents data leakage via DBT JOIN on duplicate shop_domains
        if configuration and 'shop_domain' in configuration:
            self._validate_shop_domain_unique(
                shop_domain=configuration['shop_domain'],
                source_type=source_type or ''
            )

        # Parse connection type
        conn_type = ConnectionType.SOURCE
        if connection_type.lower() == "destination":
            conn_type = ConnectionType.DESTINATION

        try:
            connection = self._repository.create_connection(
                airbyte_connection_id=airbyte_connection_id,
                connection_name=connection_name,
                connection_type=conn_type,
                airbyte_source_id=airbyte_source_id,
                airbyte_destination_id=airbyte_destination_id,
                source_type=source_type,
                configuration=configuration,
                sync_frequency_minutes=sync_frequency_minutes
            )

            logger.info(
                "Connection registered for tenant",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection.id,
                    "airbyte_connection_id": airbyte_connection_id,
                    "source_type": source_type
                }
            )

            return self._to_connection_info(connection)

        except ConnectionAlreadyExistsError:
            raise DuplicateConnectionError(
                f"Connection with Airbyte ID {airbyte_connection_id} is already registered"
            )

    def get_connection(self, connection_id: str) -> Optional[ConnectionInfo]:
        """
        Get a specific connection by ID.

        SECURITY: Only returns connection if it belongs to current tenant.

        Args:
            connection_id: Internal connection ID

        Returns:
            ConnectionInfo if found, None otherwise
        """
        connection = self._repository.get_by_id(connection_id)
        if not connection:
            return None
        return self._to_connection_info(connection)

    def get_connection_by_airbyte_id(
        self,
        airbyte_connection_id: str
    ) -> Optional[ConnectionInfo]:
        """
        Get a connection by Airbyte's connection ID.

        SECURITY: Only returns connection if it belongs to current tenant.

        Args:
            airbyte_connection_id: Airbyte's connection ID

        Returns:
            ConnectionInfo if found within tenant scope, None otherwise
        """
        connection = self._repository.get_by_airbyte_id(airbyte_connection_id)
        if not connection:
            return None
        return self._to_connection_info(connection)

    def list_connections(
        self,
        status: Optional[str] = None,
        connection_type: Optional[str] = None,
        source_type: Optional[str] = None,
        is_enabled: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0
    ) -> ConnectionListResult:
        """
        List connections for the current tenant.

        CRITICAL: Only returns connections belonging to the tenant.
        Cross-tenant access is impossible.

        Args:
            status: Filter by status (pending/active/inactive/failed/deleted)
            connection_type: Filter by type (source/destination)
            source_type: Filter by source type
            is_enabled: Filter by enabled status
            limit: Maximum number of results (default 50)
            offset: Offset for pagination

        Returns:
            ConnectionListResult with connections and pagination info
        """
        # Parse filters
        status_enum = None
        if status:
            try:
                status_enum = ConnectionStatus(status)
            except ValueError:
                logger.warning(f"Invalid status filter: {status}")

        conn_type_enum = None
        if connection_type:
            try:
                conn_type_enum = ConnectionType(connection_type)
            except ValueError:
                logger.warning(f"Invalid connection_type filter: {connection_type}")

        # Get connections
        connections = self._repository.list_connections(
            status=status_enum,
            connection_type=conn_type_enum,
            source_type=source_type,
            is_enabled=is_enabled,
            limit=limit + 1,  # Fetch one extra to check for more
            offset=offset
        )

        # Check if there are more results
        has_more = len(connections) > limit
        if has_more:
            connections = connections[:limit]

        # Get total count
        total_count = self._repository.count()

        # Convert to ConnectionInfo
        connection_infos = [
            self._to_connection_info(conn) for conn in connections
        ]

        logger.info(
            "Listed connections for tenant",
            extra={
                "tenant_id": self.tenant_id,
                "count": len(connection_infos),
                "total": total_count
            }
        )

        return ConnectionListResult(
            connections=connection_infos,
            total_count=total_count,
            has_more=has_more
        )

    def activate_connection(self, connection_id: str) -> ConnectionInfo:
        """
        Activate a connection (mark as ready for syncing).

        Args:
            connection_id: Internal connection ID

        Returns:
            Updated ConnectionInfo

        Raises:
            ConnectionNotFoundServiceError: If connection not found
        """
        connection = self._repository.update_status(
            connection_id,
            ConnectionStatus.ACTIVE
        )
        if not connection:
            raise ConnectionNotFoundServiceError(
                f"Connection {connection_id} not found"
            )

        logger.info(
            "Connection activated",
            extra={
                "tenant_id": self.tenant_id,
                "connection_id": connection_id
            }
        )

        return self._to_connection_info(connection)

    def deactivate_connection(self, connection_id: str) -> ConnectionInfo:
        """
        Deactivate a connection (mark as inactive).

        Args:
            connection_id: Internal connection ID

        Returns:
            Updated ConnectionInfo

        Raises:
            ConnectionNotFoundServiceError: If connection not found
        """
        connection = self._repository.update_status(
            connection_id,
            ConnectionStatus.INACTIVE
        )
        if not connection:
            raise ConnectionNotFoundServiceError(
                f"Connection {connection_id} not found"
            )

        logger.info(
            "Connection deactivated",
            extra={
                "tenant_id": self.tenant_id,
                "connection_id": connection_id
            }
        )

        return self._to_connection_info(connection)

    def mark_connection_failed(
        self,
        connection_id: str,
        error_message: Optional[str] = None
    ) -> ConnectionInfo:
        """
        Mark a connection as failed.

        Args:
            connection_id: Internal connection ID
            error_message: Optional error message

        Returns:
            Updated ConnectionInfo

        Raises:
            ConnectionNotFoundServiceError: If connection not found
        """
        connection = self._repository.update_status(
            connection_id,
            ConnectionStatus.FAILED,
            last_sync_status="failed"
        )
        if not connection:
            raise ConnectionNotFoundServiceError(
                f"Connection {connection_id} not found"
            )

        logger.warning(
            "Connection marked as failed",
            extra={
                "tenant_id": self.tenant_id,
                "connection_id": connection_id,
                "error_message": error_message
            }
        )

        return self._to_connection_info(connection)

    def record_sync_success(self, connection_id: str) -> ConnectionInfo:
        """
        Record a successful sync for a connection.

        Args:
            connection_id: Internal connection ID

        Returns:
            Updated ConnectionInfo

        Raises:
            ConnectionNotFoundServiceError: If connection not found
        """
        connection = self._repository.update_status(
            connection_id,
            ConnectionStatus.ACTIVE,
            last_sync_status="success"
        )
        if not connection:
            raise ConnectionNotFoundServiceError(
                f"Connection {connection_id} not found"
            )

        logger.info(
            "Sync success recorded",
            extra={
                "tenant_id": self.tenant_id,
                "connection_id": connection_id
            }
        )

        return self._to_connection_info(connection)

    def enable_connection(self, connection_id: str) -> ConnectionInfo:
        """
        Enable a connection for syncing.

        Args:
            connection_id: Internal connection ID

        Returns:
            Updated ConnectionInfo

        Raises:
            ConnectionNotFoundServiceError: If connection not found
        """
        connection = self._repository.enable_connection(connection_id)
        if not connection:
            raise ConnectionNotFoundServiceError(
                f"Connection {connection_id} not found"
            )
        return self._to_connection_info(connection)

    def disable_connection(self, connection_id: str) -> ConnectionInfo:
        """
        Disable a connection from syncing.

        Args:
            connection_id: Internal connection ID

        Returns:
            Updated ConnectionInfo

        Raises:
            ConnectionNotFoundServiceError: If connection not found
        """
        connection = self._repository.disable_connection(connection_id)
        if not connection:
            raise ConnectionNotFoundServiceError(
                f"Connection {connection_id} not found"
            )
        return self._to_connection_info(connection)

    def delete_connection(self, connection_id: str) -> ConnectionInfo:
        """
        Soft delete a connection.

        Marks the connection as deleted but retains for audit purposes.

        Args:
            connection_id: Internal connection ID

        Returns:
            Updated ConnectionInfo

        Raises:
            ConnectionNotFoundServiceError: If connection not found
        """
        connection = self._repository.soft_delete(connection_id)
        if not connection:
            raise ConnectionNotFoundServiceError(
                f"Connection {connection_id} not found"
            )

        logger.info(
            "Connection deleted",
            extra={
                "tenant_id": self.tenant_id,
                "connection_id": connection_id
            }
        )

        return self._to_connection_info(connection)

    def update_sync_frequency(self, connection_id: str, frequency_minutes: int) -> ConnectionInfo:
        """
        Update the sync frequency for a connection.

        Args:
            connection_id: Internal connection ID
            frequency_minutes: Sync interval in minutes (e.g. 60, 1440, 10080)

        Returns:
            Updated ConnectionInfo

        Raises:
            ConnectionNotFoundServiceError: If connection not found
        """
        connection = self._repository.get_by_id(connection_id)
        if not connection:
            raise ConnectionNotFoundServiceError(
                f"Connection {connection_id} not found"
            )
        connection.sync_frequency_minutes = frequency_minutes
        self.db.commit()
        self.db.refresh(connection)

        logger.info(
            "Sync frequency updated",
            extra={
                "tenant_id": self.tenant_id,
                "connection_id": connection_id,
                "frequency_minutes": frequency_minutes,
            }
        )

        return self._to_connection_info(connection)

    def get_active_connections(self) -> List[ConnectionInfo]:
        """
        Get all active and enabled connections for the tenant.

        Convenience method for getting connections ready for syncing.

        Returns:
            List of active ConnectionInfo
        """
        connections = self._repository.get_active_connections()
        return [self._to_connection_info(conn) for conn in connections]

    def connection_belongs_to_tenant(self, airbyte_connection_id: str) -> bool:
        """
        Check if an Airbyte connection belongs to the current tenant.

        Useful for validating webhook payloads or external requests.

        Args:
            airbyte_connection_id: Airbyte's connection ID

        Returns:
            True if connection belongs to tenant, False otherwise
        """
        connection = self._repository.get_by_airbyte_id(airbyte_connection_id)
        return connection is not None
