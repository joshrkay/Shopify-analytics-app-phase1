"""
Secrets management tests for AI Growth Analytics.

CRITICAL: These tests verify that:
1. Secrets are encrypted at rest
2. Secrets are never logged in plaintext
3. Secret redaction works correctly
"""

import pytest
import logging
from io import StringIO
from unittest.mock import patch, MagicMock

from src.platform.secrets import (
    SecretsManager,
    EncryptionError,
    encrypt_secret,
    decrypt_secret,
    redact_secrets,
    redact_value,
    mask_secret,
    is_secret_key,
    SecretRedactingFilter,
    get_env_secret,
    validate_encryption_configured,
    REDACTED_VALUE,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def encryption_key(monkeypatch):
    """Set up encryption key for testing."""
    monkeypatch.setenv("ENCRYPTION_KEY", "test-encryption-key-32-chars-long!")
    return "test-encryption-key-32-chars-long!"


@pytest.fixture
def secrets_manager_local(encryption_key):
    """Create a secrets manager with local encryption."""
    manager = SecretsManager()
    manager._initialize()
    return manager


@pytest.fixture
def log_capture():
    """Capture log output for testing."""
    log_stream = StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(levelname)s %(name)s %(message)s')
    handler.setFormatter(formatter)

    # Add filter
    handler.addFilter(SecretRedactingFilter())

    logger = logging.getLogger("test_secrets")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    yield log_stream

    logger.removeHandler(handler)


# ============================================================================
# TEST SUITE: SECRET KEY DETECTION
# ============================================================================

class TestSecretKeyDetection:
    """Test detection of secret-containing keys."""

    @pytest.mark.parametrize("key", [
        "api_key",
        "API_KEY",
        "apiKey",
        "secret_key",
        "SECRET_KEY",
        "access_token",
        "accessToken",
        "refresh_token",
        "password",
        "PASSWORD",
        "private_key",
        "client_secret",
        "auth_token",
        "jwt_token",
        "encryption_key",
        "signing_key",
        "hmac_secret",
        "webhook_secret",
        "database_url",
        "connection_string",
        "credentials",
    ])
    def test_secret_keys_detected(self, key):
        """CRITICAL: All secret key patterns must be detected."""
        assert is_secret_key(key), f"Failed to detect secret key: {key}"

    @pytest.mark.parametrize("key", [
        "username",
        "email",
        "name",
        "count",
        "total",
        "status",
        "created_at",
        "updated_at",
        "id",
        "tenant_id",
        "user_id",
    ])
    def test_non_secret_keys_not_detected(self, key):
        """Non-secret keys should not be flagged."""
        assert not is_secret_key(key), f"Incorrectly flagged as secret: {key}"


# ============================================================================
# TEST SUITE: VALUE REDACTION
# ============================================================================

class TestValueRedaction:
    """Test redaction of secret values."""

    def test_redact_openai_style_key(self):
        """Redact OpenAI-style API keys."""
        value = "Here is my key: sk-abcdefghijklmnopqrstuvwxyz"
        result = redact_value(value)

        assert "sk-abcdefghijklmnopqrstuvwxyz" not in result
        assert REDACTED_VALUE in result

    def test_redact_github_token(self):
        """Redact GitHub tokens."""
        value = "Token: ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        result = redact_value(value)

        assert "ghp_" not in result
        assert REDACTED_VALUE in result

    def test_redact_bearer_token(self):
        """Redact Bearer tokens."""
        value = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = redact_value(value)

        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert REDACTED_VALUE in result

    def test_redact_shopify_shared_secret(self):
        """Redact Shopify shared secrets."""
        # Test with Shopify shared secret pattern (shpss_)
        value = "Secret: shpss_testfakesecret12345678901234"
        result = redact_value(value)

        assert "shpss_" not in result
        assert REDACTED_VALUE in result


# ============================================================================
# TEST SUITE: DICTIONARY REDACTION
# ============================================================================

class TestDictionaryRedaction:
    """Test redaction of dictionaries containing secrets."""

    def test_redact_dict_with_secret_keys(self):
        """CRITICAL: Dictionaries with secret keys are redacted."""
        data = {
            "api_key": "sk-secret-key-12345",
            "password": "my-password",
            "username": "john",
            "email": "john@example.com",
        }

        result = redact_secrets(data)

        # Secret keys should be redacted
        assert result["api_key"] == REDACTED_VALUE
        assert result["password"] == REDACTED_VALUE

        # Non-secret keys should be preserved
        assert result["username"] == "john"
        assert result["email"] == "john@example.com"

    def test_redact_nested_dict(self):
        """Nested dictionaries are recursively redacted."""
        data = {
            "config": {
                "api_key": "secret-key",
                "settings": {
                    "password": "nested-password",
                    "enabled": True,
                }
            },
            "name": "test",
        }

        result = redact_secrets(data)

        assert result["config"]["api_key"] == REDACTED_VALUE
        assert result["config"]["settings"]["password"] == REDACTED_VALUE
        assert result["config"]["settings"]["enabled"] is True
        assert result["name"] == "test"

    def test_redact_list_with_secrets(self):
        """Lists containing secrets are redacted."""
        data = [
            {"api_key": "key-1"},
            {"api_key": "key-2"},
            {"name": "test"},
        ]

        result = redact_secrets(data)

        assert result[0]["api_key"] == REDACTED_VALUE
        assert result[1]["api_key"] == REDACTED_VALUE
        assert result[2]["name"] == "test"

    def test_redact_string_values_in_dict(self):
        """String values containing secrets are redacted."""
        data = {
            "message": "Token is sk-abcdefghijklmnopqrstuvwxyz",
            "safe": "No secrets here",
        }

        result = redact_secrets(data)

        assert "sk-abcdefghijklmnopqrstuvwxyz" not in result["message"]
        assert result["safe"] == "No secrets here"


# ============================================================================
# TEST SUITE: SECRET MASKING
# ============================================================================

class TestSecretMasking:
    """Test secret masking for display."""

    def test_mask_secret_default(self):
        """Mask secret showing last 4 characters."""
        secret = "sk-abcdefghijklmnopqrstuvwxyz"
        masked = mask_secret(secret)

        assert masked.endswith("wxyz")
        assert masked.count("*") == len(secret) - 4
        assert "sk-" not in masked

    def test_mask_secret_custom_visible(self):
        """Mask secret with custom visible characters."""
        secret = "password123"
        masked = mask_secret(secret, visible_chars=6)

        assert masked.endswith("ord123")
        assert masked.count("*") == len(secret) - 6

    def test_mask_short_secret(self):
        """Short secrets are fully masked."""
        secret = "abc"
        masked = mask_secret(secret)

        assert masked == "****"

    def test_mask_empty_secret(self):
        """Empty secrets return placeholder."""
        masked = mask_secret("")
        assert masked == "****"


# ============================================================================
# TEST SUITE: ENCRYPTION
# ============================================================================

class TestEncryption:
    """Test encryption and decryption functionality."""

    @pytest.mark.asyncio
    async def test_encrypt_decrypt_roundtrip(self, secrets_manager_local):
        """CRITICAL: Encrypted secrets can be decrypted."""
        plaintext = "my-secret-api-key-12345"

        encrypted = await secrets_manager_local.encrypt(plaintext)
        decrypted = await secrets_manager_local.decrypt(encrypted)

        assert decrypted == plaintext
        assert encrypted != plaintext

    @pytest.mark.asyncio
    async def test_encrypted_value_is_different(self, secrets_manager_local):
        """Encrypted value is different from plaintext."""
        plaintext = "secret-value"

        encrypted = await secrets_manager_local.encrypt(plaintext)

        assert encrypted != plaintext
        assert "secret-value" not in encrypted

    @pytest.mark.asyncio
    async def test_empty_string_raises_error(self, secrets_manager_local):
        """Encrypting empty string raises error."""
        with pytest.raises(ValueError, match="Cannot encrypt empty"):
            await secrets_manager_local.encrypt("")

    @pytest.mark.asyncio
    async def test_decrypt_invalid_ciphertext_raises_error(self, secrets_manager_local):
        """Decrypting invalid ciphertext raises error."""
        with pytest.raises(EncryptionError):
            await secrets_manager_local.decrypt("invalid-ciphertext")

    @pytest.mark.asyncio
    async def test_encryption_not_configured_raises_error(self, monkeypatch):
        """CRITICAL: Encryption fails gracefully when not configured."""
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)

        manager = SecretsManager()

        with pytest.raises(EncryptionError, match="No encryption backend"):
            await manager.encrypt("secret")


