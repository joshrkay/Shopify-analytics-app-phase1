"""
OAuth service for Shopify app installation flow.

Handles:
- Shop domain validation
- OAuth state management (CSRF protection)
- HMAC verification
- Token exchange
- Store creation/update
- Tenant ID derivation
"""

import os
import re
import secrets
import hashlib
import hmac
import base64
import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode, urlparse

import httpx
from sqlalchemy.orm import Session

from src.models.oauth_state import OAuthState
from src.models.store import ShopifyStore, StoreStatus
from src.platform.secrets import encrypt_secret
from src.platform.audit import AuditAction, log_system_audit_event_sync

logger = logging.getLogger(__name__)

# Shopify shop domain validation regex
SHOP_DOMAIN_REGEX = re.compile(r"^[a-z0-9][a-z0-9\-]*\.myshopify\.com$")


class OAuthError(Exception):
    """Base exception for OAuth errors."""
    pass


class InvalidShopDomainError(OAuthError):
    """Raised when shop domain format is invalid."""
    pass


class InvalidStateError(OAuthError):
    """Raised when OAuth state is invalid, expired, or already used."""
    pass


class HMACVerificationError(OAuthError):
    """Raised when HMAC signature verification fails."""
    pass


class TokenExchangeError(OAuthError):
    """Raised when token exchange with Shopify fails."""
    pass


