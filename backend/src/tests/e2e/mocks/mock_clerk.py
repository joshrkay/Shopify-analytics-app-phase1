"""
Mock Clerk authentication server for E2E testing.

Provides:
- JWT token generation with configurable claims
- JWKS endpoint for token verification
- Multi-tenant token support (via Clerk Organizations)
"""

import json
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

import httpx

# Use cryptography for RSA key generation
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
import jwt


@dataclass
class TokenClaims:
    """Standard JWT claims for testing."""
    tenant_id: str
    user_id: str
    email: str
    roles: List[str]
    entitlements: List[str]
    allowed_tenants: List[str]
    exp: datetime
    iat: datetime


class MockClerkServer:
    """
    Mock Clerk authentication server.

    Generates valid JWTs for testing with configurable:
    - Tenant context (org_id)
    - User roles
    - Feature entitlements
    - Multi-tenant access (agency users)

    Usage:
        mock = MockClerkServer()
        token = mock.create_test_token(
            tenant_id="tenant-123",
            entitlements=["AI_INSIGHTS", "AI_ACTIONS"]
        )

        # Use token in test requests
        response = client.get("/api/v1/insights", headers={
            "Authorization": f"Bearer {token}"
        })
    """

    def __init__(self, key_id: str = "test-key-1"):
        """
        Initialize mock Clerk server with RSA key pair.

        Args:
            key_id: Key ID (kid) to use in JWT headers
        """
        self.key_id = key_id
        self._private_key, self._public_key = self._generate_rsa_keys()
        self._tokens_issued: List[Dict] = []

    def _generate_rsa_keys(self) -> tuple:
        """Generate RSA key pair for JWT signing."""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        public_key = private_key.public_key()
        return private_key, public_key

    def create_test_token(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        email: Optional[str] = None,
        roles: Optional[List[str]] = None,
        entitlements: Optional[List[str]] = None,
        allowed_tenants: Optional[List[str]] = None,
        expires_in_hours: int = 1,
        custom_claims: Optional[Dict] = None,
    ) -> str:
        """
        Create a test JWT with specified claims.

        Args:
            tenant_id: Primary tenant ID (becomes org_id in token)
            user_id: User ID (auto-generated if not provided)
            email: User email
            roles: List of roles (default: ["user"])
            entitlements: List of feature entitlements
            allowed_tenants: List of allowed tenant IDs for multi-tenant access
            expires_in_hours: Token expiration time
            custom_claims: Additional custom claims to include

        Returns:
            Signed JWT string
        """
        now = datetime.now(timezone.utc)

        # Build claims (Clerk JWT format)
        claims = {
            "sub": user_id or f"user_{uuid.uuid4().hex[:24]}",
            "email": email or f"test-{uuid.uuid4().hex[:8]}@example.com",
            "org_id": tenant_id,  # Clerk organization ID
            "org_role": roles[0] if roles else "org:member",  # Clerk org role format
            "org_permissions": roles or ["org:member"],
            "metadata": {
                "roles": roles or ["user"],
                "entitlements": entitlements or [],
                "allowed_tenants": allowed_tenants or [tenant_id],
            },
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=expires_in_hours)).timestamp()),
            "iss": "https://clerk.example.com",  # Clerk issuer format
            "azp": "test-clerk-publishable-key",  # Clerk authorized party
            "sid": f"sess_{uuid.uuid4().hex[:24]}",  # Clerk session ID
        }

        # Add custom claims
        if custom_claims:
            claims.update(custom_claims)

        # Record token for debugging
        self._tokens_issued.append({
            "tenant_id": tenant_id,
            "user_id": claims["sub"],
            "issued_at": now.isoformat(),
        })

        # Sign token
        private_key_pem = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

        token = jwt.encode(
            claims,
            private_key_pem,
            algorithm="RS256",
            headers={"kid": self.key_id}
        )

        return token

    def create_admin_token(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
    ) -> str:
        """Create a token with admin role."""
        return self.create_test_token(
            tenant_id=tenant_id,
            user_id=user_id,
            roles=["admin", "user"],
            entitlements=[
                "AI_INSIGHTS",
                "AI_RECOMMENDATIONS",
                "AI_ACTIONS",
                "ADVANCED_ANALYTICS",
            ],
        )

    def create_agency_token(
        self,
        primary_tenant_id: str,
        allowed_tenants: List[str],
        user_id: Optional[str] = None,
    ) -> str:
        """Create a token for agency users with multi-tenant access."""
        return self.create_test_token(
            tenant_id=primary_tenant_id,
            user_id=user_id,
            roles=["agency_user", "user"],
            allowed_tenants=allowed_tenants,
            entitlements=["AI_INSIGHTS", "AI_RECOMMENDATIONS"],
        )

    def create_free_tier_token(self, tenant_id: str) -> str:
        """Create a token for free tier users (no AI entitlements)."""
        return self.create_test_token(
            tenant_id=tenant_id,
            roles=["user"],
            entitlements=[],  # No AI features
        )

    def create_expired_token(self, tenant_id: str) -> str:
        """Create an expired token (for testing auth failures)."""
        now = datetime.now(timezone.utc)

        claims = {
            "sub": f"user_{uuid.uuid4().hex[:24]}",
            "org_id": tenant_id,
            "org_role": "org:member",
            "metadata": {
                "roles": ["user"],
                "entitlements": [],
            },
            "iat": int((now - timedelta(hours=2)).timestamp()),
            "exp": int((now - timedelta(hours=1)).timestamp()),  # Already expired
            "iss": "https://clerk.example.com",
            "azp": "test-clerk-publishable-key",
        }

        private_key_pem = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

        return jwt.encode(
            claims,
            private_key_pem,
            algorithm="RS256",
            headers={"kid": self.key_id}
        )

    def get_jwks(self) -> Dict:
        """
        Get JWKS (JSON Web Key Set) for token verification.

        This is what the application fetches from Clerk to verify tokens.
        """
        public_numbers = self._public_key.public_numbers()

        # Convert to base64url encoding
        import base64

        def int_to_base64url(n: int, length: int) -> str:
            data = n.to_bytes(length, byteorder='big')
            return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

        n_bytes = (public_numbers.n.bit_length() + 7) // 8

        return {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "kid": self.key_id,
                    "alg": "RS256",
                    "n": int_to_base64url(public_numbers.n, n_bytes),
                    "e": int_to_base64url(public_numbers.e, 3),
                }
            ]
        }

    def get_public_key_pem(self) -> str:
        """Get public key in PEM format (alternative to JWKS)."""
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

    def get_tokens_issued(self) -> List[Dict]:
        """Get list of all tokens issued (for debugging)."""
        return self._tokens_issued.copy()

    def reset(self) -> None:
        """Reset state (clear issued tokens list)."""
        self._tokens_issued.clear()

    def get_mock_transport(self) -> httpx.MockTransport:
        """Create an httpx MockTransport for JWKS endpoint."""
        def handle_request(request: httpx.Request) -> httpx.Response:
            path = request.url.path

            if "/.well-known/jwks.json" in path or "/jwks" in path:
                return httpx.Response(200, json=self.get_jwks())
            elif "/oauth/token" in path:
                # Token endpoint (not typically needed for tests)
                return httpx.Response(200, json={"access_token": "mock"})
            else:
                return httpx.Response(404, json={"error": "Not found"})

        return httpx.MockTransport(handle_request)


# Backwards compatibility alias
MockFronteggServer = MockClerkServer


# Helper function to decode and inspect tokens (for debugging)
def decode_test_token(token: str, verify: bool = False) -> Dict:
    """
    Decode a test token to inspect its claims.

    Args:
        token: JWT string
        verify: Whether to verify signature (requires public key)

    Returns:
        Decoded token claims
    """
    if verify:
        raise NotImplementedError("Use MockClerkServer for verification")

    # Decode without verification (for inspection only)
    return jwt.decode(token, options={"verify_signature": False})
