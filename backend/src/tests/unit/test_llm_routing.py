"""
Unit tests for LLM routing service and models.

Tests cover:
- LLM routing service initialization
- Model selection and fallback logic
- Prompt template rendering
- Usage logging
- Cost calculation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal
from datetime import datetime, timezone

from src.models.llm_routing import (
    LLMModelRegistry,
    LLMOrgConfig,
    LLMPromptTemplate,
    LLMUsageLog,
    LLMResponseStatus,
)
from src.services.llm_routing_service import (
    LLMRoutingService,
    LLMRoutingError,
    LLMCompletionResult,
)
from src.integrations.openrouter import (
    ChatMessage,
    ChatCompletionResponse,
    TokenUsage,
    ChatChoice,
    OpenRouterRateLimitError,
    OpenRouterTimeoutError,
)


class TestLLMModelRegistry:
    """Tests for LLMModelRegistry model."""

    def test_has_capability_true(self):
        """Should return True when model has capability."""
        model = LLMModelRegistry(
            model_id="test/model",
            display_name="Test Model",
            provider="test",
            capabilities=["chat", "function_calling"],
        )
        assert model.has_capability("chat") is True
        assert model.has_capability("function_calling") is True

    def test_has_capability_false(self):
        """Should return False when model lacks capability."""
        model = LLMModelRegistry(
            model_id="test/model",
            display_name="Test Model",
            provider="test",
            capabilities=["chat"],
        )
        assert model.has_capability("vision") is False

    def test_has_capability_empty(self):
        """Should handle empty capabilities."""
        model = LLMModelRegistry(
            model_id="test/model",
            display_name="Test Model",
            provider="test",
            capabilities=None,
        )
        assert model.has_capability("chat") is False

    def test_calculate_cost(self):
        """Should calculate cost correctly."""
        model = LLMModelRegistry(
            model_id="test/model",
            display_name="Test Model",
            provider="test",
            cost_per_input_token=Decimal("0.00001"),
            cost_per_output_token=Decimal("0.00003"),
        )
        cost = model.calculate_cost(input_tokens=100, output_tokens=50)
        # 100 * 0.00001 + 50 * 0.00003 = 0.001 + 0.0015 = 0.0025
        assert cost == Decimal("0.0025")

    def test_calculate_cost_zero_tokens(self):
        """Should handle zero tokens."""
        model = LLMModelRegistry(
            model_id="test/model",
            display_name="Test Model",
            provider="test",
            cost_per_input_token=Decimal("0.00001"),
            cost_per_output_token=Decimal("0.00003"),
        )
        cost = model.calculate_cost(input_tokens=0, output_tokens=0)
        assert cost == Decimal("0")


class TestLLMPromptTemplate:
    """Tests for LLMPromptTemplate model."""

    def test_render_simple(self):
        """Should render simple template correctly."""
        template = LLMPromptTemplate(
            template_key="test",
            template_content="Hello {{name}}!",
            variables=["name"],
        )
        result = template.render({"name": "World"})
        assert result == "Hello World!"

    def test_render_multiple_variables(self):
        """Should render multiple variables correctly."""
        template = LLMPromptTemplate(
            template_key="test",
            template_content="{{greeting}} {{name}}, your score is {{score}}.",
            variables=["greeting", "name", "score"],
        )
        result = template.render({
            "greeting": "Hello",
            "name": "Alice",
            "score": 100,
        })
        assert result == "Hello Alice, your score is 100."

    def test_render_missing_variable_left_as_is(self):
        """Should leave missing variables as-is."""
        template = LLMPromptTemplate(
            template_key="test",
            template_content="Hello {{name}}, your role is {{role}}.",
            variables=["name", "role"],
        )
        result = template.render({"name": "Bob"})
        assert result == "Hello Bob, your role is {{role}}."

    def test_render_extra_variables_ignored(self):
        """Should ignore extra variables not in template."""
        template = LLMPromptTemplate(
            template_key="test",
            template_content="Hello {{name}}!",
            variables=["name"],
        )
        result = template.render({"name": "World", "extra": "ignored"})
        assert result == "Hello World!"


class TestLLMUsageLog:
    """Tests for LLMUsageLog model."""

    def test_create_usage_log(self):
        """Should create usage log with all fields."""
        log = LLMUsageLog(
            tenant_id="tenant-123",
            model_id="openai/gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            latency_ms=500,
            cost_usd=Decimal("0.005"),
            response_status=LLMResponseStatus.SUCCESS.value,
        )
        assert log.tenant_id == "tenant-123"
        assert log.model_id == "openai/gpt-4"
        assert log.total_tokens == 150
        assert log.response_status == "success"


class TestLLMRoutingServiceInitialization:
    """Tests for LLMRoutingService initialization."""

    def test_init_requires_tenant_id(self):
        """Should raise ValueError if tenant_id is missing."""
        mock_session = MagicMock()
        with pytest.raises(ValueError, match="tenant_id is required"):
            LLMRoutingService(mock_session, tenant_id="")

    def test_init_success(self):
        """Should initialize with valid parameters."""
        mock_session = MagicMock()
        service = LLMRoutingService(mock_session, tenant_id="tenant-123")
        assert service.tenant_id == "tenant-123"
        assert service.db == mock_session


class TestLLMRoutingServiceModelSelection:
    """Tests for model selection logic."""

    def test_get_primary_model_from_config(self):
        """Should return primary model from org config."""
        mock_session = MagicMock()

        # Mock org config
        mock_config = LLMOrgConfig(
            tenant_id="tenant-123",
            primary_model_id="openai/gpt-4",
        )

        # Mock model registry
        mock_model = LLMModelRegistry(
            model_id="openai/gpt-4",
            display_name="GPT-4",
            provider="openai",
            is_enabled=True,
        )

        mock_session.query.return_value.filter.return_value.first.side_effect = [
            mock_config,  # First call for org config
            mock_model,   # Second call for model registry
        ]

        service = LLMRoutingService(mock_session, tenant_id="tenant-123")
        model = service.get_primary_model()

        assert model.model_id == "openai/gpt-4"

    def test_get_primary_model_fallback_to_default(self):
        """Should fall back to default model when no config."""
        mock_session = MagicMock()

        # Mock default model
        mock_model = LLMModelRegistry(
            model_id="anthropic/claude-3-haiku",
            display_name="Claude 3 Haiku",
            provider="anthropic",
            is_enabled=True,
        )

        mock_session.query.return_value.filter.return_value.first.side_effect = [
            None,        # No org config
            mock_model,  # Default model
        ]

        service = LLMRoutingService(mock_session, tenant_id="tenant-123")
        model = service.get_primary_model()

        assert model.model_id == "anthropic/claude-3-haiku"

    def test_get_primary_model_raises_when_no_model(self):
        """Should raise LLMRoutingError when no model available."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        service = LLMRoutingService(mock_session, tenant_id="tenant-123")

        with pytest.raises(LLMRoutingError, match="No LLM model available"):
            service.get_primary_model()

    def test_get_fallback_model(self):
        """Should return fallback model from org config."""
        mock_session = MagicMock()

        mock_config = LLMOrgConfig(
            tenant_id="tenant-123",
            primary_model_id="openai/gpt-4",
            fallback_model_id="anthropic/claude-3-haiku",
        )

        mock_model = LLMModelRegistry(
            model_id="anthropic/claude-3-haiku",
            display_name="Claude 3 Haiku",
            provider="anthropic",
            is_enabled=True,
        )

        mock_session.query.return_value.filter.return_value.first.side_effect = [
            mock_config,
            mock_model,
        ]

        service = LLMRoutingService(mock_session, tenant_id="tenant-123")
        fallback = service.get_fallback_model()

        assert fallback.model_id == "anthropic/claude-3-haiku"

    def test_get_fallback_model_returns_none(self):
        """Should return None when no fallback configured."""
        mock_session = MagicMock()

        mock_config = LLMOrgConfig(
            tenant_id="tenant-123",
            primary_model_id="openai/gpt-4",
            fallback_model_id=None,
        )

        mock_session.query.return_value.filter.return_value.first.return_value = mock_config

        service = LLMRoutingService(mock_session, tenant_id="tenant-123")
        fallback = service.get_fallback_model()

        assert fallback is None


