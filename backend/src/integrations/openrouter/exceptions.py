"""
OpenRouter-specific exceptions for error handling.

Follows the same pattern as Airbyte exceptions for consistency.
"""

from typing import Optional, Dict, Any


class OpenRouterError(Exception):
    """Base exception for OpenRouter API errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        code: Optional[str] = None,
        response: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.response = response or {}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, status_code={self.status_code})"


class OpenRouterAuthenticationError(OpenRouterError):
    """Raised when API authentication fails (401/403)."""

    def __init__(
        self,
        message: str = "Authentication failed - API key may be invalid or missing",
        status_code: int = 401,
        **kwargs,
    ):
        super().__init__(message, status_code=status_code, **kwargs)


class OpenRouterRateLimitError(OpenRouterError):
    """Raised when API rate limit is exceeded (429)."""

    def __init__(
        self,
        message: str = "Rate limit exceeded - please retry after a delay",
        retry_after: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(message, status_code=429, **kwargs)
        self.retry_after = retry_after


class OpenRouterConnectionError(OpenRouterError):
    """Raised when network/connection errors occur."""

    def __init__(
        self,
        message: str = "Connection error - unable to reach OpenRouter API",
        **kwargs,
    ):
        super().__init__(message, **kwargs)


class OpenRouterTimeoutError(OpenRouterError):
    """Raised when request times out."""

    def __init__(
        self,
        message: str = "Request timed out",
        **kwargs,
    ):
        super().__init__(message, **kwargs)


class OpenRouterModelUnavailableError(OpenRouterError):
    """Raised when requested model is unavailable (404 or model-specific error)."""

    def __init__(
        self,
        message: str = "Requested model is unavailable",
        model_id: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(message, status_code=404, **kwargs)
        self.model_id = model_id


class OpenRouterContentFilterError(OpenRouterError):
    """Raised when content is blocked by safety filters."""

    def __init__(
        self,
        message: str = "Request blocked by content filter",
        **kwargs,
    ):
        super().__init__(message, status_code=400, code="content_filter", **kwargs)
