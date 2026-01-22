"""
Secrets management and encryption for AI Growth Analytics.

CRITICAL SECURITY REQUIREMENTS:
- NEVER store secrets in plaintext in DB, logs, or frontend
- All encrypt/decrypt operations MUST use this module
- Any variable name containing token/secret/key MUST be redacted from logs
- Do not print environment variables or secrets, EVER
- Use cloud KMS/Secrets Manager for encryption key management

This module supports:
1. AWS KMS for encryption key management (production)
2. Local encryption key for development (via ENCRYPTION_KEY env var)
3. Automatic secret redaction from logs

Usage:
    from src.platform.secrets import encrypt_secret, decrypt_secret, redact_secrets

    # Encrypt a secret before storing in DB
    encrypted_api_key = await encrypt_secret(api_key)

    # Decrypt a secret after reading from DB
    api_key = await decrypt_secret(encrypted_api_key)

    # Redact secrets from log data
    safe_data = redact_secrets({"api_key": "sk-123", "name": "test"})
"""

import base64
import hashlib
import logging
import os
import re
from functools import lru_cache
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Patterns for detecting secrets in logs
SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key)", re.IGNORECASE),
    re.compile(r"(secret[_-]?key)", re.IGNORECASE),
    re.compile(r"(access[_-]?token)", re.IGNORECASE),
    re.compile(r"(refresh[_-]?token)", re.IGNORECASE),
    re.compile(r"(bearer[_-]?token)", re.IGNORECASE),
    re.compile(r"(password)", re.IGNORECASE),
    re.compile(r"(private[_-]?key)", re.IGNORECASE),
    re.compile(r"(client[_-]?secret)", re.IGNORECASE),
    re.compile(r"(auth[_-]?token)", re.IGNORECASE),
    re.compile(r"(jwt[_-]?token)", re.IGNORECASE),
    re.compile(r"(session[_-]?token)", re.IGNORECASE),
    re.compile(r"(encryption[_-]?key)", re.IGNORECASE),
    re.compile(r"(signing[_-]?key)", re.IGNORECASE),
    re.compile(r"(hmac[_-]?secret)", re.IGNORECASE),
    re.compile(r"(webhook[_-]?secret)", re.IGNORECASE),
    re.compile(r"(database[_-]?url)", re.IGNORECASE),
    re.compile(r"(connection[_-]?string)", re.IGNORECASE),
    re.compile(r"(credentials)", re.IGNORECASE),
]

# Common secret value patterns to redact
SECRET_VALUE_PATTERNS = [
    re.compile(r"(sk-[a-zA-Z0-9]{20,})"),  # OpenAI-style keys
    re.compile(r"(ghp_[a-zA-Z0-9]{36,})"),  # GitHub tokens
    re.compile(r"(ghs_[a-zA-Z0-9]{36,})"),  # GitHub tokens
    re.compile(r"(Bearer\s+[a-zA-Z0-9._-]+)"),  # Bearer tokens
    re.compile(r"(shpat_[a-fA-F0-9]{32,})"),  # Shopify access tokens
    re.compile(r"(shpss_[a-zA-Z0-9]{24,})"),  # Shopify shared secrets
]

REDACTED_VALUE = "[REDACTED]"


class EncryptionError(Exception):
    """Raised when encryption/decryption operations fail."""
    pass


