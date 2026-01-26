"""
Shared utilities for governance modules.

Provides common functionality for configuration loading, audit logging,
and serialization to reduce duplication across governance modules.
"""

import logging
import uuid
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


def load_yaml_config(config_path: str | Path, logger: logging.Logger | None = None) -> dict[str, Any]:
    """
    Load configuration from a YAML file.

    Args:
        config_path: Path to the YAML configuration file
        logger: Optional logger for info message

    Returns:
        Parsed configuration dictionary

    Raises:
        FileNotFoundError: If the config file doesn't exist
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with open(path) as f:
        config = yaml.safe_load(f)

    if logger:
        logger.info(f"Loaded config from {path}")

    return config


class AuditLogger:
    """
    Shared audit logging utility.

    Provides consistent audit logging across governance modules.
    """

    def __init__(self, logger_name: str = "governance_audit"):
        """
        Initialize the audit logger.

        Args:
            logger_name: Name for the audit logger
        """
        self.logger = logging.getLogger(logger_name)
        self._entries: list[dict[str, Any]] = []

    def log(
        self,
        action: str,
        resource_id: str,
        result: str,
        reason: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """
        Log an audit entry.

        Args:
            action: The action being performed
            resource_id: ID of the resource being acted upon
            result: Result of the action (e.g., "PASS", "BLOCK", "ALLOWED")
            reason: Optional reason for the result
            context: Optional additional context

        Returns:
            The audit entry ID
        """
        entry_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)

        entry = {
            "audit_id": entry_id,
            "timestamp": timestamp.isoformat(),
            "action": action,
            "resource_id": resource_id,
            "result": result,
            "reason": reason,
            "context": context or {},
        }

        self._entries.append(entry)
        self.logger.info(
            f"AUDIT: {action} | ID: {resource_id} | Result: {result}"
            + (f" | Reason: {reason}" if reason else "")
        )

        return entry_id

    def get_entries(self) -> list[dict[str, Any]]:
        """Get all audit log entries."""
        return self._entries.copy()

    def clear(self) -> None:
        """Clear the audit log (for testing only)."""
        self._entries.clear()


def serialize_dataclass(obj: Any) -> dict[str, Any]:
    """
    Serialize a dataclass to a dictionary.

    Handles:
    - Enum values (converts to .value)
    - Datetime objects (converts to ISO format)
    - Nested dataclasses (recursively serializes)
    - Lists of dataclasses

    Args:
        obj: The dataclass instance to serialize

    Returns:
        Dictionary representation
    """
    if not is_dataclass(obj):
        raise TypeError(f"Expected dataclass, got {type(obj)}")

    result = {}
    for field in fields(obj):
        value = getattr(obj, field.name)
        result[field.name] = _serialize_value(value)

    return result


def _serialize_value(value: Any) -> Any:
    """Serialize a single value, handling special types."""
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return serialize_dataclass(value)
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    return value
