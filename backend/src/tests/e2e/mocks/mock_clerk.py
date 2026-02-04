"""
Mock Clerk authentication server for E2E testing.

Provides:
- JWT token generation with Clerk-compatible claims
- JWKS endpoint for token verification
- Multi-tenant token support via Clerk Organizations
"""

import json
import time
import uuid
import base64
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
class ClerkTokenClaims:
    """Standard Clerk JWT claims for testing."""
    user_id: str
    org_id: str
    org_role: str
    email: str
    metadata: Dict[str, Any]
    exp: datetime
    iat: datetime


class MockClerkServer:
    """
    Mock Clerk authentication server.

    Generates valid JWTs for testing with configurable:
    - Organization context (org_id)
    - Organization roles (org_role)
    - Custom metadata (roles, entitlements, allowed_tenants, billing_tier)
    - Multi-tenant access (agency users)

    Usage:
        mock = MockClerkServer()
        token = mock.create_test_token(
            org_id="org_123",
            metadata={"billing_tier": "growth", "roles": ["MERCHANT_ADMIN"]}
        )

        # Use token in test requests
        response = client.get("/api/v1/insights", headers={
            "Authorization": f"Bearer {token}"
        })
    """

    # Default Clerk Frontend API URL for tests
    DEFAULT_ISSUER = "https://test-app.clerk.accounts.dev"

    def __init__(self, key_id: str = "test-key-1", issuer: Optional[str] = None):
        """
        Initialize mock Clerk server with RSA key pair.

        Args:
            key_id: Key ID (kid) to use in JWT headers
            issuer: Clerk issuer URL (defaults to test URL)
        """
        self.key_id = key_id
        self.issuer = issuer or self.DEFAULT_ISSUER
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
        org_id: str,
        user_id: Optional[str] = None,
        email: Optional[str] = None,
        org_role: str = "org:member",
        org_permissions: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        expires_in_hours: int = 1,
        custom_claims: Optional[Dict] = None,
    ) -> str:
        """
        Create a test JWT with Clerk-compatible claims.

        Args:
            org_id: Organization ID (tenant ID)
            user_id: User ID (auto-generated if not provided)
            email: User email
            org_role: Clerk organization role (e.g., "org:admin", "org:member")
            org_permissions: List of organization permissions
            metadata: Custom metadata (roles, entitlements, allowed_tenants, billing_tier)
            expires_in_hours: Token expiration time
            custom_claims: Additional custom claims to include

        Returns:
            Signed JWT string
        """
        now = datetime.now(timezone.utc)
        user_id = user_id or f"user_{uuid.uuid4().hex[:8]}"

        # Ensure metadata has required fields for our app
        metadata = metadata or {}
        if "roles" not in metadata:
            # Map Clerk org_role to app roles
            role_mapping = {
                "org:admin": "MERCHANT_ADMIN",
                "org:member": "MERCHANT_VIEWER",
                "admin": "ADMIN",
            }
            metadata["roles"] = [role_mapping.get(org_role, "MERCHANT_VIEWER")]
        if "allowed_tenants" not in metadata:
            metadata["allowed_tenants"] = [org_id]
        if "billing_tier" not in metadata:
            metadata["billing_tier"] = "free"

        # Build Clerk-compatible claims
        claims = {
            # Standard JWT claims
            "sub": user_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=expires_in_hours)).timestamp()),
            "iss": self.issuer,

            # Clerk-specific claims
            "azp": "pk_test_abc123",  # Authorized party (publishable key)
            "org_id": org_id,
            "org_role": org_role,
            "org_permissions": org_permissions or [],

            # Custom metadata for our app
            "metadata": metadata,

            # Optional email
            "email": email or f"test-{uuid.uuid4().hex[:8]}@example.com",
        }

        # Add custom claims
        if custom_claims:
            claims.update(custom_claims)

        # Record token for debugging
        self._tokens_issued.append({
            "org_id": org_id,
            "user_id": user_id,
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
        org_id: str,
        user_id: Optional[str] = None,
    ) -> str:
        """Create a token with admin role."""
        return self.create_test_token(
            org_id=org_id,
            user_id=user_id,
            org_role="org:admin",
            metadata={
                "roles": ["MERCHANT_ADMIN"],
                "billing_tier": "growth",
                "allowed_tenants": [org_id],
            },
        )

    def create_agency_token(
        self,
        primary_org_id: str,
        allowed_tenants: List[str],
        user_id: Optional[str] = None,
    ) -> str:
        """Create a token for agency users with multi-tenant access."""
        return self.create_test_token(
            org_id=primary_org_id,
            user_id=user_id,
            org_role="org:admin",
            metadata={
                "roles": ["AGENCY_ADMIN"],
                "billing_tier": "enterprise",
                "allowed_tenants": allowed_tenants,
            },
        )

    def create_free_tier_token(self, org_id: str) -> str:
        """Create a token for free tier users (no AI entitlements)."""
        return self.create_test_token(
            org_id=org_id,
            org_role="org:member",
            metadata={
                "roles": ["MERCHANT_VIEWER"],
                "billing_tier": "free",
                "allowed_tenants": [org_id],
            },
        )

    def create_expired_token(self, org_id: str) -> str:
        """Create an expired token (for testing auth failures)."""
        now = datetime.now(timezone.utc)

        claims = {
            "sub": f"user_{uuid.uuid4().hex[:8]}",
            "org_id": org_id,
            "org_role": "org:member",
            "metadata": {"roles": ["MERCHANT_VIEWER"], "billing_tier": "free"},
            "iat": int((now - timedelta(hours=2)).timestamp()),
            "exp": int((now - timedelta(hours=1)).timestamp()),  # Already expired
            "iss": self.issuer,
            "azp": "pk_test_abc123",
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
