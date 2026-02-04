"""
Authentication module for Clerk-based authentication.

This module provides:
- JWT verification using Clerk's JWKS
- Authentication middleware for FastAPI
- User context resolution and mapping
- Session/token management

SECURITY NOTES:
- Clerk is the ONLY authentication authority
- NO custom tokens are issued by this application
- All JWTs must be verified against Clerk's JWKS
- clerk_user_id maps to internal User records for authorization
"""

from src.auth.clerk_verifier import ClerkJWTVerifier, ClerkVerificationError
from src.auth.jwt import ClerkJWTClaims, extract_claims
from src.auth.context_resolver import AuthContext, resolve_auth_context
from src.auth.token_service import TokenService, SessionInfo
from src.auth.middleware import ClerkAuthMiddleware, require_auth, get_current_user

__all__ = [
    # Verifier
    "ClerkJWTVerifier",
    "ClerkVerificationError",
    # JWT Claims
    "ClerkJWTClaims",
    "extract_claims",
    # Context
    "AuthContext",
    "resolve_auth_context",
    # Token Service
    "TokenService",
    "SessionInfo",
    # Middleware
    "ClerkAuthMiddleware",
    "require_auth",
    "get_current_user",
]
