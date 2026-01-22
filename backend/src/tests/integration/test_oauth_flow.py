"""
Integration tests for Shopify OAuth installation flow.

Tests cover:
- Full OAuth install/callback flow
- Reinstall scenarios (tenant_id preservation)
- State management and expiration
- HMAC verification
"""

import os
import pytest
import hmac
import hashlib
import base64
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test environment
os.environ["ENV"] = "test"
os.environ["SHOPIFY_API_KEY"] = "test-api-key"
os.environ["SHOPIFY_API_SECRET"] = "test-api-secret"
os.environ["SHOPIFY_APP_HANDLE"] = "test-app"
os.environ["APP_URL"] = "https://test.example.com"
os.environ["SHOPIFY_SCOPES"] = "read_products,write_products"
os.environ["ENCRYPTION_KEY"] = "test-encryption-key-32-chars-long!"


@pytest.fixture
def db_engine():
    """Create in-memory SQLite database for testing."""
    from src.db_base import Base
    from src.models import oauth_state, store
    from src.platform.audit import AuditBase
    
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    AuditBase.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    AuditBase.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(db_engine):
    """Create database session."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def test_app(db_session):
    """Create FastAPI test app with dependency overrides."""
    from main import app
    from src.api.routes.auth import get_db_session
    
    def override_get_db_session():
        yield db_session
    
    app.dependency_overrides[get_db_session] = override_get_db_session
    
    yield app
    
    app.dependency_overrides.clear()


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


@pytest.fixture
def test_shop_domain():
    """Test shop domain."""
    return "test-store.myshopify.com"


class TestOAuthInstallFlow:
    """Test OAuth installation flow."""
    
    def test_install_route_valid_shop(self, client, test_shop_domain, db_session):
        """Test install route with valid shop domain."""
        response = client.get(f"/api/auth/install?shop={test_shop_domain}")
        
        assert response.status_code == 302  # Redirect
        assert "admin/oauth/authorize" in response.headers["location"]
        assert "client_id=test-api-key" in response.headers["location"]
        assert "state=" in response.headers["location"]
        
        # Verify state was created in database
        from src.models.oauth_state import OAuthState
        states = db_session.query(OAuthState).filter(
            OAuthState.shop_domain == test_shop_domain
        ).all()
        assert len(states) == 1
        assert states[0].state in response.headers["location"]
    
    def test_install_route_invalid_shop(self, client):
        """Test install route with invalid shop domain."""
        response = client.get("/api/auth/install?shop=invalid-shop")
        
        assert response.status_code == 400
        assert "Invalid Shop Domain" in response.text
    
    def test_install_route_missing_shop(self, client):
        """Test install route without shop parameter."""
        response = client.get("/api/auth/install")
        
        assert response.status_code == 422  # Validation error


class TestOAuthCallbackFlow:
    """Test OAuth callback flow."""
    
    def _create_oauth_state(self, db_session, shop_domain: str, state: str):
        """Helper to create OAuth state."""
        from src.models.oauth_state import OAuthState
        
        oauth_state = OAuthState(
            id=str(uuid.uuid4()),
            shop_domain=shop_domain,
            state=state,
            nonce="test-nonce",
            scopes="read_products,write_products",
            redirect_uri="https://test.example.com/api/auth/callback",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)
        )
        db_session.add(oauth_state)
        db_session.commit()
        return oauth_state
    
    def _compute_hmac(self, params: dict) -> str:
        """Helper to compute HMAC for callback parameters."""
        hmac_value = params.pop("hmac", None)
        sorted_params = sorted(params.items())
        query_string = "&".join([f"{k}={v}" for k, v in sorted_params])
        
        computed_hmac = hmac.new(
            "test-api-secret".encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        )
        return base64.b64encode(computed_hmac.digest()).decode("utf-8")
    
    @pytest.mark.asyncio
    async def test_callback_success_new_install(
        self, client, test_shop_domain, db_session
    ):
        """Test successful callback for new installation."""
        state = "test-state-123"
        self._create_oauth_state(db_session, test_shop_domain, state)
        
        params = {
            "code": "test-auth-code",
            "state": state,
            "shop": test_shop_domain,
            "timestamp": "1234567890"
        }
        params["hmac"] = self._compute_hmac(params.copy())
        
        # Mock token exchange
        mock_token_response = {
            "access_token": "test-access-token",
            "scope": "read_products,write_products"
        }
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock()
            mock_post.raise_for_status = AsyncMock()
            mock_post.json.return_value = mock_token_response
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_post
            )
            
            response = client.get("/api/auth/callback", params=params)
            
            # Should redirect to embedded app
            assert response.status_code == 302
            assert test_shop_domain in response.headers["location"]
            assert "admin/apps/test-app" in response.headers["location"]
            
            # Verify store was created
            from src.models.store import ShopifyStore
            store = db_session.query(ShopifyStore).filter(
                ShopifyStore.shop_domain == test_shop_domain
            ).first()
            
            assert store is not None
            assert store.status == "active"
            assert store.access_token_encrypted is not None
            assert store.installed_at is not None
            
            # Verify audit log was created
            from src.platform.audit import AuditLog, AuditAction
            audit_logs = db_session.query(AuditLog).filter(
                AuditLog.tenant_id == store.tenant_id,
                AuditLog.action == AuditAction.APP_INSTALLED.value
            ).all()
            assert len(audit_logs) == 1
            assert audit_logs[0].resource_type == "store"
            assert audit_logs[0].resource_id == store.id
            assert audit_logs[0].event_metadata["is_reinstall"] is False
            assert audit_logs[0].event_metadata["shop_domain"] == test_shop_domain
            assert audit_logs[0].user_id == "system"
    
    @pytest.mark.asyncio
    async def test_callback_success_reinstall(
        self, client, test_shop_domain, db_session
    ):
        """Test successful callback for reinstall (preserves tenant_id)."""
        state = "test-state-reinstall"
        self._create_oauth_state(db_session, test_shop_domain, state)
        
        # Create existing store (simulating previous install)
        from src.models.store import ShopifyStore
        import hashlib
        
        original_tenant_id = hashlib.sha256(
            f"shopify:{test_shop_domain}".encode()
        ).hexdigest()[:32]
        
        existing_store = ShopifyStore(
            id=str(uuid.uuid4()),
            shop_domain=test_shop_domain,
            tenant_id=original_tenant_id,
            access_token_encrypted="old-encrypted-token",
            scopes="old-scopes",
            status="uninstalled",
            uninstalled_at=datetime.now(timezone.utc) - timedelta(days=1)
        )
        db_session.add(existing_store)
        db_session.commit()
        
        params = {
            "code": "test-auth-code",
            "state": state,
            "shop": test_shop_domain,
            "timestamp": "1234567890"
        }
        params["hmac"] = self._compute_hmac(params.copy())
        
        # Mock token exchange
        mock_token_response = {
            "access_token": "new-access-token",
            "scope": "read_products,write_products"
        }
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock()
            mock_post.raise_for_status = AsyncMock()
            mock_post.json.return_value = mock_token_response
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_post
            )
            
            response = client.get("/api/auth/callback", params=params)
            
            assert response.status_code == 302
            
            # Verify store was updated (not created)
            db_session.refresh(existing_store)
            assert existing_store.status == "active"
            assert existing_store.access_token_encrypted != "old-encrypted-token"
            assert existing_store.uninstalled_at is None
            assert existing_store.installed_at is not None
            
            # CRITICAL: tenant_id must be preserved
            assert existing_store.tenant_id == original_tenant_id
            
            # Verify audit log was created for reinstall
            from src.platform.audit import AuditLog, AuditAction
            audit_logs = db_session.query(AuditLog).filter(
                AuditLog.tenant_id == original_tenant_id,
                AuditLog.action == AuditAction.APP_INSTALLED.value
            ).all()
            assert len(audit_logs) >= 1  # At least one (may have previous installs)
            latest = max(audit_logs, key=lambda x: x.timestamp)
            assert latest.event_metadata["is_reinstall"] is True
            assert latest.event_metadata["shop_domain"] == test_shop_domain
            assert latest.resource_type == "store"
            assert latest.resource_id == existing_store.id
            assert latest.user_id == "system"
    
    def test_callback_invalid_hmac(self, client, test_shop_domain, db_session):
        """Test callback with invalid HMAC."""
        state = "test-state"
        self._create_oauth_state(db_session, test_shop_domain, state)
        
        params = {
            "code": "test-auth-code",
            "state": state,
            "shop": test_shop_domain,
            "hmac": "invalid-hmac"
        }
        
        response = client.get("/api/auth/callback", params=params)
        
        assert response.status_code == 400
        assert "Security Verification Failed" in response.text
    
    def test_callback_invalid_state(self, client, test_shop_domain):
        """Test callback with invalid state."""
        params = {
            "code": "test-auth-code",
            "state": "non-existent-state",
            "shop": test_shop_domain,
            "timestamp": "1234567890"
        }
        params["hmac"] = self._compute_hmac(params.copy())
        
        response = client.get("/api/auth/callback", params=params)
        
        assert response.status_code == 400
        assert "Invalid OAuth State" in response.text
    
    def test_callback_expired_state(self, client, test_shop_domain, db_session):
        """Test callback with expired state."""
        from src.models.oauth_state import OAuthState
        
        state = "expired-state"
        oauth_state = OAuthState(
            id=str(uuid.uuid4()),
            shop_domain=test_shop_domain,
            state=state,
            nonce="test-nonce",
            scopes="read_products",
            redirect_uri="https://test.example.com/api/auth/callback",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)  # Expired
        )
        db_session.add(oauth_state)
        db_session.commit()
        
        params = {
            "code": "test-auth-code",
            "state": state,
            "shop": test_shop_domain,
            "timestamp": "1234567890"
        }
        params["hmac"] = self._compute_hmac(params.copy())
        
        response = client.get("/api/auth/callback", params=params)
        
        assert response.status_code == 400
        assert "Invalid OAuth State" in response.text
    
    def test_callback_used_state(self, client, test_shop_domain, db_session):
        """Test callback with already-used state."""
        state = "used-state"
        oauth_state = OAuthState(
            id=str(uuid.uuid4()),
            shop_domain=test_shop_domain,
            state=state,
            nonce="test-nonce",
            scopes="read_products",
            redirect_uri="https://test.example.com/api/auth/callback",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            used_at=datetime.now(timezone.utc)  # Already used
        )
        db_session.add(oauth_state)
        db_session.commit()
        
        params = {
            "code": "test-auth-code",
            "state": state,
            "shop": test_shop_domain,
            "timestamp": "1234567890"
        }
        params["hmac"] = self._compute_hmac(params.copy())
        
        response = client.get("/api/auth/callback", params=params)
        
        assert response.status_code == 400
        assert "Invalid OAuth State" in response.text
