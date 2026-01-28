"""
Integration tests for Sync Health API.

Tests cover:
- Compact health endpoint (Story 9.5)
- Active incidents endpoint (Story 9.6)
- Tenant isolation

Story 9.5 - Data Freshness Indicators
Story 9.6 - Incident Communication
"""

import pytest
import uuid
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.api.dq.routes import router, get_dq_service
from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session


# =============================================================================
# Test Setup
# =============================================================================


@pytest.fixture
def app():
    """Create a test FastAPI application."""
    app = FastAPI()
    app.include_router(router)
    return app


def create_app_with_overrides(mock_dq_service, mock_db_session):
    """Create app with dependency overrides."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_dq_service] = lambda: mock_dq_service
    app.dependency_overrides[get_db_session] = lambda: mock_db_session
    return app


@pytest.fixture
def tenant_id():
    """Test tenant ID."""
    return "test-tenant-123"


@pytest.fixture
def user_id():
    """Test user ID."""
    return "user-456"


@pytest.fixture
def mock_tenant_context(tenant_id, user_id):
    """Create a mock tenant context."""
    context = MagicMock()
    context.tenant_id = tenant_id
    context.user_id = user_id
    return context


@pytest.fixture
def sample_connector():
    """Create a sample connector health object."""
    from src.api.dq.service import ConnectorSyncHealth, DQSeverity

    return ConnectorSyncHealth(
        connector_id="conn-123",
        connector_name="Shopify Orders",
        source_type="shopify",
        status="healthy",
        freshness_status="fresh",
        severity=None,
        last_sync_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        last_rows_synced=1500,
        minutes_since_sync=30,
        message="Connector is fresh",
        merchant_message="Data is up to date.",
        recommended_actions=[],
        is_blocking=False,
        has_open_incidents=False,
        open_incident_count=0,
    )


@pytest.fixture
def stale_connector():
    """Create a stale connector health object."""
    from src.api.dq.service import ConnectorSyncHealth, DQSeverity

    return ConnectorSyncHealth(
        connector_id="conn-456",
        connector_name="Meta Ads",
        source_type="meta_ads",
        status="delayed",
        freshness_status="stale",
        severity=DQSeverity.WARNING,
        last_sync_at=datetime.now(timezone.utc) - timedelta(hours=5),
        last_rows_synced=500,
        minutes_since_sync=300,
        message="Connector is stale",
        merchant_message="Your Meta Ads data may be slightly delayed.",
        recommended_actions=["Retry sync"],
        is_blocking=False,
        has_open_incidents=False,
        open_incident_count=0,
    )


@pytest.fixture
def sample_summary(tenant_id, sample_connector, stale_connector):
    """Create a sample sync health summary."""
    from src.api.dq.service import SyncHealthSummary

    return SyncHealthSummary(
        tenant_id=tenant_id,
        total_connectors=2,
        healthy_count=1,
        delayed_count=1,
        error_count=0,
        blocking_issues=0,
        overall_status="degraded",
        health_score=50.0,
        connectors=[sample_connector, stale_connector],
        has_blocking_issues=False,
    )


@pytest.fixture
def sample_incident(tenant_id):
    """Create a sample DQ incident."""
    incident = MagicMock()
    incident.id = str(uuid.uuid4())
    incident.tenant_id = tenant_id
    incident.connector_id = "conn-456"
    incident.severity = "warning"
    incident.status = "open"
    incident.is_blocking = False
    incident.title = "Data Sync Delayed"
    incident.description = "Meta Ads sync is delayed"
    incident.merchant_message = "Your Meta Ads data is delayed."
    incident.recommended_actions = ["Retry sync"]
    incident.opened_at = datetime.now(timezone.utc) - timedelta(hours=1)
    incident.acknowledged_at = None
    incident.resolved_at = None
    return incident


@pytest.fixture
def critical_incident(tenant_id):
    """Create a critical blocking DQ incident."""
    incident = MagicMock()
    incident.id = str(uuid.uuid4())
    incident.tenant_id = tenant_id
    incident.connector_id = "conn-789"
    incident.severity = "critical"
    incident.status = "open"
    incident.is_blocking = True
    incident.title = "Critical Data Issue"
    incident.description = "Shopify orders sync failed"
    incident.merchant_message = "Your Shopify data is significantly delayed."
    incident.recommended_actions = ["Check connection", "Contact support"]
    incident.opened_at = datetime.now(timezone.utc) - timedelta(hours=2)
    incident.acknowledged_at = None
    incident.resolved_at = None
    return incident


@pytest.fixture
def mock_dq_service(sample_summary):
    """Create a mock DQ service."""
    service = MagicMock()
    service.get_sync_health_summary.return_value = sample_summary
    service.get_open_incidents.return_value = []
    service.get_incident_scope.return_value = "Meta Ads connector"
    service.get_incident_eta.return_value = "Expected resolution: 1-2 hours"
    return service


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    return MagicMock()


# =============================================================================
# Test: Compact Health Endpoint (Story 9.5)
# =============================================================================


class TestCompactHealthEndpoint:
    """Tests for /compact endpoint - Story 9.5."""

    def test_compact_health_returns_lightweight_response(
        self, mock_tenant_context, mock_dq_service, mock_db_session
    ):
        """Compact endpoint returns minimal data for polling."""
        app = create_app_with_overrides(mock_dq_service, mock_db_session)
        with patch("src.api.dq.routes.get_tenant_context", return_value=mock_tenant_context):
            client = TestClient(app)
            response = client.get("/api/sync-health/compact")

        assert response.status_code == 200
        data = response.json()

        # Verify lightweight fields
        assert "overall_status" in data
        assert "health_score" in data
        assert "stale_count" in data
        assert "critical_count" in data
        assert "has_blocking_issues" in data
        assert "oldest_sync_minutes" in data
        assert "last_checked_at" in data

        # Verify no heavy fields (connectors list)
        assert "connectors" not in data

    def test_compact_health_status_values(
        self, mock_tenant_context, mock_dq_service, mock_db_session
    ):
        """Compact endpoint returns correct status values."""
        app = create_app_with_overrides(mock_dq_service, mock_db_session)
        with patch("src.api.dq.routes.get_tenant_context", return_value=mock_tenant_context):
            client = TestClient(app)
            response = client.get("/api/sync-health/compact")

        assert response.status_code == 200
        data = response.json()

        assert data["overall_status"] == "degraded"
        assert data["health_score"] == 50.0
        assert data["stale_count"] == 1
        assert data["critical_count"] == 0
        assert data["has_blocking_issues"] is False

    def test_compact_health_oldest_sync_calculation(
        self, mock_tenant_context, mock_dq_service, mock_db_session
    ):
        """Compact endpoint calculates oldest sync correctly."""
        app = create_app_with_overrides(mock_dq_service, mock_db_session)
        with patch("src.api.dq.routes.get_tenant_context", return_value=mock_tenant_context):
            client = TestClient(app)
            response = client.get("/api/sync-health/compact")

        assert response.status_code == 200
        data = response.json()

        # Should be the max of 30 and 300 minutes
        assert data["oldest_sync_minutes"] == 300

    def test_compact_health_empty_connectors(
        self, mock_tenant_context, mock_db_session, tenant_id
    ):
        """Compact endpoint handles no connectors gracefully."""
        from src.api.dq.service import SyncHealthSummary

        empty_summary = SyncHealthSummary(
            tenant_id=tenant_id,
            total_connectors=0,
            healthy_count=0,
            delayed_count=0,
            error_count=0,
            blocking_issues=0,
            overall_status="healthy",
            health_score=100.0,
            connectors=[],
            has_blocking_issues=False,
        )

        mock_service = MagicMock()
        mock_service.get_sync_health_summary.return_value = empty_summary

        app = create_app_with_overrides(mock_service, mock_db_session)
        with patch("src.api.dq.routes.get_tenant_context", return_value=mock_tenant_context):
            client = TestClient(app)
            response = client.get("/api/sync-health/compact")

        assert response.status_code == 200
        data = response.json()

        assert data["overall_status"] == "healthy"
        assert data["oldest_sync_minutes"] is None

    def test_compact_health_includes_timestamp(
        self, mock_tenant_context, mock_dq_service, mock_db_session
    ):
        """Compact endpoint includes last_checked_at timestamp."""
        app = create_app_with_overrides(mock_dq_service, mock_db_session)
        with patch("src.api.dq.routes.get_tenant_context", return_value=mock_tenant_context):
            client = TestClient(app)
            response = client.get("/api/sync-health/compact")

        assert response.status_code == 200
        data = response.json()

        # Should be ISO format timestamp
        assert "last_checked_at" in data
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(data["last_checked_at"].replace("Z", "+00:00"))


# =============================================================================
# Test: Active Incidents Endpoint (Story 9.6)
# =============================================================================


class TestActiveIncidentsEndpoint:
    """Tests for /incidents/active endpoint - Story 9.6."""

    def test_active_incidents_returns_banner_format(
        self, mock_tenant_context, mock_db_session, sample_incident
    ):
        """Active incidents endpoint returns banner-ready format."""
        mock_service = MagicMock()
        mock_service.get_open_incidents.return_value = [sample_incident]
        mock_service.get_incident_scope.return_value = "Meta Ads connector"
        mock_service.get_incident_eta.return_value = "Expected resolution: 1-2 hours"

        app = create_app_with_overrides(mock_service, mock_db_session)
        with patch("src.api.dq.routes.get_tenant_context", return_value=mock_tenant_context):
            client = TestClient(app)
            response = client.get("/api/sync-health/incidents/active")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "incidents" in data
        assert "has_critical" in data
        assert "has_blocking" in data

        # Verify incident banner fields
        assert len(data["incidents"]) == 1
        incident = data["incidents"][0]
        assert "id" in incident
        assert "severity" in incident
        assert "title" in incident
        assert "message" in incident
        assert "scope" in incident
        assert "eta" in incident
        assert "status_page_url" in incident
        assert "started_at" in incident

    def test_active_incidents_includes_scope_and_eta(
        self, mock_tenant_context, mock_db_session, sample_incident
    ):
        """Active incidents include scope and ETA messaging."""
        mock_service = MagicMock()
        mock_service.get_open_incidents.return_value = [sample_incident]
        mock_service.get_incident_scope.return_value = "Meta Ads connector"
        mock_service.get_incident_eta.return_value = "Expected resolution: 1-2 hours"

        app = create_app_with_overrides(mock_service, mock_db_session)
        with patch("src.api.dq.routes.get_tenant_context", return_value=mock_tenant_context):
            client = TestClient(app)
            response = client.get("/api/sync-health/incidents/active")

        assert response.status_code == 200
        data = response.json()

        incident = data["incidents"][0]
        assert incident["scope"] == "Meta Ads connector"
        assert incident["eta"] == "Expected resolution: 1-2 hours"

    def test_active_incidents_detects_critical(
        self, mock_tenant_context, mock_db_session, critical_incident
    ):
        """Active incidents correctly flags critical incidents."""
        mock_service = MagicMock()
        mock_service.get_open_incidents.return_value = [critical_incident]
        mock_service.get_incident_scope.return_value = "Shopify connector"
        mock_service.get_incident_eta.return_value = "Investigating - updates every 30 minutes"

        app = create_app_with_overrides(mock_service, mock_db_session)
        with patch("src.api.dq.routes.get_tenant_context", return_value=mock_tenant_context):
            client = TestClient(app)
            response = client.get("/api/sync-health/incidents/active")

        assert response.status_code == 200
        data = response.json()

        assert data["has_critical"] is True
        assert data["has_blocking"] is True

    def test_active_incidents_detects_blocking(
        self, mock_tenant_context, mock_db_session, critical_incident
    ):
        """Active incidents correctly flags blocking incidents."""
        mock_service = MagicMock()
        mock_service.get_open_incidents.return_value = [critical_incident]
        mock_service.get_incident_scope.return_value = "Shopify connector"
        mock_service.get_incident_eta.return_value = "Investigating"

        app = create_app_with_overrides(mock_service, mock_db_session)
        with patch("src.api.dq.routes.get_tenant_context", return_value=mock_tenant_context):
            client = TestClient(app)
            response = client.get("/api/sync-health/incidents/active")

        assert response.status_code == 200
        data = response.json()

        assert data["has_blocking"] is True

    def test_active_incidents_empty_list(
        self, mock_tenant_context, mock_db_session
    ):
        """Active incidents returns empty list when no incidents."""
        mock_service = MagicMock()
        mock_service.get_open_incidents.return_value = []

        app = create_app_with_overrides(mock_service, mock_db_session)
        with patch("src.api.dq.routes.get_tenant_context", return_value=mock_tenant_context):
            client = TestClient(app)
            response = client.get("/api/sync-health/incidents/active")

        assert response.status_code == 200
        data = response.json()

        assert data["incidents"] == []
        assert data["has_critical"] is False
        assert data["has_blocking"] is False

    def test_active_incidents_includes_status_page_url(
        self, mock_tenant_context, mock_db_session, sample_incident
    ):
        """Active incidents includes status page URL from environment."""
        mock_service = MagicMock()
        mock_service.get_open_incidents.return_value = [sample_incident]
        mock_service.get_incident_scope.return_value = "Meta Ads connector"
        mock_service.get_incident_eta.return_value = "1-2 hours"

        app = create_app_with_overrides(mock_service, mock_db_session)
        with patch("src.api.dq.routes.get_tenant_context", return_value=mock_tenant_context), \
             patch.dict(os.environ, {"STATUS_PAGE_URL": "https://status.example.com"}):
            client = TestClient(app)
            response = client.get("/api/sync-health/incidents/active")

        assert response.status_code == 200
        data = response.json()

        incident = data["incidents"][0]
        assert incident["status_page_url"] == "https://status.example.com"


# =============================================================================
# Test: DQService Helper Methods
# =============================================================================


class TestDQServiceHelpers:
    """Tests for DQService helper methods - Stories 9.5 & 9.6."""

    def test_get_incident_scope_returns_connector_name(self):
        """get_incident_scope returns connector name."""
        from src.api.dq.service import DQService

        mock_db = MagicMock()
        mock_connector = MagicMock()
        mock_connector.connection_name = "Meta Ads"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_connector

        service = DQService(mock_db, "tenant-123")

        mock_incident = MagicMock()
        mock_incident.connector_id = "conn-456"

        scope = service.get_incident_scope(mock_incident)

        assert scope == "Meta Ads connector"

    def test_get_incident_scope_fallback_when_connector_not_found(self):
        """get_incident_scope returns fallback when connector not found."""
        from src.api.dq.service import DQService

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        service = DQService(mock_db, "tenant-123")

        mock_incident = MagicMock()
        mock_incident.connector_id = "unknown-conn"

        scope = service.get_incident_scope(mock_incident)

        assert scope == "Data pipeline"

    def test_get_incident_eta_warning_severity(self):
        """get_incident_eta returns correct ETA for warning severity."""
        from src.api.dq.service import DQService

        mock_db = MagicMock()
        service = DQService(mock_db, "tenant-123")

        mock_incident = MagicMock()
        mock_incident.severity = "warning"

        eta = service.get_incident_eta(mock_incident)

        assert eta == "Expected resolution: 1-2 hours"

    def test_get_incident_eta_high_severity(self):
        """get_incident_eta returns correct ETA for high severity."""
        from src.api.dq.service import DQService

        mock_db = MagicMock()
        service = DQService(mock_db, "tenant-123")

        mock_incident = MagicMock()
        mock_incident.severity = "high"

        eta = service.get_incident_eta(mock_incident)

        assert eta == "Expected resolution: 2-4 hours"

    def test_get_incident_eta_critical_severity(self):
        """get_incident_eta returns correct ETA for critical severity."""
        from src.api.dq.service import DQService

        mock_db = MagicMock()
        service = DQService(mock_db, "tenant-123")

        mock_incident = MagicMock()
        mock_incident.severity = "critical"

        eta = service.get_incident_eta(mock_incident)

        assert eta == "Investigating - updates every 30 minutes"

    def test_get_incident_eta_unknown_severity(self):
        """get_incident_eta returns None for unknown severity."""
        from src.api.dq.service import DQService

        mock_db = MagicMock()
        service = DQService(mock_db, "tenant-123")

        mock_incident = MagicMock()
        mock_incident.severity = "unknown"

        eta = service.get_incident_eta(mock_incident)

        assert eta is None
