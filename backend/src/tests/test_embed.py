"""
Tests for Embedded Analytics functionality.

Tests cover:
- JWT token generation
- Token refresh
- CSP headers
- Security validation
"""

import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import jwt
from fastapi.testclient import TestClient

# Set test environment variables before importing app
os.environ.setdefault("SUPERSET_JWT_SECRET", "test-secret-key-for-testing-only")
os.environ.setdefault("FRONTEGG_CLIENT_ID", "test-client-id")
os.environ.setdefault("SUPERSET_EMBED_URL", "https://analytics.test.com")

from src.services.embed_token_service import (
    EmbedTokenService,
    EmbedTokenConfig,
    EmbedTokenError,
    TokenExpiredError,
    TokenValidationError,
)
from src.platform.tenant_context import TenantContext
from src.platform.csp_middleware import CSPConfig, validate_frame_origin


class TestEmbedTokenService:
    """Tests for EmbedTokenService."""

    @pytest.fixture
    def config(self):
        """Create test config."""
        return EmbedTokenConfig(
            jwt_secret="test-secret-key-for-testing",
            algorithm="HS256",
            default_lifetime_minutes=60,
            refresh_threshold_minutes=5,
            issuer="test-issuer",
        )

    @pytest.fixture
    def service(self, config):
        """Create test service."""
        return EmbedTokenService(config=config)

    @pytest.fixture
    def tenant_context(self):
        """Create test tenant context."""
        return TenantContext(
            tenant_id="tenant_123",
            user_id="user_456",
            roles=["merchant_admin"],
            org_id="org_789",
            allowed_tenants=["tenant_123"],
        )

    def test_generate_embed_token_success(self, service, tenant_context):
        """Test successful token generation."""
        result = service.generate_embed_token(
            tenant_context=tenant_context,
            dashboard_id="dashboard_1",
        )

        assert result.jwt_token is not None
        assert len(result.jwt_token) > 0
        assert result.expires_at > datetime.utcnow()
        assert result.refresh_before < result.expires_at
        assert "dashboard_1" in result.dashboard_url

    def test_generate_embed_token_custom_lifetime(self, service, tenant_context):
        """Test token generation with custom lifetime."""
        result = service.generate_embed_token(
            tenant_context=tenant_context,
            dashboard_id="dashboard_1",
            lifetime_minutes=30,
        )

        # Check expiry is approximately 30 minutes
        expected_expiry = datetime.utcnow() + timedelta(minutes=30)
        diff = abs((result.expires_at - expected_expiry).total_seconds())
        assert diff < 5  # Within 5 seconds

    def test_generate_embed_token_includes_tenant_claims(self, service, tenant_context):
        """Test that generated token includes tenant claims."""
        result = service.generate_embed_token(
            tenant_context=tenant_context,
            dashboard_id="dashboard_1",
        )

        # Decode token to verify claims
        payload = jwt.decode(
            result.jwt_token,
            service.config.jwt_secret,
            algorithms=[service.config.algorithm],
        )

        assert payload["sub"] == "user_456"
        assert payload["tenant_id"] == "tenant_123"
        assert payload["roles"] == ["merchant_admin"]
        assert payload["allowed_tenants"] == ["tenant_123"]
        assert payload["dashboard_id"] == "dashboard_1"
        assert "rls_filter" in payload

    def test_validate_token_success(self, service, tenant_context):
        """Test successful token validation."""
        result = service.generate_embed_token(
            tenant_context=tenant_context,
            dashboard_id="dashboard_1",
        )

        payload = service.validate_token(result.jwt_token)

        assert payload.sub == "user_456"
        assert payload.tenant_id == "tenant_123"

    def test_validate_token_expired(self, service, config):
        """Test validation of expired token."""
        # Create expired token manually
        now = datetime.utcnow()
        expired_time = now - timedelta(minutes=10)

        payload = {
            "sub": "user_456",
            "tenant_id": "tenant_123",
            "roles": ["merchant_admin"],
            "allowed_tenants": ["tenant_123"],
            "dashboard_id": "dashboard_1",
            "iss": config.issuer,
            "iat": int(expired_time.timestamp()),
            "exp": int((expired_time + timedelta(minutes=5)).timestamp()),
        }

        token = jwt.encode(payload, config.jwt_secret, algorithm=config.algorithm)

        with pytest.raises(TokenExpiredError):
            service.validate_token(token)

    def test_validate_token_invalid_signature(self, service):
        """Test validation of token with invalid signature."""
        # Create token with wrong secret
        payload = {
            "sub": "user_456",
            "tenant_id": "tenant_123",
            "iss": service.config.issuer,
            "iat": int(datetime.utcnow().timestamp()),
            "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp()),
        }

        token = jwt.encode(payload, "wrong-secret", algorithm="HS256")

        with pytest.raises(TokenValidationError):
            service.validate_token(token)

    def test_should_refresh_returns_true_near_expiry(self, service, tenant_context):
        """Test should_refresh returns true when token is near expiry."""
        # Create token that expires in 3 minutes (less than 5 min threshold)
        result = service.generate_embed_token(
            tenant_context=tenant_context,
            dashboard_id="dashboard_1",
            lifetime_minutes=3,
        )

        assert service.should_refresh(result.jwt_token) is True

    def test_should_refresh_returns_false_when_fresh(self, service, tenant_context):
        """Test should_refresh returns false when token is fresh."""
        result = service.generate_embed_token(
            tenant_context=tenant_context,
            dashboard_id="dashboard_1",
            lifetime_minutes=60,
        )

        assert service.should_refresh(result.jwt_token) is False

    def test_refresh_token_success(self, service, tenant_context):
        """Test successful token refresh."""
        # Generate initial token
        initial_result = service.generate_embed_token(
            tenant_context=tenant_context,
            dashboard_id="dashboard_1",
        )

        # Refresh token
        refreshed_result = service.refresh_token(
            old_token=initial_result.jwt_token,
            tenant_context=tenant_context,
        )

        assert refreshed_result.jwt_token != initial_result.jwt_token
        assert refreshed_result.expires_at > initial_result.expires_at

    def test_refresh_token_mismatched_tenant(self, service, tenant_context):
        """Test refresh fails when tenant context doesn't match token."""
        # Generate token for one tenant
        result = service.generate_embed_token(
            tenant_context=tenant_context,
            dashboard_id="dashboard_1",
        )

        # Try to refresh with different tenant context
        different_tenant_context = TenantContext(
            tenant_id="different_tenant",
            user_id="user_456",
            roles=["merchant_admin"],
            org_id="org_789",
            allowed_tenants=["different_tenant"],
        )

        with pytest.raises(TokenValidationError):
            service.refresh_token(
                old_token=result.jwt_token,
                tenant_context=different_tenant_context,
            )

    def test_dashboard_url_includes_embed_params(self, service, tenant_context):
        """Test that dashboard URL includes embed parameters."""
        result = service.generate_embed_token(
            tenant_context=tenant_context,
            dashboard_id="dashboard_1",
        )

        assert "standalone=1" in result.dashboard_url
        assert "show_filters=0" in result.dashboard_url
        assert "show_title=0" in result.dashboard_url


