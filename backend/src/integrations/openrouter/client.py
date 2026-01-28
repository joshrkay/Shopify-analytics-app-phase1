"""
OpenRouter API client for LLM routing.

This client handles:
- Chat completions via OpenRouter's unified API
- Model availability checks
- Rate limiting and error handling

Documentation: https://openrouter.ai/docs

SECURITY:
- API key must be stored securely and never logged
- No sensitive data in request metadata
"""

import logging
import os
import time
from typing import Optional, List, Dict, Any

import httpx

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
    ModelInfo,
)

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0


class OpenRouterClient:
    """
    Async client for OpenRouter API.

    This client provides access to multiple LLM providers through
    OpenRouter's unified API. All methods are async and should be
    used with async/await.

    SECURITY: API key must be stored securely and never logged.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        app_name: Optional[str] = None,
        site_url: Optional[str] = None,
    ):
        """
        Initialize OpenRouter client.

        Args:
            api_key: OpenRouter API key (default: from OPENROUTER_API_KEY env)
            base_url: API base URL (default: https://openrouter.ai/api/v1)
            timeout: Request timeout in seconds
            connect_timeout: Connection timeout in seconds
            app_name: Application name for OpenRouter headers
            site_url: Site URL for OpenRouter headers
        """
        self.base_url = (
            base_url or os.getenv("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.app_name = app_name or os.getenv("OPENROUTER_APP_NAME", "AI Growth Analytics")
        self.site_url = site_url or os.getenv("OPENROUTER_SITE_URL")

        if not self.api_key:
            raise ValueError(
                "OpenRouter API key is required. Set OPENROUTER_API_KEY environment variable "
                "or pass api_key parameter."
            )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": self.site_url or "",
            "X-Title": self.app_name,
        }

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            headers=headers,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "OpenRouterClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the OpenRouter API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            json: Request body as JSON
            params: Query parameters

        Returns:
            Response data as dictionary

        Raises:
            OpenRouterError: On API errors
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            response = await self._client.request(
                method=method,
                url=url,
                json=json,
                params=params,
            )

            if response.status_code == 401:
                logger.error(
                    "OpenRouter API authentication failed",
                    extra={"status_code": 401, "endpoint": endpoint},
                )
                raise OpenRouterAuthenticationError()

            if response.status_code == 403:
                logger.error(
                    "OpenRouter API authorization failed",
                    extra={"status_code": 403, "endpoint": endpoint},
                )
                raise OpenRouterAuthenticationError(
                    message="Authorization failed - API key may lack required permissions",
                    status_code=403,
                )

            if response.status_code == 404:
                raise OpenRouterModelUnavailableError(
                    message=f"Resource not found: {endpoint}",
                )

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                logger.warning(
                    "OpenRouter API rate limited",
                    extra={
                        "endpoint": endpoint,
                        "retry_after": retry_after,
                    },
                )
                raise OpenRouterRateLimitError(
                    retry_after=int(retry_after) if retry_after else None
                )

            if response.status_code >= 400:
                error_body = {}
                try:
                    error_body = response.json()
                except Exception:
                    pass

                error_message = error_body.get("error", {}).get("message", "")
                error_code = error_body.get("error", {}).get("code", "")

                # Check for content filter
                if error_code == "content_filter" or "content" in error_message.lower():
                    raise OpenRouterContentFilterError(
                        message=error_message or "Content blocked by filter",
                        response=error_body,
                    )

                logger.error(
                    "OpenRouter API error",
                    extra={
                        "status_code": response.status_code,
                        "endpoint": endpoint,
                        "error_code": error_code,
                        "response": str(error_body)[:500],
                    },
                )
                raise OpenRouterError(
                    message=f"OpenRouter API error: {response.status_code} - {error_message}",
                    status_code=response.status_code,
                    code=error_code,
                    response=error_body,
                )

            if response.status_code == 204:
                return {}

            return response.json()

        except httpx.TimeoutException as e:
            logger.error(
                "OpenRouter API timeout",
                extra={"endpoint": endpoint, "error": str(e)},
            )
            raise OpenRouterTimeoutError(f"Request timeout: {e}")
        except httpx.RequestError as e:
            logger.error(
                "OpenRouter API connection error",
                extra={"endpoint": endpoint, "error": str(e)},
            )
            raise OpenRouterConnectionError(f"Connection error: {e}")

    async def chat_completion(
        self,
        messages: List[ChatMessage],
        model: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        top_p: Optional[float] = None,
        stop: Optional[List[str]] = None,
    ) -> ChatCompletionResponse:
        """
        Create a chat completion.

        Args:
            messages: List of chat messages
            model: Model ID (e.g., 'openai/gpt-4-turbo')
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0-2.0)
            top_p: Nucleus sampling parameter
            stop: Stop sequences

        Returns:
            ChatCompletionResponse with generated content

        Raises:
            OpenRouterError: On API errors
        """
        request_body: Dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
        }

        if max_tokens is not None:
            request_body["max_tokens"] = max_tokens
        if top_p is not None:
            request_body["top_p"] = top_p
        if stop:
            request_body["stop"] = stop

        start_time = time.time()

        data = await self._request("POST", "/chat/completions", json=request_body)

        latency_ms = int((time.time() - start_time) * 1000)

        response = ChatCompletionResponse.from_dict(data)

        logger.info(
            "OpenRouter chat completion successful",
            extra={
                "model": model,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "latency_ms": latency_ms,
            },
        )

        return response

    async def list_models(self) -> List[ModelInfo]:
        """
        List available models.

        Returns:
            List of ModelInfo objects

        Raises:
            OpenRouterError: On API errors
        """
        data = await self._request("GET", "/models")

        models = []
        for model_data in data.get("data", []):
            models.append(ModelInfo.from_dict(model_data))

        logger.debug(
            "Listed OpenRouter models",
            extra={"model_count": len(models)},
        )

        return models

    async def check_health(self) -> bool:
        """
        Check if OpenRouter API is reachable.

        Returns:
            True if API is healthy

        Raises:
            OpenRouterError: On connection errors
        """
        try:
            await self.list_models()
            return True
        except OpenRouterError:
            return False


def get_openrouter_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> OpenRouterClient:
    """
    Factory function to create an OpenRouterClient.

    Args:
        api_key: Override API key
        base_url: Override API base URL

    Returns:
        Configured OpenRouterClient instance
    """
    return OpenRouterClient(
        api_key=api_key,
        base_url=base_url,
    )
