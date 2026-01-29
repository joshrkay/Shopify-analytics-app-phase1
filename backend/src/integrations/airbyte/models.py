"""
Data models for Airbyte API responses.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any


class AirbyteJobStatus(str, Enum):
    """Status of an Airbyte sync job."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"


class ConnectionStatus(str, Enum):
    """Status of an Airbyte connection."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"


class ScheduleType(str, Enum):
    """Type of sync schedule."""

    MANUAL = "manual"
    BASIC = "basic"
    CRON = "cron"


@dataclass
class AirbyteHealth:
    """Health check response from Airbyte API."""

    available: bool
    db: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AirbyteHealth":
        return cls(
            available=data.get("available", False),
            db=data.get("db", True),
        )


@dataclass
class AirbyteSchedule:
    """Sync schedule configuration."""

    schedule_type: ScheduleType
    cron_expression: Optional[str] = None
    basic_timing: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AirbyteSchedule":
        return cls(
            schedule_type=ScheduleType(data.get("scheduleType", "manual")),
            cron_expression=data.get("cronExpression"),
            basic_timing=data.get("basicTiming"),
        )


@dataclass
class AirbyteConnection:
    """Airbyte connection (source -> destination pipeline)."""

    connection_id: str
    name: str
    source_id: str
    destination_id: str
    status: ConnectionStatus
    schedule: Optional[AirbyteSchedule] = None
    namespace_definition: Optional[str] = None
    namespace_format: Optional[str] = None
    prefix: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AirbyteConnection":
        schedule = None
        if "schedule" in data and data["schedule"]:
            schedule = AirbyteSchedule.from_dict(data["schedule"])

        return cls(
            connection_id=data.get("connectionId", ""),
            name=data.get("name", ""),
            source_id=data.get("sourceId", ""),
            destination_id=data.get("destinationId", ""),
            status=ConnectionStatus(data.get("status", "inactive")),
            schedule=schedule,
            namespace_definition=data.get("namespaceDefinition"),
            namespace_format=data.get("namespaceFormat"),
            prefix=data.get("prefix"),
        )


@dataclass
class AirbyteJobAttempt:
    """Attempt within an Airbyte sync job."""

    attempt_number: int
    status: AirbyteJobStatus
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    bytes_synced: int = 0
    records_synced: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AirbyteJobAttempt":
        def parse_timestamp(ts: Any) -> Optional[datetime]:
            if ts is None:
                return None
            if isinstance(ts, (int, float)):
                return datetime.fromtimestamp(ts)
            if isinstance(ts, str):
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return None

        return cls(
            attempt_number=data.get("attemptNumber", 0),
            status=AirbyteJobStatus(data.get("status", "pending")),
            created_at=parse_timestamp(data.get("createdAt")),
            updated_at=parse_timestamp(data.get("updatedAt")),
            ended_at=parse_timestamp(data.get("endedAt")),
            bytes_synced=data.get("bytesSynced", 0),
            records_synced=data.get("recordsSynced", 0),
        )


@dataclass
class AirbyteJob:
    """Airbyte sync job."""

    job_id: str
    config_type: str
    config_id: str
    status: AirbyteJobStatus
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    attempts: List[AirbyteJobAttempt] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AirbyteJob":
        def parse_timestamp(ts: Any) -> Optional[datetime]:
            if ts is None:
                return None
            if isinstance(ts, (int, float)):
                return datetime.fromtimestamp(ts)
            if isinstance(ts, str):
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return None

        job_data = data.get("job", data)
        attempts_data = job_data.get("attempts", [])
        attempts = [AirbyteJobAttempt.from_dict(a) for a in attempts_data]

        return cls(
            job_id=str(job_data.get("id", job_data.get("jobId", ""))),
            config_type=job_data.get("configType", "sync"),
            config_id=job_data.get("configId", ""),
            status=AirbyteJobStatus(job_data.get("status", "pending")),
            created_at=parse_timestamp(job_data.get("createdAt")),
            updated_at=parse_timestamp(job_data.get("updatedAt")),
            attempts=attempts,
        )

    @property
    def is_running(self) -> bool:
        return self.status in (AirbyteJobStatus.PENDING, AirbyteJobStatus.RUNNING)

    @property
    def is_complete(self) -> bool:
        return self.status in (
            AirbyteJobStatus.SUCCEEDED,
            AirbyteJobStatus.FAILED,
            AirbyteJobStatus.CANCELLED,
        )

    @property
    def is_successful(self) -> bool:
        return self.status == AirbyteJobStatus.SUCCEEDED


@dataclass
class AirbyteSyncResult:
    """Result of a sync operation."""

    job_id: str
    status: AirbyteJobStatus
    connection_id: str
    records_synced: int = 0
    bytes_synced: int = 0
    duration_seconds: float = 0.0
    error_message: Optional[str] = None

    @property
    def is_successful(self) -> bool:
        return self.status == AirbyteJobStatus.SUCCEEDED


class SourceType(str, Enum):
    """Supported Airbyte source types for data ingestion."""

    SHOPIFY = "source-shopify"
    META_ADS = "source-facebook-marketing"
    GOOGLE_ADS = "source-google-ads"
    TIKTOK_ADS = "source-tiktok-marketing"
    SNAPCHAT_ADS = "source-snapchat-marketing"
    KLAVIYO = "source-klaviyo"
    ATTENTIVE = "source-attentive"
    POSTSCRIPT = "source-postscript"
    SMSBUMP = "source-smsbump"


@dataclass
class AirbyteSource:
    """Airbyte source (data source connector)."""

    source_id: str
    name: str
    source_type: str
    workspace_id: str
    configuration: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AirbyteSource":
        return cls(
            source_id=data.get("sourceId", ""),
            name=data.get("name", ""),
            source_type=data.get("sourceType", ""),
            workspace_id=data.get("workspaceId", ""),
            configuration=data.get("configuration", {}),
        )


@dataclass
class AirbyteDestination:
    """Airbyte destination (data destination connector)."""

    destination_id: str
    name: str
    destination_type: str
    workspace_id: str
    configuration: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AirbyteDestination":
        return cls(
            destination_id=data.get("destinationId", ""),
            name=data.get("name", ""),
            destination_type=data.get("destinationType", ""),
            workspace_id=data.get("workspaceId", ""),
            configuration=data.get("configuration", {}),
        )


@dataclass
class SourceCreationRequest:
    """Request to create a new Airbyte source."""

    name: str
    source_type: str
    configuration: Dict[str, Any]
    workspace_id: Optional[str] = None

    def to_dict(self, workspace_id: str) -> Dict[str, Any]:
        return {
            "name": self.name,
            "sourceType": self.source_type,
            "workspaceId": workspace_id,
            "configuration": self.configuration,
        }


@dataclass
class ConnectionCreationRequest:
    """Request to create a new Airbyte connection."""

    source_id: str
    destination_id: str
    name: str
    schedule_type: ScheduleType = ScheduleType.MANUAL
    namespace_definition: str = "destination"
    status: str = "active"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "destinationId": self.destination_id,
            "name": self.name,
            "schedule": {"scheduleType": self.schedule_type.value},
            "namespaceDefinition": self.namespace_definition,
            "status": self.status,
        }