class TestCSPConfig:
    """Tests for CSP configuration."""

    def test_default_frame_ancestors(self):
        """Test default frame ancestors include Shopify Admin."""
        config = CSPConfig()

        assert "'self'" in config.frame_ancestors
        assert "https://admin.shopify.com" in config.frame_ancestors
        assert "https://*.myshopify.com" in config.frame_ancestors

    def test_build_csp_header(self):
        """Test CSP header generation."""
        config = CSPConfig()
        header = config.build_csp_header()

        assert "frame-ancestors" in header
        assert "default-src 'self'" in header
        assert "https://admin.shopify.com" in header

    @patch.dict(os.environ, {"EMBED_FRAME_ANCESTORS": "https://custom.com,https://other.com"})
    def test_custom_frame_ancestors_from_env(self):
        """Test frame ancestors can be configured via environment."""
        config = CSPConfig()

        assert "https://custom.com" in config.frame_ancestors
        assert "https://other.com" in config.frame_ancestors


class TestFrameOriginValidation:
    """Tests for frame origin validation."""

    def test_validate_shopify_admin_origin(self):
        """Test that Shopify Admin origin is allowed."""
        mock_request = MagicMock()
        mock_request.headers = {
            "Origin": "https://admin.shopify.com",
            "Referer": "",
        }
        mock_request.url.path = "/api/v1/embed/token"

        assert validate_frame_origin(mock_request) is True

    def test_validate_myshopify_origin(self):
        """Test that myshopify.com origin is allowed."""
        mock_request = MagicMock()
        mock_request.headers = {
            "Origin": "https://mystore.myshopify.com",
            "Referer": "",
        }
        mock_request.url.path = "/api/v1/embed/token"

        assert validate_frame_origin(mock_request) is True

    def test_validate_referer_fallback(self):
        """Test that Referer header is used as fallback."""
        mock_request = MagicMock()
        mock_request.headers = {
            "Origin": "",
            "Referer": "https://admin.shopify.com/store/mystore",
        }
        mock_request.url.path = "/api/v1/embed/token"

        assert validate_frame_origin(mock_request) is True

    def test_validate_direct_access_allowed(self):
        """Test that direct access (no Origin/Referer) is allowed."""
        mock_request = MagicMock()
        mock_request.headers = {
            "Origin": "",
            "Referer": "",
        }
        mock_request.url.path = "/api/v1/embed/token"

        # Direct access is allowed
        assert validate_frame_origin(mock_request) is True