# ============================================================================
# TEST SUITE: LOGGING FILTER
# ============================================================================

class TestLoggingFilter:
    """Test the secret redacting logging filter."""

    def test_filter_redacts_secret_in_message(self, log_capture):
        """CRITICAL: Logging filter redacts secrets in messages."""
        logger = logging.getLogger("test_secrets")

        logger.info("API key is sk-abcdefghijklmnopqrstuvwxyz")

        log_output = log_capture.getvalue()

        # The secret should be redacted
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in log_output
        assert REDACTED_VALUE in log_output

    def test_filter_allows_safe_messages(self, log_capture):
        """Safe messages pass through unchanged."""
        logger = logging.getLogger("test_secrets")

        logger.info("Processing request for user-123")

        log_output = log_capture.getvalue()

        assert "Processing request for user-123" in log_output


# ============================================================================
# TEST SUITE: ENVIRONMENT SECRETS
# ============================================================================

class TestEnvironmentSecrets:
    """Test environment secret handling."""

    def test_get_env_secret_returns_value(self, monkeypatch):
        """get_env_secret returns the secret value."""
        monkeypatch.setenv("TEST_SECRET", "secret-value")

        result = get_env_secret("TEST_SECRET")

        assert result == "secret-value"

    def test_get_env_secret_returns_default(self, monkeypatch):
        """get_env_secret returns default when not set."""
        monkeypatch.delenv("MISSING_SECRET", raising=False)

        result = get_env_secret("MISSING_SECRET", default="default-value")

        assert result == "default-value"

    def test_validate_encryption_configured_true(self, monkeypatch):
        """validate_encryption_configured returns True when configured."""
        monkeypatch.setenv("ENCRYPTION_KEY", "test-key")

        assert validate_encryption_configured() is True

    def test_validate_encryption_configured_false(self, monkeypatch):
        """validate_encryption_configured returns False when not configured."""
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)

        assert validate_encryption_configured() is False