class OAuthService:
    """Service for handling Shopify OAuth installation flow."""
    
    def __init__(self):
        self.api_key = os.getenv("SHOPIFY_API_KEY")
        self.api_secret = os.getenv("SHOPIFY_API_SECRET")
        self.app_handle = os.getenv("SHOPIFY_APP_HANDLE", "signals-ai")
        self.app_url = os.getenv("APP_URL", os.getenv("application_url", ""))
        self.scopes = os.getenv("SHOPIFY_SCOPES", "read_orders,read_products,read_customers,read_analytics")
        
        if not self.api_key:
            raise ValueError("SHOPIFY_API_KEY environment variable is required")
        if not self.api_secret:
            raise ValueError("SHOPIFY_API_SECRET environment variable is required")
        if not self.app_url:
            raise ValueError("APP_URL environment variable is required")
    
    def validate_shop_domain(self, shop: str) -> bool:
        """
        Validate Shopify shop domain format.
        
        Args:
            shop: Shop domain (e.g., "mystore.myshopify.com")
            
        Returns:
            True if valid, False otherwise
        """
        if not shop:
            return False
        
        # Normalize: remove protocol and trailing slash
        shop = shop.replace("https://", "").replace("http://", "").rstrip("/")
        
        return bool(SHOP_DOMAIN_REGEX.match(shop.lower()))
    
    def create_authorization_url(
        self,
        shop: str,
        session: Session,
        redirect_uri: Optional[str] = None
    ) -> str:
        """
        Create Shopify OAuth authorization URL with state/nonce.
        
        Args:
            shop: Shop domain
            session: Database session
            redirect_uri: Optional custom redirect URI
            
        Returns:
            OAuth authorization URL
            
        Raises:
            InvalidShopDomainError: If shop domain is invalid
        """
        if not self.validate_shop_domain(shop):
            raise InvalidShopDomainError(f"Invalid shop domain: {shop}")
        
        # Normalize shop domain
        shop = shop.replace("https://", "").replace("http://", "").rstrip("/").lower()
        
        # Generate cryptographically secure state and nonce
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        
        # Default redirect URI
        if not redirect_uri:
            redirect_uri = f"{self.app_url.rstrip('/')}/api/auth/callback"
        
        # Store state in database with 10-minute TTL
        oauth_state = OAuthState(
            id=str(secrets.token_urlsafe(16)),
            shop_domain=shop,
            state=state,
            nonce=nonce,
            scopes=self.scopes,
            redirect_uri=redirect_uri,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)
        )
        
        session.add(oauth_state)
        session.commit()
        
        logger.info("Created OAuth state", extra={
            "shop_domain": shop,
            "state_id": oauth_state.id
        })
        
        # Build authorization URL
        params = {
            "client_id": self.api_key,
            "scope": self.scopes,
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": nonce
        }
        
        auth_url = f"https://{shop}/admin/oauth/authorize?{urlencode(params)}"
        return auth_url
    
    def verify_callback_hmac(self, params: dict) -> bool:
        """
        Verify Shopify OAuth callback HMAC signature.
        
        Shopify signs OAuth callbacks using HMAC-SHA256 with the API secret.
        The signature is computed over a sorted query string.
        
        Args:
            params: Query parameters from callback (must include 'hmac')
            
        Returns:
            True if HMAC is valid, False otherwise
        """
        if "hmac" not in params:
            return False
        
        hmac_value = params.pop("hmac")
        
        # Sort parameters and create query string
        sorted_params = sorted(params.items())
        query_string = "&".join([f"{k}={v}" for k, v in sorted_params])
        
        # Compute HMAC
        computed_hmac = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        )
        computed_digest = base64.b64encode(computed_hmac.digest()).decode("utf-8")
        
        # Constant-time comparison
        return hmac.compare_digest(computed_digest, hmac_value)
    
    def validate_state(
        self,
        state: str,
        shop: str,
        session: Session
    ) -> OAuthState:
        """
        Validate OAuth state exists, not expired, and not used.
        
        Args:
            state: State parameter from callback
            shop: Shop domain
            session: Database session
            
        Returns:
            OAuthState instance
            
        Raises:
            InvalidStateError: If state is invalid, expired, or used
        """
        # Normalize shop domain
        shop = shop.replace("https://", "").replace("http://", "").rstrip("/").lower()
        
        # Find state
        oauth_state = session.query(OAuthState).filter(
            OAuthState.state == state,
            OAuthState.shop_domain == shop
        ).first()
        
        if not oauth_state:
            raise InvalidStateError("OAuth state not found")
        
        if oauth_state.is_expired:
            raise InvalidStateError("OAuth state has expired")
        
        if oauth_state.is_used:
            raise InvalidStateError("OAuth state has already been used")
        
        return oauth_state
    
    async def exchange_code_for_token(self, shop: str, code: str) -> dict:
        """
        Exchange OAuth authorization code for access token.
        
        Args:
            shop: Shop domain
            code: Authorization code from callback
            
        Returns:
            Token response dict with access_token, scope, etc.
            
        Raises:
            TokenExchangeError: If exchange fails
        """
        # Normalize shop domain
        shop = shop.replace("https://", "").replace("http://", "").rstrip("/").lower()
        
        url = f"https://{shop}/admin/oauth/access_token"
        
        payload = {
            "client_id": self.api_key,
            "client_secret": self.api_secret,
            "code": code
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                
                token_data = response.json()
                
                if "access_token" not in token_data:
                    raise TokenExchangeError("Token response missing access_token")
                
                logger.info("Token exchange successful", extra={
                    "shop_domain": shop
                })
                
                return token_data
                
        except httpx.HTTPStatusError as e:
            logger.error("Token exchange failed", extra={
                "shop_domain": shop,
                "status_code": e.response.status_code,
                "response_text": e.response.text[:500]
            })
            raise TokenExchangeError(f"Token exchange failed: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error("Token exchange request error", extra={
                "shop_domain": shop,
                "error": str(e)
            })
            raise TokenExchangeError(f"Token exchange request error: {e}")
    
    def _derive_tenant_id(self, shop_domain: str) -> str:
        """
        Derive tenant_id from shop domain deterministically.
        
        Each Shopify shop maps to a unique tenant_id via SHA256 hash.
        This ensures:
        - Same shop always maps to same tenant
        - No external API calls needed
        - Consistent across reinstalls
        
        Args:
            shop_domain: Shop domain (e.g., "mystore.myshopify.com")
            
        Returns:
            32-character hex string (first 32 chars of SHA256 hash)
        """
        # Normalize shop domain
        shop_domain = shop_domain.replace("https://", "").replace("http://", "").rstrip("/").lower()
        
        # Hash with prefix to namespace Shopify tenants
        hash_input = f"shopify:{shop_domain}".encode()
        hash_digest = hashlib.sha256(hash_input).hexdigest()
        
        # Return first 32 characters (128 bits of entropy)
        return hash_digest[:32]
    
    async def _create_or_update_store(
        self,
        shop_domain: str,
        access_token: str,
        scopes: str,
        session: Session
    ) -> ShopifyStore:
        """
        Create or update ShopifyStore record.
        
        For new installs: creates new store with derived tenant_id.
        For reinstalls: updates existing store, preserving tenant_id.
        
        Args:
            shop_domain: Shop domain
            access_token: Decrypted access token (will be encrypted)
            scopes: Granted OAuth scopes
            session: Database session
            
        Returns:
            ShopifyStore instance
        """
        # Normalize shop domain
        shop_domain = shop_domain.replace("https://", "").replace("http://", "").rstrip("/").lower()
        
        # Derive tenant_id
        tenant_id = self._derive_tenant_id(shop_domain)
        
        # Encrypt access token
        access_token_encrypted = await encrypt_secret(access_token)
        
        # Check if store exists
        existing_store = session.query(ShopifyStore).filter(
            ShopifyStore.shop_domain == shop_domain
        ).first()
        
        if existing_store:
            # Reinstall: update existing store, preserve tenant_id
            logger.info("Updating existing store (reinstall)", extra={
                "shop_domain": shop_domain,
                "tenant_id": existing_store.tenant_id
            })
            
            existing_store.access_token_encrypted = access_token_encrypted
            existing_store.scopes = scopes
            existing_store.status = StoreStatus.ACTIVE.value
            existing_store.installed_at = datetime.now(timezone.utc)
            existing_store.uninstalled_at = None
            
            # CRITICAL: Preserve tenant_id for data continuity
            # Do not update tenant_id even if it differs (shouldn't happen)
            
            session.commit()
            
            # Log audit event for reinstall
            log_system_audit_event_sync(
                db=session,
                tenant_id=existing_store.tenant_id,
                action=AuditAction.APP_INSTALLED,
                resource_type="store",
                resource_id=existing_store.id,
                metadata={
                    "shop_domain": shop_domain,
                    "is_reinstall": True,
                    "scopes": scopes
                }
            )
            
            return existing_store
        else:
            # New install: create store
            logger.info("Creating new store", extra={
                "shop_domain": shop_domain,
                "tenant_id": tenant_id
            })
            
            new_store = ShopifyStore(
                shop_domain=shop_domain,
                tenant_id=tenant_id,  # Derived from shop_domain
                access_token_encrypted=access_token_encrypted,
                scopes=scopes,
                status=StoreStatus.ACTIVE.value,
                installed_at=datetime.now(timezone.utc)
            )
            
            session.add(new_store)
            session.commit()
            
            # Log audit event for new install
            log_system_audit_event_sync(
                db=session,
                tenant_id=tenant_id,
                action=AuditAction.APP_INSTALLED,
                resource_type="store",
                resource_id=new_store.id,
                metadata={
                    "shop_domain": shop_domain,
                    "is_reinstall": False,
                    "scopes": scopes
                }
            )
            
            return new_store
    
    async def complete_oauth(
        self,
        shop: str,
        code: str,
        state: str,
        params: dict,
        session: Session
    ) -> ShopifyStore:
        """
        Complete OAuth flow: verify, exchange token, create/update store.
        
        Args:
            shop: Shop domain
            code: Authorization code
            state: State parameter
            params: All callback parameters (for HMAC verification)
            session: Database session
            
        Returns:
            ShopifyStore instance
            
        Raises:
            HMACVerificationError: If HMAC verification fails
            InvalidStateError: If state validation fails
            TokenExchangeError: If token exchange fails
        """
        # Verify HMAC
        if not self.verify_callback_hmac(params.copy()):
            raise HMACVerificationError("Invalid HMAC signature")
        
        # Validate state
        oauth_state = self.validate_state(state, shop, session)
        
        # Check if store already exists (to determine if this is a reinstall)
        # Do this BEFORE marking state as used and creating/updating store
        from src.models.store import ShopifyStore
        existing_store = session.query(ShopifyStore).filter(
            ShopifyStore.shop_domain == shop.replace("https://", "").replace("http://", "").rstrip("/").lower()
        ).first()
        is_reinstall = existing_store is not None
        
        # Mark state as used
        oauth_state.used_at = datetime.now(timezone.utc)
        session.commit()
        
        # Exchange code for token
        token_data = await self.exchange_code_for_token(shop, code)
        
        # Create or update store
        store = await self._create_or_update_store(
            shop_domain=shop,
            access_token=token_data["access_token"],
            scopes=token_data.get("scope", self.scopes),
            session=session
        )
        
        logger.info("OAuth flow completed", extra={
            "shop_domain": shop,
            "tenant_id": store.tenant_id,
            "is_reinstall": is_reinstall
        })
        
        return store
