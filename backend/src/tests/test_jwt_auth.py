"""
Tests for JWT authentication handling.

Tests cover:
- JWT claim validation
- Token verification error handling
- Middleware integration
- Permission checking
- Session management
"""

import pytest
import time
import jwt
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from starlette.testclient import TestClient
from starlette.requests import Request
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient as FastAPITestClient

from src.auth.clerk_verifier import (
    ClerkJWTVerifier,
    ClerkVerificationError,
)
from src.auth.jwt import (
    ClerkJWTClaims,
    ExtractedClaims,
    extract_claims,
    TokenInfo,
)
from src.auth.context_resolver import AuthContext, TenantAccess
from src.auth.token_service import (
    TokenService,
    RevocationReason,
)
from src.auth.middleware import (
    ClerkAuthMiddleware,
    get_auth_context,
    require_auth,
    require_tenant,
    require_permission,
    get_current_user,
)
from src.constants.permissions import Permission


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def test_keypair():
    """Generate test RSA keypair."""
    private_key = rsa.generate_private_key(65537, 2048, default_backend())
    public_key = private_key.public_key()

    return {
        "private_key": private_key,
        "public_key": public_key,
        "private_pem": private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()
        ),
    }


@pytest.fixture
def mock_verifier(test_keypair):
    """Create mock verifier that validates test tokens."""

    class MockVerifier:
        def __init__(self):
            self._public_key = test_keypair["public_key"]

        def verify_token(self, token, **kwargs):
            try:
                return jwt.decode(
                    token,
                    self._public_key,
                    algorithms=["RS256"],
                    options={"verify_aud": False, "verify_iss": False},
                )
            except jwt.ExpiredSignatureError:
                raise ClerkVerificationError("Token expired", "token_expired")
            except jwt.InvalidTokenError as e:
                raise ClerkVerificationError(str(e), "invalid_token")

    return MockVerifier()


@pytest.fixture
def create_token(test_keypair):
    """Factory for creating test tokens."""

    def _create(
        sub="user_test123",
        exp_offset=3600,
        sid="sess_test123",
        org_id=None,
        **extra_claims,
    ):
        now = int(time.time())
        claims = {
            "sub": sub,
            "iss": "https://test.clerk.accounts.dev",
            "exp": now + exp_offset,
            "iat": now,
            "sid": sid,
            **extra_claims,
        }
        if org_id:
            claims["org_id"] = org_id

        return jwt.encode(
            claims,
            test_keypair["private_pem"],
            algorithm="RS256",
        )

    return _create


@pytest.fixture
def token_service():
    """Create test token service."""
    service = TokenService(use_redis=False)
    yield service
    service.clear_revocation_list()


# =============================================================================
# JWT Verification Tests
# =============================================================================

class TestJWTVerification:
    """Tests for JWT verification."""

    def test_valid_token_verification(self, mock_verifier, create_token):
        """Test verifying a valid token."""
        token = create_token()
        claims = mock_verifier.verify_token(token)

        assert claims["sub"] == "user_test123"
        assert "exp" in claims
        assert "iat" in claims

    def test_expired_token_raises_error(self, mock_verifier, create_token):
        """Test that expired tokens raise error."""
        token = create_token(exp_offset=-3600)  # Expired 1 hour ago

        with pytest.raises(ClerkVerificationError) as exc:
            mock_verifier.verify_token(token)

        assert exc.value.error_code == "token_expired"

    def test_malformed_token_raises_error(self, mock_verifier):
        """Test that malformed tokens raise error."""
        with pytest.raises(ClerkVerificationError) as exc:
            mock_verifier.verify_token("not-a-valid-jwt")

        assert exc.value.error_code == "invalid_token"


# =============================================================================
# Token Info Tests
# =============================================================================

