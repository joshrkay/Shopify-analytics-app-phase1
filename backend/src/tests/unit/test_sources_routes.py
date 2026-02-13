"""
Unit tests for the new Sources API routes (Phase 3).

Tests cover:
- GET /api/sources/catalog — returns full platform catalog
- POST /api/sources/{platform}/oauth/initiate — generates state + auth URL
- POST /api/sources/oauth/callback — validates state, creates connection
- DELETE /api/sources/{source_id} — soft deletes a source
- POST /api/sources/{source_id}/test — tests connection health
- PATCH /api/sources/{source_id}/config — updates sync frequency
- GET /api/sources/sync-settings — returns global settings
- PUT /api/sources/sync-settings — updates global settings

Phase 3 — Data Sources backend routes
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.api.routes.sources import router, _oauth_state_store, _tenant_sync_settings
from src.api.schemas.sources import (
    PLATFORM_DISPLAY_NAMES,
    PLATFORM_AUTH_TYPE,
    PLATFORM_CATEGORIES,
)
from src.database.session import get_db_session


# =============================================================================
# Fixtures
# =============================================================================

TENANT_ID = "test-tenant-phase3"


@pytest.fixture
def mock_tenant_context():
    context = MagicMock()
    context.tenant_id = TENANT_ID
    context.user_id = "user-001"
    return context


@pytest.fixture
def app(mock_tenant_context):
    """Create a test FastAPI app with mocked dependencies."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db_session] = lambda: MagicMock()
    # Clear state between tests
    _oauth_state_store.clear()
    _tenant_sync_settings.clear()
    return app


@pytest.fixture
def client(app):
    # Patch tenant context globally for all routes
    with patch("src.api.routes.sources.get_tenant_context") as mock_gtc:
        ctx = MagicMock()
        ctx.tenant_id = TENANT_ID
        ctx.user_id = "user-001"
        mock_gtc.return_value = ctx
        yield TestClient(app)


# =============================================================================
# GET /api/sources/catalog
# =============================================================================

class TestGetSourceCatalog:

    def test_returns_all_platforms(self, client):
        """Catalog returns entries for all known platforms."""
        response = client.get("/api/sources/catalog")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == len(PLATFORM_DISPLAY_NAMES)
        platforms = {s["platform"] for s in data["sources"]}
        assert "shopify" in platforms
        assert "meta_ads" in platforms
        assert "google_ads" in platforms

    def test_catalog_entry_fields(self, client):
        """Each catalog entry has all required fields."""
        response = client.get("/api/sources/catalog")

        data = response.json()
        for entry in data["sources"]:
            assert "id" in entry
            assert "platform" in entry
            assert "display_name" in entry
            assert "description" in entry
            assert "auth_type" in entry
            assert "category" in entry
            assert "is_enabled" in entry

    def test_catalog_auth_types_match(self, client):
        """Catalog auth types match PLATFORM_AUTH_TYPE."""
        response = client.get("/api/sources/catalog")

        data = response.json()
        for entry in data["sources"]:
            expected_auth = PLATFORM_AUTH_TYPE.get(entry["platform"], "api_key")
            assert entry["auth_type"] == expected_auth

    def test_catalog_categories_match(self, client):
        """Catalog categories match PLATFORM_CATEGORIES."""
        response = client.get("/api/sources/catalog")

        data = response.json()
        for entry in data["sources"]:
            expected_cat = PLATFORM_CATEGORIES.get(entry["platform"], "other")
            assert entry["category"] == expected_cat


# =============================================================================
# POST /api/sources/{platform}/oauth/initiate
# =============================================================================

class TestInitiateOAuth:

    def test_returns_authorization_url_and_state(self, client):
        """Returns a valid auth URL and state token for OAuth platforms."""
        response = client.post("/api/sources/meta_ads/oauth/initiate")

        assert response.status_code == 200
        data = response.json()
        assert "authorization_url" in data
        assert "state" in data
        assert len(data["state"]) > 0
        assert "facebook.com" in data["authorization_url"]

    def test_stores_state_with_tenant(self, client):
        """State token is stored with tenant context."""
        response = client.post("/api/sources/meta_ads/oauth/initiate")

        data = response.json()
        state = data["state"]
        assert state in _oauth_state_store
        assert _oauth_state_store[state]["tenant_id"] == TENANT_ID
        assert _oauth_state_store[state]["platform"] == "meta_ads"

    def test_rejects_non_oauth_platform(self, client):
        """Rejects platforms that use api_key auth."""
        response = client.post("/api/sources/klaviyo/oauth/initiate")

        assert response.status_code == 400
        assert "does not support OAuth" in response.json()["detail"]

    def test_google_ads_url(self, client):
        """Google Ads returns accounts.google.com URL."""
        response = client.post("/api/sources/google_ads/oauth/initiate")

        assert response.status_code == 200
        assert "accounts.google.com" in response.json()["authorization_url"]


# =============================================================================
# POST /api/sources/oauth/callback
# =============================================================================