# ============================================================================
# TEST SUITE: COMPREHENSIVE REDACTION
# ============================================================================

class TestComprehensiveRedaction:
    """Test comprehensive secret redaction scenarios."""

    def test_complex_nested_structure(self):
        """Complex nested structures are fully redacted."""
        data = {
            "user": {
                "profile": {
                    "name": "John",
                    "api_key": "user-api-key",
                },
                "auth": {
                    "password": "user-password",
                    "tokens": [
                        {"access_token": "token-1"},
                        {"refresh_token": "token-2"},
                    ]
                }
            },
            "settings": {
                "webhook_secret": "webhook-secret-value",
                "enabled": True,
            }
        }

        result = redact_secrets(data)

        # All secrets should be redacted
        assert result["user"]["profile"]["api_key"] == REDACTED_VALUE
        assert result["user"]["auth"]["password"] == REDACTED_VALUE
        assert result["user"]["auth"]["tokens"][0]["access_token"] == REDACTED_VALUE
        assert result["user"]["auth"]["tokens"][1]["refresh_token"] == REDACTED_VALUE
        assert result["settings"]["webhook_secret"] == REDACTED_VALUE

        # Non-secrets preserved
        assert result["user"]["profile"]["name"] == "John"
        assert result["settings"]["enabled"] is True

    def test_redaction_handles_none_values(self):
        """Redaction handles None values gracefully."""
        data = {
            "api_key": None,
            "name": None,
        }

        result = redact_secrets(data)

        # api_key should be redacted even if None
        assert result["api_key"] == REDACTED_VALUE
        # name is not a secret key, so None is preserved
        assert result["name"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
