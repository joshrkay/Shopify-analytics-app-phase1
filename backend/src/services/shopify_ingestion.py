"""
Shopify data ingestion service via Airbyte.

This service handles:
- Shopify Airbyte source configuration
- Encrypted credential storage
- Initial and incremental sync orchestration
- Sync result logging and error handling

SECURITY: All Shopify credentials are encrypted at rest using Fernet encryption.
Tenant isolation is enforced - each store's data sync is scoped to its tenant.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.integrations.airbyte.client import AirbyteClient, get_airbyte_client
from src.integrations.airbyte.models import AirbyteSyncResult, AirbyteJobStatus
from src.integrations.airbyte.exceptions import (
    AirbyteError,
    AirbyteSyncError,
    AirbyteConnectionError,
)
from src.services.airbyte_service import AirbyteService
from src.models.store import ShopifyStore
from src.platform.secrets import encrypt_secret, decrypt_secret, redact_secrets

logger = logging.getLogger(__name__)


@dataclass
class ShopifyIngestionConfig:
    """Configuration for Shopify Airbyte source."""

    shop_domain: str
    access_token: str
    start_date: Optional[str] = None  # ISO format date string
    stream_selection: Optional[Dict[str, bool]] = None  # Which streams to sync


@dataclass
class SyncResult:
    """Result of a sync operation."""

    success: bool
    job_id: Optional[str] = None
    connection_id: Optional[str] = None
    records_synced: int = 0
    bytes_synced: int = 0
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    synced_at: Optional[datetime] = None


class ShopifyIngestionError(Exception):
    """Base exception for Shopify ingestion errors."""

    pass


class CredentialEncryptionError(ShopifyIngestionError):
    """Raised when credential encryption/decryption fails."""

    pass


class SourceConfigurationError(ShopifyIngestionError):
    """Raised when Airbyte source configuration is invalid."""

    pass


class SyncExecutionError(ShopifyIngestionError):
    """Raised when sync execution fails."""

    pass


class ShopifyIngestionService:
    """
    Service for managing Shopify data ingestion via Airbyte.

    This service orchestrates:
    - Shopify Airbyte source setup and registration
    - Encrypted credential storage
    - Initial and incremental sync execution
    - Sync result logging and status tracking

    SECURITY:
    - All credentials are encrypted before storage
    - Tenant isolation is enforced via AirbyteService
    - No credentials are logged (redacted automatically)
    """

    def __init__(self, db_session: Session, tenant_id: str):
        """
        Initialize Shopify ingestion service.

        Args:
            db_session: Database session
            tenant_id: Tenant ID from JWT (org_id)

        Raises:
            ValueError: If tenant_id is empty
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id
        self._airbyte_service = AirbyteService(db_session, tenant_id)

    async def create_shopify_source(
        self,
        store: ShopifyStore,
        airbyte_source_id: str,
        connection_name: Optional[str] = None,
        airbyte_connection_id: Optional[str] = None,
        sync_frequency_minutes: str = "60",
    ) -> str:
        """
        Register a Shopify Airbyte source for a store.

        NOTE: The Airbyte source must be created manually in Airbyte Cloud UI first.
        This method registers the existing source with our tenant-scoped connection tracking.

        Steps to create source in Airbyte UI:
        1. Go to Sources in Airbyte Cloud
        2. Click "+ New Source"
        3. Select "Shopify"
        4. Configure:
           - Name: Store name
           - Shop: Store domain (e.g., mystore.myshopify.com)
           - Credentials: Use the encrypted access token from store
           - Start Date: When to start syncing from
        5. Copy the Source ID and pass it to this method

        Args:
            store: ShopifyStore instance
            airbyte_source_id: Airbyte source ID (from Airbyte UI)
            connection_name: Optional connection name (defaults to store name)
            airbyte_connection_id: Optional existing Airbyte connection ID
            sync_frequency_minutes: Sync frequency in minutes (default: 60)

        Returns:
            Internal connection ID

        Raises:
            SourceConfigurationError: If source configuration is invalid
            CredentialEncryptionError: If credential encryption fails
        """
        if not store.has_valid_token:
            raise SourceConfigurationError(
                f"Store {store.shop_domain} does not have a valid access token"
            )

        # Decrypt access token for Airbyte source configuration
        try:
            access_token = await decrypt_secret(store.access_token_encrypted)
        except Exception as e:
            logger.error(
                "Failed to decrypt store access token",
                extra={
                    "tenant_id": self.tenant_id,
                    "store_id": store.id,
                    "shop_domain": store.shop_domain,
                    "error": str(e),
                },
            )
            raise CredentialEncryptionError(f"Failed to decrypt access token: {e}")

        # Register connection with Airbyte service
        connection_name = connection_name or f"{store.shop_name or store.shop_domain} - Shopify"

        try:
            connection_info = self._airbyte_service.register_connection(
                airbyte_connection_id=airbyte_connection_id or f"shopify-{store.id}",
                connection_name=connection_name,
                connection_type="source",
                airbyte_source_id=airbyte_source_id,
                source_type="shopify",
                configuration={
                    "shop_domain": store.shop_domain,
                    "shop_name": store.shop_name,
                    "streams": ["orders", "customers"],  # Default streams
                },
                sync_frequency_minutes=sync_frequency_minutes,
            )

            logger.info(
                "Shopify Airbyte source registered",
                extra={
                    "tenant_id": self.tenant_id,
                    "store_id": store.id,
                    "connection_id": connection_info.id,
                    "airbyte_source_id": airbyte_source_id,
                    "shop_domain": redact_secrets({"shop_domain": store.shop_domain}),
                },
            )

            return connection_info.id

        except Exception as e:
            logger.error(
                "Failed to register Shopify Airbyte source",
                extra={
                    "tenant_id": self.tenant_id,
                    "store_id": store.id,
                    "error": str(e),
                },
            )
            raise SourceConfigurationError(f"Failed to register source: {e}")

    async def trigger_initial_sync(
        self,
        connection_id: str,
        wait_for_completion: bool = True,
        timeout_seconds: float = 3600.0,
    ) -> SyncResult:
        """
        Trigger an initial full sync for a Shopify connection.

        This performs a full historical sync of orders and customers.

        Args:
            connection_id: Internal connection ID
            wait_for_completion: Whether to wait for sync to complete
            timeout_seconds: Maximum wait time if waiting for completion

        Returns:
            SyncResult with sync status and metrics

        Raises:
            SyncExecutionError: If sync fails
        """
        # Get connection info
        connection_info = self._airbyte_service.get_connection(connection_id)
        if not connection_info:
            raise SyncExecutionError(f"Connection {connection_id} not found")

        if not connection_info.can_sync:
            raise SyncExecutionError(
                f"Connection {connection_id} is not enabled or active"
            )

        # Get Airbyte client
        airbyte_client = get_airbyte_client()

        try:
            logger.info(
                "Triggering initial Shopify sync",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id,
                    "airbyte_connection_id": connection_info.airbyte_connection_id,
                },
            )

            if wait_for_completion:
                # Trigger and wait for completion
                sync_result = await airbyte_client.sync_and_wait(
                    connection_id=connection_info.airbyte_connection_id,
                    timeout_seconds=timeout_seconds,
                )

                result = SyncResult(
                    success=sync_result.is_successful,
                    job_id=sync_result.job_id,
                    connection_id=connection_id,
                    records_synced=sync_result.records_synced,
                    bytes_synced=sync_result.bytes_synced,
                    duration_seconds=sync_result.duration_seconds,
                    error_message=sync_result.error_message,
                    synced_at=datetime.now(timezone.utc),
                )

                # Update connection status
                if result.success:
                    self._airbyte_service.record_sync_success(connection_id)
                    logger.info(
                        "Initial Shopify sync completed successfully",
                        extra={
                            "tenant_id": self.tenant_id,
                            "connection_id": connection_id,
                            "records_synced": result.records_synced,
                            "bytes_synced": result.bytes_synced,
                            "duration_seconds": result.duration_seconds,
                        },
                    )
                else:
                    self._airbyte_service.mark_connection_failed(
                        connection_id, result.error_message
                    )
                    logger.warning(
                        "Initial Shopify sync failed",
                        extra={
                            "tenant_id": self.tenant_id,
                            "connection_id": connection_id,
                            "error_message": result.error_message,
                        },
                    )

            else:
                # Just trigger, don't wait
                job_id = await airbyte_client.trigger_sync(
                    connection_info.airbyte_connection_id
                )

                result = SyncResult(
                    success=True,  # Trigger succeeded
                    job_id=job_id,
                    connection_id=connection_id,
                    synced_at=datetime.now(timezone.utc),
                )

                logger.info(
                    "Initial Shopify sync triggered",
                    extra={
                        "tenant_id": self.tenant_id,
                        "connection_id": connection_id,
                        "job_id": job_id,
                    },
                )

            return result

        except AirbyteSyncError as e:
            error_msg = f"Sync failed: {str(e)}"
            logger.error(
                "Shopify sync error",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id,
                    "error": error_msg,
                },
            )

            self._airbyte_service.mark_connection_failed(connection_id, error_msg)

            raise SyncExecutionError(error_msg) from e

        except AirbyteError as e:
            error_msg = f"Airbyte API error: {str(e)}"
            logger.error(
                "Airbyte API error during sync",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id,
                    "error": error_msg,
                },
            )

            raise SyncExecutionError(error_msg) from e

        finally:
            await airbyte_client.close()

    async def trigger_incremental_sync(
        self,
        connection_id: str,
        wait_for_completion: bool = False,
        timeout_seconds: float = 3600.0,
    ) -> SyncResult:
        """
        Trigger an incremental sync for a Shopify connection.

        This syncs only new/updated data since the last sync.

        Args:
            connection_id: Internal connection ID
            wait_for_completion: Whether to wait for sync to complete
            timeout_seconds: Maximum wait time if waiting for completion

        Returns:
            SyncResult with sync status and metrics

        Raises:
            SyncExecutionError: If sync fails
        """
        # Incremental sync uses the same mechanism as initial sync
        # Airbyte handles incremental logic based on connection configuration
        return await self.trigger_initial_sync(
            connection_id=connection_id,
            wait_for_completion=wait_for_completion,
            timeout_seconds=timeout_seconds,
        )

    async def sync_all_active_stores(
        self, wait_for_completion: bool = False
    ) -> Dict[str, SyncResult]:
        """
        Sync all active Shopify stores for the tenant.

        This method is designed to be called by a scheduled job (cron).

        Args:
            wait_for_completion: Whether to wait for each sync to complete

        Returns:
            Dictionary mapping connection_id to SyncResult
        """
        # Get all active Shopify connections for tenant
        connections = self._airbyte_service.list_connections(
            source_type="shopify",
            is_enabled=True,
            limit=100,  # Reasonable limit
        )

        results = {}

        logger.info(
            "Syncing all active Shopify stores",
            extra={
                "tenant_id": self.tenant_id,
                "connection_count": len(connections.connections),
            },
        )

        for connection in connections.connections:
            try:
                result = await self.trigger_incremental_sync(
                    connection_id=connection.id,
                    wait_for_completion=wait_for_completion,
                )
                results[connection.id] = result

            except Exception as e:
                logger.error(
                    "Failed to sync connection",
                    extra={
                        "tenant_id": self.tenant_id,
                        "connection_id": connection.id,
                        "error": str(e),
                    },
                )

                results[connection.id] = SyncResult(
                    success=False,
                    connection_id=connection.id,
                    error_message=str(e),
                    synced_at=datetime.now(timezone.utc),
                )

        # Log summary
        successful = sum(1 for r in results.values() if r.success)
        failed = len(results) - successful
        total_records = sum(r.records_synced for r in results.values() if r.success)

        logger.info(
            "Completed sync of all active Shopify stores",
            extra={
                "tenant_id": self.tenant_id,
                "total_connections": len(results),
                "successful": successful,
                "failed": failed,
                "total_records_synced": total_records,
            },
        )

        return results

    def get_sync_status(self, connection_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the current sync status for a connection.

        Args:
            connection_id: Internal connection ID

        Returns:
            Dictionary with sync status information, or None if connection not found
        """
        connection_info = self._airbyte_service.get_connection(connection_id)
        if not connection_info:
            return None

        return {
            "connection_id": connection_info.id,
            "connection_name": connection_info.connection_name,
            "status": connection_info.status,
            "is_enabled": connection_info.is_enabled,
            "can_sync": connection_info.can_sync,
            "last_sync_at": (
                connection_info.last_sync_at.isoformat()
                if connection_info.last_sync_at
                else None
            ),
            "last_sync_status": connection_info.last_sync_status,
        }
