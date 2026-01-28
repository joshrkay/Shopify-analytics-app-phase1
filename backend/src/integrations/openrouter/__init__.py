"""
OpenRouter integration for LLM routing.

Provides unified access to multiple LLM providers via OpenRouter API.
"""

from src.integrations.openrouter.client import (
    OpenRouterClient,
    get_openrouter_client,
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
    ChatChoice,
    TokenUsage,
    ChatCompletionResponse,
    ModelInfo,
)

__all__ = [
    # Client
    "OpenRouterClient",
    "get_openrouter_client",
    # Exceptions
    "OpenRouterError",
    "OpenRouterAuthenticationError",
    "OpenRouterRateLimitError",
    "OpenRouterConnectionError",
    "OpenRouterTimeoutError",
    "OpenRouterModelUnavailableError",
    "OpenRouterContentFilterError",
    # Models
    "ChatMessage",
    "ChatChoice",
    "TokenUsage",
    "ChatCompletionResponse",
    "ModelInfo",
]
