"""
Unit tests for AI Insights API endpoints.

Tests cover:
- List insights with filtering and pagination
- Get single insight by ID
- Mark insight as read
- Dismiss insight
- Batch mark as read
- Entitlement enforcement (402 for unentitled tenants)
- Tenant isolation (404 for cross-tenant access)

Story 8.1 - AI Insight Generation (Read-Only Analytics)
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.testclient import TestClient

from src.api.routes.insights import (
    router,
    InsightResponse,
    InsightsListResponse,
    InsightActionResponse,
    SupportingMetricResponse,
    _insight_to_response,
    check_ai_insights_entitlement,
)
from src.models.ai_insight import AIInsight, InsightType, InsightSeverity
from src.platform.tenant_context import TenantContext


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_insight():
    """Create a sample AIInsight instance for testing."""
    insight = AIInsight(
        id="insight-123",
        tenant_id="tenant-1",
        insight_type=InsightType.SPEND_ANOMALY,
        severity=InsightSeverity.WARNING,
        summary="Marketing spend increased by 25% week-over-week",
        supporting_metrics=[
            {
                "metric": "spend",
                "current_value": 12500.0,
                "prior_value": 10000.0,
                "delta": 2500.0,
                "delta_pct": 25.0,
                "timeframe": "weekly",
            }
        ],
        confidence_score=0.85,
        period_type="weekly",
        period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        period_end=datetime(2024, 1, 7, tzinfo=timezone.utc),
        comparison_type="week_over_week",
        platform="facebook",
        campaign_id="campaign-abc",
        currency="USD",
        generated_at=datetime(2024, 1, 8, tzinfo=timezone.utc),
        job_id="job-456",
        content_hash="abc123def456",
        is_read=0,
        is_dismissed=0,
    )
    return insight


@pytest.fixture
def sample_insights():
    """Create multiple sample insights for list testing."""
    base_time = datetime(2024, 1, 8, tzinfo=timezone.utc)
    insights = []

    for i in range(5):
        insight = AIInsight(
            id=f"insight-{i}",
            tenant_id="tenant-1",
            insight_type=InsightType.SPEND_ANOMALY if i % 2 == 0 else InsightType.ROAS_CHANGE,
            severity=InsightSeverity.WARNING if i < 3 else InsightSeverity.INFO,
            summary=f"Test insight {i}",
            supporting_metrics=[
                {
                    "metric": "test",
                    "current_value": 100.0,
                    "prior_value": 80.0,
                    "delta": 20.0,
                    "delta_pct": 25.0,
                    "timeframe": "weekly",
                }
            ],
            confidence_score=0.8,
            period_type="weekly",
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 1, 7, tzinfo=timezone.utc),
            comparison_type="week_over_week",
            generated_at=base_time - timedelta(hours=i),
            content_hash=f"hash-{i}",
            is_read=0,
            is_dismissed=0,
        )
        insights.append(insight)

    return insights


@pytest.fixture
def mock_tenant_context():
    """Create a mock tenant context."""
    return TenantContext(
        tenant_id="tenant-1",
        user_id="user-1",
        roles=["admin"],
        org_id="org-1",
    )


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    return MagicMock()


# =============================================================================
# Response Model Conversion Tests
# =============================================================================


class TestInsightToResponse:
    """Tests for _insight_to_response helper function."""

    def test_converts_insight_to_response(self, sample_insight):
        """Insight model is correctly converted to response model."""
        response = _insight_to_response(sample_insight)

        assert isinstance(response, InsightResponse)
        assert response.insight_id == "insight-123"
        assert response.insight_type == "spend_anomaly"
        assert response.severity == "warning"
        assert response.summary == "Marketing spend increased by 25% week-over-week"
        assert response.confidence_score == 0.85
        assert response.period_type == "weekly"
        assert response.comparison_type == "week_over_week"
        assert response.platform == "facebook"
        assert response.campaign_id == "campaign-abc"
        assert response.currency == "USD"
        assert response.is_read is False
        assert response.is_dismissed is False

    def test_converts_supporting_metrics(self, sample_insight):
        """Supporting metrics are correctly converted."""
        response = _insight_to_response(sample_insight)

        assert len(response.supporting_metrics) == 1
        metric = response.supporting_metrics[0]
        assert isinstance(metric, SupportingMetricResponse)
        assert metric.metric == "spend"
        assert metric.current_value == 12500.0
        assert metric.prior_value == 10000.0
        assert metric.delta == 2500.0
        assert metric.delta_pct == 25.0
        assert metric.timeframe == "weekly"

    def test_handles_empty_supporting_metrics(self, sample_insight):
        """Empty supporting metrics are handled gracefully."""
        sample_insight.supporting_metrics = None
        response = _insight_to_response(sample_insight)
        assert response.supporting_metrics == []

        sample_insight.supporting_metrics = []
        response = _insight_to_response(sample_insight)
        assert response.supporting_metrics == []

    def test_handles_is_read_as_integer(self, sample_insight):
        """is_read integer values are converted to boolean."""
        sample_insight.is_read = 1
        response = _insight_to_response(sample_insight)
        assert response.is_read is True

        sample_insight.is_read = 0
        response = _insight_to_response(sample_insight)
        assert response.is_read is False

    def test_handles_is_dismissed_as_integer(self, sample_insight):
        """is_dismissed integer values are converted to boolean."""
        sample_insight.is_dismissed = 1
        response = _insight_to_response(sample_insight)
        assert response.is_dismissed is True

        sample_insight.is_dismissed = 0
        response = _insight_to_response(sample_insight)
        assert response.is_dismissed is False


# =============================================================================
# API Endpoint Tests
# =============================================================================


class TestListInsightsEndpoint:
    """Tests for GET /api/insights endpoint."""

    def test_list_insights_returns_insights(
        self, mock_tenant_context, mock_db_session, sample_insights
    ):
        """List endpoint returns insights for tenant."""
        app = FastAPI()
        app.include_router(router)

        # Configure mock query
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.count.return_value = len(sample_insights)
        mock_query.all.return_value = sample_insights
        mock_db_session.query.return_value = mock_query

        # Override dependencies
        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            response = client.get("/api/insights")

        assert response.status_code == 200
        data = response.json()

        assert "insights" in data
        assert "total" in data
        assert "has_more" in data
        assert data["total"] == len(sample_insights)

    def test_list_insights_response_format(
        self, mock_tenant_context, mock_db_session, sample_insights
    ):
        """List endpoint returns correctly formatted response."""
        app = FastAPI()
        app.include_router(router)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.count.return_value = len(sample_insights)
        mock_query.all.return_value = sample_insights
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            response = client.get("/api/insights")

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert isinstance(data["insights"], list)
        assert isinstance(data["total"], int)
        assert isinstance(data["has_more"], bool)

        # Verify insight structure
        if data["insights"]:
            insight = data["insights"][0]
            assert "insight_id" in insight
            assert "insight_type" in insight
            assert "severity" in insight
            assert "summary" in insight
            assert "supporting_metrics" in insight
            assert "confidence_score" in insight
            assert "is_read" in insight
            assert "is_dismissed" in insight


class TestEntitlementEnforcement:
    """Tests for entitlement enforcement on API endpoints."""

    def test_returns_402_when_not_entitled(self, mock_tenant_context):
        """Endpoint returns 402 when tenant not entitled to AI insights."""
        app = FastAPI()
        app.include_router(router)

        # Override entitlement to raise 402
        def raise_402():
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="AI Insights requires a growth plan",
            )

        app.dependency_overrides[check_ai_insights_entitlement] = raise_402

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/insights")

        assert response.status_code == 402
        assert "requires" in response.json()["detail"].lower()


class TestGetInsightEndpoint:
    """Tests for GET /api/insights/{insight_id} endpoint."""

    def test_get_insight_returns_insight(
        self, mock_tenant_context, mock_db_session, sample_insight
    ):
        """Get endpoint returns insight by ID."""
        app = FastAPI()
        app.include_router(router)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = sample_insight
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            response = client.get(f"/api/insights/{sample_insight.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["insight_id"] == sample_insight.id
        assert data["insight_type"] == "spend_anomaly"

    def test_get_insight_returns_404_when_not_found(
        self, mock_tenant_context, mock_db_session
    ):
        """Get endpoint returns 404 when insight not found."""
        app = FastAPI()
        app.include_router(router)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            response = client.get("/api/insights/nonexistent-id")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestMarkInsightReadEndpoint:
    """Tests for PATCH /api/insights/{insight_id}/read endpoint."""

    def test_mark_read_returns_success(
        self, mock_tenant_context, mock_db_session, sample_insight
    ):
        """Mark read endpoint returns success response."""
        app = FastAPI()
        app.include_router(router)

        # Add mock methods
        sample_insight.mark_read = MagicMock()

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = sample_insight
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            response = client.patch(f"/api/insights/{sample_insight.id}/read")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["insight_id"] == sample_insight.id

    def test_mark_read_calls_mark_read_method(
        self, mock_tenant_context, mock_db_session, sample_insight
    ):
        """Mark read endpoint calls insight.mark_read()."""
        app = FastAPI()
        app.include_router(router)

        sample_insight.mark_read = MagicMock()

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = sample_insight
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            client.patch(f"/api/insights/{sample_insight.id}/read")

        sample_insight.mark_read.assert_called_once()


class TestDismissInsightEndpoint:
    """Tests for PATCH /api/insights/{insight_id}/dismiss endpoint."""

    def test_dismiss_returns_success(
        self, mock_tenant_context, mock_db_session, sample_insight
    ):
        """Dismiss endpoint returns success response."""
        app = FastAPI()
        app.include_router(router)

        sample_insight.mark_dismissed = MagicMock()

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = sample_insight
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            response = client.patch(f"/api/insights/{sample_insight.id}/dismiss")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["insight_id"] == sample_insight.id

    def test_dismiss_calls_mark_dismissed_method(
        self, mock_tenant_context, mock_db_session, sample_insight
    ):
        """Dismiss endpoint calls insight.mark_dismissed()."""
        app = FastAPI()
        app.include_router(router)

        sample_insight.mark_dismissed = MagicMock()

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = sample_insight
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            client.patch(f"/api/insights/{sample_insight.id}/dismiss")

        sample_insight.mark_dismissed.assert_called_once()


class TestBatchMarkReadEndpoint:
    """Tests for POST /api/insights/batch/read endpoint."""

    def test_batch_read_returns_updated_count(
        self, mock_tenant_context, mock_db_session
    ):
        """Batch read endpoint returns count of updated insights."""
        app = FastAPI()
        app.include_router(router)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.update.return_value = 3
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            response = client.post(
                "/api/insights/batch/read",
                json=["insight-1", "insight-2", "insight-3"],
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["updated"] == 3

    def test_batch_read_rejects_empty_list(
        self, mock_tenant_context, mock_db_session
    ):
        """Batch read endpoint rejects empty insight list."""
        app = FastAPI()
        app.include_router(router)

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            response = client.post("/api/insights/batch/read", json=[])

        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_batch_read_rejects_too_many_insights(
        self, mock_tenant_context, mock_db_session
    ):
        """Batch read endpoint rejects more than 100 insights."""
        app = FastAPI()
        app.include_router(router)

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            insight_ids = [f"insight-{i}" for i in range(101)]
            response = client.post("/api/insights/batch/read", json=insight_ids)

        assert response.status_code == 400
        assert "100" in response.json()["detail"]


class TestTenantIsolation:
    """Tests for tenant isolation in API endpoints."""

    def test_insights_filtered_by_tenant(
        self, mock_tenant_context, mock_db_session, sample_insights
    ):
        """List endpoint only returns insights for authenticated tenant."""
        app = FastAPI()
        app.include_router(router)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.count.return_value = len(sample_insights)
        mock_query.all.return_value = sample_insights
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            client.get("/api/insights")

        # Verify filter was called (tenant isolation check)
        assert mock_query.filter.called

    def test_cross_tenant_access_returns_404(
        self, mock_db_session
    ):
        """Accessing insight from different tenant returns 404."""
        app = FastAPI()
        app.include_router(router)

        tenant1_ctx = TenantContext(
            tenant_id="tenant-1",
            user_id="user-1",
            roles=["admin"],
            org_id="org-1",
        )

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None  # Not found for this tenant
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=tenant1_ctx
        ):
            client = TestClient(app)
            response = client.get("/api/insights/insight-from-other-tenant")

        assert response.status_code == 404


class TestFilteringAndPagination:
    """Tests for filtering and pagination parameters."""

    def test_filter_by_insight_type(
        self, mock_tenant_context, mock_db_session, sample_insights
    ):
        """Filter by insight_type parameter works."""
        app = FastAPI()
        app.include_router(router)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.count.return_value = len(sample_insights)
        mock_query.all.return_value = sample_insights
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            response = client.get("/api/insights?insight_type=spend_anomaly")

        assert response.status_code == 200
        assert mock_query.filter.called

    def test_filter_by_severity(
        self, mock_tenant_context, mock_db_session, sample_insights
    ):
        """Filter by severity parameter works."""
        app = FastAPI()
        app.include_router(router)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.count.return_value = len(sample_insights)
        mock_query.all.return_value = sample_insights
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            response = client.get("/api/insights?severity=warning")

        assert response.status_code == 200
        assert mock_query.filter.called

    def test_invalid_insight_type_returns_400(
        self, mock_tenant_context, mock_db_session
    ):
        """Invalid insight_type returns 400 error."""
        app = FastAPI()
        app.include_router(router)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            response = client.get("/api/insights?insight_type=invalid_type")

        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    def test_invalid_severity_returns_400(
        self, mock_tenant_context, mock_db_session
    ):
        """Invalid severity returns 400 error."""
        app = FastAPI()
        app.include_router(router)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.count.return_value = 0
        mock_query.all.return_value = []
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            response = client.get("/api/insights?severity=invalid_severity")

        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    def test_pagination_parameters(
        self, mock_tenant_context, mock_db_session, sample_insights
    ):
        """Pagination parameters (limit, offset) work correctly."""
        app = FastAPI()
        app.include_router(router)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.count.return_value = len(sample_insights)
        mock_query.all.return_value = sample_insights
        mock_db_session.query.return_value = mock_query

        app.dependency_overrides[check_ai_insights_entitlement] = lambda: mock_db_session

        with patch(
            "src.api.routes.insights.get_tenant_context", return_value=mock_tenant_context
        ):
            client = TestClient(app)
            response = client.get("/api/insights?limit=10&offset=20")

        assert response.status_code == 200
        mock_query.offset.assert_called_with(20)
        # limit is called with limit + 1 to check has_more
        mock_query.limit.assert_called_with(11)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
