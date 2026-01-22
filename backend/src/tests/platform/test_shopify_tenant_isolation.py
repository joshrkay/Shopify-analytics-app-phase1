"""
Platform gate tests for Shopify tenant isolation.

CRITICAL: These tests verify that Shopify shops cannot access each other's data.
This is a quality gate test that MUST pass before deployment.

Rule 2: "Add tests for every new entity proving tenant isolation."
Rule 11: "platform tests (tenant isolation, RBAC, secrets redaction) are mandatory"
"""

import pytest
import jwt
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.platform.tenant_context import TenantContextMiddleware, get_tenant_context
from src.platform.shopify_session import ShopifySessionContext


def create_shopify_token(shop_domain: str, api_key: str, api_secret: str) -> str:
    """Create a valid Shopify session token for testing."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=1)
    
    payload = {
        "iss": f"https://{shop_domain}/admin",
        "dest": f"https://{shop_domain}",
        "aud": api_key,
        "sub": "test-user-id",
        "exp": int(exp.timestamp()),
        "nbf": int(now.timestamp()),
        "iat": int(now.timestamp()),
        "jti": "test-jti",
        "sid": "test-session-id"
    }
    
    return jwt.encode(payload, api_secret, algorithm="HS256")


@pytest.fixture
def app_with_shopify_auth(monkeypatch):
    """Create FastAPI app with dual auth middleware."""
    monkeypatch.setenv("SHOPIFY_API_KEY", "test-api-key")
    monkeypatch.setenv("SHOPIFY_API_SECRET", "test-api-secret")
    monkeypatch.setenv("FRONTEGG_CLIENT_ID", "test-client-id")
    
    # Reset singleton verifier to ensure fresh state
    import src.platform.shopify_session
    src.platform.shopify_session._verifier = None
    
    app = FastAPI()
    
    # Add middleware
    middleware = TenantContextMiddleware()
    app.middleware("http")(middleware)
    
    @app.get("/health")
    async def health():
        return {"status": "ok"}
    
    @app.get("/api/shopify/data")
    async def get_shopify_data(request: Request):
        """Test endpoint that requires tenant context."""
        tenant_ctx = get_tenant_context(request)
        return {
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
            "data": f"data-for-{tenant_ctx.tenant_id}",
            "auth_type": "shopify"
        }
    
    @app.post("/api/shopify/data")
    async def create_shopify_data(request: Request):
        """Test endpoint for creating data."""
        tenant_ctx = get_tenant_context(request)
        body = await request.json()
        
        # CRITICAL: tenant_id from body should be ignored
        return {
            "tenant_id": tenant_ctx.tenant_id,  # Always from session token
            "created": True,
            "body_tenant_id": body.get("tenant_id", "not-provided")
        }
    
    return app


class TestShopifyTenantIsolation:
    """
    CRITICAL QUALITY GATE: Verify Shopify shops cannot access each other's data.
    
    This test MUST pass - cross-tenant access is a critical security violation.
    """
    
    def test_shop_a_cannot_access_shop_b_data(
        self, app_with_shopify_auth
    ):
        """
        QUALITY GATE: Shop A cannot access Shop B's data via session tokens.
        
        Each Shopify shop gets its own tenant_id derived from shop_domain.
        Shops must be completely isolated from each other.
        """
        client = TestClient(app_with_shopify_auth)
        
        # Create tokens for two different shops
        shop_a_token = create_shopify_token(
            "store-a.myshopify.com",
            "test-api-key",
            "test-api-secret"
        )
        shop_b_token = create_shopify_token(
            "store-b.myshopify.com",
            "test-api-key",
            "test-api-secret"
        )
        
        # Shop A makes request
        response_a = client.get(
            "/api/shopify/data",
            headers={"Authorization": f"Bearer {shop_a_token}"}
        )
        
        assert response_a.status_code == 200
        data_a = response_a.json()
        tenant_id_a = data_a["tenant_id"]
        
        # Shop B makes request
        response_b = client.get(
            "/api/shopify/data",
            headers={"Authorization": f"Bearer {shop_b_token}"}
        )
        
        assert response_b.status_code == 200
        data_b = response_b.json()
        tenant_id_b = data_b["tenant_id"]
        
        # CRITICAL: Tenant IDs must be different
        assert tenant_id_a != tenant_id_b, (
            f"Tenant isolation violation: Shop A and Shop B have same tenant_id: {tenant_id_a}"
        )
        
        # Verify tenant_id derivation is deterministic
        expected_tenant_id_a = hashlib.sha256(
            "shopify:store-a.myshopify.com".encode()
        ).hexdigest()[:32]
        expected_tenant_id_b = hashlib.sha256(
            "shopify:store-b.myshopify.com".encode()
        ).hexdigest()[:32]
        
        assert tenant_id_a == expected_tenant_id_a
        assert tenant_id_b == expected_tenant_id_b
    
    def test_shop_cannot_override_tenant_id_in_body(
        self, app_with_shopify_auth
    ):
        """
        QUALITY GATE: Shop cannot override tenant_id via request body.
        
        tenant_id MUST come from session token, never from client input.
        """
        client = TestClient(app_with_shopify_auth)
        
        shop_token = create_shopify_token(
            "store-a.myshopify.com",
            "test-api-key",
            "test-api-secret"
        )
        
        # Try to send different tenant_id in body
        response = client.post(
            "/api/shopify/data",
            headers={"Authorization": f"Bearer {shop_token}"},
            json={"tenant_id": "malicious-tenant-id", "data": "test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # CRITICAL: tenant_id from body must be ignored
        expected_tenant_id = hashlib.sha256(
            "shopify:store-a.myshopify.com".encode()
        ).hexdigest()[:32]
        
        assert data["tenant_id"] == expected_tenant_id
        assert data["body_tenant_id"] == "malicious-tenant-id"  # Logged but ignored
    
    def test_same_shop_gets_same_tenant_id(
        self, app_with_shopify_auth
    ):
        """
        QUALITY GATE: Same shop always gets same tenant_id (deterministic).
        
        This ensures data continuity across reinstalls.
        """
        client = TestClient(app_with_shopify_auth)
        
        shop_domain = "store-a.myshopify.com"
        
        # Create two tokens for the same shop (different sessions)
        token1 = create_shopify_token(shop_domain, "test-api-key", "test-api-secret")
        token2 = create_shopify_token(shop_domain, "test-api-key", "test-api-secret")
        
        # Make requests with different tokens
        response1 = client.get(
            "/api/shopify/data",
            headers={"Authorization": f"Bearer {token1}"}
        )
        response2 = client.get(
            "/api/shopify/data",
            headers={"Authorization": f"Bearer {token2}"}
        )
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        tenant_id1 = response1.json()["tenant_id"]
        tenant_id2 = response2.json()["tenant_id"]
        
        # CRITICAL: Same shop must get same tenant_id
        assert tenant_id1 == tenant_id2, (
            f"Tenant ID not deterministic: {tenant_id1} != {tenant_id2}"
        )
        
        # Verify it matches expected derivation
        expected_tenant_id = hashlib.sha256(
            f"shopify:{shop_domain}".encode()
        ).hexdigest()[:32]
        
        assert tenant_id1 == expected_tenant_id
        assert tenant_id2 == expected_tenant_id
    
    def test_shopify_and_frontegg_tenants_isolated(
        self, app_with_shopify_auth
    ):
        """
        QUALITY GATE: Shopify shops and Frontegg tenants are separate tenant spaces.
        
        A Shopify shop tenant_id should never match a Frontegg org_id tenant_id.
        """
        # Reset singleton verifier to ensure fresh state
        from src.platform.shopify_session import _verifier
        import src.platform.shopify_session
        src.platform.shopify_session._verifier = None
        
        client = TestClient(app_with_shopify_auth)
        
        # Shopify shop token (valid)
        shop_token = create_shopify_token(
            "store-a.myshopify.com",
            "test-api-key",
            "test-api-secret"
        )
        
        # Frontegg JWT token (mocked) - use a different token string so it doesn't match Shopify
        frontegg_token = "frontegg-jwt-token-different-from-shopify"
        
        # Mock Frontegg JWT verification
        with patch('src.platform.tenant_context.jwt.decode') as mock_decode, \
             patch('src.platform.tenant_context.FronteggJWKSClient.get_signing_key') as mock_get_key:
            
            mock_signing_key = MagicMock()
            mock_signing_key.key = "mock-key"
            
            # Configure mock to only decode Frontegg token, not Shopify token
            def decode_side_effect(token, *args, **kwargs):
                if token == frontegg_token:
                    return {
                        "org_id": "frontegg-org-123",
                        "sub": "frontegg-user-1",
                        "roles": ["admin"],
                        "aud": "test-client-id",
                        "iss": "https://api.frontegg.com",
                        "exp": 9999999999,
                    }
                # For Shopify token, raise error so Frontegg verification fails
                # This ensures Shopify token uses Shopify verification, not Frontegg
                from jwt.exceptions import InvalidTokenError
                raise InvalidTokenError("Not a Frontegg token")
            
            mock_decode.side_effect = decode_side_effect
            
            # Also mock get_signing_key to only work for Frontegg token
            def get_key_side_effect(token):
                if token == frontegg_token:
                    return mock_signing_key
                # For Shopify token, raise error so Frontegg verification fails
                from jwt.exceptions import PyJWKClientError
                raise PyJWKClientError("Not a Frontegg token")
            
            mock_get_key.side_effect = get_key_side_effect
            
            # Shopify shop request (should use Shopify token verification)
            shop_response = client.get(
                "/api/shopify/data",
                headers={"Authorization": f"Bearer {shop_token}"}
            )
            
            # Frontegg request (should use Frontegg JWT verification)
            frontegg_response = client.get(
                "/api/shopify/data",
                headers={"Authorization": f"Bearer {frontegg_token}"}
            )
            
            assert shop_response.status_code == 200, f"Shopify request failed: {shop_response.text}"
            assert frontegg_response.status_code == 200, f"Frontegg request failed: {frontegg_response.text}"
            
            shop_tenant_id = shop_response.json()["tenant_id"]
            frontegg_tenant_id = frontegg_response.json()["tenant_id"]
            
            # CRITICAL: They must be different (separate tenant spaces)
            assert shop_tenant_id != frontegg_tenant_id, (
                f"Tenant isolation violation: Shopify shop and Frontegg org have same tenant_id: {shop_tenant_id}"
            )
