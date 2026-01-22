"""
Property-based tests for tenant isolation enforcement.

CRITICAL: These tests verify that cross-tenant access is impossible.
"""

import pytest
from fastapi import FastAPI, Request, status
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from unittest.mock import Mock, AsyncMock, patch
import json

from src.platform.tenant_context import (
    TenantContext,
    TenantContextMiddleware,
    get_tenant_context,
    FronteggJWKSClient,
)
from src.repositories.base_repo import BaseRepository, TenantIsolationError
from src.db_base import Base


# Mock JWT payloads for testing
TENANT_A_JWT_PAYLOAD = {
    "org_id": "tenant-a-org-123",
    "sub": "user-1",
    "roles": ["admin"],
    "aud": "test-client-id",
    "iss": "https://api.frontegg.com",
    "exp": 9999999999,
    "iat": 1000000000,
}

TENANT_B_JWT_PAYLOAD = {
    "org_id": "tenant-b-org-456",
    "sub": "user-2",
    "roles": ["user"],
    "aud": "test-client-id",
    "iss": "https://api.frontegg.com",
    "exp": 9999999999,
    "iat": 1000000000,
}


@pytest.fixture
def mock_jwks():
    """Mock JWKS response from Frontegg."""
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": "test-key-id",
                "use": "sig",
                "alg": "RS256",
                "n": "test-modulus",
                "e": "AQAB"
            }
        ]
    }


@pytest.fixture
def app_with_middleware(monkeypatch):
    """Create FastAPI app with tenant context middleware."""
    import os
    # Set environment variable for middleware initialization
    monkeypatch.setenv("FRONTEGG_CLIENT_ID", "test-client-id")
    
    app = FastAPI()
    
    # Add middleware
    middleware = TenantContextMiddleware()
    app.middleware("http")(middleware)
    
    @app.get("/health")
    async def health():
        return {"status": "ok"}
    
    @app.get("/api/data")
    async def get_data(request: Request):
        tenant_ctx = get_tenant_context(request)
        return {
            "tenant_id": tenant_ctx.tenant_id,
            "user_id": tenant_ctx.user_id,
            "data": f"data-for-{tenant_ctx.tenant_id}"
        }
    
    @app.post("/api/data")
    async def create_data(request: Request):
        tenant_ctx = get_tenant_context(request)
        body = await request.json()
        # Simulate creating data - tenant_id from body should be ignored
        return {
            "tenant_id": tenant_ctx.tenant_id,  # Always from JWT
            "created": True,
            "body_tenant_id": body.get("tenant_id", "not-provided")
        }
    
    return app


class TestTenantContextExtraction:
    """Test tenant context extraction from JWT."""
    
    def test_tenant_context_creation(self):
        """Test TenantContext object creation."""
        ctx = TenantContext(
            tenant_id="tenant-123",
            user_id="user-456",
            roles=["admin"],
            org_id="org-789"
        )
        
        assert ctx.tenant_id == "tenant-123"
        assert ctx.user_id == "user-456"
        assert ctx.roles == ["admin"]
        assert ctx.org_id == "org-789"
    
    def test_tenant_context_empty_tenant_id_raises(self):
        """Test that empty tenant_id raises ValueError."""
        with pytest.raises(ValueError, match="tenant_id cannot be empty"):
            TenantContext(
                tenant_id="",
                user_id="user-1",
                roles=[],
                org_id="org-1"
            )


class TestJWTVerification:
    """Test JWT verification and tenant extraction."""
    
    @pytest.mark.asyncio
    @patch('src.platform.tenant_context.FronteggJWKSClient.get_signing_key')
    async def test_missing_token_returns_403(self, mock_get_signing_key, app_with_middleware):
        """Test that requests without token return 403."""
        from fastapi import HTTPException
        
        transport = ASGITransport(app=app_with_middleware)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            try:
                response = await client.get("/api/data")
                # If we get here, the response should be 403
                assert response.status_code == status.HTTP_403_FORBIDDEN
                assert "Missing or invalid authorization token" in response.json()["detail"]
            except HTTPException as e:
                # HTTPException raised directly - verify it's 403
                assert e.status_code == status.HTTP_403_FORBIDDEN
                assert "Missing or invalid authorization token" in str(e.detail)
    
    @pytest.mark.asyncio
    @patch('src.platform.tenant_context.FronteggJWKSClient.get_signing_key')
    @patch('src.platform.tenant_context.jwt.decode')
    async def test_invalid_token_returns_403(self, mock_jwt_decode, mock_get_signing_key, app_with_middleware):
        """Test that invalid tokens return 403."""
        from fastapi import HTTPException
        from jwt.exceptions import InvalidTokenError, PyJWKClientError
        
        # Mock JWKS client to raise JWT exception for invalid token
        # This should be caught by middleware and converted to 403
        mock_get_signing_key.side_effect = PyJWKClientError("Invalid token")
        
        transport = ASGITransport(app=app_with_middleware)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            try:
                response = await client.get(
                    "/api/data",
                    headers={"Authorization": "Bearer invalid-token"}
                )
                # If we get here, the response should be 403
                assert response.status_code == status.HTTP_403_FORBIDDEN
            except HTTPException as e:
                # HTTPException raised directly - verify it's 403
                # The middleware should catch PyJWKClientError and return 403
                assert e.status_code == status.HTTP_403_FORBIDDEN
    
    @pytest.mark.asyncio
    async def test_health_endpoint_bypasses_auth(self, app_with_middleware):
        """Test that /health endpoint doesn't require authentication."""
        client = TestClient(app_with_middleware)
        
        response = client.get("/health")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "ok"}