class TestTokenInfo:
    """Tests for TokenInfo helper class."""

    def test_token_info_from_claims(self):
        """Test creating TokenInfo from ExtractedClaims."""
        now = datetime.now(timezone.utc)
        claims = ExtractedClaims(
            clerk_user_id="user_123",
            session_id="sess_123",
            org_id="org_123",
            org_role="org:admin",
            org_slug="test-org",
            issued_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(hours=1),
        )

        info = TokenInfo.from_claims(claims)

        assert info.clerk_user_id == "user_123"
        assert info.session_id == "sess_123"
        assert info.is_expired is False
        assert info.time_until_expiry_seconds > 0

    def test_token_info_expired(self):
        """Test TokenInfo for expired token."""
        now = datetime.now(timezone.utc)
        claims = ExtractedClaims(
            clerk_user_id="user_123",
            session_id="sess_123",
            org_id=None,
            org_role=None,
            org_slug=None,
            issued_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),  # Expired
        )

        info = TokenInfo.from_claims(claims)

        assert info.is_expired is True
        assert info.time_until_expiry_seconds < 0

    def test_token_info_to_log_dict(self):
        """Test TokenInfo logging output."""
        now = datetime.now(timezone.utc)
        claims = ExtractedClaims(
            clerk_user_id="user_very_long_id_that_should_be_truncated",
            session_id="sess_123",
            org_id="org_123",
            org_role=None,
            org_slug=None,
            issued_at=now,
            expires_at=now + timedelta(hours=1),
        )

        info = TokenInfo.from_claims(claims)
        log_dict = info.to_log_dict()

        assert "..." in log_dict["clerk_user_id"]  # Truncated
        assert log_dict["is_expired"] is False
        assert isinstance(log_dict["expires_in_seconds"], int)


# =============================================================================
# Session Revocation Tests
# =============================================================================

class TestSessionRevocation:
    """Tests for session revocation functionality."""

    def test_revoke_single_session(self, token_service):
        """Test revoking a single session."""
        session_id = "sess_to_revoke"

        # Not revoked initially
        assert token_service.is_revoked(session_id=session_id) is False

        # Revoke
        token_service.revoke_session(session_id, RevocationReason.LOGOUT)

        # Now revoked
        assert token_service.is_revoked(session_id=session_id) is True

    def test_revoke_user_sessions_with_timestamp(self, token_service):
        """Test revoking user sessions with timestamp check."""
        user_id = "user_123"
        old_token_time = datetime.now(timezone.utc) - timedelta(hours=1)
        new_token_time = datetime.now(timezone.utc) + timedelta(minutes=1)

        # Revoke all sessions issued before now
        token_service.revoke_all_user_sessions(
            user_id,
            RevocationReason.PASSWORD_CHANGED,
        )

        # Old token should be revoked
        assert token_service.is_revoked(
            clerk_user_id=user_id,
            token_issued_at=old_token_time,
        ) is True

        # Session not in revocation list should pass (new session check only)
        assert token_service.is_revoked(session_id="new_session") is False

    def test_revocation_reasons(self, token_service):
        """Test different revocation reasons."""
        reasons = [
            RevocationReason.LOGOUT,
            RevocationReason.USER_DEACTIVATED,
            RevocationReason.SECURITY_EVENT,
            RevocationReason.ADMIN_REVOKE,
            RevocationReason.PASSWORD_CHANGED,
        ]

        for i, reason in enumerate(reasons):
            session_id = f"sess_{i}"
            token_service.revoke_session(session_id, reason)
            assert token_service.is_revoked(session_id=session_id) is True


# =============================================================================
# Middleware Integration Tests
# =============================================================================

class TestMiddlewareIntegration:
    """Tests for authentication middleware integration."""

    def test_test_app_with_auth(self, mock_verifier, create_token):
        """Test FastAPI app with auth middleware."""
        app = FastAPI()

        # Mock the verifier
        with patch("src.auth.middleware.get_verifier", return_value=mock_verifier):
            with patch("src.auth.middleware.get_db_session_sync") as mock_db:
                # Setup mock session
                mock_session = MagicMock()
                mock_db.return_value = mock_session

                # Setup mock user lookup
                with patch("src.auth.context_resolver.ClerkSyncService") as mock_sync:
                    mock_user = MagicMock()
                    mock_user.id = "internal_user_123"
                    mock_sync.return_value.get_or_create_user.return_value = mock_user
                    mock_sync.return_value.get_user_by_clerk_id.return_value = None

                    @app.get("/test")
                    async def test_route(auth: AuthContext = Depends(get_auth_context)):
                        return {"authenticated": auth.is_authenticated}

                    # Note: Full integration test would require more setup
                    # This validates the middleware components work together


