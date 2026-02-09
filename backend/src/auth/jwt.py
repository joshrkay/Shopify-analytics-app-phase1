"""
JWT claims handling for Clerk-issued tokens.

This module provides:
- Pydantic models for Clerk JWT claims
- Claim extraction utilities
- Type-safe access to JWT data

IMPORTANT: Clerk is the authentication authority.
This module does NOT issue tokens - it only handles Clerk-issued JWTs.

JWT Claims Used:
- sub: clerk_user_id (unique user identifier)
- exp: Expiration timestamp
- iat: Issued at timestamp
- sid: Session ID (for session-based auth)
- org_id: Organization ID (for org context)
- org_role: Organization role
- org_slug: Organization slug
- azp: Authorized party (client ID)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, FrozenSet
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClerkOrgRole(str, Enum):
    """
    Clerk organization roles.

    These are the standard roles in Clerk's organization model.
    They are mapped to application roles in context_resolver.py.
    """
    ADMIN = "org:admin"
    MEMBER = "org:member"
    BILLING = "org:billing"
    OWNER = "org:owner"


class ClerkJWTClaims(BaseModel):
    """
    Pydantic model for Clerk JWT claims.

    Standard claims from Clerk JWTs:
    - sub: User ID (clerk_user_id)
    - iss: Issuer URL
    - exp: Expiration timestamp
    - iat: Issued at timestamp
    - nbf: Not before timestamp (optional)
    - sid: Session ID
    - azp: Authorized party (client ID)

    Organization claims (when user is in org context):
    - org_id: Organization ID
    - org_role: Organization role
    - org_slug: Organization slug
    - org_permissions: Organization permissions (optional)
    """

    # Required standard claims
    sub: str = Field(..., description="Clerk user ID (clerk_user_id)")
    iss: str = Field(..., description="Token issuer URL")
    exp: int = Field(..., description="Expiration timestamp (Unix)")
    iat: int = Field(..., description="Issued at timestamp (Unix)")

    # Optional standard claims
    nbf: Optional[int] = Field(None, description="Not before timestamp (Unix)")
    sid: Optional[str] = Field(None, description="Session ID")
    azp: Optional[str] = Field(None, description="Authorized party (client ID)")
    jti: Optional[str] = Field(None, description="JWT ID (unique identifier)")

    # Organization context claims
    org_id: Optional[str] = Field(None, description="Clerk organization ID")
    org_role: Optional[str] = Field(None, description="User's role in the organization")
    org_slug: Optional[str] = Field(None, description="Organization slug")
    org_permissions: Optional[List[str]] = Field(
        None, description="Organization permissions"
    )

    # Custom claims (Clerk allows custom claims via metadata)
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Custom metadata from Clerk"
    )

    # Verification metadata (added by verifier)
    verified_at: Optional[str] = Field(None, description="Timestamp when token was verified")
    token_type: Optional[str] = Field(None, description="Type of token (e.g., clerk_jwt)")

    model_config = ConfigDict(extra="allow")

    @property
    def clerk_user_id(self) -> str:
        """Get the Clerk user ID (alias for sub claim)."""
        return self.sub

    @property
    def session_id(self) -> Optional[str]:
        """Get the session ID (alias for sid claim)."""
        return self.sid

    @property
    def expiration_datetime(self) -> datetime:
        """Get expiration as datetime."""
        return datetime.fromtimestamp(self.exp, tz=timezone.utc)

    @property
    def issued_at_datetime(self) -> datetime:
        """Get issued at as datetime."""
        return datetime.fromtimestamp(self.iat, tz=timezone.utc)

    @property
    def is_expired(self) -> bool:
        """Check if token is expired."""
        return datetime.now(timezone.utc) > self.expiration_datetime

    @property
    def has_org_context(self) -> bool:
        """Check if token has organization context."""
        return self.org_id is not None

    @property
    def is_org_admin(self) -> bool:
        """Check if user is organization admin."""
        return self.org_role in (ClerkOrgRole.ADMIN.value, ClerkOrgRole.OWNER.value)

    def get_org_context(self) -> Optional[Dict[str, Any]]:
        """Get organization context if present."""
        if not self.has_org_context:
            return None
        return {
            "org_id": self.org_id,
            "org_role": self.org_role,
            "org_slug": self.org_slug,
            "org_permissions": self.org_permissions,
        }


@dataclass(frozen=True)
class ExtractedClaims:
    """
    Immutable extracted claims for use in application logic.

    This provides a clean interface for accessing JWT claims
    with type safety and immutability.
    """

    clerk_user_id: str
    session_id: Optional[str]
    org_id: Optional[str]
    org_role: Optional[str]
    org_slug: Optional[str]
    issued_at: datetime
    expires_at: datetime
    azp: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_org_context(self) -> bool:
        """Check if claims have organization context."""
        return self.org_id is not None

    @property
    def is_expired(self) -> bool:
        """Check if token is expired."""
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def time_until_expiry(self) -> float:
        """Get seconds until token expires (negative if expired)."""
        return (self.expires_at - datetime.now(timezone.utc)).total_seconds()


def extract_claims(jwt_claims: Dict[str, Any]) -> ExtractedClaims:
    """
    Extract and normalize claims from a verified JWT.

    Args:
        jwt_claims: Raw claims dict from JWT verification

    Returns:
        ExtractedClaims with normalized claim values

    Raises:
        ValueError: If required claims are missing
    """
    # Validate required claims
    if "sub" not in jwt_claims:
        raise ValueError("Missing required claim: sub")
    if "exp" not in jwt_claims:
        raise ValueError("Missing required claim: exp")
    if "iat" not in jwt_claims:
        raise ValueError("Missing required claim: iat")

    # Extract timestamps
    try:
        expires_at = datetime.fromtimestamp(jwt_claims["exp"], tz=timezone.utc)
        issued_at = datetime.fromtimestamp(jwt_claims["iat"], tz=timezone.utc)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid timestamp in claims: {e}")

    # Build extracted claims
    return ExtractedClaims(
        clerk_user_id=jwt_claims["sub"],
        session_id=jwt_claims.get("sid"),
        org_id=jwt_claims.get("org_id"),
        org_role=jwt_claims.get("org_role"),
        org_slug=jwt_claims.get("org_slug"),
        issued_at=issued_at,
        expires_at=expires_at,
        azp=jwt_claims.get("azp"),
        metadata=jwt_claims.get("metadata", {}),
    )


def parse_clerk_claims(jwt_claims: Dict[str, Any]) -> ClerkJWTClaims:
    """
    Parse raw JWT claims into ClerkJWTClaims model.

    Args:
        jwt_claims: Raw claims dict from JWT verification

    Returns:
        ClerkJWTClaims model instance

    Raises:
        ValueError: If claims are invalid
    """
    try:
        return ClerkJWTClaims(**jwt_claims)
    except Exception as e:
        raise ValueError(f"Failed to parse JWT claims: {e}")


@dataclass
class TokenInfo:
    """
    Token information for logging and debugging.

    Contains non-sensitive information about a token.
    """

    clerk_user_id: str
    session_id: Optional[str]
    org_id: Optional[str]
    issued_at: datetime
    expires_at: datetime
    is_expired: bool
    time_until_expiry_seconds: float

    @classmethod
    def from_claims(cls, claims: ExtractedClaims) -> "TokenInfo":
        """Create TokenInfo from ExtractedClaims."""
        return cls(
            clerk_user_id=claims.clerk_user_id,
            session_id=claims.session_id,
            org_id=claims.org_id,
            issued_at=claims.issued_at,
            expires_at=claims.expires_at,
            is_expired=claims.is_expired,
            time_until_expiry_seconds=claims.time_until_expiry,
        )

    def to_log_dict(self) -> Dict[str, Any]:
        """Convert to dict suitable for logging (no sensitive data)."""
        return {
            "clerk_user_id": self.clerk_user_id[:20] + "..." if len(self.clerk_user_id) > 20 else self.clerk_user_id,
            "session_id": self.session_id[:10] + "..." if self.session_id and len(self.session_id) > 10 else self.session_id,
            "org_id": self.org_id,
            "is_expired": self.is_expired,
            "expires_in_seconds": int(self.time_until_expiry_seconds),
        }
