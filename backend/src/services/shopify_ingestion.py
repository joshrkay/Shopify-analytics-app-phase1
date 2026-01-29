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

import os
import httpx

from src.integrations.airbyte.client import AirbyteClient, get_airbyte_client
from src.integrations.airbyte.models import (
    AirbyteSyncResult,
    AirbyteJobStatus,
    SourceCreationRequest,
    ConnectionCreationRequest,
    ScheduleType,
)
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


# =============================================================================
# Token Validation Utilities
# =============================================================================

@dataclass
class ShopifyTokenValidationResult:
    """Result of validating a Shopify access token."""

    valid: bool
    shop_domain: str
    shop_name: Optional[str] = None
    shop_email: Optional[str] = None
    shop_owner: Optional[str] = None
    currency: Optional[str] = None
    country_code: Optional[str] = None
    timezone: Optional[str] = None
    scopes: Optional[list] = None
    error_message: Optional[str] = None


SHOPIFY_API_VERSION = "2024-01"


async def validate_shopify_token(
    shop_domain: str,
    access_token: str,
) -> ShopifyTokenValidationResult:
    """
    Validate a Shopify access token by querying the Shop API.

    This method makes a GraphQL request to Shopify to verify the token
    is valid and retrieve basic shop information.

    Args:
        shop_domain: Shopify store domain (e.g., 'mystore.myshopify.com')
        access_token: Shopify access token to validate

    Returns:
        ShopifyTokenValidationResult with validation status and shop info
    """
    # Normalize shop domain
    shop_domain = shop_domain.replace("https://", "").replace("http://", "").rstrip("/")

    graphql_url = f"https://{shop_domain}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"

    query = """
    query {
        shop {
            name
            email
            myshopifyDomain
            primaryDomain {
                url
            }
            currencyCode
            timezoneAbbreviation
            billingAddress {
                countryCodeV2
            }
        }
        currentAppInstallation {
            accessScopes {
                handle
            }
        }
    }
    """

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0)
    ) as client:
        try:
            response = await client.post(
                graphql_url,
                json={"query": query},
                headers={
                    "Content-Type": "application/json",
                    "X-Shopify-Access-Token": access_token,
                },
            )

            if response.status_code == 401:
                logger.warning(
                    "Shopify token validation failed: unauthorized",
                    extra={"shop_domain": shop_domain},
                )
                return ShopifyTokenValidationResult(
                    valid=False,
                    shop_domain=shop_domain,
                    error_message="Invalid or expired access token",
                )

            if response.status_code == 402:
                logger.warning(
                    "Shopify token validation failed: store frozen",
                    extra={"shop_domain": shop_domain},
                )
                return ShopifyTokenValidationResult(
                    valid=False,
                    shop_domain=shop_domain,
                    error_message="Store is frozen or payment required",
                )

            if response.status_code >= 400:
                logger.warning(
                    "Shopify token validation failed",
                    extra={
                        "shop_domain": shop_domain,
                        "status_code": response.status_code,
                    },
                )
                return ShopifyTokenValidationResult(
                    valid=False,
                    shop_domain=shop_domain,
                    error_message=f"API error: {response.status_code}",
                )

            result = response.json()

            # Check for GraphQL errors
            if "errors" in result:
                error_msg = str(result["errors"][:200])
                logger.warning(
                    "Shopify token validation GraphQL error",
                    extra={
                        "shop_domain": shop_domain,
                        "errors": error_msg,
                    },
                )
                return ShopifyTokenValidationResult(
                    valid=False,
                    shop_domain=shop_domain,
                    error_message=f"GraphQL error: {error_msg}",
                )

            data = result.get("data", {})
            shop_data = data.get("shop", {})
            app_data = data.get("currentAppInstallation", {})

            # Extract scopes
            scopes = []
            for scope in app_data.get("accessScopes", []):
                if scope.get("handle"):
                    scopes.append(scope["handle"])

            logger.info(
                "Shopify token validated successfully",
                extra={
                    "shop_domain": shop_domain,
                    "shop_name": shop_data.get("name"),
                    "scope_count": len(scopes),
                },
            )

            return ShopifyTokenValidationResult(
                valid=True,
                shop_domain=shop_domain,
                shop_name=shop_data.get("name"),
                shop_email=shop_data.get("email"),
                currency=shop_data.get("currencyCode"),
                timezone=shop_data.get("timezoneAbbreviation"),
                country_code=shop_data.get("billingAddress", {}).get("countryCodeV2"),
                scopes=scopes,
            )

        except httpx.TimeoutException:
            logger.error(
                "Shopify token validation timed out",
                extra={"shop_domain": shop_domain},
            )
            return ShopifyTokenValidationResult(
                valid=False,
                shop_domain=shop_domain,
                error_message="Request timed out",
            )

        except httpx.RequestError as e:
            logger.error(
                "Shopify token validation network error",
                extra={"shop_domain": shop_domain, "error": str(e)},
            )
            return ShopifyTokenValidationResult(
                valid=False,
                shop_domain=shop_domain,
                error_message=f"Network error: {str(e)}",
            )


# =============================================================================
# Automatic Airbyte Source Setup
# =============================================================================

@dataclass
class AutomaticSetupResult:
    """Result of automatic Shopify Airbyte source setup."""

    success: bool
    source_id: Optional[str] = None
    connection_id: Optional[str] = None
    internal_connection_id: Optional[str] = None
    error_message: Optional[str] = None


