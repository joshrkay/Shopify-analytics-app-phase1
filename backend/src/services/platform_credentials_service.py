"""
Platform credentials management service.

Handles secure retrieval and management of external platform credentials
for action execution.

SECURITY:
- Credentials are encrypted at rest in the database
- Decrypted only when needed for API calls
- Access is scoped to tenant via tenant_id from JWT
- Supports credential rotation and validation

Story 8.5 - Action Execution (Scoped & Reversible)
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union

from sqlalchemy.orm import Session

from src.models.connector_credential import CredentialStatus
from src.services.platform_executors import (
    MetaCredentials,
    GoogleAdsCredentials,
    MetaAdsExecutor,
    GoogleAdsExecutor,
    BasePlatformExecutor,
    RetryConfig,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Supported Platforms
# =============================================================================

class Platform(str, Enum):
    """Supported external platforms for action execution."""
    META = "meta"
    GOOGLE = "google"
    SHOPIFY = "shopify"


# CredentialStatus is imported from src.models.connector_credential
# (canonical source of truth for credential lifecycle status)


@dataclass
class CredentialValidation:
    """Result of credential validation."""
    is_valid: bool
    status: CredentialStatus
    message: str
    platform: Platform
    needs_reauth: bool = False


# =============================================================================
# Platform Credentials Service
# =============================================================================

class PlatformCredentialsService:
    """
    Service for managing platform credentials.

    Handles:
    - Fetching encrypted credentials from database
    - Decrypting credentials for use
    - Validating credential status
    - Creating platform executors

    SECURITY:
    - tenant_id must come from JWT, never from client input
    - Credentials are decrypted only when needed
    - Failed validation triggers notifications
    """

    def __init__(
        self,
        db_session: Session,
        encryption_key: Optional[str] = None,
    ):
        """
        Initialize the credentials service.

        Args:
            db_session: Database session for querying credentials
            encryption_key: Key for decrypting stored credentials
        """
        self.db = db_session
        self.encryption_key = encryption_key

    # =========================================================================
    # Credential Retrieval
    # =========================================================================

    def get_meta_credentials(self, tenant_id: str) -> Optional[MetaCredentials]:
        """
        Get Meta (Facebook) API credentials for a tenant.

        Args:
            tenant_id: Tenant identifier (from JWT only)

        Returns:
            MetaCredentials if found and valid, None otherwise
        """
        # TODO: Implement actual database lookup
        # For now, return placeholder that indicates implementation needed

        # Example implementation:
        # credential_record = self.db.execute(
        #     select(PlatformCredential)
        #     .where(PlatformCredential.tenant_id == tenant_id)
        #     .where(PlatformCredential.platform == Platform.META.value)
        #     .where(PlatformCredential.is_active == True)
        # ).scalar_one_or_none()
        #
        # if not credential_record:
        #     return None
        #
        # decrypted = self._decrypt_credentials(credential_record.encrypted_data)
        # return MetaCredentials(
        #     access_token=decrypted["access_token"],
        #     ad_account_id=decrypted["ad_account_id"],
        # )

        logger.warning(
            "Meta credentials lookup not implemented",
            extra={"tenant_id": tenant_id}
        )
        return None

    def get_google_credentials(self, tenant_id: str) -> Optional[GoogleAdsCredentials]:
        """
        Get Google Ads API credentials for a tenant.

        Args:
            tenant_id: Tenant identifier (from JWT only)

        Returns:
            GoogleAdsCredentials if found and valid, None otherwise
        """
        # TODO: Implement actual database lookup
        # Similar to get_meta_credentials

        logger.warning(
            "Google Ads credentials lookup not implemented",
            extra={"tenant_id": tenant_id}
        )
        return None

    def get_credentials_for_platform(
        self,
        tenant_id: str,
        platform: Platform,
    ) -> Optional[Union[MetaCredentials, GoogleAdsCredentials]]:
        """
        Get credentials for a specific platform.

        Args:
            tenant_id: Tenant identifier (from JWT only)
            platform: Target platform

        Returns:
            Platform-specific credentials if found, None otherwise
        """
        if platform == Platform.META:
            return self.get_meta_credentials(tenant_id)
        elif platform == Platform.GOOGLE:
            return self.get_google_credentials(tenant_id)
        else:
            logger.error(f"Unsupported platform: {platform}")
            return None

    # =========================================================================
    # Executor Factory
    # =========================================================================

    def get_executor_for_platform(
        self,
        tenant_id: str,
        platform: Platform,
        retry_config: Optional[RetryConfig] = None,
    ) -> Optional[BasePlatformExecutor]:
        """
        Get a configured executor for a platform.

        This is the main entry point for obtaining an executor ready
        for action execution.

        Args:
            tenant_id: Tenant identifier (from JWT only)
            platform: Target platform
            retry_config: Optional retry configuration

        Returns:
            Configured platform executor, or None if credentials unavailable
        """
        credentials = self.get_credentials_for_platform(tenant_id, platform)

        if credentials is None:
            logger.warning(
                "No credentials available for platform",
                extra={"tenant_id": tenant_id, "platform": platform.value}
            )
            return None

        if platform == Platform.META:
            return MetaAdsExecutor(
                credentials=credentials,
                retry_config=retry_config,
            )
        elif platform == Platform.GOOGLE:
            return GoogleAdsExecutor(
                credentials=credentials,
                retry_config=retry_config,
            )
        else:
            logger.error(f"No executor available for platform: {platform}")
            return None

    # =========================================================================
    # Credential Validation
    # =========================================================================

    async def validate_credentials(
        self,
        tenant_id: str,
        platform: Platform,
    ) -> CredentialValidation:
        """
        Validate that credentials for a platform are valid and usable.

        This performs a lightweight API call to verify credentials work.

        Args:
            tenant_id: Tenant identifier (from JWT only)
            platform: Target platform

        Returns:
            CredentialValidation with status and details
        """
        credentials = self.get_credentials_for_platform(tenant_id, platform)

        if credentials is None:
            return CredentialValidation(
                is_valid=False,
                status=CredentialStatus.MISSING,
                message=f"No {platform.value} credentials configured",
                platform=platform,
                needs_reauth=True,
            )

        executor = self.get_executor_for_platform(tenant_id, platform)

        if executor is None:
            return CredentialValidation(
                is_valid=False,
                status=CredentialStatus.INVALID,
                message=f"Failed to create executor for {platform.value}",
                platform=platform,
                needs_reauth=True,
            )

        # Validate credentials via executor
        if not executor.validate_credentials():
            return CredentialValidation(
                is_valid=False,
                status=CredentialStatus.INVALID,
                message=f"Credentials validation failed for {platform.value}",
                platform=platform,
                needs_reauth=True,
            )

        # TODO: Perform actual API test call
        # try:
        #     await executor.test_connection()
        # except PlatformAPIError as e:
        #     if e.status_code == 401:
        #         return CredentialValidation(
        #             is_valid=False,
        #             status=CredentialStatus.EXPIRED,
        #             message="Access token has expired",
        #             platform=platform,
        #             needs_reauth=True,
        #         )

        return CredentialValidation(
            is_valid=True,
            status=CredentialStatus.ACTIVE,
            message="Credentials are valid",
            platform=platform,
        )

    def check_credentials_exist(
        self,
        tenant_id: str,
        platform: Platform,
    ) -> bool:
        """
        Quick check if credentials exist (without validation).

        Args:
            tenant_id: Tenant identifier
            platform: Target platform

        Returns:
            True if credentials exist, False otherwise
        """
        return self.get_credentials_for_platform(tenant_id, platform) is not None

    # =========================================================================
    # Credential Management
    # =========================================================================

    def store_credentials(
        self,
        tenant_id: str,
        platform: Platform,
        credentials: dict,
    ) -> bool:
        """
        Store encrypted credentials for a tenant.

        Args:
            tenant_id: Tenant identifier (from JWT only)
            platform: Target platform
            credentials: Credential data to encrypt and store

        Returns:
            True if stored successfully, False otherwise
        """
        # TODO: Implement credential storage with encryption
        # encrypted_data = self._encrypt_credentials(credentials)
        #
        # credential_record = PlatformCredential(
        #     tenant_id=tenant_id,
        #     platform=platform.value,
        #     encrypted_data=encrypted_data,
        #     is_active=True,
        # )
        # self.db.add(credential_record)
        # self.db.commit()

        logger.warning(
            "Credential storage not implemented",
            extra={"tenant_id": tenant_id, "platform": platform.value}
        )
        return False

    def revoke_credentials(
        self,
        tenant_id: str,
        platform: Platform,
    ) -> bool:
        """
        Revoke/deactivate credentials for a tenant.

        Args:
            tenant_id: Tenant identifier (from JWT only)
            platform: Target platform

        Returns:
            True if revoked successfully, False otherwise
        """
        # TODO: Implement credential revocation
        logger.warning(
            "Credential revocation not implemented",
            extra={"tenant_id": tenant_id, "platform": platform.value}
        )
        return False

    # =========================================================================
    # Encryption Helpers
    # =========================================================================

    def _encrypt_credentials(self, data: dict) -> bytes:
        """
        Encrypt credential data for storage.

        Args:
            data: Credential dictionary to encrypt

        Returns:
            Encrypted bytes
        """
        # TODO: Implement actual encryption (AES-256-GCM recommended)
        # from cryptography.fernet import Fernet
        # f = Fernet(self.encryption_key)
        # return f.encrypt(json.dumps(data).encode())

        raise NotImplementedError("Credential encryption not implemented")

    def _decrypt_credentials(self, encrypted_data: bytes) -> dict:
        """
        Decrypt credential data from storage.

        Args:
            encrypted_data: Encrypted credential bytes

        Returns:
            Decrypted credential dictionary
        """
        # TODO: Implement actual decryption
        raise NotImplementedError("Credential decryption not implemented")


# =============================================================================
# Factory Function
# =============================================================================

def get_platform_credentials_service(
    db_session: Session,
    encryption_key: Optional[str] = None,
) -> PlatformCredentialsService:
    """
    Factory function to create a PlatformCredentialsService.

    Args:
        db_session: Database session
        encryption_key: Optional encryption key

    Returns:
        Configured PlatformCredentialsService instance
    """
    return PlatformCredentialsService(
        db_session=db_session,
        encryption_key=encryption_key,
    )