class TestOAuthCallback:

    def test_rejects_invalid_state(self, client):
        """Rejects callback with unknown state token."""
        response = client.post(
            "/api/sources/oauth/callback",
            json={"code": "auth-code", "state": "invalid-state"},
        )

        assert response.status_code == 400
        assert "Invalid or expired" in response.json()["detail"]

    @patch("src.api.routes.sources.get_airbyte_client")
    @patch("src.api.routes.sources.AirbyteService")
    def test_successful_callback_creates_connection(
        self, MockAirbyteService, mock_get_client, client
    ):
        """Successful OAuth callback creates Airbyte source and connection."""
        # Set up state
        state = "test-csrf-state-123"
        _oauth_state_store[state] = {
            "tenant_id": TENANT_ID,
            "user_id": "user-001",
            "platform": "meta_ads",
        }

        # Mock Airbyte client
        mock_client = AsyncMock()
        mock_source = MagicMock()
        mock_source.source_id = "airbyte-src-001"
        mock_client.create_source.return_value = mock_source
        mock_client.list_destinations.return_value = []
        mock_get_client.return_value = mock_client

        # Mock AirbyteService
        mock_service = MagicMock()
        mock_conn_info = MagicMock()
        mock_conn_info.id = "conn-001"
        mock_service.register_connection.return_value = mock_conn_info
        MockAirbyteService.return_value = mock_service

        response = client.post(
            "/api/sources/oauth/callback",
            json={"code": "auth-code", "state": state},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["connection_id"] == "conn-001"
        assert "Meta Ads" in data["message"]

        # Verify state was consumed
        assert state not in _oauth_state_store


# =============================================================================
# DELETE /api/sources/{source_id}
# =============================================================================

class TestDisconnectSource:

    @patch("src.api.routes.sources.AirbyteService")
    def test_disconnect_returns_204(self, MockService, client):
        """Successful disconnect returns 204."""
        mock_service = MagicMock()
        MockService.return_value = mock_service

        response = client.delete("/api/sources/conn-001")

        assert response.status_code == 204
        mock_service.delete_connection.assert_called_once_with("conn-001")

    @patch("src.api.routes.sources.AirbyteService")
    def test_disconnect_not_found(self, MockService, client):
        """Returns 404 for unknown source."""
        from src.services.airbyte_service import ConnectionNotFoundServiceError

        mock_service = MagicMock()
        mock_service.delete_connection.side_effect = ConnectionNotFoundServiceError("not found")
        MockService.return_value = mock_service

        response = client.delete("/api/sources/nonexistent")

        assert response.status_code == 404


# =============================================================================
# POST /api/sources/{source_id}/test
# =============================================================================

class TestTestConnection:

    @patch("src.api.routes.sources.get_airbyte_client")
    @patch("src.api.routes.sources.AirbyteService")
    def test_healthy_connection(self, MockService, mock_get_client, client):
        """Returns success for a healthy connection."""
        mock_service = MagicMock()
        mock_conn = MagicMock()
        mock_conn.airbyte_connection_id = "ab-conn-001"
        mock_service.get_connection.return_value = mock_conn
        MockService.return_value = mock_service

        mock_client = AsyncMock()
        mock_source = MagicMock()
        mock_source.source_id = "src-001"
        mock_source.source_type = "source-facebook-marketing"
        mock_client.get_source.return_value = mock_source
        mock_get_client.return_value = mock_client

        response = client.post("/api/sources/conn-001/test")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Connection is healthy"

    @patch("src.api.routes.sources.AirbyteService")
    def test_not_found_returns_404(self, MockService, client):
        """Returns 404 for unknown source."""
        mock_service = MagicMock()
        mock_service.get_connection.return_value = None
        MockService.return_value = mock_service

        response = client.post("/api/sources/nonexistent/test")

        assert response.status_code == 404


# =============================================================================
# PATCH /api/sources/{source_id}/config
# =============================================================================

class TestUpdateSyncConfig:

    @patch("src.api.routes.sources.AirbyteService")
    def test_update_frequency(self, MockService, client):
        """Updates sync frequency returns 204."""
        mock_service = MagicMock()
        mock_service.get_connection.return_value = MagicMock()
        MockService.return_value = mock_service

        response = client.patch(
            "/api/sources/conn-001/config",
            json={"sync_frequency": "daily"},
        )

        assert response.status_code == 204
        mock_service.update_sync_frequency.assert_called_once_with("conn-001", 1440)

    @patch("src.api.routes.sources.AirbyteService")
    def test_invalid_frequency(self, MockService, client):
        """Rejects invalid frequency value."""
        mock_service = MagicMock()
        mock_service.get_connection.return_value = MagicMock()
        MockService.return_value = mock_service

        response = client.patch(
            "/api/sources/conn-001/config",
            json={"sync_frequency": "every_5_minutes"},
        )

        assert response.status_code == 400
        assert "Invalid frequency" in response.json()["detail"]


# =============================================================================
# GET /api/sources/sync-settings
# =============================================================================

class TestGetSyncSettings:

    def test_returns_defaults(self, client):
        """Returns default settings for new tenant."""
        response = client.get("/api/sources/sync-settings")

        assert response.status_code == 200
        data = response.json()
        assert data["default_frequency"] == "hourly"
        assert data["pause_all_syncs"] is False
        assert data["max_concurrent_syncs"] == 5


# =============================================================================
# PUT /api/sources/sync-settings
# =============================================================================

class TestUpdateSyncSettings:

    def test_update_frequency(self, client):
        """Can update default frequency."""
        response = client.put(
            "/api/sources/sync-settings",
            json={"default_frequency": "daily"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["default_frequency"] == "daily"
        assert data["pause_all_syncs"] is False

    def test_update_pause_all(self, client):
        """Can pause all syncs."""
        response = client.put(
            "/api/sources/sync-settings",
            json={"pause_all_syncs": True},
        )

        assert response.status_code == 200
        assert response.json()["pause_all_syncs"] is True

    def test_invalid_frequency_rejected(self, client):
        """Rejects invalid frequency."""
        response = client.put(
            "/api/sources/sync-settings",
            json={"default_frequency": "every_minute"},
        )

        assert response.status_code == 400

    def test_invalid_concurrent_rejected(self, client):
        """Rejects out-of-range concurrent syncs."""
        response = client.put(
            "/api/sources/sync-settings",
            json={"max_concurrent_syncs": 100},
        )

        assert response.status_code == 400
