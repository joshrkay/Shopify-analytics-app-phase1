"""
Airbyte-specific exceptions for error handling.
"""

from typing import Optional, Dict, Any


class AirbyteError(Exception):
    """Base exception for Airbyte API errors."""

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


class AirbyteAuthenticationError(AirbyteError):
    """Raised when API authentication fails (401/403)."""

    def __init__(
        self,
        message: str = "Authentication failed - API token may be invalid or expired",
        status_code: int = 401,
        **kwargs,
    ):
        super().__init__(message, status_code=status_code, **kwargs)


class AirbyteRateLimitError(AirbyteError):
    """Raised when API rate limit is exceeded (429)."""

    def __init__(
        self,
        message: str = "Rate limit exceeded - please retry after a delay",
        retry_after: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(message, status_code=429, **kwargs)
        self.retry_after = retry_after


class AirbyteConnectionError(AirbyteError):
    """Raised when network/connection errors occur."""

    def __init__(
        self,
        message: str = "Connection error - unable to reach Airbyte API",
        **kwargs,
    ):
        super().__init__(message, **kwargs)


class AirbyteSyncError(AirbyteError):
    """Raised when a sync job fails or times out."""

    def __init__(
        self,
        message: str,
        job_id: Optional[str] = None,
        connection_id: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(message, **kwargs)
        self.job_id = job_id
        self.connection_id = connection_id


class AirbyteNotFoundError(AirbyteError):
    """Raised when a requested resource is not found (404)."""

    def __init__(
        self,
        message: str = "Resource not found",
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(message, status_code=404, **kwargs)
        self.resource_type = resource_type
        self.resource_id = resource_id