class TestLLMRoutingServicePromptTemplates:
    """Tests for prompt template retrieval."""

    def test_get_prompt_template_tenant_specific(self):
        """Should prefer tenant-specific template."""
        mock_session = MagicMock()

        mock_template = LLMPromptTemplate(
            tenant_id="tenant-123",
            template_key="test_template",
            version=1,
            template_content="Tenant template: {{var}}",
            is_active=True,
            is_system=False,
        )

        mock_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_template

        service = LLMRoutingService(mock_session, tenant_id="tenant-123")
        template = service.get_prompt_template("test_template")

        assert template.template_content == "Tenant template: {{var}}"

    def test_get_prompt_template_fallback_to_system(self):
        """Should fall back to system template when no tenant template."""
        mock_session = MagicMock()

        system_template = LLMPromptTemplate(
            tenant_id=None,
            template_key="test_template",
            version=1,
            template_content="System template: {{var}}",
            is_active=True,
            is_system=True,
        )

        # First query returns None (no tenant template), second returns system
        mock_session.query.return_value.filter.return_value.order_by.return_value.first.side_effect = [
            None,
            system_template,
        ]

        service = LLMRoutingService(mock_session, tenant_id="tenant-123")
        template = service.get_prompt_template("test_template")

        assert template.template_content == "System template: {{var}}"

    def test_render_template(self):
        """Should render template with variables."""
        mock_session = MagicMock()

        mock_template = LLMPromptTemplate(
            template_key="test",
            template_content="Hello {{name}}!",
            is_active=True,
        )

        mock_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_template

        service = LLMRoutingService(mock_session, tenant_id="tenant-123")
        result = service.render_template("test", {"name": "World"})

        assert result == "Hello World!"

    def test_render_template_not_found(self):
        """Should return None when template not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        service = LLMRoutingService(mock_session, tenant_id="tenant-123")
        result = service.render_template("nonexistent", {})

        assert result is None


class TestLLMRoutingServiceComplete:
    """Tests for completion with fallback."""

    @pytest.mark.asyncio
    async def test_complete_success(self):
        """Should complete successfully with primary model."""
        mock_session = MagicMock()

        # Mock model
        mock_model = LLMModelRegistry(
            model_id="openai/gpt-4",
            display_name="GPT-4",
            provider="openai",
            cost_per_input_token=Decimal("0.00001"),
            cost_per_output_token=Decimal("0.00003"),
            is_enabled=True,
        )

        # Mock client response
        mock_response = ChatCompletionResponse(
            id="chat-123",
            model="openai/gpt-4",
            choices=[ChatChoice(index=0, message=ChatMessage(role="assistant", content="Hello!"))],
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

        mock_client = AsyncMock()
        mock_client.chat_completion.return_value = mock_response

        # Setup mock queries
        mock_session.query.return_value.filter.return_value.first.side_effect = [
            None,        # No org config
            mock_model,  # Default model
        ]

        service = LLMRoutingService(mock_session, tenant_id="tenant-123", client=mock_client)

        messages = [ChatMessage(role="user", content="Hi")]
        result = await service.complete(messages)

        assert result.content == "Hello!"
        assert result.model_id == "openai/gpt-4"
        assert result.was_fallback is False
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    @pytest.mark.asyncio
    async def test_complete_with_fallback(self):
        """Should use fallback model when primary fails."""
        mock_session = MagicMock()

        # Mock models
        primary_model = LLMModelRegistry(
            model_id="openai/gpt-4",
            display_name="GPT-4",
            provider="openai",
            cost_per_input_token=Decimal("0.00001"),
            cost_per_output_token=Decimal("0.00003"),
            is_enabled=True,
        )

        fallback_model = LLMModelRegistry(
            model_id="anthropic/claude-3-haiku",
            display_name="Claude 3 Haiku",
            provider="anthropic",
            cost_per_input_token=Decimal("0.000001"),
            cost_per_output_token=Decimal("0.000003"),
            is_enabled=True,
        )

        mock_config = LLMOrgConfig(
            tenant_id="tenant-123",
            primary_model_id="openai/gpt-4",
            fallback_model_id="anthropic/claude-3-haiku",
        )

        # Mock client: first call fails, second succeeds
        mock_response = ChatCompletionResponse(
            id="chat-123",
            model="anthropic/claude-3-haiku",
            choices=[ChatChoice(index=0, message=ChatMessage(role="assistant", content="Fallback response!"))],
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

        mock_client = AsyncMock()
        mock_client.chat_completion.side_effect = [
            OpenRouterRateLimitError("Rate limited"),
            mock_response,
        ]

        # Setup mock queries
        mock_session.query.return_value.filter.return_value.first.side_effect = [
            mock_config,     # Org config
            primary_model,   # Primary model
            mock_config,     # Org config again for fallback
            fallback_model,  # Fallback model
        ]

        service = LLMRoutingService(mock_session, tenant_id="tenant-123", client=mock_client)

        messages = [ChatMessage(role="user", content="Hi")]
        result = await service.complete(messages)

        assert result.content == "Fallback response!"
        assert result.model_id == "anthropic/claude-3-haiku"
        assert result.was_fallback is True
        assert result.fallback_reason == "OpenRouterRateLimitError"


class TestLLMRoutingServiceUsageStats:
    """Tests for usage statistics."""

    def test_get_usage_stats(self):
        """Should return usage statistics."""
        mock_session = MagicMock()

        # Mock aggregation result
        mock_result = MagicMock()
        mock_result.total_tokens = 10000
        mock_result.total_cost = Decimal("0.50")
        mock_result.request_count = 100
        mock_result.success_count = 95
        mock_result.fallback_count = 5

        mock_session.query.return_value.filter.return_value.first.return_value = mock_result

        service = LLMRoutingService(mock_session, tenant_id="tenant-123")
        stats = service.get_usage_stats(days=30)

        assert stats["total_tokens"] == 10000
        assert stats["total_cost_usd"] == 0.50
        assert stats["request_count"] == 100
        assert stats["success_count"] == 95
        assert stats["fallback_count"] == 5
        assert stats["period_days"] == 30