async def setup_shopify_airbyte_source(
    tenant_id: str,
    shop_domain: str,
    access_token: str,
    db_session: Session,
    destination_id: Optional[str] = None,
    start_date: Optional[str] = None,
    trigger_initial_sync: bool = True,
) -> AutomaticSetupResult:
    """
    Automatically set up a Shopify Airbyte source and connection.

    This method:
    1. Creates a new Airbyte source with Shopify credentials
    2. Creates a connection to the destination
    3. Registers the connection in our tracking system
    4. Optionally triggers an initial sync

    Args:
        tenant_id: Tenant ID from JWT
        shop_domain: Shopify store domain
        access_token: Shopify access token (will be encrypted)
        db_session: Database session
        destination_id: Airbyte destination ID (defaults to env var)
        start_date: Optional start date for sync (ISO format)
        trigger_initial_sync: Whether to trigger initial sync

    Returns:
        AutomaticSetupResult with setup status and IDs
    """
    # Normalize shop domain
    shop_domain = shop_domain.replace("https://", "").replace("http://", "").rstrip("/")

    # Get destination ID from environment if not provided
    destination_id = destination_id or os.getenv("AIRBYTE_DESTINATION_ID")
    if not destination_id:
        logger.error(
            "Airbyte destination ID not configured",
            extra={"tenant_id": tenant_id, "shop_domain": shop_domain},
        )
        return AutomaticSetupResult(
            success=False,
            error_message="Airbyte destination ID not configured. Set AIRBYTE_DESTINATION_ID environment variable.",
        )

    # Default start date to 1 year ago if not provided
    if not start_date:
        from datetime import datetime, timedelta
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    airbyte_client = get_airbyte_client()

    try:
        # Step 1: Create Airbyte source
        logger.info(
            "Creating Shopify Airbyte source",
            extra={"tenant_id": tenant_id, "shop_domain": shop_domain},
        )

        source_request = SourceCreationRequest(
            name=f"Shopify - {shop_domain}",
            source_type="source-shopify",
            configuration={
                "shop": shop_domain,
                "credentials": {
                    "auth_method": "api_password",
                    "api_password": access_token,
                },
                "start_date": start_date,
                "bulk_window_in_days": 30,
            },
        )

        source = await airbyte_client.create_source(source_request)

        logger.info(
            "Shopify Airbyte source created",
            extra={
                "tenant_id": tenant_id,
                "shop_domain": shop_domain,
                "source_id": source.source_id,
            },
        )

        # Step 2: Create Airbyte connection
        logger.info(
            "Creating Airbyte connection",
            extra={
                "tenant_id": tenant_id,
                "source_id": source.source_id,
                "destination_id": destination_id,
            },
        )

        connection_request = ConnectionCreationRequest(
            source_id=source.source_id,
            destination_id=destination_id,
            name=f"Shopify - {shop_domain} → Warehouse",
            schedule_type=ScheduleType.BASIC,  # Will sync on schedule
        )

        connection = await airbyte_client.create_connection(connection_request)

        logger.info(
            "Airbyte connection created",
            extra={
                "tenant_id": tenant_id,
                "connection_id": connection.connection_id,
            },
        )

        # Step 3: Register in our tracking system
        airbyte_service = AirbyteService(db_session, tenant_id)

        internal_connection = airbyte_service.register_connection(
            airbyte_connection_id=connection.connection_id,
            connection_name=f"{shop_domain} - Shopify",
            connection_type="source",
            airbyte_source_id=source.source_id,
            source_type="source-shopify",
            configuration={
                "shop_domain": shop_domain,
                "start_date": start_date,
                "streams": ["orders", "customers", "products", "inventory_levels"],
            },
            sync_frequency_minutes="60",
        )

        logger.info(
            "Connection registered in tracking system",
            extra={
                "tenant_id": tenant_id,
                "internal_connection_id": internal_connection.id,
            },
        )

        # Step 4: Optionally trigger initial sync
        if trigger_initial_sync:
            logger.info(
                "Triggering initial sync",
                extra={
                    "tenant_id": tenant_id,
                    "connection_id": connection.connection_id,
                },
            )

            job_id = await airbyte_client.trigger_sync(connection.connection_id)

            logger.info(
                "Initial sync triggered",
                extra={
                    "tenant_id": tenant_id,
                    "job_id": job_id,
                },
            )

        return AutomaticSetupResult(
            success=True,
            source_id=source.source_id,
            connection_id=connection.connection_id,
            internal_connection_id=internal_connection.id,
        )

    except AirbyteError as e:
        logger.error(
            "Failed to set up Shopify Airbyte source",
            extra={
                "tenant_id": tenant_id,
                "shop_domain": shop_domain,
                "error": str(e),
            },
        )
        return AutomaticSetupResult(
            success=False,
            error_message=f"Airbyte API error: {str(e)}",
        )

    except Exception as e:
        logger.error(
            "Unexpected error setting up Shopify Airbyte source",
            extra={
                "tenant_id": tenant_id,
                "shop_domain": shop_domain,
                "error": str(e),
            },
        )
        return AutomaticSetupResult(
            success=False,
            error_message=f"Unexpected error: {str(e)}",
        )

    finally:
        await airbyte_client.close()
