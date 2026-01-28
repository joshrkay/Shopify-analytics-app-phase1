"""
Unit tests for OpenRouter client.

Tests cover:
- Client initialization and validation
- Chat completion requests
- Model listing
- Error handling for various HTTP status codes
- Timeout and connection error handling
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from decimal import Decimal

import httpx

from src.integrations.openrouter.client import (
    OpenRouterClient,
    get_openrouter_client,
    DEFAULT_BASE_URL,
)
from src.integrations.openrouter.exceptions import (
    OpenRouterError,
    OpenRouterAuthenticationError,
    OpenRouterRateLimitError,
    OpenRouterConnectionError,
    OpenRouterTimeoutError,
    OpenRouterModelUnavailableError,
    OpenRouterContentFilterError,
)
from src.integrations.openrouter.models import (
    ChatMessage,
    ChatCompletionResponse,
    TokenUsage,
    ModelInfo,
)


# Test fixtures
@pytest.fixture
def mock_env(monkeypatch):
    """Set up mock environment variables."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key-12345")
    monkeypatch.setenv("OPENROUTER_APP_NAME", "Test App")


@pytest.fixture
def client(mock_env):
    """Create a test client instance."""
    return OpenRouterClient()


class TestOpenRouterClientInitialization:
    """Tests for client initialization."""

    def test_init_with_env_vars(self, mock_env):
        """Client should initialize from environment variables."""
        client = OpenRouterClient()
        assert client.api_key == "sk-test-key-12345"
        assert client.base_url == DEFAULT_BASE_URL
        assert client.app_name == "Test App"

    def test_init_with_explicit_params(self, mock_env):
        """Client should prefer explicit parameters over env vars."""
        client = OpenRouterClient(
            api_key="custom-key",
            base_url="https://custom.api.com/v1",
            app_name="Custom App",
        )
        assert client.api_key == "custom-key"
        assert client.base_url == "https://custom.api.com/v1"
        assert client.app_name == "Custom App"

    def test_init_strips_trailing_slash(self, mock_env):
        """Base URL should not have trailing slash."""
        client = OpenRouterClient(base_url="https://openrouter.ai/api/v1/")
        assert client.base_url == "https://openrouter.ai/api/v1"

    def test_init_missing_key_raises(self, monkeypatch):
        """Should raise ValueError if API key is missing."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        with pytest.raises(ValueError, match="API key is required"):
            OpenRouterClient()

    def test_factory_function(self, mock_env):
        """Factory function should create client correctly."""
        client = get_openrouter_client()
        assert client.api_key == "sk-test-key-12345"


class TestOpenRouterClientChatCompletion:
    """Tests for chat completion functionality."""

    @pytest.mark.asyncio
    async def test_chat_completion_success(self, client):
        """Should return completion response on success."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "model": "openai/gpt-4",
            "created": 1704067200,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello! How can I help you?",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 8,
                "total_tokens": 18,
            },
        }

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            messages = [ChatMessage(role="user", content="Hello")]
            response = await client.chat_completion(
                messages=messages,
                model="openai/gpt-4",
            )

            assert response.id == "chatcmpl-123"
            assert response.model == "openai/gpt-4"
            assert response.content == "Hello! How can I help you?"
            assert response.input_tokens == 10
            assert response.output_tokens == 8
            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_completion_with_params(self, client):
        """Should pass parameters correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "model": "openai/gpt-4",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            messages = [ChatMessage(role="user", content="Hi")]
            await client.chat_completion(
                messages=messages,
                model="openai/gpt-4",
                max_tokens=100,
                temperature=0.5,
                top_p=0.9,
                stop=["END"],
            )

            # Verify request body
            call_kwargs = mock_request.call_args
            json_body = call_kwargs.kwargs.get("json", {})
            assert json_body["model"] == "openai/gpt-4"
            assert json_body["max_tokens"] == 100
            assert json_body["temperature"] == 0.5
            assert json_body["top_p"] == 0.9
            assert json_body["stop"] == ["END"]

    @pytest.mark.asyncio
    async def test_chat_completion_auth_failure(self, client):
        """Should raise OpenRouterAuthenticationError on 401."""
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            messages = [ChatMessage(role="user", content="Hello")]
            with pytest.raises(OpenRouterAuthenticationError):
                await client.chat_completion(messages=messages, model="openai/gpt-4")


class TestOpenRouterClientListModels:
    """Tests for model listing."""

    @pytest.mark.asyncio
    async def test_list_models_success(self, client):
        """Should list models successfully."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "openai/gpt-4",
                    "name": "GPT-4",
                    "context_length": 8192,
                    "pricing": {"prompt": "0.00003", "completion": "0.00006"},
                },
                {
                    "id": "anthropic/claude-3-opus",
                    "name": "Claude 3 Opus",
                    "context_length": 200000,
                    "pricing": {"prompt": "0.000015", "completion": "0.000075"},
                },
            ]
        }

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            models = await client.list_models()

            assert len(models) == 2
            assert models[0].id == "openai/gpt-4"
            assert models[0].name == "GPT-4"
            assert models[0].context_length == 8192

    @pytest.mark.asyncio
    async def test_list_models_empty(self, client):
        """Should return empty list when no models available."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            models = await client.list_models()

            assert len(models) == 0


class TestOpenRouterClientHealthCheck:
    """Tests for health check."""

    @pytest.mark.asyncio
    async def test_check_health_success(self, client):
        """Should return True when API is healthy."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            is_healthy = await client.check_health()

            assert is_healthy is True

    @pytest.mark.asyncio
    async def test_check_health_failure(self, client):
        """Should return False when API is unhealthy."""
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = OpenRouterConnectionError("Connection failed")

            is_healthy = await client.check_health()

            assert is_healthy is False


class TestOpenRouterClientErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, client):
        """Should raise OpenRouterRateLimitError on 429."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            with pytest.raises(OpenRouterRateLimitError) as exc_info:
                await client.list_models()

            assert exc_info.value.retry_after == 60

    @pytest.mark.asyncio
    async def test_forbidden_error(self, client):
        """Should raise OpenRouterAuthenticationError on 403."""
        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            with pytest.raises(OpenRouterAuthenticationError) as exc_info:
                await client.list_models()

            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_not_found_error(self, client):
        """Should raise OpenRouterModelUnavailableError on 404."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            with pytest.raises(OpenRouterModelUnavailableError):
                await client.list_models()

    @pytest.mark.asyncio
    async def test_content_filter_error(self, client):
        """Should raise OpenRouterContentFilterError on content policy violation."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": {
                "code": "content_filter",
                "message": "Content blocked by safety filter",
            }
        }

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            messages = [ChatMessage(role="user", content="test")]
            with pytest.raises(OpenRouterContentFilterError):
                await client.chat_completion(messages=messages, model="test")

    @pytest.mark.asyncio
    async def test_generic_server_error(self, client):
        """Should raise OpenRouterError on 5xx errors."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": {"message": "Internal Server Error"}}

        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            with pytest.raises(OpenRouterError) as exc_info:
                await client.list_models()

            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_timeout_error(self, client):
        """Should raise OpenRouterTimeoutError on timeout."""
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = httpx.TimeoutException("Connection timed out")

            with pytest.raises(OpenRouterTimeoutError, match="timeout"):
                await client.list_models()

    @pytest.mark.asyncio
    async def test_connection_error(self, client):
        """Should raise OpenRouterConnectionError on network failure."""
        with patch.object(client._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = httpx.ConnectError("Connection refused")

            with pytest.raises(OpenRouterConnectionError, match="Connection error"):
                await client.list_models()


class TestOpenRouterClientContextManager:
    """Tests for async context manager behavior."""

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self, mock_env):
        """Context manager should close client on exit."""
        async with OpenRouterClient() as client:
            assert client._client is not None

        # After exiting context, client should be closed
        assert client._client.is_closed

    @pytest.mark.asyncio
    async def test_manual_close(self, mock_env):
        """Manual close should work correctly."""
        client = OpenRouterClient()
        await client.close()
        assert client._client.is_closed


class TestOpenRouterModels:
    """Tests for data model parsing."""

    def test_chat_message_to_dict(self):
        """Should convert message to dict correctly."""
        message = ChatMessage(role="user", content="Hello")
        assert message.to_dict() == {"role": "user", "content": "Hello"}

    def test_chat_message_from_dict(self):
        """Should parse message from dict correctly."""
        data = {"role": "assistant", "content": "Hi there"}
        message = ChatMessage.from_dict(data)
        assert message.role == "assistant"
        assert message.content == "Hi there"

    def test_token_usage_from_dict(self):
        """Should parse token usage correctly."""
        data = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        usage = TokenUsage.from_dict(data)
        assert usage.prompt_tokens == 10
        assert usage.completion_tokens == 20
        assert usage.total_tokens == 30

    def test_token_usage_defaults(self):
        """Should use defaults for missing fields."""
        usage = TokenUsage.from_dict({})
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    def test_completion_response_from_dict(self):
        """Should parse completion response correctly."""
        data = {
            "id": "chatcmpl-123",
            "model": "gpt-4",
            "created": 1704067200,
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": "Hello"}}
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }
        response = ChatCompletionResponse.from_dict(data)
        assert response.id == "chatcmpl-123"
        assert response.model == "gpt-4"
        assert response.content == "Hello"
        assert response.input_tokens == 5
        assert response.output_tokens == 1

    def test_completion_response_empty_choices(self):
        """Should handle empty choices gracefully."""
        data = {
            "id": "chatcmpl-123",
            "model": "gpt-4",
            "choices": [],
            "usage": {},
        }
        response = ChatCompletionResponse.from_dict(data)
        assert response.content == ""

    def test_model_info_from_dict(self):
        """Should parse model info correctly."""
        data = {
            "id": "openai/gpt-4",
            "name": "GPT-4",
            "context_length": 8192,
            "pricing": {"prompt": "0.00003", "completion": "0.00006"},
        }
        model = ModelInfo.from_dict(data)
        assert model.id == "openai/gpt-4"
        assert model.name == "GPT-4"
        assert model.context_length == 8192
        assert model.pricing["prompt"] == 0.00003
