"""
Integration tests for LLM Configuration API routes.

Tests cover:
- Model listing endpoints
- Org configuration CRUD
- Prompt template management
- Usage statistics retrieval
- Entitlement checks
"""

import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from main import app
from src.models.llm_routing import (
    LLMModelRegistry,
    LLMOrgConfig,
    LLMPromptTemplate,
    LLMUsageLog,
)
from src.services.billing_entitlements import BillingFeature


@pytest.fixture
def mock_tenant_context():
    """Mock tenant context for authenticated requests."""
    mock_ctx = MagicMock()
    mock_ctx.tenant_id = "test-tenant-123"
    mock_ctx.user_id = "test-user-456"
    mock_ctx.roles = ["admin"]
    return mock_ctx


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    return MagicMock()


@pytest.fixture
def client(mock_tenant_context, mock_db_session):
    """Create test client with mocked dependencies."""
    with patch("src.platform.tenant_context.get_tenant_context", return_value=mock_tenant_context):
        with patch("src.database.session.get_db_session", return_value=mock_db_session):
            yield TestClient(app)


class TestListModelsEndpoint:
    """Tests for GET /api/llm/models endpoint."""

    def test_list_models_entitled(self, client, mock_db_session):
        """Should list models when entitled."""
        # Mock entitlement check
        with patch("src.api.routes.llm_config.BillingEntitlementsService") as mock_entitlements:
            mock_service = MagicMock()
            mock_service.check_feature_entitlement.return_value = MagicMock(is_entitled=True)
            mock_service.get_billing_tier.return_value = "growth"
            mock_entitlements.return_value = mock_service

            # Mock models
            mock_models = [
                MagicMock(
                    model_id="openai/gpt-4",
                    display_name="GPT-4",
                    provider="openai",
                    context_window=8192,
                    max_output_tokens=4096,
                    cost_per_input_token=Decimal("0.00003"),
                    cost_per_output_token=Decimal("0.00006"),
                    capabilities=["chat", "function_calling"],
                    tier_restriction=None,
                    is_enabled=True,
                ),
            ]
            mock_db_session.query.return_value.filter.return_value.all.return_value = mock_models

            response = client.get("/api/llm/models")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["model_id"] == "openai/gpt-4"

    def test_list_models_not_entitled(self, client, mock_db_session):
        """Should return 402 when not entitled."""
        with patch("src.api.routes.llm_config.BillingEntitlementsService") as mock_entitlements:
            mock_service = MagicMock()
            mock_service.check_feature_entitlement.return_value = MagicMock(
                is_entitled=False,
                current_tier="free",
                required_tier="growth",
            )
            mock_entitlements.return_value = mock_service

            response = client.get("/api/llm/models")

            assert response.status_code == 402

    def test_list_models_filtered_by_tier(self, client, mock_db_session):
        """Should filter models by billing tier."""
        with patch("src.api.routes.llm_config.BillingEntitlementsService") as mock_entitlements:
            mock_service = MagicMock()
            mock_service.check_feature_entitlement.return_value = MagicMock(is_entitled=True)
            mock_service.get_billing_tier.return_value = "growth"
            mock_entitlements.return_value = mock_service

            # Mock models - one available, one enterprise-only
            mock_models = [
                MagicMock(
                    model_id="anthropic/claude-3-haiku",
                    display_name="Claude 3 Haiku",
                    provider="anthropic",
                    context_window=200000,
                    max_output_tokens=4096,
                    cost_per_input_token=Decimal("0.000001"),
                    cost_per_output_token=Decimal("0.000003"),
                    capabilities=["chat"],
                    tier_restriction=None,
                    is_enabled=True,
                ),
                MagicMock(
                    model_id="openai/gpt-4-turbo",
                    display_name="GPT-4 Turbo",
                    provider="openai",
                    context_window=128000,
                    max_output_tokens=4096,
                    cost_per_input_token=Decimal("0.00001"),
                    cost_per_output_token=Decimal("0.00003"),
                    capabilities=["chat", "vision"],
                    tier_restriction="enterprise",  # Enterprise only
                    is_enabled=True,
                ),
            ]
            mock_db_session.query.return_value.filter.return_value.all.return_value = mock_models

            response = client.get("/api/llm/models")

            assert response.status_code == 200
            data = response.json()
            # Only haiku should be returned (growth tier can't access enterprise models)
            assert len(data) == 1
            assert data[0]["model_id"] == "anthropic/claude-3-haiku"