class SecretsManager:
    """
    Manages secret encryption and decryption.

    Supports:
    - AWS KMS (production)
    - Local encryption key (development)
    """

    def __init__(self):
        self._kms_client = None
        self._kms_key_id = None
        self._local_key = None
        self._initialized = False

    def _initialize(self):
        """Lazy initialization of encryption backend."""
        if self._initialized:
            return

        # Check for AWS KMS configuration first (production)
        kms_key_id = os.getenv("AWS_KMS_KEY_ID")
        if kms_key_id:
            self._initialize_kms(kms_key_id)
        else:
            # Fall back to local encryption key (development)
            self._initialize_local()

        self._initialized = True

    def _initialize_kms(self, key_id: str):
        """Initialize AWS KMS client."""
        try:
            import boto3
            from botocore.exceptions import ClientError

            self._kms_client = boto3.client("kms")
            self._kms_key_id = key_id

            # Verify the key exists and we have access
            try:
                self._kms_client.describe_key(KeyId=key_id)
                logger.info("AWS KMS encryption initialized")
            except ClientError as e:
                logger.error(
                    "Failed to access AWS KMS key",
                    extra={"error_code": e.response["Error"]["Code"]}
                )
                raise EncryptionError(f"Cannot access KMS key: {e}")

        except ImportError:
            logger.warning("boto3 not installed - falling back to local encryption")
            self._initialize_local()

    def _initialize_local(self):
        """Initialize local encryption using Fernet."""
        encryption_key = os.getenv("ENCRYPTION_KEY")

        if not encryption_key:
            logger.warning(
                "No encryption configuration found. "
                "Set AWS_KMS_KEY_ID for production or ENCRYPTION_KEY for development."
            )
            return

        try:
            # Derive a valid Fernet key from the provided key
            # Using PBKDF2 for key derivation
            derived_key = hashlib.pbkdf2_hmac(
                "sha256",
                encryption_key.encode(),
                b"shopify-analytics-salt",  # Static salt (in production, use unique salt)
                100000,  # Iterations
                dklen=32,  # Fernet requires 32 bytes
            )
            self._local_key = base64.urlsafe_b64encode(derived_key)
            logger.info("Local encryption initialized (development mode)")

        except Exception as e:
            logger.error("Failed to initialize local encryption", extra={"error": str(e)})
            raise EncryptionError(f"Cannot initialize local encryption: {e}")

    def _get_fernet(self):
        """Get Fernet cipher for local encryption."""
        if not self._local_key:
            raise EncryptionError("Local encryption not initialized")

        from cryptography.fernet import Fernet
        return Fernet(self._local_key)

    async def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string.

        Args:
            plaintext: The string to encrypt

        Returns:
            Base64-encoded encrypted string

        Raises:
            EncryptionError: If encryption fails
        """
        self._initialize()

        if not plaintext:
            raise ValueError("Cannot encrypt empty string")

        # Use KMS if available
        if self._kms_client:
            return await self._encrypt_kms(plaintext)

        # Fall back to local encryption
        if self._local_key:
            return self._encrypt_local(plaintext)

        raise EncryptionError("No encryption backend configured")

    async def _encrypt_kms(self, plaintext: str) -> str:
        """Encrypt using AWS KMS."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        def _kms_encrypt():
            response = self._kms_client.encrypt(
                KeyId=self._kms_key_id,
                Plaintext=plaintext.encode("utf-8"),
            )
            return base64.b64encode(response["CiphertextBlob"]).decode("utf-8")

        # Run KMS call in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, _kms_encrypt)

    def _encrypt_local(self, plaintext: str) -> str:
        """Encrypt using local Fernet cipher."""
        fernet = self._get_fernet()
        encrypted = fernet.encrypt(plaintext.encode("utf-8"))
        return encrypted.decode("utf-8")

    async def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt an encrypted string.

        Args:
            ciphertext: Base64-encoded encrypted string

        Returns:
            Decrypted plaintext string

        Raises:
            EncryptionError: If decryption fails
        """
        self._initialize()

        if not ciphertext:
            raise ValueError("Cannot decrypt empty string")

        # Use KMS if available
        if self._kms_client:
            return await self._decrypt_kms(ciphertext)

        # Fall back to local encryption
        if self._local_key:
            return self._decrypt_local(ciphertext)

        raise EncryptionError("No encryption backend configured")

    async def _decrypt_kms(self, ciphertext: str) -> str:
        """Decrypt using AWS KMS."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        def _kms_decrypt():
            ciphertext_blob = base64.b64decode(ciphertext)
            response = self._kms_client.decrypt(
                CiphertextBlob=ciphertext_blob,
            )
            return response["Plaintext"].decode("utf-8")

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, _kms_decrypt)

    def _decrypt_local(self, ciphertext: str) -> str:
        """Decrypt using local Fernet cipher."""
        from cryptography.fernet import InvalidToken

        try:
            fernet = self._get_fernet()
            decrypted = fernet.decrypt(ciphertext.encode("utf-8"))
            return decrypted.decode("utf-8")
        except InvalidToken:
            raise EncryptionError("Invalid ciphertext or wrong encryption key")