class TestAgencyUserEmbedTokens:
    """Tests for agency users with multi-tenant access."""

    @pytest.fixture
    def config(self):
        """Create test config."""
        return EmbedTokenConfig(
            jwt_secret="test-secret-key-for-testing",
            algorithm="HS256",
            default_lifetime_minutes=60,
            refresh_threshold_minutes=5,
            issuer="test-issuer",
        )

    @pytest.fixture
    def service(self, config):
        """Create test service."""
        return EmbedTokenService(config=config)

    @pytest.fixture
    def agency_tenant_context(self):
        """Create agency user tenant context with multiple tenants."""
        return TenantContext(
            tenant_id="tenant_123",  # Currently active tenant
            user_id="agency_user_1",
            roles=["agency_admin"],
            org_id="agency_org",
            allowed_tenants=["tenant_123", "tenant_456", "tenant_789"],
        )

    def test_agency_token_includes_allowed_tenants(self, service, agency_tenant_context):
        """Test that agency user token includes all allowed tenants."""
        result = service.generate_embed_token(
            tenant_context=agency_tenant_context,
            dashboard_id="dashboard_1",
        )

        payload = jwt.decode(
            result.jwt_token,
            service.config.jwt_secret,
            algorithms=[service.config.algorithm],
        )

        assert payload["tenant_id"] == "tenant_123"
        assert len(payload["allowed_tenants"]) == 3
        assert "tenant_456" in payload["allowed_tenants"]

    def test_agency_token_rls_filter_includes_all_tenants(self, service, agency_tenant_context):
        """Test that RLS filter includes all allowed tenants."""
        result = service.generate_embed_token(
            tenant_context=agency_tenant_context,
            dashboard_id="dashboard_1",
        )

        payload = jwt.decode(
            result.jwt_token,
            service.config.jwt_secret,
            algorithms=[service.config.algorithm],
        )

        rls_filter = payload["rls_filter"]
        assert "tenant_123" in rls_filter
        assert "tenant_456" in rls_filter
        assert "tenant_789" in rls_filter
        assert "IN" in rls_filter


class TestEmbedServiceInitialization:
    """Tests for service initialization."""

    def test_service_requires_jwt_secret(self):
        """Test that service requires JWT secret."""
        with patch.dict(os.environ, {"SUPERSET_JWT_SECRET": ""}):
            # Clear any cached value
            if "SUPERSET_JWT_SECRET" in os.environ:
                del os.environ["SUPERSET_JWT_SECRET"]

            with pytest.raises(ValueError, match="SUPERSET_JWT_SECRET"):
                EmbedTokenService()

    def test_service_uses_env_defaults(self):
        """Test that service uses environment variable defaults."""
        with patch.dict(os.environ, {
            "SUPERSET_JWT_SECRET": "env-secret",
            "EMBED_TOKEN_LIFETIME_MINUTES": "45",
        }):
            service = EmbedTokenService()
            assert service.config.default_lifetime_minutes == 45