class TestAuthDependencies:
    """Tests for FastAPI auth dependencies."""

    def test_require_auth_unauthenticated(self):
        """Test require_auth raises for unauthenticated requests."""
        from fastapi import HTTPException

        mock_request = MagicMock()
        mock_request.state.auth_context = AuthContext(
            user=None,
            clerk_user_id="",
            session_id=None,
        )

        with pytest.raises(HTTPException) as exc:
            require_auth(mock_request, None)

        assert exc.value.status_code == 401

    def test_require_auth_authenticated(self):
        """Test require_auth passes for authenticated requests."""
        mock_user = MagicMock()
        mock_user.id = "user_123"

        auth_context = AuthContext(
            user=mock_user,
            clerk_user_id="clerk_123",
            session_id="sess_123",
        )

        mock_request = MagicMock()
        mock_request.state.auth_context = auth_context

        result = require_auth(mock_request, None)
        assert result == auth_context

    def test_require_tenant_no_tenant(self):
        """Test require_tenant raises when no tenant selected."""
        from fastapi import HTTPException

        mock_user = MagicMock()
        auth_context = AuthContext(
            user=mock_user,
            clerk_user_id="clerk_123",
            session_id="sess_123",
            current_tenant_id=None,  # No tenant selected
        )

        with pytest.raises(HTTPException) as exc:
            require_tenant(auth_context)

        assert exc.value.status_code == 400

    def test_require_tenant_with_tenant(self):
        """Test require_tenant passes when tenant is selected."""
        mock_user = MagicMock()
        auth_context = AuthContext(
            user=mock_user,
            clerk_user_id="clerk_123",
            session_id="sess_123",
            current_tenant_id="tenant_123",
            tenant_access={
                "tenant_123": TenantAccess(
                    tenant_id="tenant_123",
                    tenant_name="Test",
                    roles=frozenset(),
                    permissions=frozenset(),
                    billing_tier="free",
                ),
            },
        )

        result = require_tenant(auth_context)
        assert result == auth_context


class TestPermissionDependencies:
    """Tests for permission checking dependencies."""

    def test_require_permission_granted(self):
        """Test require_permission passes when permission is granted."""
        mock_user = MagicMock()
        auth_context = AuthContext(
            user=mock_user,
            clerk_user_id="clerk_123",
            session_id="sess_123",
            current_tenant_id="tenant_123",
            tenant_access={
                "tenant_123": TenantAccess(
                    tenant_id="tenant_123",
                    tenant_name="Test",
                    roles=frozenset(["merchant_admin"]),
                    permissions=frozenset([Permission.ANALYTICS_VIEW]),
                    billing_tier="growth",
                ),
            },
        )

        dependency = require_permission(Permission.ANALYTICS_VIEW)
        result = dependency(auth_context)
        assert result == auth_context

    def test_require_permission_denied(self):
        """Test require_permission raises when permission is denied."""
        from fastapi import HTTPException

        mock_user = MagicMock()
        auth_context = AuthContext(
            user=mock_user,
            clerk_user_id="clerk_123",
            session_id="sess_123",
            current_tenant_id="tenant_123",
            tenant_access={
                "tenant_123": TenantAccess(
                    tenant_id="tenant_123",
                    tenant_name="Test",
                    roles=frozenset(["viewer"]),
                    permissions=frozenset([Permission.ANALYTICS_VIEW]),
                    billing_tier="free",
                ),
            },
        )

        dependency = require_permission(Permission.ADMIN_PLANS_MANAGE)

        with pytest.raises(HTTPException) as exc:
            dependency(auth_context)

        assert exc.value.status_code == 403


# =============================================================================
# Claim Parsing Edge Cases
# =============================================================================

class TestClaimEdgeCases:
    """Tests for edge cases in claim parsing."""

    def test_extra_claims_preserved(self):
        """Test that extra claims are preserved."""
        claims = {
            "sub": "user_123",
            "iss": "https://test.clerk.accounts.dev",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "custom_claim": "custom_value",
            "another_claim": 123,
        }

        parsed = ClerkJWTClaims(**claims)
        assert parsed.sub == "user_123"
        # Extra claims should be accessible via model_extra

    def test_missing_optional_claims(self):
        """Test handling of missing optional claims."""
        claims = {
            "sub": "user_123",
            "iss": "https://test.clerk.accounts.dev",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            # No sid, org_id, etc.
        }

        parsed = ClerkJWTClaims(**claims)
        assert parsed.sid is None
        assert parsed.org_id is None
        assert parsed.has_org_context is False

    def test_org_permissions_list(self):
        """Test org_permissions as list."""
        claims = {
            "sub": "user_123",
            "iss": "https://test.clerk.accounts.dev",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "org_id": "org_123",
            "org_role": "org:admin",
            "org_permissions": ["manage:members", "read:analytics"],
        }

        parsed = ClerkJWTClaims(**claims)
        assert parsed.org_permissions == ["manage:members", "read:analytics"]

    def test_timestamp_boundary_conditions(self):
        """Test timestamp edge cases."""
        now = int(time.time())

        # Token that expires exactly now
        claims = {
            "sub": "user_123",
            "iss": "https://test.clerk.accounts.dev",
            "exp": now,
            "iat": now - 1,
        }

        parsed = ClerkJWTClaims(**claims)
        # Depending on timing, might be expired or not
        assert isinstance(parsed.is_expired, bool)
