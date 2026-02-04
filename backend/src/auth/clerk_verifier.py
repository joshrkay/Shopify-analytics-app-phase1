"""
Clerk JWT Verifier for authenticating Clerk-issued JWTs.

This module handles:
- Fetching and caching JWKS from Clerk
- JWT signature verification
- Token expiration validation
- Claim extraction

SECURITY:
- Clerk is the ONLY authentication authority
- All JWTs MUST be verified against Clerk's JWKS
- NO custom tokens are issued or accepted

Documentation: https://clerk.com/docs/backend-requests/handling/manual-jwt
"""

import os
import time
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from functools import lru_cache
from threading import Lock

import httpx
import jwt
from jwt import PyJWKClient, PyJWKClientError
from jwt.exceptions import (
    InvalidTokenError,
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
)

logger = logging.getLogger(__name__)


class ClerkVerificationError(Exception):
    """Exception raised when Clerk JWT verification fails."""

    def __init__(self, message: str, error_code: str = "verification_failed"):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class ClerkJWTVerifier:
    """
    Verifies Clerk-issued JWTs using JWKS.

    Clerk JWT structure:
    - Header: alg (RS256), typ (JWT), kid (key ID)
    - Payload:
        - sub: clerk_user_id (e.g., "user_2abc123")
        - iss: Clerk frontend API URL
        - aud: Optional audience claim
        - exp: Expiration timestamp
        - iat: Issued at timestamp
        - nbf: Not before timestamp (optional)
        - sid: Session ID
        - azp: Authorized party (client ID)
        - org_id: Organization ID (if in org context)
        - org_role: Organization role (if in org context)
        - org_slug: Organization slug (if in org context)

    Usage:
        verifier = ClerkJWTVerifier()
        claims = verifier.verify_token(token)
        user_id = claims["sub"]
    """

    # JWKS cache duration in seconds
    JWKS_CACHE_DURATION = 3600  # 1 hour

    # Clock skew tolerance in seconds (for exp/iat validation)
    CLOCK_SKEW_SECONDS = 60

    def __init__(
        self,
        jwks_url: Optional[str] = None,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
    ):
        """
        Initialize the Clerk JWT verifier.

        Args:
            jwks_url: Clerk JWKS URL. If not provided, constructed from CLERK_ISSUER_URL
            issuer: Expected issuer claim. If not provided, uses CLERK_ISSUER_URL
            audience: Expected audience claim (optional)
        """
        # Get Clerk configuration
        self._clerk_issuer = issuer or os.getenv("CLERK_ISSUER_URL")
        self._clerk_publishable_key = os.getenv("CLERK_PUBLISHABLE_KEY")

        if not self._clerk_issuer:
            # Try to construct from publishable key
            if self._clerk_publishable_key:
                # Format: pk_test_xxx or pk_live_xxx
                # Extract the domain part after the prefix
                parts = self._clerk_publishable_key.split("_")
                if len(parts) >= 3:
                    # Clerk domains are like: https://xxx.clerk.accounts.dev
                    pass
            raise ClerkVerificationError(
                "CLERK_ISSUER_URL environment variable is required",
                error_code="config_error",
            )

        # JWKS URL (Clerk's JWKS endpoint)
        self._jwks_url = jwks_url or f"{self._clerk_issuer.rstrip('/')}/.well-known/jwks.json"

        # Expected audience (optional)
        self._audience = audience

        # JWKS client (lazy initialization)
        self._jwks_client: Optional[PyJWKClient] = None
        self._jwks_client_lock = Lock()
        self._jwks_last_refresh: float = 0

        logger.info(
            "Initialized ClerkJWTVerifier",
            extra={"issuer": self._clerk_issuer, "jwks_url": self._jwks_url},
        )

    def _get_jwks_client(self) -> PyJWKClient:
        """
        Get or create JWKS client with caching.

        Returns:
            PyJWKClient configured for Clerk's JWKS endpoint
        """
        with self._jwks_client_lock:
            now = time.time()

            # Create new client if not exists or cache expired
            if (
                self._jwks_client is None
                or now - self._jwks_last_refresh > self.JWKS_CACHE_DURATION
            ):
                try:
                    self._jwks_client = PyJWKClient(
                        self._jwks_url,
                        cache_keys=True,
                        lifespan=self.JWKS_CACHE_DURATION,
                    )
                    self._jwks_last_refresh = now
                    logger.debug("Refreshed JWKS client", extra={"jwks_url": self._jwks_url})
                except Exception as e:
                    logger.error(f"Failed to create JWKS client: {e}")
                    raise ClerkVerificationError(
                        f"Failed to fetch JWKS: {e}",
                        error_code="jwks_fetch_error",
                    )

            return self._jwks_client

    def verify_token(
        self,
        token: str,
        verify_exp: bool = True,
        required_claims: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Verify a Clerk JWT and return its claims.

        Args:
            token: The JWT to verify
            verify_exp: Whether to verify expiration (default True)
            required_claims: List of claim names that must be present

        Returns:
            Dict containing the verified JWT claims

        Raises:
            ClerkVerificationError: If verification fails
        """
        if not token:
            raise ClerkVerificationError("Token is required", error_code="missing_token")

        # Remove "Bearer " prefix if present
        if token.startswith("Bearer "):
            token = token[7:]

        try:
            # Get signing key from JWKS
            jwks_client = self._get_jwks_client()
            signing_key = jwks_client.get_signing_key_from_jwt(token)

            # Decode and verify the JWT
            decode_options = {
                "verify_signature": True,
                "verify_exp": verify_exp,
                "verify_iat": True,
                "verify_nbf": True,
                "require": ["sub", "iss", "exp", "iat"],
            }

            # Add leeway for clock skew
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=self._clerk_issuer,
                audience=self._audience,
                options=decode_options,
                leeway=self.CLOCK_SKEW_SECONDS,
            )

            # Verify required claims if specified
            if required_claims:
                missing = [c for c in required_claims if c not in claims]
                if missing:
                    raise ClerkVerificationError(
                        f"Missing required claims: {missing}",
                        error_code="missing_claims",
                    )

            # Add verification metadata
            claims["verified_at"] = datetime.now(timezone.utc).isoformat()
            claims["token_type"] = "clerk_jwt"

            logger.debug(
                "Token verified successfully",
                extra={"sub": claims.get("sub"), "sid": claims.get("sid")},
            )

            return claims

        except ExpiredSignatureError:
            logger.warning("Token has expired")
            raise ClerkVerificationError("Token has expired", error_code="token_expired")

        except InvalidIssuerError:
            logger.warning("Invalid token issuer")
            raise ClerkVerificationError("Invalid token issuer", error_code="invalid_issuer")

        except InvalidAudienceError:
            logger.warning("Invalid token audience")
            raise ClerkVerificationError("Invalid token audience", error_code="invalid_audience")

        except PyJWKClientError as e:
            logger.error(f"JWKS client error: {e}")
            raise ClerkVerificationError(
                f"Failed to fetch signing key: {e}",
                error_code="jwks_error",
            )

        except InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            raise ClerkVerificationError(f"Invalid token: {e}", error_code="invalid_token")

        except Exception as e:
            logger.error(f"Unexpected verification error: {e}")
            raise ClerkVerificationError(
                f"Token verification failed: {e}",
                error_code="verification_error",
            )

    def verify_session_token(self, token: str) -> Dict[str, Any]:
        """
        Verify a Clerk session token (requires session_id claim).

        Args:
            token: The session JWT to verify

        Returns:
            Dict containing verified claims with session_id

        Raises:
            ClerkVerificationError: If verification fails or session_id missing
        """
        claims = self.verify_token(token, required_claims=["sid"])
        return claims

    def get_clerk_user_id(self, token: str) -> str:
        """
        Extract clerk_user_id (sub claim) from a verified token.

        Args:
            token: The JWT to verify and extract user ID from

        Returns:
            The clerk_user_id from the sub claim

        Raises:
            ClerkVerificationError: If verification fails
        """
        claims = self.verify_token(token)
        return claims["sub"]

    def get_session_id(self, token: str) -> Optional[str]:
        """
        Extract session_id from a verified token.

        Args:
            token: The JWT to verify and extract session ID from

        Returns:
            The session_id (sid claim) or None if not present

        Raises:
            ClerkVerificationError: If verification fails
        """
        claims = self.verify_token(token)
        return claims.get("sid")

    def get_organization_context(self, token: str) -> Optional[Dict[str, str]]:
        """
        Extract organization context from a verified token.

        Args:
            token: The JWT to verify

        Returns:
            Dict with org_id, org_role, org_slug if present, None otherwise
        """
        claims = self.verify_token(token)

        if "org_id" in claims:
            return {
                "org_id": claims["org_id"],
                "org_role": claims.get("org_role"),
                "org_slug": claims.get("org_slug"),
            }
        return None

    def refresh_jwks(self) -> None:
        """
        Force refresh the JWKS cache.

        Useful when rotating keys or debugging.
        """
        with self._jwks_client_lock:
            self._jwks_client = None
            self._jwks_last_refresh = 0
        logger.info("JWKS cache cleared, will refresh on next verification")


# Singleton verifier instance (lazy initialization)
_verifier_instance: Optional[ClerkJWTVerifier] = None
_verifier_lock = Lock()


def get_verifier() -> ClerkJWTVerifier:
    """
    Get the singleton ClerkJWTVerifier instance.

    Returns:
        ClerkJWTVerifier instance

    Raises:
        ClerkVerificationError: If configuration is invalid
    """
    global _verifier_instance

    with _verifier_lock:
        if _verifier_instance is None:
            _verifier_instance = ClerkJWTVerifier()
        return _verifier_instance


def verify_clerk_token(token: str) -> Dict[str, Any]:
    """
    Convenience function to verify a Clerk token.

    Args:
        token: The JWT to verify

    Returns:
        Dict containing verified claims

    Raises:
        ClerkVerificationError: If verification fails
    """
    return get_verifier().verify_token(token)
