"""
Airbyte Cloud integration for data ingestion.

This module provides a client for interacting with Airbyte Cloud API
to manage data synchronization pipelines.
"""

from src.integrations.airbyte.client import AirbyteClient, get_airbyte_client
from src.integrations.airbyte.exceptions import (
    AirbyteError,
    AirbyteAuthenticationError,
    AirbyteRateLimitError,
    AirbyteConnectionError,
    AirbyteSyncError,
)
from src.integrations.airbyte.models import (
    AirbyteHealth,
    AirbyteConnection,
    AirbyteJob,
    AirbyteJobStatus,
    AirbyteSyncResult,
)

__all__ = [
    # Client
    "AirbyteClient",
    "get_airbyte_client",
    # Exceptions
    "AirbyteError",
    "AirbyteAuthenticationError",
    "AirbyteRateLimitError",
    "AirbyteConnectionError",
    "AirbyteSyncError",
    # Models
    "AirbyteHealth",
    "AirbyteConnection",
    "AirbyteJob",
    "AirbyteJobStatus",
    "AirbyteSyncResult",
]
