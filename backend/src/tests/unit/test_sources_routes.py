"""
Unit tests for the Sources API routes (Phase 3).

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

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.api.routes.sources import (
    router,
    _oauth_state_store_fallback,
    _store_oauth_state,
    _pop_oauth_state,
)
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
    _oauth_state_store_fallback.clear()
    return app


@pytest.fixture
def client(app):
    # Patch tenant context and Redis globally for all routes
    with (
        patch("src.api.routes.sources.get_tenant_context") as mock_gtc,
        patch("src.api.routes.sources._get_redis_client", return_value=None),
    ):
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

    def test_stores_state_in_fallback(self, client):
        """State token is stored in in-memory fallback when Redis unavailable."""
        response = client.post("/api/sources/meta_ads/oauth/initiate")

        data = response.json()
        state = data["state"]
        assert state in _oauth_state_store_fallback
        assert _oauth_state_store_fallback[state]["tenant_id"] == TENANT_ID
        assert _oauth_state_store_fallback[state]["platform"] == "meta_ads"

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

    def test_shopify_requires_shop_domain(self, client):
        """Shopify OAuth requires shop_domain in request body."""
        response = client.post("/api/sources/shopify/oauth/initiate")

        assert response.status_code == 400
        assert "shop_domain" in response.json()["detail"]

    def test_shopify_with_shop_domain(self, client):
        """Shopify OAuth works when shop_domain is provided."""
        response = client.post(
            "/api/sources/shopify/oauth/initiate",
            json={"shop_domain": "mystore.myshopify.com"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "mystore.myshopify.com" in data["authorization_url"]
        state = data["state"]
        assert _oauth_state_store_fallback[state].get("shop_domain") == "mystore.myshopify.com"


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
        # Set up state in fallback store
        state = "test-csrf-state-123"
        _oauth_state_store_fallback[state] = {
            "tenant_id": TENANT_ID,
            "user_id": "user-001",
            "platform": "meta_ads",
        }

        # Mock Airbyte client with destination + connection
        mock_client = AsyncMock()
        mock_source = MagicMock()
        mock_source.source_id = "airbyte-src-001"
        mock_client.create_source.return_value = mock_source
        mock_dest = MagicMock()
        mock_dest.destination_id = "airbyte-dest-001"
        mock_client.list_destinations.return_value = [mock_dest]
        mock_connection = MagicMock()
        mock_connection.connection_id = "airbyte-conn-001"
        mock_client.create_connection.return_value = mock_connection
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

        # Verify register_connection used the real connection ID, not source ID
        reg_call = mock_service.register_connection.call_args
        assert reg_call.kwargs.get("airbyte_connection_id") == "airbyte-conn-001"
        assert reg_call.kwargs.get("airbyte_source_id") == "airbyte-src-001"

        # Verify state was consumed
        assert state not in _oauth_state_store_fallback

    @patch("src.api.routes.sources.get_airbyte_client")
    @patch("src.api.routes.sources.AirbyteService")
    def test_callback_rejects_when_no_destination(
        self, MockAirbyteService, mock_get_client, client
    ):
        """OAuth callback returns 502 when no Airbyte destination is configured."""
        state = "test-state-no-dest"
        _oauth_state_store_fallback[state] = {
            "tenant_id": TENANT_ID,
            "user_id": "user-001",
            "platform": "meta_ads",
        }

        mock_client = AsyncMock()
        mock_source = MagicMock()
        mock_source.source_id = "airbyte-src-nodest"
        mock_client.create_source.return_value = mock_source
        mock_client.list_destinations.return_value = []
        mock_get_client.return_value = mock_client

        mock_service = MagicMock()
        MockAirbyteService.return_value = mock_service

        response = client.post(
            "/api/sources/oauth/callback",
            json={"code": "auth-code", "state": state},
        )

        assert response.status_code == 502
        assert "no destination configured" in response.json()["detail"]
        # register_connection should never be called when pipeline can't be set up
        mock_service.register_connection.assert_not_called()

    @patch("src.api.routes.sources.get_airbyte_client")
    @patch("src.api.routes.sources.AirbyteService")
    def test_callback_uses_source_creation_request(
        self, MockAirbyteService, mock_get_client, client
    ):
        """OAuth callback uses SourceCreationRequest, not keyword args."""
        state = "test-state-request-pattern"
        _oauth_state_store_fallback[state] = {
            "tenant_id": TENANT_ID,
            "user_id": "user-001",
            "platform": "meta_ads",
        }

        mock_client = AsyncMock()
        mock_source = MagicMock()
        mock_source.source_id = "airbyte-src-002"
        mock_client.create_source.return_value = mock_source
        mock_dest = MagicMock()
        mock_dest.destination_id = "airbyte-dest-002"
        mock_client.list_destinations.return_value = [mock_dest]
        mock_connection = MagicMock()
        mock_connection.connection_id = "airbyte-conn-002"
        mock_client.create_connection.return_value = mock_connection
        mock_get_client.return_value = mock_client

        mock_service = MagicMock()
        mock_conn_info = MagicMock()
        mock_conn_info.id = "conn-002"
        mock_service.register_connection.return_value = mock_conn_info
        MockAirbyteService.return_value = mock_service

        response = client.post(
            "/api/sources/oauth/callback",
            json={"code": "auth-code", "state": state},
        )

        assert response.status_code == 200
        # Verify create_source was called with a SourceCreationRequest
        call_args = mock_client.create_source.call_args
        from src.integrations.airbyte.models import SourceCreationRequest
        assert isinstance(call_args[0][0], SourceCreationRequest)

    @patch("src.api.routes.sources.get_airbyte_client")
    @patch("src.api.routes.sources.AirbyteService")
    def test_callback_includes_shop_domain_in_config(
        self, MockAirbyteService, mock_get_client, client
    ):
        """OAuth callback passes shop_domain through to register_connection config."""
        state = "test-state-shop-domain"
        _oauth_state_store_fallback[state] = {
            "tenant_id": TENANT_ID,
            "user_id": "user-001",
            "platform": "shopify",
            "shop_domain": "mystore.myshopify.com",
        }

        mock_client = AsyncMock()
        mock_source = MagicMock()
        mock_source.source_id = "airbyte-src-003"
        mock_client.create_source.return_value = mock_source
        mock_dest = MagicMock()
        mock_dest.destination_id = "airbyte-dest-003"
        mock_client.list_destinations.return_value = [mock_dest]
        mock_connection = MagicMock()
        mock_connection.connection_id = "airbyte-conn-003"
        mock_client.create_connection.return_value = mock_connection
        mock_get_client.return_value = mock_client

        mock_service = MagicMock()
        mock_conn_info = MagicMock()
        mock_conn_info.id = "conn-003"
        mock_service.register_connection.return_value = mock_conn_info
        MockAirbyteService.return_value = mock_service

        response = client.post(
            "/api/sources/oauth/callback",
            json={"code": "auth-code", "state": state},
        )

        assert response.status_code == 200
        # Verify register_connection was called with shop_domain in config
        reg_call = mock_service.register_connection.call_args
        config = reg_call.kwargs.get("configuration") or reg_call[1].get("configuration")
        assert config["shop_domain"] == "mystore.myshopify.com"

    @patch("src.api.routes.sources.get_airbyte_client")
    @patch("src.api.routes.sources.AirbyteService")
    def test_callback_sanitizes_error_messages(
        self, MockAirbyteService, mock_get_client, client
    ):
        """OAuth callback does not leak internal error details to the client."""
        state = "test-state-error-sanitize"
        _oauth_state_store_fallback[state] = {
            "tenant_id": TENANT_ID,
            "user_id": "user-001",
            "platform": "meta_ads",
        }

        mock_client = AsyncMock()
        mock_client.create_source.side_effect = RuntimeError(
            "Internal DB connection string: postgresql://user:secret@host/db"
        )
        mock_get_client.return_value = mock_client

        response = client.post(
            "/api/sources/oauth/callback",
            json={"code": "auth-code", "state": state},
        )

        assert response.status_code == 500
        detail = response.json()["detail"]
        # Must NOT contain the raw exception message
        assert "postgresql://" not in detail
        assert "secret" not in detail
        assert "Please try again" in detail


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
        """Returns success when check_source_connection succeeds."""
        mock_service = MagicMock()
        mock_conn = MagicMock()
        mock_conn.airbyte_connection_id = "ab-conn-001"
        mock_service.get_connection.return_value = mock_conn

        # Mock the repository to return a raw connection with airbyte_source_id
        mock_raw_conn = MagicMock()
        mock_raw_conn.airbyte_source_id = "ab-src-001"
        mock_service._repository.get_by_id.return_value = mock_raw_conn
        MockService.return_value = mock_service

        mock_client = AsyncMock()
        mock_client.check_source_connection.return_value = {"status": "succeeded"}
        mock_get_client.return_value = mock_client

        response = client.post("/api/sources/conn-001/test")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Connection is healthy"

        # Verify it used the source ID, not the connection ID
        mock_client.check_source_connection.assert_called_once_with("ab-src-001")

    @patch("src.api.routes.sources.get_airbyte_client")
    @patch("src.api.routes.sources.AirbyteService")
    def test_unhealthy_connection(self, MockService, mock_get_client, client):
        """Returns failure when check_source_connection reports failure."""
        mock_service = MagicMock()
        mock_conn = MagicMock()
        mock_conn.airbyte_connection_id = "ab-conn-002"
        mock_service.get_connection.return_value = mock_conn

        mock_raw_conn = MagicMock()
        mock_raw_conn.airbyte_source_id = "ab-src-002"
        mock_service._repository.get_by_id.return_value = mock_raw_conn
        MockService.return_value = mock_service

        mock_client = AsyncMock()
        mock_client.check_source_connection.return_value = {
            "status": "failed",
            "message": "Invalid credentials",
        }
        mock_get_client.return_value = mock_client

        response = client.post("/api/sources/conn-002/test")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Invalid credentials" in data["message"]

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

    @patch("src.api.routes.sources._get_sync_settings_from_db")
    @patch("src.api.routes.sources.AirbyteService")
    def test_returns_defaults(self, MockService, mock_get_settings, client):
        """Returns default settings for new tenant."""
        mock_get_settings.return_value = {
            "default_frequency": "hourly",
            "pause_all_syncs": False,
            "max_concurrent_syncs": 5,
        }
        MockService.return_value = MagicMock()

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

    @patch("src.api.routes.sources._save_sync_settings_to_db")
    @patch("src.api.routes.sources._get_sync_settings_from_db")
    @patch("src.api.routes.sources.AirbyteService")
    def test_update_frequency(self, MockService, mock_get, mock_save, client):
        """Can update default frequency."""
        mock_get.return_value = {
            "default_frequency": "hourly",
            "pause_all_syncs": False,
            "max_concurrent_syncs": 5,
        }
        MockService.return_value = MagicMock()

        response = client.put(
            "/api/sources/sync-settings",
            json={"default_frequency": "daily"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["default_frequency"] == "daily"
        assert data["pause_all_syncs"] is False
        mock_save.assert_called_once()

    @patch("src.api.routes.sources._save_sync_settings_to_db")
    @patch("src.api.routes.sources._get_sync_settings_from_db")
    @patch("src.api.routes.sources.AirbyteService")
    def test_update_pause_all(self, MockService, mock_get, mock_save, client):
        """Can pause all syncs."""
        mock_get.return_value = {
            "default_frequency": "hourly",
            "pause_all_syncs": False,
            "max_concurrent_syncs": 5,
        }
        MockService.return_value = MagicMock()

        response = client.put(
            "/api/sources/sync-settings",
            json={"pause_all_syncs": True},
        )

        assert response.status_code == 200
        assert response.json()["pause_all_syncs"] is True

    @patch("src.api.routes.sources._get_sync_settings_from_db")
    @patch("src.api.routes.sources.AirbyteService")
    def test_invalid_frequency_rejected(self, MockService, mock_get, client):
        """Rejects invalid frequency."""
        mock_get.return_value = {
            "default_frequency": "hourly",
            "pause_all_syncs": False,
            "max_concurrent_syncs": 5,
        }
        MockService.return_value = MagicMock()

        response = client.put(
            "/api/sources/sync-settings",
            json={"default_frequency": "every_minute"},
        )

        assert response.status_code == 400

    @patch("src.api.routes.sources._get_sync_settings_from_db")
    @patch("src.api.routes.sources.AirbyteService")
    def test_invalid_concurrent_rejected(self, MockService, mock_get, client):
        """Rejects out-of-range concurrent syncs."""
        mock_get.return_value = {
            "default_frequency": "hourly",
            "pause_all_syncs": False,
            "max_concurrent_syncs": 5,
        }
        MockService.return_value = MagicMock()

        response = client.put(
            "/api/sources/sync-settings",
            json={"max_concurrent_syncs": 100},
        )

        assert response.status_code == 400


# =============================================================================
# OAuth state store helpers
# =============================================================================

class TestOAuthStateStore:

    def test_fallback_store_and_pop(self):
        """In-memory fallback: store and pop works."""
        with patch("src.api.routes.sources._get_redis_client", return_value=None):
            data = {"tenant_id": "t1", "platform": "meta_ads"}
            _store_oauth_state("state-1", data)
            result = _pop_oauth_state("state-1")
            assert result == data
            # Second pop returns None (consumed)
            assert _pop_oauth_state("state-1") is None

    def test_redis_store_and_pop(self):
        """Redis-backed: store and pop uses Redis methods."""
        mock_redis = MagicMock()
        stored_data = {"tenant_id": "t1", "platform": "meta_ads"}
        mock_redis.get.return_value = json.dumps(stored_data)

        with patch("src.api.routes.sources._get_redis_client", return_value=mock_redis):
            _store_oauth_state("state-2", stored_data)
            mock_redis.set.assert_called_once()

            result = _pop_oauth_state("state-2")
            assert result == stored_data
            mock_redis.delete.assert_called_once_with("oauth_state:state-2")
