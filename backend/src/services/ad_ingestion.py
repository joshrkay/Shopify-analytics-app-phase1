"""
Ad platform ingestion service for Meta Ads and Google Ads.

This service orchestrates:
- OAuth credential storage (encrypted)
- Airbyte source/connection creation for ad platforms
- Sync triggering and health monitoring

SECURITY: OAuth tokens are encrypted before storage.
CRITICAL: All operations are tenant-scoped via tenant_id from JWT.

Story 3.4 - Ad Platform Ingestion
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, List

from sqlalchemy.orm import Session

from src.integrations.airbyte.client import AirbyteClient, get_airbyte_client
from src.integrations.airbyte.exceptions import (
    AirbyteError,
    AirbyteNotFoundError,
    AirbyteSyncError,
)
from src.integrations.airbyte.models import AirbyteJobStatus
from src.platform.secrets import encrypt_secret, decrypt_secret
from src.services.airbyte_service import (
    AirbyteService,
    ConnectionNotFoundServiceError,
    DuplicateConnectionError,
)

logger = logging.getLogger(__name__)


class AdPlatform(str, Enum):
    """Supported ad platforms."""
    META_ADS = "meta_ads"
    GOOGLE_ADS = "google_ads"


# Airbyte source type identifiers
AIRBYTE_SOURCE_TYPES = {
    AdPlatform.META_ADS: "source-facebook-marketing",
    AdPlatform.GOOGLE_ADS: "source-google-ads",
}


@dataclass
class AdAccountCredentials:
    """OAuth credentials for an ad platform account."""
    platform: AdPlatform
    account_id: str
    access_token: str
    refresh_token: Optional[str] = None
    # Meta-specific fields
    app_id: Optional[str] = None
    app_secret: Optional[str] = None
    # Google-specific fields
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    developer_token: Optional[str] = None
    customer_id: Optional[str] = None


@dataclass
class AdAccountInfo:
    """Information about a connected ad account."""
    id: str
    platform: str
    account_id: str
    account_name: str
    connection_id: str
    airbyte_connection_id: str
    status: str
    is_enabled: bool
    last_sync_at: Optional[datetime]
    last_sync_status: Optional[str]
    created_at: datetime


@dataclass
class SyncStatus:
    """Status of a sync operation."""
    job_id: str
    connection_id: str
    status: str
    is_running: bool
    is_complete: bool
    is_successful: bool
    records_synced: int
    bytes_synced: int
    duration_seconds: Optional[float]
    error_message: Optional[str]


class AdIngestionError(Exception):
    """Base exception for ad ingestion errors."""
    pass


class InvalidCredentialsError(AdIngestionError):
    """Credentials are invalid or incomplete."""
    pass


class AccountNotFoundError(AdIngestionError):
    """Ad account not found within tenant scope."""
    pass


class SyncError(AdIngestionError):
    """Sync operation failed."""
    pass


class AdIngestionService:
    """
    Service for managing ad platform data ingestion.

    Supports Meta Ads and Google Ads connectors via Airbyte.
    OAuth tokens are stored encrypted for security.

    SECURITY: All methods require tenant_id from JWT context.
    """

    def __init__(
        self,
        db_session: Session,
        tenant_id: str,
        airbyte_client: Optional[AirbyteClient] = None,
    ):
        """
        Initialize ad ingestion service.

        Args:
            db_session: Database session
            tenant_id: Tenant ID from JWT (org_id)
            airbyte_client: Optional Airbyte client (creates default if not provided)

        Raises:
            ValueError: If tenant_id is empty or None
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id
        self._airbyte_service = AirbyteService(db_session, tenant_id)
        self._airbyte_client = airbyte_client

    def _get_airbyte_client(self) -> AirbyteClient:
        """Get or create Airbyte client."""
        if self._airbyte_client is None:
            self._airbyte_client = get_airbyte_client()
        return self._airbyte_client

    def _validate_meta_credentials(self, credentials: AdAccountCredentials) -> None:
        """Validate Meta Ads credentials are complete."""
        if not credentials.access_token:
            raise InvalidCredentialsError("Meta Ads requires access_token")
        if not credentials.account_id:
            raise InvalidCredentialsError("Meta Ads requires account_id")

    def _validate_google_credentials(self, credentials: AdAccountCredentials) -> None:
        """Validate Google Ads credentials are complete."""
        if not credentials.access_token:
            raise InvalidCredentialsError("Google Ads requires access_token")
        if not credentials.refresh_token:
            raise InvalidCredentialsError("Google Ads requires refresh_token")
        if not credentials.client_id:
            raise InvalidCredentialsError("Google Ads requires client_id")
        if not credentials.client_secret:
            raise InvalidCredentialsError("Google Ads requires client_secret")
        if not credentials.developer_token:
            raise InvalidCredentialsError("Google Ads requires developer_token")
        if not credentials.customer_id:
            raise InvalidCredentialsError("Google Ads requires customer_id")

    def _validate_credentials(self, credentials: AdAccountCredentials) -> None:
        """Validate credentials based on platform."""
        if credentials.platform == AdPlatform.META_ADS:
            self._validate_meta_credentials(credentials)
        elif credentials.platform == AdPlatform.GOOGLE_ADS:
            self._validate_google_credentials(credentials)
        else:
            raise InvalidCredentialsError(f"Unsupported platform: {credentials.platform}")

    async def _encrypt_credentials(
        self,
        credentials: AdAccountCredentials
    ) -> dict:
        """
        Encrypt OAuth credentials for secure storage.

        SECURITY: All tokens are encrypted before being stored.

        Args:
            credentials: The credentials to encrypt

        Returns:
            Dictionary with encrypted credential values
        """
        encrypted = {
            "platform": credentials.platform.value,
            "account_id": credentials.account_id,
        }

        # Encrypt access token (always required)
        encrypted["access_token_encrypted"] = await encrypt_secret(
            credentials.access_token
        )

        # Encrypt optional tokens if present
        if credentials.refresh_token:
            encrypted["refresh_token_encrypted"] = await encrypt_secret(
                credentials.refresh_token
            )

        if credentials.app_secret:
            encrypted["app_secret_encrypted"] = await encrypt_secret(
                credentials.app_secret
            )

        if credentials.client_secret:
            encrypted["client_secret_encrypted"] = await encrypt_secret(
                credentials.client_secret
            )

        if credentials.developer_token:
            encrypted["developer_token_encrypted"] = await encrypt_secret(
                credentials.developer_token
            )

        # Non-sensitive identifiers (stored unencrypted)
        if credentials.app_id:
            encrypted["app_id"] = credentials.app_id
        if credentials.client_id:
            encrypted["client_id"] = credentials.client_id
        if credentials.customer_id:
            encrypted["customer_id"] = credentials.customer_id

        return encrypted

    async def _decrypt_credentials(
        self,
        encrypted_config: dict
    ) -> AdAccountCredentials:
        """
        Decrypt stored credentials.

        Args:
            encrypted_config: Dictionary with encrypted credentials

        Returns:
            Decrypted AdAccountCredentials
        """
        platform = AdPlatform(encrypted_config["platform"])

        access_token = await decrypt_secret(
            encrypted_config["access_token_encrypted"]
        )

        refresh_token = None
        if encrypted_config.get("refresh_token_encrypted"):
            refresh_token = await decrypt_secret(
                encrypted_config["refresh_token_encrypted"]
            )

        app_secret = None
        if encrypted_config.get("app_secret_encrypted"):
            app_secret = await decrypt_secret(
                encrypted_config["app_secret_encrypted"]
            )

        client_secret = None
        if encrypted_config.get("client_secret_encrypted"):
            client_secret = await decrypt_secret(
                encrypted_config["client_secret_encrypted"]
            )

        developer_token = None
        if encrypted_config.get("developer_token_encrypted"):
            developer_token = await decrypt_secret(
                encrypted_config["developer_token_encrypted"]
            )

        return AdAccountCredentials(
            platform=platform,
            account_id=encrypted_config["account_id"],
            access_token=access_token,
            refresh_token=refresh_token,
            app_id=encrypted_config.get("app_id"),
            app_secret=app_secret,
            client_id=encrypted_config.get("client_id"),
            client_secret=client_secret,
            developer_token=developer_token,
            customer_id=encrypted_config.get("customer_id"),
        )

    async def connect_ad_account(
        self,
        credentials: AdAccountCredentials,
        account_name: str,
        airbyte_connection_id: str,
        airbyte_source_id: Optional[str] = None,
    ) -> AdAccountInfo:
        """
        Connect an ad platform account.

        Validates credentials, encrypts OAuth tokens, and registers
        the Airbyte connection with the tenant.

        SECURITY: OAuth tokens are encrypted before storage.

        Args:
            credentials: OAuth credentials for the ad platform
            account_name: Human-readable account name
            airbyte_connection_id: Airbyte connection ID for this source
            airbyte_source_id: Optional Airbyte source ID

        Returns:
            AdAccountInfo with connection details

        Raises:
            InvalidCredentialsError: If credentials are incomplete
            DuplicateConnectionError: If account already connected
        """
        # Validate credentials
        self._validate_credentials(credentials)

        # Encrypt credentials for storage
        encrypted_config = await self._encrypt_credentials(credentials)

        # Get source type for this platform
        source_type = AIRBYTE_SOURCE_TYPES[credentials.platform]

        # Register connection with Airbyte service
        try:
            connection_info = self._airbyte_service.register_connection(
                airbyte_connection_id=airbyte_connection_id,
                connection_name=account_name,
                connection_type="source",
                airbyte_source_id=airbyte_source_id,
                source_type=source_type,
                configuration=encrypted_config,
            )
        except DuplicateConnectionError:
            raise DuplicateConnectionError(
                f"Ad account {credentials.account_id} is already connected"
            )

        # Activate the connection
        activated_connection = self._airbyte_service.activate_connection(
            connection_info.id
        )

        logger.info(
            "Ad account connected",
            extra={
                "tenant_id": self.tenant_id,
                "platform": credentials.platform.value,
                "account_id": credentials.account_id,
                "connection_id": connection_info.id,
            },
        )

        return AdAccountInfo(
            id=activated_connection.id,
            platform=credentials.platform.value,
            account_id=credentials.account_id,
            account_name=account_name,
            connection_id=activated_connection.id,
            airbyte_connection_id=activated_connection.airbyte_connection_id,
            status=activated_connection.status,
            is_enabled=activated_connection.is_enabled,
            last_sync_at=activated_connection.last_sync_at,
            last_sync_status=activated_connection.last_sync_status,
            created_at=activated_connection.created_at,
        )

    def get_ad_account(self, connection_id: str) -> Optional[AdAccountInfo]:
        """
        Get an ad account by connection ID.

        SECURITY: Only returns accounts belonging to current tenant.

        Args:
            connection_id: Internal connection ID

        Returns:
            AdAccountInfo if found, None otherwise
        """
        connection = self._airbyte_service.get_connection(connection_id)
        if not connection:
            return None

        # Verify this is an ad platform connection
        if connection.source_type not in AIRBYTE_SOURCE_TYPES.values():
            return None

        config = connection.source_type
        platform = None
        for p, source in AIRBYTE_SOURCE_TYPES.items():
            if source == connection.source_type:
                platform = p.value
                break

        return AdAccountInfo(
            id=connection.id,
            platform=platform or "unknown",
            account_id=connection.airbyte_connection_id,
            account_name=connection.connection_name,
            connection_id=connection.id,
            airbyte_connection_id=connection.airbyte_connection_id,
            status=connection.status,
            is_enabled=connection.is_enabled,
            last_sync_at=connection.last_sync_at,
            last_sync_status=connection.last_sync_status,
            created_at=connection.created_at,
        )

    def list_ad_accounts(
        self,
        platform: Optional[AdPlatform] = None,
        is_enabled: Optional[bool] = None,
    ) -> List[AdAccountInfo]:
        """
        List all ad accounts for the current tenant.

        Args:
            platform: Optional filter by platform
            is_enabled: Optional filter by enabled status

        Returns:
            List of AdAccountInfo
        """
        # Get source type filter if platform specified
        source_type = None
        if platform:
            source_type = AIRBYTE_SOURCE_TYPES.get(platform)

        # If platform specified but not found, return empty list
        if platform and not source_type:
            return []

        # List all source connections
        result = self._airbyte_service.list_connections(
            connection_type="source",
            source_type=source_type,
            is_enabled=is_enabled,
        )

        # Filter to only ad platform connections
        ad_accounts = []
        for conn in result.connections:
            if conn.source_type in AIRBYTE_SOURCE_TYPES.values():
                # Determine platform from source type
                platform_value = None
                for p, source in AIRBYTE_SOURCE_TYPES.items():
                    if source == conn.source_type:
                        platform_value = p.value
                        break

                ad_accounts.append(
                    AdAccountInfo(
                        id=conn.id,
                        platform=platform_value or "unknown",
                        account_id=conn.airbyte_connection_id,
                        account_name=conn.connection_name,
                        connection_id=conn.id,
                        airbyte_connection_id=conn.airbyte_connection_id,
                        status=conn.status,
                        is_enabled=conn.is_enabled,
                        last_sync_at=conn.last_sync_at,
                        last_sync_status=conn.last_sync_status,
                        created_at=conn.created_at,
                    )
                )

        return ad_accounts

    async def trigger_sync(self, connection_id: str) -> SyncStatus:
        """
        Trigger a sync for an ad account.

        Args:
            connection_id: Internal connection ID

        Returns:
            SyncStatus with job details

        Raises:
            AccountNotFoundError: If account not found
            SyncError: If sync trigger fails
        """
        # Verify connection exists and belongs to tenant
        connection = self._airbyte_service.get_connection(connection_id)
        if not connection:
            raise AccountNotFoundError(f"Ad account {connection_id} not found")

        if not connection.can_sync:
            raise SyncError(
                f"Connection {connection_id} cannot sync: "
                f"status={connection.status}, enabled={connection.is_enabled}"
            )

        try:
            client = self._get_airbyte_client()
            job_id = await client.trigger_sync(connection.airbyte_connection_id)

            logger.info(
                "Ad sync triggered",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id,
                    "airbyte_connection_id": connection.airbyte_connection_id,
                    "job_id": job_id,
                },
            )

            return SyncStatus(
                job_id=job_id,
                connection_id=connection_id,
                status="running",
                is_running=True,
                is_complete=False,
                is_successful=False,
                records_synced=0,
                bytes_synced=0,
                duration_seconds=None,
                error_message=None,
            )

        except AirbyteError as e:
            logger.error(
                "Failed to trigger ad sync",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id,
                    "error": str(e),
                },
            )
            raise SyncError(f"Failed to trigger sync: {e}")

    async def get_sync_status(self, job_id: str) -> SyncStatus:
        """
        Get the status of a sync job.

        Args:
            job_id: Airbyte job ID

        Returns:
            SyncStatus with current job status

        Raises:
            SyncError: If status retrieval fails
        """
        try:
            client = self._get_airbyte_client()
            job = await client.get_job(job_id)

            is_running = job.status in (
                AirbyteJobStatus.RUNNING,
                AirbyteJobStatus.PENDING,
            )
            is_complete = job.is_complete
            is_successful = job.is_successful

            records_synced = 0
            bytes_synced = 0
            if job.attempts:
                last_attempt = job.attempts[-1]
                records_synced = last_attempt.records_synced
                bytes_synced = last_attempt.bytes_synced

            error_message = None
            if job.status == AirbyteJobStatus.FAILED and job.attempts:
                last_attempt = job.attempts[-1]
                if hasattr(last_attempt, "failure_reason"):
                    error_message = str(last_attempt.failure_reason)

            return SyncStatus(
                job_id=job_id,
                connection_id=job.config_id or "",
                status=job.status.value,
                is_running=is_running,
                is_complete=is_complete,
                is_successful=is_successful,
                records_synced=records_synced,
                bytes_synced=bytes_synced,
                duration_seconds=None,
                error_message=error_message,
            )

        except AirbyteNotFoundError:
            raise SyncError(f"Sync job {job_id} not found")
        except AirbyteError as e:
            raise SyncError(f"Failed to get sync status: {e}")

    async def sync_and_wait(
        self,
        connection_id: str,
        timeout_seconds: float = 3600,
    ) -> SyncStatus:
        """
        Trigger a sync and wait for completion.

        Args:
            connection_id: Internal connection ID
            timeout_seconds: Maximum wait time

        Returns:
            SyncStatus with final job status

        Raises:
            AccountNotFoundError: If account not found
            SyncError: If sync fails or times out
        """
        # Verify connection exists
        connection = self._airbyte_service.get_connection(connection_id)
        if not connection:
            raise AccountNotFoundError(f"Ad account {connection_id} not found")

        try:
            client = self._get_airbyte_client()
            result = await client.sync_and_wait(
                connection_id=connection.airbyte_connection_id,
                timeout_seconds=timeout_seconds,
            )

            # Update connection status based on result
            if result.status == AirbyteJobStatus.SUCCEEDED:
                self._airbyte_service.record_sync_success(connection_id)
            else:
                self._airbyte_service.mark_connection_failed(
                    connection_id,
                    f"Sync completed with status: {result.status.value}",
                )

            logger.info(
                "Ad sync completed",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id,
                    "job_id": result.job_id,
                    "status": result.status.value,
                    "records_synced": result.records_synced,
                },
            )

            return SyncStatus(
                job_id=result.job_id,
                connection_id=connection_id,
                status=result.status.value,
                is_running=False,
                is_complete=True,
                is_successful=result.status == AirbyteJobStatus.SUCCEEDED,
                records_synced=result.records_synced,
                bytes_synced=result.bytes_synced,
                duration_seconds=result.duration_seconds,
                error_message=None,
            )

        except AirbyteSyncError as e:
            self._airbyte_service.mark_connection_failed(connection_id, str(e))
            raise SyncError(f"Sync failed: {e}")
        except AirbyteError as e:
            raise SyncError(f"Sync error: {e}")

    def get_sync_health(self, connection_id: str) -> dict:
        """
        Get sync health information for an ad account.

        Args:
            connection_id: Internal connection ID

        Returns:
            Dictionary with health information

        Raises:
            AccountNotFoundError: If account not found
        """
        connection = self._airbyte_service.get_connection(connection_id)
        if not connection:
            raise AccountNotFoundError(f"Ad account {connection_id} not found")

        return {
            "connection_id": connection_id,
            "status": connection.status,
            "is_enabled": connection.is_enabled,
            "is_active": connection.is_active,
            "can_sync": connection.can_sync,
            "last_sync_at": connection.last_sync_at.isoformat() if connection.last_sync_at else None,
            "last_sync_status": connection.last_sync_status,
        }

    def disable_ad_account(self, connection_id: str) -> AdAccountInfo:
        """
        Disable an ad account from syncing.

        Args:
            connection_id: Internal connection ID

        Returns:
            Updated AdAccountInfo

        Raises:
            AccountNotFoundError: If account not found
        """
        try:
            connection = self._airbyte_service.disable_connection(connection_id)
        except ConnectionNotFoundServiceError:
            raise AccountNotFoundError(f"Ad account {connection_id} not found")

        logger.info(
            "Ad account disabled",
            extra={
                "tenant_id": self.tenant_id,
                "connection_id": connection_id,
            },
        )

        return self.get_ad_account(connection_id)

    def enable_ad_account(self, connection_id: str) -> AdAccountInfo:
        """
        Enable an ad account for syncing.

        Args:
            connection_id: Internal connection ID

        Returns:
            Updated AdAccountInfo

        Raises:
            AccountNotFoundError: If account not found
        """
        try:
            connection = self._airbyte_service.enable_connection(connection_id)
        except ConnectionNotFoundServiceError:
            raise AccountNotFoundError(f"Ad account {connection_id} not found")

        logger.info(
            "Ad account enabled",
            extra={
                "tenant_id": self.tenant_id,
                "connection_id": connection_id,
            },
        )

        return self.get_ad_account(connection_id)

    def disconnect_ad_account(self, connection_id: str) -> AdAccountInfo:
        """
        Disconnect (soft delete) an ad account.

        Args:
            connection_id: Internal connection ID

        Returns:
            Updated AdAccountInfo with deleted status

        Raises:
            AccountNotFoundError: If account not found
        """
        try:
            connection = self._airbyte_service.delete_connection(connection_id)
        except ConnectionNotFoundServiceError:
            raise AccountNotFoundError(f"Ad account {connection_id} not found")

        logger.info(
            "Ad account disconnected",
            extra={
                "tenant_id": self.tenant_id,
                "connection_id": connection_id,
            },
        )

        # Return the final state (will show as deleted)
        return AdAccountInfo(
            id=connection.id,
            platform="unknown",  # Config not available after delete
            account_id=connection.airbyte_connection_id,
            account_name=connection.connection_name,
            connection_id=connection.id,
            airbyte_connection_id=connection.airbyte_connection_id,
            status=connection.status,
            is_enabled=connection.is_enabled,
            last_sync_at=connection.last_sync_at,
            last_sync_status=connection.last_sync_status,
            created_at=connection.created_at,
        )
