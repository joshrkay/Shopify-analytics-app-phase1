"""
Shopify session token authentication for embedded apps.

Shopify embedded apps use session tokens (JWTs) signed by Shopify with the app's API secret.
These tokens are used instead of cookies for authentication in embedded contexts.

Documentation: https://shopify.dev/docs/apps/auth/oauth/session-tokens
"""

import os
import hashlib
import logging
from typing import Optional
from dataclasses import dataclass

import jwt
from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# Security scheme for extracting Bearer token
security = HTTPBearer(auto_error=False)


@dataclass
class ShopifySessionContext:
    """Context extracted from Shopify session token."""
    shop_domain: str
    shop_id: str
    user_id: Optional[str]
    tenant_id: str  # Derived from shop_domain


class ShopifySessionTokenVerifier:
    """
    Verifies Shopify session tokens (JWTs).
    
    Session tokens are signed with HS256 using the app's API secret.
    """
    
    def __init__(self):
        self.api_key = os.getenv("SHOPIFY_API_KEY")
        self.api_secret = os.getenv("SHOPIFY_API_SECRET")
        
        if not self.api_key:
            raise ValueError("SHOPIFY_API_KEY environment variable is required")
        if not self.api_secret:
            raise ValueError("SHOPIFY_API_SECRET environment variable is required")
    
    def _derive_tenant_id(self, shop_domain: str) -> str:
        """
        Derive tenant_id from shop domain deterministically.
        
        Same logic as OAuthService to ensure consistency.
        
        Args:
            shop_domain: Shop domain (e.g., "mystore.myshopify.com")
            
        Returns:
            32-character hex string
        """
        # Normalize shop domain
        shop_domain = shop_domain.replace("https://", "").replace("http://", "").rstrip("/").lower()
        
        # Hash with prefix to namespace Shopify tenants
        hash_input = f"shopify:{shop_domain}".encode()
        hash_digest = hashlib.sha256(hash_input).hexdigest()
        
        # Return first 32 characters
        return hash_digest[:32]
    
    def verify_session_token(self, token: str) -> ShopifySessionContext:
        """
        Verify Shopify session token and extract context.
        
        Args:
            token: JWT session token from Shopify
            
        Returns:
            ShopifySessionContext with shop and tenant information
            
        Raises:
            HTTPException: If token is invalid, expired, or verification fails
        """
        try:
            # Decode and verify JWT
            # Shopify signs with HS256 using API secret
            payload = jwt.decode(
                token,
                self.api_secret,
                algorithms=["HS256"],
                audience=self.api_key,  # Verify 'aud' claim matches API key
                options={
                    "verify_signature": True,
                    "verify_aud": True,
                    "verify_exp": True,
                    "verify_iat": False,  # iat is optional
                }
            )
            
            # Extract shop domain from 'dest' claim
            # 'dest' contains the shop domain (e.g., "https://mystore.myshopify.com")
            dest = payload.get("dest")
            if not dest:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session token missing 'dest' claim"
                )
            
            # Parse shop domain from dest URL
            # Format: "https://mystore.myshopify.com" or "mystore.myshopify.com"
            shop_domain = dest.replace("https://", "").replace("http://", "").rstrip("/").lower()
            
            # Extract shop_id from 'iss' claim
            # Format: "https://mystore.myshopify.com/admin" -> extract shop from URL
            iss = payload.get("iss", "")
            shop_id = ""
            if iss:
                # Extract shop ID from issuer URL if available
                # For now, we'll use shop_domain as shop_id identifier
                shop_id = shop_domain
            
            # Extract user_id from 'sub' claim (optional)
            user_id = payload.get("sub")
            
            # Derive tenant_id from shop_domain
            tenant_id = self._derive_tenant_id(shop_domain)
            
            logger.debug("Session token verified", extra={
                "shop_domain": shop_domain,
                "tenant_id": tenant_id
            })
            
            return ShopifySessionContext(
                shop_domain=shop_domain,
                shop_id=shop_id,
                user_id=user_id,
                tenant_id=tenant_id
            )
            
        except jwt.ExpiredSignatureError:
            logger.warning("Session token expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session token has expired"
            )
        except jwt.InvalidAudienceError:
            logger.warning("Session token invalid audience", extra={
                "expected": self.api_key
            })
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session token has invalid audience"
            )
        except jwt.InvalidSignatureError:
            logger.warning("Session token invalid signature")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session token signature is invalid"
            )
        except jwt.DecodeError as e:
            logger.warning("Session token decode error", extra={"error": str(e)})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session token is malformed"
            )
        except Exception as e:
            logger.error("Session token verification error", extra={"error": str(e)})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session token verification failed"
            )


# Singleton verifier instance
_verifier = None


def get_session_token_verifier() -> Optional[ShopifySessionTokenVerifier]:
    """
    Get singleton session token verifier.
    
    Returns None if Shopify API credentials are not configured.
    This allows the middleware to gracefully fall back to Frontegg JWT.
    """
    global _verifier
    if _verifier is None:
        # Check if credentials are available before initializing
        api_key = os.getenv("SHOPIFY_API_KEY")
        api_secret = os.getenv("SHOPIFY_API_SECRET")
        
        if not api_key or not api_secret:
            # Not configured - return None (middleware will fall back to Frontegg JWT)
            return None
        
        try:
            _verifier = ShopifySessionTokenVerifier()
        except ValueError:
            # Initialization failed - return None
            return None
    
    return _verifier


async def get_shopify_session(request: Request) -> ShopifySessionContext:
    """
    FastAPI dependency to extract and verify Shopify session token.
    
    Usage:
        @router.get("/api/shopify/data")
        async def get_data(session: ShopifySessionContext = Depends(get_shopify_session)):
            # Use session.shop_domain, session.tenant_id, etc.
    
    Args:
        request: FastAPI request
        
    Returns:
        ShopifySessionContext
        
    Raises:
        HTTPException: If token is missing or invalid
    """
    # Extract Bearer token
    credentials: Optional[HTTPAuthorizationCredentials] = await security(request)
    
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization token"
        )
    
    token = credentials.credentials
    
    # Verify token
    verifier = get_session_token_verifier()
    return verifier.verify_session_token(token)
