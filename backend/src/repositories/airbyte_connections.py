"""
Repository for tenant-scoped Airbyte connection management.

CRITICAL: All operations are strictly scoped by tenant_id.
Cross-tenant access is impossible by design.
"""

import logging
from typing import Optional, List
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from src.repositories.base_repo import BaseRepository, TenantIsolationError
from src.models.airbyte_connection import (
    TenantAirbyteConnection,
    ConnectionStatus,
    ConnectionType,
)

logger = logging.getLogger(__name__)


class AirbyteConnectionRepositoryError(Exception):
    """Base exception for Airbyte connection repository errors."""
    pass


class ConnectionNotFoundError(AirbyteConnectionRepositoryError):
    """Connection not found within tenant scope."""
    pass


class ConnectionAlreadyExistsError(AirbyteConnectionRepositoryError):
    """Connection with same Airbyte ID already exists."""
    pass


class AirbyteConnectionsRepository(BaseRepository[TenantAirbyteConnection]):
    """
    Repository for managing tenant-scoped Airbyte connections.

    SECURITY: All operations are automatically scoped to tenant_id.
    No query can access connections belonging to other tenants.
    """

    def _get_model_class(self) -> type[TenantAirbyteConnection]:
        """Return the model class for this repository."""
        return TenantAirbyteConnection

    def _get_tenant_column_name(self) -> str:
        """Return the name of the tenant_id column."""
        return "tenant_id"

    def get_by_airbyte_id(
        self,
        airbyte_connection_id: str,
        tenant_id: Optional[str] = None
    ) -> Optional[TenantAirbyteConnection]:
        """
        Get connection by Airbyte connection ID, scoped to tenant.

        Args:
            airbyte_connection_id: Airbyte's connection ID
            tenant_id: Optional tenant_id for validation

        Returns:
            TenantAirbyteConnection if found within tenant scope, None otherwise

        Raises:
            TenantIsolationError: If tenant_id mismatch detected
        """
        self._validate_tenant_id(tenant_id, "get_by_airbyte_id")

        query = self.db_session.query(self._model_class)
        query = self._enforce_tenant_scope(query)
        return query.filter(
            TenantAirbyteConnection.airbyte_connection_id == airbyte_connection_id
        ).first()

    def list_connections(
        self,
        status: Optional[ConnectionStatus] = None,
        connection_type: Optional[ConnectionType] = None,
        source_type: Optional[str] = None,
        is_enabled: Optional[bool] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        tenant_id: Optional[str] = None
    ) -> List[TenantAirbyteConnection]:
        """
        List connections for tenant with optional filters.

        SECURITY: Only returns connections belonging to the tenant.

        Args:
            status: Filter by connection status
            connection_type: Filter by connection type (source/destination)
            source_type: Filter by source type (e.g., shopify, postgres)
            is_enabled: Filter by enabled status
            limit: Maximum number of results
            offset: Offset for pagination
            tenant_id: Optional tenant_id for validation

        Returns:
            List of TenantAirbyteConnection for the tenant

        Raises:
            TenantIsolationError: If tenant_id mismatch detected
        """
        self._validate_tenant_id(tenant_id, "list_connections")

        query = self.db_session.query(self._model_class)
        query = self._enforce_tenant_scope(query)

        if status is not None:
            query = query.filter(TenantAirbyteConnection.status == status)

        if connection_type is not None:
            query = query.filter(TenantAirbyteConnection.connection_type == connection_type)

        if source_type is not None:
            query = query.filter(TenantAirbyteConnection.source_type == source_type)

        if is_enabled is not None:
            query = query.filter(TenantAirbyteConnection.is_enabled == is_enabled)

        # Order by created_at descending (newest first)
        query = query.order_by(TenantAirbyteConnection.created_at.desc())

        if offset:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)

        return query.all()

    def create_connection(
        self,
        airbyte_connection_id: str,
        connection_name: str,
        connection_type: ConnectionType = ConnectionType.SOURCE,
        airbyte_source_id: Optional[str] = None,
        airbyte_destination_id: Optional[str] = None,
        source_type: Optional[str] = None,
        configuration: Optional[dict] = None,
        sync_frequency_minutes: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> TenantAirbyteConnection:
        """
        Create a new Airbyte connection for the tenant.

        SECURITY: tenant_id is always set from repository context,
        never from parameters.

        Args:
            airbyte_connection_id: Airbyte's connection ID
            connection_name: Human-readable connection name
            connection_type: Type of connection (source/destination)
            airbyte_source_id: Airbyte source ID
            airbyte_destination_id: Airbyte destination ID
            source_type: Type of data source
            configuration: Non-sensitive configuration metadata
            sync_frequency_minutes: Sync frequency
            tenant_id: Optional tenant_id for validation

        Returns:
            Created TenantAirbyteConnection

        Raises:
            TenantIsolationError: If tenant_id mismatch detected
            ConnectionAlreadyExistsError: If connection with same Airbyte ID exists
        """
        self._validate_tenant_id(tenant_id, "create_connection")

        # Build entity data
        entity_data = {
            "airbyte_connection_id": airbyte_connection_id,
            "connection_name": connection_name,
            "connection_type": connection_type,
            "airbyte_source_id": airbyte_source_id,
            "airbyte_destination_id": airbyte_destination_id,
            "source_type": source_type,
            "configuration": configuration or {},
            "sync_frequency_minutes": sync_frequency_minutes or "60",
            "status": ConnectionStatus.PENDING,
            "is_enabled": True,
        }

        try:
            connection = self.create(entity_data)

            logger.info(
                "Airbyte connection created",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection.id,
                    "airbyte_connection_id": airbyte_connection_id,
                    "connection_name": connection_name
                }
            )

            return connection

        except IntegrityError as e:
            self.db_session.rollback()
            if "airbyte_connection_id" in str(e).lower() or "unique" in str(e).lower():
                logger.warning(
                    "Duplicate Airbyte connection ID",
                    extra={
                        "tenant_id": self.tenant_id,
                        "airbyte_connection_id": airbyte_connection_id
                    }
                )
                raise ConnectionAlreadyExistsError(
                    f"Connection with Airbyte ID {airbyte_connection_id} already exists"
                )
            raise

    def update_status(
        self,
        connection_id: str,
        status: ConnectionStatus,
        last_sync_status: Optional[str] = None,
        tenant_id: Optional[str] = None
    ) -> Optional[TenantAirbyteConnection]:
        """
        Update connection status within tenant scope.

        Args:
            connection_id: Connection ID
            status: New status
            last_sync_status: Status of last sync (optional)
            tenant_id: Optional tenant_id for validation

        Returns:
            Updated TenantAirbyteConnection or None if not found

        Raises:
            TenantIsolationError: If tenant_id mismatch detected
        """
        self._validate_tenant_id(tenant_id, "update_status")

        connection = self.get_by_id(connection_id)
        if not connection:
            return None

        old_status = connection.status
        connection.status = status

        if last_sync_status:
            connection.last_sync_status = last_sync_status
            if last_sync_status == "success":
                connection.last_sync_at = datetime.now(timezone.utc)

        try:
            self.db_session.commit()
            self.db_session.refresh(connection)

            logger.info(
                "Connection status updated",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id,
                    "old_status": old_status.value if old_status else None,
                    "new_status": status.value
                }
            )

            return connection

        except SQLAlchemyError as e:
            self.db_session.rollback()
            logger.error(
                "Failed to update connection status",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id,
                    "error": str(e)
                }
            )
            raise

    def enable_connection(
        self,
        connection_id: str,
        tenant_id: Optional[str] = None
    ) -> Optional[TenantAirbyteConnection]:
        """
        Enable a connection for syncing.

        Args:
            connection_id: Connection ID
            tenant_id: Optional tenant_id for validation

        Returns:
            Updated TenantAirbyteConnection or None if not found

        Raises:
            TenantIsolationError: If tenant_id mismatch detected
        """
        self._validate_tenant_id(tenant_id, "enable_connection")

        connection = self.get_by_id(connection_id)
        if not connection:
            return None

        connection.is_enabled = True

        try:
            self.db_session.commit()
            self.db_session.refresh(connection)

            logger.info(
                "Connection enabled",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id
                }
            )

            return connection

        except SQLAlchemyError as e:
            self.db_session.rollback()
            logger.error(
                "Failed to enable connection",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id,
                    "error": str(e)
                }
            )
            raise

    def disable_connection(
        self,
        connection_id: str,
        tenant_id: Optional[str] = None
    ) -> Optional[TenantAirbyteConnection]:
        """
        Disable a connection from syncing.

        Args:
            connection_id: Connection ID
            tenant_id: Optional tenant_id for validation

        Returns:
            Updated TenantAirbyteConnection or None if not found

        Raises:
            TenantIsolationError: If tenant_id mismatch detected
        """
        self._validate_tenant_id(tenant_id, "disable_connection")

        connection = self.get_by_id(connection_id)
        if not connection:
            return None

        connection.is_enabled = False

        try:
            self.db_session.commit()
            self.db_session.refresh(connection)

            logger.info(
                "Connection disabled",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id
                }
            )

            return connection

        except SQLAlchemyError as e:
            self.db_session.rollback()
            logger.error(
                "Failed to disable connection",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id,
                    "error": str(e)
                }
            )
            raise

    def get_active_connections(
        self,
        tenant_id: Optional[str] = None
    ) -> List[TenantAirbyteConnection]:
        """
        Get all active and enabled connections for tenant.

        Convenience method for getting connections ready for syncing.

        Args:
            tenant_id: Optional tenant_id for validation

        Returns:
            List of active TenantAirbyteConnection

        Raises:
            TenantIsolationError: If tenant_id mismatch detected
        """
        return self.list_connections(
            status=ConnectionStatus.ACTIVE,
            is_enabled=True,
            tenant_id=tenant_id
        )

    def soft_delete(
        self,
        connection_id: str,
        tenant_id: Optional[str] = None
    ) -> Optional[TenantAirbyteConnection]:
        """
        Soft delete a connection (mark as deleted).

        Does not remove from database, just marks status as DELETED
        and disables the connection.

        Args:
            connection_id: Connection ID
            tenant_id: Optional tenant_id for validation

        Returns:
            Updated TenantAirbyteConnection or None if not found

        Raises:
            TenantIsolationError: If tenant_id mismatch detected
        """
        self._validate_tenant_id(tenant_id, "soft_delete")

        connection = self.get_by_id(connection_id)
        if not connection:
            return None

        connection.status = ConnectionStatus.DELETED
        connection.is_enabled = False

        try:
            self.db_session.commit()
            self.db_session.refresh(connection)

            logger.info(
                "Connection soft deleted",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id
                }
            )

            return connection

        except SQLAlchemyError as e:
            self.db_session.rollback()
            logger.error(
                "Failed to soft delete connection",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id,
                    "error": str(e)
                }
            )
            raise
