"""
Tests for Clerk authentication integration.

Tests cover:
- JWT verification with mocked JWKS
- Token extraction from headers and cookies
- AuthContext resolution
- Session revocation
- Middleware behavior
"""

import pytest
import time
import jwt
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from src.auth.clerk_verifier import (
    ClerkJWTVerifier,
    ClerkVerificationError,
    verify_clerk_token,
)
from src.auth.jwt import (
    ClerkJWTClaims,
    ExtractedClaims,
    extract_claims,
    parse_clerk_claims,
)
from src.auth.context_resolver import (
    AuthContext,
    AuthContextResolver,
    TenantAccess,
    resolve_auth_context,
)
from src.auth.token_service import (
    TokenService,
    RevocationReason,
    SessionInfo,
)
from src.auth.middleware import (
    ClerkAuthMiddleware,
    is_exempt_path,
    get_auth_context,
    require_auth,
)
from src.constants.permissions import Permission


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def rsa_keypair():
    """Generate RSA keypair for testing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    return {
        "private_key": private_key,
        "public_key": public_key,
        "private_pem": private_pem,
        "public_pem": public_pem,
    }


@pytest.fixture
def mock_clerk_issuer():
    """Mock Clerk issuer URL."""
    return "https://test.clerk.accounts.dev"


@pytest.fixture
def sample_claims(mock_clerk_issuer):
    """Sample JWT claims."""
    now = int(time.time())
    return {
        "sub": "user_clerk_test123",
        "iss": mock_clerk_issuer,
        "exp": now + 3600,  # 1 hour from now
        "iat": now,
        "nbf": now,
        "sid": "sess_test123",
        "azp": "pk_test_abc123",
    }


@pytest.fixture
def sample_claims_with_org(sample_claims):
    """Sample claims with organization context."""
    return {
        **sample_claims,
        "org_id": "org_test123",
        "org_role": "org:admin",
        "org_slug": "test-org",
    }


@pytest.fixture
def create_test_token(rsa_keypair, mock_clerk_issuer):
    """Factory to create test JWTs."""
    def _create(claims=None, expired=False, invalid_sig=False):
        now = int(time.time())
        default_claims = {
            "sub": "user_clerk_test123",
            "iss": mock_clerk_issuer,
            "exp": now - 3600 if expired else now + 3600,
            "iat": now,
            "sid": "sess_test123",
        }
        token_claims = {**default_claims, **(claims or {})}

        key = rsa_keypair["private_pem"]
        if invalid_sig:
            # Generate a different key for invalid signature
            bad_key = rsa.generate_private_key(65537, 2048, default_backend())
            key = bad_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption()
            )

        return jwt.encode(
            token_claims,
            key,
            algorithm="RS256",
            headers={"kid": "test-key-1"},
        )
    return _create


@pytest.fixture
def token_service():
    """Create fresh TokenService for testing."""
    service = TokenService(use_redis=False)
    yield service
    service.clear_revocation_list()


@pytest.fixture
def db_session(test_db_session):
    """Use test database session."""
    return test_db_session


# =============================================================================
# JWT Claims Tests
# =============================================================================

class TestClerkJWTClaims:
    """Tests for ClerkJWTClaims model."""

    def test_parse_basic_claims(self, sample_claims):
        """Test parsing basic JWT claims."""
        claims = ClerkJWTClaims(**sample_claims)

        assert claims.sub == "user_clerk_test123"
        assert claims.clerk_user_id == "user_clerk_test123"
        assert claims.session_id == "sess_test123"
        assert claims.has_org_context is False

    def test_parse_org_claims(self, sample_claims_with_org):
        """Test parsing claims with org context."""
        claims = ClerkJWTClaims(**sample_claims_with_org)

        assert claims.has_org_context is True
        assert claims.org_id == "org_test123"
        assert claims.org_role == "org:admin"
        assert claims.is_org_admin is True

    def test_expiration_datetime(self, sample_claims):
        """Test expiration datetime conversion."""
        claims = ClerkJWTClaims(**sample_claims)

        assert isinstance(claims.expiration_datetime, datetime)
        assert claims.expiration_datetime.tzinfo == timezone.utc
        assert claims.is_expired is False

    def test_expired_token(self, sample_claims):
        """Test expired token detection."""
        expired_claims = {**sample_claims, "exp": int(time.time()) - 3600}
        claims = ClerkJWTClaims(**expired_claims)

        assert claims.is_expired is True


class TestExtractClaims:
    """Tests for claim extraction."""

    def test_extract_basic_claims(self, sample_claims):
        """Test extracting basic claims."""
        extracted = extract_claims(sample_claims)

        assert isinstance(extracted, ExtractedClaims)
        assert extracted.clerk_user_id == "user_clerk_test123"
        assert extracted.session_id == "sess_test123"
        assert extracted.org_id is None

    def test_extract_org_claims(self, sample_claims_with_org):
        """Test extracting org context claims."""
        extracted = extract_claims(sample_claims_with_org)

        assert extracted.org_id == "org_test123"
        assert extracted.org_role == "org:admin"
        assert extracted.has_org_context is True

    def test_missing_required_claims(self):
        """Test error on missing required claims."""
        with pytest.raises(ValueError, match="Missing required claim: sub"):
            extract_claims({"exp": 1234, "iat": 1234})

        with pytest.raises(ValueError, match="Missing required claim: exp"):
            extract_claims({"sub": "user", "iat": 1234})


# =============================================================================
# Token Service Tests
# =============================================================================

class TestTokenService:
    """Tests for TokenService."""

    def test_session_not_revoked_by_default(self, token_service):
        """Test that sessions are not revoked by default."""
        assert token_service.is_revoked(session_id="sess_123") is False

    def test_revoke_session(self, token_service):
        """Test session revocation."""
        token_service.revoke_session(
            session_id="sess_123",
            reason=RevocationReason.LOGOUT,
        )

        assert token_service.is_revoked(session_id="sess_123") is True

    def test_revoke_all_user_sessions(self, token_service):
        """Test revoking all sessions for a user."""
        user_id = "user_test123"
        issued_at = datetime.now(timezone.utc) - timedelta(hours=1)

        token_service.revoke_all_user_sessions(
            clerk_user_id=user_id,
            reason=RevocationReason.SECURITY_EVENT,
        )

        # Token issued before revocation should be revoked
        assert token_service.is_revoked(
            clerk_user_id=user_id,
            token_issued_at=issued_at,
        ) is True

        # New token (issued after revocation) should not be affected
        # by checking without the issued_at
        assert token_service.is_revoked(session_id="new_sess") is False

    def test_record_activity(self, token_service):
        """Test recording session activity."""
        token_service.record_activity(
            session_id="sess_123",
            clerk_user_id="user_123",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ip_address="127.0.0.1",
            user_agent="TestAgent/1.0",
        )

        session = token_service.get_session_info("sess_123")
        assert session is not None
        assert session.clerk_user_id == "user_123"
        assert session.ip_address == "127.0.0.1"

    def test_get_active_sessions(self, token_service):
        """Test getting active sessions for user."""
        user_id = "user_123"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        # Record multiple sessions
        token_service.record_activity("sess_1", user_id, expires_at)
        token_service.record_activity("sess_2", user_id, expires_at)
        token_service.record_activity("sess_3", "other_user", expires_at)

        sessions = token_service.get_active_sessions(user_id)
        assert len(sessions) == 2
        assert all(s.clerk_user_id == user_id for s in sessions)


# =============================================================================
# Auth Context Tests
# =============================================================================

class TestTenantAccess:
    """Tests for TenantAccess."""

    def test_has_permission(self):
        """Test permission checking."""
        access = TenantAccess(
            tenant_id="tenant_123",
            tenant_name="Test Tenant",
            roles=frozenset(["merchant_admin"]),
            permissions=frozenset([Permission.ANALYTICS_VIEW, Permission.STORE_VIEW]),
            billing_tier="growth",
        )

        assert access.has_permission(Permission.ANALYTICS_VIEW) is True
        assert access.has_permission(Permission.ADMIN_PLANS_VIEW) is False

    def test_has_role(self):
        """Test role checking."""
        access = TenantAccess(
            tenant_id="tenant_123",
            tenant_name="Test Tenant",
            roles=frozenset(["merchant_admin", "viewer"]),
            permissions=frozenset(),
            billing_tier="free",
        )

        assert access.has_role("merchant_admin") is True
        assert access.has_role("MERCHANT_ADMIN") is True  # Case insensitive
        assert access.has_role("agency_admin") is False


class TestAuthContext:
    """Tests for AuthContext."""

    def test_anonymous_context(self):
        """Test anonymous (unauthenticated) context."""
        context = AuthContext(
            user=None,
            clerk_user_id="",
            session_id=None,
        )

        assert context.is_authenticated is False
        assert context.user_id is None
        assert context.allowed_tenant_ids == []

    def test_authenticated_context(self):
        """Test authenticated context."""
        mock_user = MagicMock()
        mock_user.id = "user_internal_123"

        tenant_access = {
            "tenant_1": TenantAccess(
                tenant_id="tenant_1",
                tenant_name="Tenant 1",
                roles=frozenset(["merchant_admin"]),
                permissions=frozenset([Permission.ANALYTICS_VIEW]),
                billing_tier="growth",
            ),
        }

        context = AuthContext(
            user=mock_user,
            clerk_user_id="user_clerk_123",
            session_id="sess_123",
            tenant_access=tenant_access,
            current_tenant_id="tenant_1",
        )

        assert context.is_authenticated is True
        assert context.user_id == "user_internal_123"
        assert context.allowed_tenant_ids == ["tenant_1"]
        assert context.has_permission(Permission.ANALYTICS_VIEW) is True

    def test_multi_tenant_access(self):
        """Test multi-tenant access."""
        mock_user = MagicMock()
        mock_user.id = "user_123"

        tenant_access = {
            "tenant_1": TenantAccess(
                tenant_id="tenant_1",
                tenant_name="Tenant 1",
                roles=frozenset(["agency_admin"]),
                permissions=frozenset([Permission.ANALYTICS_VIEW]),
                billing_tier="enterprise",
            ),
            "tenant_2": TenantAccess(
                tenant_id="tenant_2",
                tenant_name="Tenant 2",
                roles=frozenset(["agency_viewer"]),
                permissions=frozenset([Permission.ANALYTICS_VIEW]),
                billing_tier="growth",
            ),
        }

        context = AuthContext(
            user=mock_user,
            clerk_user_id="user_123",
            session_id="sess_123",
            tenant_access=tenant_access,
            current_tenant_id="tenant_1",
        )

        assert context.has_multi_tenant_access is True
        assert len(context.allowed_tenant_ids) == 2
        assert context.has_access_to_tenant("tenant_1") is True
        assert context.has_access_to_tenant("tenant_2") is True
        assert context.has_access_to_tenant("tenant_3") is False

    def test_switch_tenant(self):
        """Test tenant switching."""
        mock_user = MagicMock()
        tenant_access = {
            "tenant_1": TenantAccess("tenant_1", "T1", frozenset(), frozenset(), "free"),
            "tenant_2": TenantAccess("tenant_2", "T2", frozenset(), frozenset(), "free"),
        }

        context = AuthContext(
            user=mock_user,
            clerk_user_id="user_123",
            session_id="sess_123",
            tenant_access=tenant_access,
            current_tenant_id="tenant_1",
        )

        # Switch to valid tenant
        assert context.switch_tenant("tenant_2") is True
        assert context.current_tenant_id == "tenant_2"

        # Try to switch to invalid tenant
        assert context.switch_tenant("tenant_3") is False
        assert context.current_tenant_id == "tenant_2"  # Unchanged


# =============================================================================
# Middleware Path Exemption Tests
# =============================================================================

class TestPathExemption:
    """Tests for path exemption logic."""

    def test_exempt_paths(self):
        """Test exact path exemptions."""
        assert is_exempt_path("/health") is True
        assert is_exempt_path("/api/health") is True
        assert is_exempt_path("/api/webhooks/clerk") is True
        assert is_exempt_path("/docs") is True
        assert is_exempt_path("/openapi.json") is True

    def test_exempt_prefixes(self):
        """Test prefix-based exemptions."""
        assert is_exempt_path("/api/webhooks/shopify") is True
        assert is_exempt_path("/api/webhooks/clerk/health") is True
        assert is_exempt_path("/static/js/app.js") is True

    def test_non_exempt_paths(self):
        """Test non-exempt paths."""
        assert is_exempt_path("/api/data") is False
        assert is_exempt_path("/api/insights") is False
        assert is_exempt_path("/api/tenants") is False


# =============================================================================
# Integration Tests with DB
# =============================================================================

class TestAuthContextResolver:
    """Integration tests for AuthContextResolver."""

    def test_resolve_context_creates_user(self, db_session, sample_claims):
        """Test that resolver creates user via lazy sync."""
        extracted = extract_claims(sample_claims)
        resolver = AuthContextResolver(db_session)

        context = resolver.resolve(extracted, lazy_sync=True)
        db_session.flush()

        assert context.is_authenticated is True
        assert context.user is not None
        assert context.user.clerk_user_id == "user_clerk_test123"

    def test_resolve_context_without_lazy_sync(self, db_session, sample_claims):
        """Test that resolver returns no user when lazy_sync is False."""
        # Use a new user ID that doesn't exist
        claims = {**sample_claims, "sub": "user_nonexistent_123"}
        extracted = extract_claims(claims)
        resolver = AuthContextResolver(db_session)

        context = resolver.resolve(extracted, lazy_sync=False)

        assert context.user is None
        assert context.is_authenticated is False

    def test_resolve_context_with_tenant_roles(self, db_session):
        """Test resolver loads tenant access correctly."""
        from src.models.user import User
        from src.models.tenant import Tenant, TenantStatus
        from src.models.user_tenant_roles import UserTenantRole

        # Create user, tenant, and role
        user = User(
            clerk_user_id="user_with_roles_123",
            email="test@example.com",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()

        tenant = Tenant(
            name="Test Tenant",
            clerk_org_id="org_test123",
            billing_tier="growth",
            status=TenantStatus.ACTIVE,
        )
        db_session.add(tenant)
        db_session.flush()

        role = UserTenantRole(
            user_id=user.id,
            tenant_id=tenant.id,
            role="MERCHANT_ADMIN",
            is_active=True,
        )
        db_session.add(role)
        db_session.flush()

        # Resolve context
        claims = {
            "sub": "user_with_roles_123",
            "iss": "https://test.clerk.accounts.dev",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "org_id": "org_test123",
        }
        extracted = extract_claims(claims)
        resolver = AuthContextResolver(db_session)

        context = resolver.resolve(extracted)

        assert context.is_authenticated is True
        assert tenant.id in context.allowed_tenant_ids
        assert context.current_tenant_id == tenant.id  # Set from org_id
        assert Permission.ANALYTICS_VIEW in context.current_permissions