class TestOrgConfigEndpoint:
    """Tests for GET/PUT /api/llm/config endpoints."""

    def test_get_config_existing(self, client, mock_db_session):
        """Should return existing org config."""
        with patch("src.api.routes.llm_config.BillingEntitlementsService") as mock_entitlements:
            mock_service = MagicMock()
            mock_service.check_feature_entitlement.return_value = MagicMock(is_entitled=True)
            mock_entitlements.return_value = mock_service

            mock_config = MagicMock()
            mock_config.primary_model_id = "openai/gpt-4"
            mock_config.fallback_model_id = "anthropic/claude-3-haiku"
            mock_config.max_tokens_per_request = 2048
            mock_config.temperature = Decimal("0.7")
            mock_config.monthly_token_budget = 100000

            mock_db_session.query.return_value.filter.return_value.first.return_value = mock_config

            response = client.get("/api/llm/config")

            assert response.status_code == 200
            data = response.json()
            assert data["primary_model_id"] == "openai/gpt-4"
            assert data["fallback_model_id"] == "anthropic/claude-3-haiku"
            assert data["max_tokens_per_request"] == 2048
            assert data["temperature"] == 0.7

    def test_get_config_default(self, client, mock_db_session):
        """Should return defaults when no config exists."""
        with patch("src.api.routes.llm_config.BillingEntitlementsService") as mock_entitlements:
            mock_service = MagicMock()
            mock_service.check_feature_entitlement.return_value = MagicMock(is_entitled=True)
            mock_entitlements.return_value = mock_service

            mock_db_session.query.return_value.filter.return_value.first.return_value = None

            response = client.get("/api/llm/config")

            assert response.status_code == 200
            data = response.json()
            assert data["primary_model_id"] == "anthropic/claude-3-haiku"
            assert data["fallback_model_id"] is None
            assert data["max_tokens_per_request"] == 2048
            assert data["temperature"] == 0.7

    def test_update_config(self, client, mock_db_session):
        """Should update org config."""
        with patch("src.api.routes.llm_config.BillingEntitlementsService") as mock_entitlements:
            mock_service = MagicMock()
            mock_service.check_feature_entitlement.return_value = MagicMock(is_entitled=True)
            mock_entitlements.return_value = mock_service

            # Mock model validation
            mock_model = MagicMock()
            mock_model.model_id = "openai/gpt-4"
            mock_model.is_enabled = True

            # First query for model validation, second for existing config
            mock_db_session.query.return_value.filter.return_value.first.side_effect = [
                mock_model,  # Primary model validation
                None,        # No existing config
            ]

            response = client.put(
                "/api/llm/config",
                json={
                    "primary_model_id": "openai/gpt-4",
                    "max_tokens_per_request": 4096,
                    "temperature": 0.5,
                },
            )

            assert response.status_code == 200
            # Verify config was added to session
            mock_db_session.add.assert_called_once()

    def test_update_config_invalid_model(self, client, mock_db_session):
        """Should return 400 for invalid model ID."""
        with patch("src.api.routes.llm_config.BillingEntitlementsService") as mock_entitlements:
            mock_service = MagicMock()
            mock_service.check_feature_entitlement.return_value = MagicMock(is_entitled=True)
            mock_entitlements.return_value = mock_service

            # Model not found
            mock_db_session.query.return_value.filter.return_value.first.return_value = None

            response = client.put(
                "/api/llm/config",
                json={"primary_model_id": "nonexistent/model"},
            )

            assert response.status_code == 400
            assert "Invalid primary model" in response.json()["detail"]