# Singleton instance
_secrets_manager = SecretsManager()


async def encrypt_secret(plaintext: str) -> str:
    """
    Encrypt a secret for storage.

    Args:
        plaintext: The secret to encrypt

    Returns:
        Encrypted string safe for database storage
    """
    return await _secrets_manager.encrypt(plaintext)


async def decrypt_secret(ciphertext: str) -> str:
    """
    Decrypt a stored secret.

    Args:
        ciphertext: The encrypted secret from database

    Returns:
        Decrypted secret
    """
    return await _secrets_manager.decrypt(ciphertext)


def is_secret_key(key: str) -> bool:
    """
    Check if a dictionary key likely contains a secret.

    Args:
        key: The key name to check

    Returns:
        True if the key name suggests it contains a secret
    """
    return any(pattern.search(key) for pattern in SECRET_PATTERNS)


def redact_value(value: Any) -> Any:
    """
    Redact secret patterns from a value.

    Args:
        value: The value to redact

    Returns:
        Redacted value
    """
    if not isinstance(value, str):
        return value

    result = value
    for pattern in SECRET_VALUE_PATTERNS:
        result = pattern.sub(REDACTED_VALUE, result)

    return result


def redact_secrets(data: Any, _depth: int = 0) -> Any:
    """
    Recursively redact secrets from a data structure.

    Use this before logging any data that might contain secrets.

    Args:
        data: Dictionary, list, or other data structure

    Returns:
        Copy of data with secrets redacted

    Usage:
        safe_data = redact_secrets({"api_key": "sk-123", "name": "test"})
        logger.info("Request data", extra=safe_data)
    """
    # Prevent infinite recursion
    if _depth > 10:
        return data

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if is_secret_key(key):
                result[key] = REDACTED_VALUE
            else:
                result[key] = redact_secrets(value, _depth + 1)
        return result

    if isinstance(data, list):
        return [redact_secrets(item, _depth + 1) for item in data]

    if isinstance(data, str):
        return redact_value(data)

    return data


def mask_secret(secret: str, visible_chars: int = 4) -> str:
    """
    Mask a secret showing only the last few characters.

    Useful for displaying secrets in UIs.

    Args:
        secret: The secret to mask
        visible_chars: Number of characters to show at the end

    Returns:
        Masked string like "****abcd"
    """
    if not secret or len(secret) <= visible_chars:
        return "*" * max(len(secret) if secret else 0, 4)

    return "*" * (len(secret) - visible_chars) + secret[-visible_chars:]


class SecretRedactingFilter(logging.Filter):
    """
    Logging filter that redacts secrets from log records.

    Add this filter to loggers to automatically redact secrets.

    Usage:
        logger.addFilter(SecretRedactingFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact the message
        if isinstance(record.msg, str):
            record.msg = redact_value(record.msg)

        # Redact args
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_secrets(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact_value(arg) if isinstance(arg, str) else arg
                    for arg in record.args
                )

        # Redact extra fields
        if hasattr(record, "__dict__"):
            for key in list(record.__dict__.keys()):
                if is_secret_key(key):
                    setattr(record, key, REDACTED_VALUE)

        return True


def get_env_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Get a secret from environment variables.

    IMPORTANT: Never log the return value of this function.

    Args:
        key: Environment variable name
        default: Default value if not set

    Returns:
        The secret value (never log this!)
    """
    value = os.getenv(key, default)

    # Log that we accessed a secret, but not the value
    logger.debug(
        "Environment secret accessed",
        extra={"key": key, "has_value": value is not None}
    )

    return value


def validate_encryption_configured() -> bool:
    """
    Check if encryption is properly configured.

    Returns:
        True if encryption is configured, False otherwise
    """
    return bool(os.getenv("AWS_KMS_KEY_ID") or os.getenv("ENCRYPTION_KEY"))