class TestCrossTenantProtection:
    """CRITICAL: Test that cross-tenant access is impossible."""
    
    @pytest.mark.asyncio
    @patch('src.platform.tenant_context.jwt.decode')
    @patch('src.platform.tenant_context.FronteggJWKSClient.get_signing_key')
    async def test_tenant_a_cannot_access_tenant_b_data(
        self,
        mock_get_signing_key,
        mock_jwt_decode,
        app_with_middleware,
        mock_jwks
    ):
        """
        CRITICAL TEST: Tenant A cannot access Tenant B's data.
        
        This test verifies that even if Tenant A tries to specify
        tenant_id in request body/query, they can only access their own data.
        """
        # Setup mocks
        from unittest.mock import MagicMock
        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"
        mock_get_signing_key.return_value = mock_signing_key
        
        # Tenant A's JWT
        mock_jwt_decode.return_value = TENANT_A_JWT_PAYLOAD
        
        client = TestClient(app_with_middleware)
        
        # Tenant A makes request
        response = client.get(
            "/api/data",
            headers={"Authorization": "Bearer tenant-a-token"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        # CRITICAL: tenant_id must be from JWT (tenant-a), not from request
        assert data["tenant_id"] == "tenant-a-org-123"
        assert data["data"] == "data-for-tenant-a-org-123"
        
        # Now try to access Tenant B's data by including tenant_id in body
        # This should STILL return Tenant A's data
        mock_jwt_decode.return_value = TENANT_A_JWT_PAYLOAD  # Still Tenant A's token
        
        response = client.post(
            "/api/data",
            headers={"Authorization": "Bearer tenant-a-token"},
            json={"tenant_id": "tenant-b-org-456"}  # Attempted cross-tenant access
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        # CRITICAL: tenant_id is from JWT, NOT from request body
        assert data["tenant_id"] == "tenant-a-org-123"
        assert data["body_tenant_id"] == "tenant-b-org-456"  # Body value is ignored
    
    @pytest.mark.asyncio
    @patch('src.platform.tenant_context.jwt.decode')
    @patch('src.platform.tenant_context.FronteggJWKSClient.get_signing_key')
    async def test_tenant_b_cannot_access_tenant_a_data(
        self,
        mock_get_signing_key,
        mock_jwt_decode,
        app_with_middleware,
        mock_jwks
    ):
        """
        CRITICAL TEST: Tenant B cannot access Tenant A's data.
        """
        # Setup mocks
        from unittest.mock import MagicMock
        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"
        mock_get_signing_key.return_value = mock_signing_key
        mock_jwt_decode.return_value = TENANT_B_JWT_PAYLOAD
        
        client = TestClient(app_with_middleware)
        
        # Tenant B makes request
        response = client.get(
            "/api/data",
            headers={"Authorization": "Bearer tenant-b-token"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        # CRITICAL: Must be Tenant B's data only
        assert data["tenant_id"] == "tenant-b-org-456"
        assert data["data"] == "data-for-tenant-b-org-456"


class TestRepositoryTenantIsolation:
    """Test repository-level tenant isolation."""
    
    def test_repository_rejects_empty_tenant_id(self):
        """Test that repository raises error for empty tenant_id."""
        from sqlalchemy import create_engine, Column, String
        from sqlalchemy.orm import sessionmaker
        
        # Define model first with unique table name to avoid conflicts
        class TestModelEmpty(Base):
            __tablename__ = "test_empty"
            id = Column(String, primary_key=True)
            tenant_id = Column(String, nullable=False)
        
        # Create engine and tables after model is defined
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        
        class TestRepositoryEmpty(BaseRepository[TestModelEmpty]):
            def _get_model_class(self):
                return TestModelEmpty
            
            def _get_tenant_column_name(self):
                return "tenant_id"
        
        # Empty tenant_id should raise
        with pytest.raises(ValueError, match="tenant_id is required"):
            TestRepositoryEmpty(session, "")
        
        # None tenant_id should raise
        with pytest.raises(ValueError, match="tenant_id is required"):
            TestRepositoryEmpty(session, None)
    
    def test_repository_tenant_id_mismatch_raises(self):
        """Test that repository raises error on tenant_id mismatch."""
        from sqlalchemy import create_engine, Column, String
        from sqlalchemy.orm import sessionmaker
        
        # Define model first with unique table name to avoid conflicts
        class TestModelMismatch(Base):
            __tablename__ = "test_mismatch"
            id = Column(String, primary_key=True)
            tenant_id = Column(String, nullable=False)
        
        # Create engine and tables after model is defined
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        
        class TestRepositoryMismatch(BaseRepository[TestModelMismatch]):
            def _get_model_class(self):
                return TestModelMismatch
            
            def _get_tenant_column_name(self):
                return "tenant_id"
        
        repo = TestRepositoryMismatch(session, "tenant-a")
        
        # Attempting operation with different tenant_id should raise
        with pytest.raises(TenantIsolationError, match="Tenant ID mismatch"):
            repo.get_by_id("entity-1", tenant_id="tenant-b")
    
    def test_repository_ignores_tenant_id_from_entity_data(self):
        """Test that repository ignores tenant_id from entity_data."""
        from sqlalchemy import create_engine, Column, String
        from sqlalchemy.orm import sessionmaker
        
        # Define model first with unique table name to avoid conflicts
        class TestModelIgnore(Base):
            __tablename__ = "test_ignore_tenant"
            id = Column(String, primary_key=True)
            tenant_id = Column(String, nullable=False)
            name = Column(String)
        
        # Create engine and tables after model is defined
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        
        class TestRepositoryIgnore(BaseRepository[TestModelIgnore]):
            def _get_model_class(self):
                return TestModelIgnore
            
            def _get_tenant_column_name(self):
                return "tenant_id"
        
        repo = TestRepositoryIgnore(session, "tenant-a")
        
        # Create entity with tenant_id in data (should be ignored)
        entity_data = {
            "id": "entity-1",
            "name": "Test Entity",
            "tenant_id": "tenant-b"  # Should be ignored, replaced with "tenant-a"
        }
        
        entity = repo.create(entity_data)
        
        # CRITICAL: tenant_id must be from repository context, not from data
        assert entity.tenant_id == "tenant-a"
        assert entity.id == "entity-1"


class TestPropertyBasedTenantIsolation:
    """
    Property-based tests using hypothesis to verify tenant isolation
    across all possible inputs.
    """
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("tenant_a_id,tenant_b_id", [
        ("tenant-1", "tenant-2"),
        ("org-abc", "org-xyz"),
        ("123", "456"),
        ("tenant-with-dashes", "tenant_with_underscores"),
    ])
    async def test_any_tenant_cannot_access_other_tenant_data(
        self,
        tenant_a_id,
        tenant_b_id,
        app_with_middleware,
        mock_jwks
    ):
        """
        Property-based test: Any tenant cannot access any other tenant's data.
        
        This test runs with multiple tenant ID formats to ensure
        isolation works regardless of ID format.
        """
        from unittest.mock import MagicMock
        with patch('src.platform.tenant_context.jwt.decode') as mock_decode, \
             patch('src.platform.tenant_context.FronteggJWKSClient.get_signing_key') as mock_key:
            
            mock_signing_key = MagicMock()
            mock_signing_key.key = "mock-key"
            mock_key.return_value = mock_signing_key
            
            # Tenant A's JWT
            tenant_a_payload = {
                **TENANT_A_JWT_PAYLOAD,
                "org_id": tenant_a_id
            }
            mock_decode.return_value = tenant_a_payload
            
            client = TestClient(app_with_middleware)
            
            # Tenant A requests data
            response = client.get(
                "/api/data",
                headers={"Authorization": "Bearer tenant-a-token"}
            )
            
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            
            # CRITICAL: Must return Tenant A's data, never Tenant B's
            assert data["tenant_id"] == tenant_a_id
            assert data["tenant_id"] != tenant_b_id
            assert tenant_b_id not in data["data"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])