class TestPromptTemplatesEndpoint:
    """Tests for prompt template endpoints."""

    def test_list_templates(self, client, mock_db_session):
        """Should list available templates."""
        with patch("src.api.routes.llm_config.BillingEntitlementsService") as mock_entitlements:
            mock_service = MagicMock()
            mock_service.check_feature_entitlement.return_value = MagicMock(is_entitled=True)
            mock_entitlements.return_value = mock_service

            mock_templates = [
                MagicMock(
                    id="template-1",
                    template_key="insight_analysis",
                    version=1,
                    template_content="Analyze: {{metric}}",
                    variables=["metric"],
                    is_active=True,
                    is_system=True,
                    created_at=datetime.now(timezone.utc),
                ),
            ]
            mock_db_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_templates

            response = client.get("/api/llm/templates")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["template_key"] == "insight_analysis"

    def test_get_template(self, client, mock_db_session):
        """Should get specific template."""
        with patch("src.api.routes.llm_config.BillingEntitlementsService") as mock_entitlements:
            mock_service = MagicMock()
            mock_service.check_feature_entitlement.return_value = MagicMock(is_entitled=True)
            mock_entitlements.return_value = mock_service

            mock_template = MagicMock(
                id="template-1",
                template_key="insight_analysis",
                version=1,
                template_content="Analyze: {{metric}}",
                variables=["metric"],
                is_active=True,
                is_system=True,
                created_at=datetime.now(timezone.utc),
            )
            mock_db_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_template

            response = client.get("/api/llm/templates/insight_analysis")

            assert response.status_code == 200
            data = response.json()
            assert data["template_key"] == "insight_analysis"

    def test_get_template_not_found(self, client, mock_db_session):
        """Should return 404 when template not found."""
        with patch("src.api.routes.llm_config.BillingEntitlementsService") as mock_entitlements:
            mock_service = MagicMock()
            mock_service.check_feature_entitlement.return_value = MagicMock(is_entitled=True)
            mock_entitlements.return_value = mock_service

            mock_db_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

            response = client.get("/api/llm/templates/nonexistent")

            assert response.status_code == 404

    def test_create_template_enterprise_only(self, client, mock_db_session):
        """Should require enterprise tier for custom templates."""
        with patch("src.api.routes.llm_config.BillingEntitlementsService") as mock_entitlements:
            mock_service = MagicMock()
            mock_service.check_feature_entitlement.return_value = MagicMock(is_entitled=True)
            mock_service.get_billing_tier.return_value = "growth"  # Not enterprise
            mock_entitlements.return_value = mock_service

            response = client.post(
                "/api/llm/templates",
                json={
                    "template_key": "custom_template",
                    "template_content": "Custom: {{var}}",
                    "variables": ["var"],
                },
            )

            assert response.status_code == 402
            assert "Enterprise" in response.json()["detail"]


class TestUsageStatsEndpoint:
    """Tests for usage statistics endpoints."""

    def test_get_usage_stats(self, client, mock_db_session):
        """Should return usage statistics."""
        with patch("src.api.routes.llm_config.BillingEntitlementsService") as mock_entitlements:
            mock_service = MagicMock()
            mock_service.check_feature_entitlement.return_value = MagicMock(is_entitled=True)
            mock_entitlements.return_value = mock_service

            with patch("src.api.routes.llm_config.LLMRoutingService") as mock_routing:
                mock_routing_instance = MagicMock()
                mock_routing_instance.get_usage_stats.return_value = {
                    "total_tokens": 10000,
                    "total_cost_usd": 0.50,
                    "request_count": 100,
                    "success_count": 95,
                    "fallback_count": 5,
                    "period_days": 30,
                }
                mock_routing.return_value = mock_routing_instance

                response = client.get("/api/llm/usage/stats?days=30")

                assert response.status_code == 200
                data = response.json()
                assert data["total_tokens"] == 10000
                assert data["request_count"] == 100

    def test_list_usage_logs(self, client, mock_db_session):
        """Should list usage logs."""
        with patch("src.api.routes.llm_config.BillingEntitlementsService") as mock_entitlements:
            mock_service = MagicMock()
            mock_service.check_feature_entitlement.return_value = MagicMock(is_entitled=True)
            mock_entitlements.return_value = mock_service

            mock_logs = [
                MagicMock(
                    id="log-1",
                    model_id="openai/gpt-4",
                    prompt_template_key="insight_analysis",
                    input_tokens=100,
                    output_tokens=50,
                    total_tokens=150,
                    latency_ms=500,
                    cost_usd=Decimal("0.005"),
                    was_fallback=False,
                    response_status="success",
                    created_at=datetime.now(timezone.utc),
                ),
            ]
            mock_db_session.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = mock_logs
            mock_db_session.query.return_value.filter.return_value.count.return_value = 1

            response = client.get("/api/llm/usage/logs")

            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 1
            assert len(data["logs"]) == 1
            assert data["logs"][0]["model_id"] == "openai/gpt-4"
